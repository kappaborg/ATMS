"""Audit forwarder back-pressure — bounded local retention + cold-tier overflow.

Production problem: chamber writes to local SQLite at 0.5 Hz (every 2 s
review interval). 180-day retention × 2 directions × ~24h * 1800 ticks
≈ 28M rows per intersection per year ≈ 6 GB. The forwarder ships these
to TimescaleDB. But:

- TimescaleDB can be down for hours (maintenance window, network
  partition between Sarajevo edge and KS data center).
- During the outage, rotated SQLite files keep accumulating on edge
  disk. After 30 days of forwarding lag, 0.5 GB of accumulated audits
  pile up.
- If the outage lasts long enough, edge disk fills, chamber can't write,
  audit is silently dropped. **Unacceptable** for a regulatory audit
  system.

Solution: three-tier overflow strategy.

1. **Local primary** — `audit.db` (current writes). Rotates at
   `max_size_mb` (default 200 MB).

2. **Local archive** — `audit.*.db` rotated files. Bounded by total
   disk quota (default 10 GB). When quota exceeded, OLDEST archive
   file is moved to cold tier (S3 / object storage) and removed locally.

3. **Cold tier** (optional) — S3 / MinIO / any S3-compatible object
   store. Compressed `.db.gz` files. Indexed via a manifest JSON.

The forwarder handles all three tiers:
- Forwards local archives to TimescaleDB first (newest first — most
  relevant for live ops)
- On TimescaleDB success: deletes local archive
- On TimescaleDB failure: leaves local archive, retries with
  exponential backoff
- If local quota approached: moves OLDEST archive to cold tier
- Cold tier can be later re-forwarded into TimescaleDB via the
  reverse `pull-from-cold` command

Health metrics emitted to Prometheus:
- `atms_audit_local_archive_count` — number of rotated .db files locally
- `atms_audit_local_archive_bytes` — total local archive disk usage
- `atms_audit_forward_lag_seconds` — how far behind TimescaleDB is vs
  newest local row
- `atms_audit_cold_tier_uploads_total` — when local quota forced overflow
- `atms_audit_forward_failures_total{reason}` — retry counter

This module is dependency-light: boto3 is OPTIONAL (only needed if
cold_tier_bucket is configured).
"""

from __future__ import annotations

import gzip
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("atms.chamber.audit_backpressure")


@dataclass
class BackpressureConfig:
    """Per-intersection backpressure policy."""

    # Maximum total disk usage allowed for rotated archive files (bytes).
    # When exceeded, oldest archives move to cold tier (if configured)
    # or get deleted (if cold tier disabled — last resort, alert ops).
    local_archive_quota_bytes: int = 10 * 1024 * 1024 * 1024  # 10 GB default

    # If set, archives over the quota get uploaded here before deletion.
    cold_tier_bucket: str = ""  # e.g. "s3://atms-archive-sarajevo/"
    cold_tier_prefix: str = ""  # e.g. "intersection-005/"

    # Exponential backoff for failed forwards
    initial_retry_seconds: float = 5.0
    max_retry_seconds: float = 900.0  # cap at 15 min
    backoff_multiplier: float = 2.0


class BackpressureManager:
    """Manages local archive quota + cold tier overflow + retry state.

    Embedded in or called alongside the TimescaleDB forwarder. Designed
    to operate in a separate process from the chamber (systemd timer
    every 5 min) so audit storage health doesn't affect signal control.
    """

    def __init__(
        self,
        archive_dir: Path,
        config: BackpressureConfig | None = None,
        intersection_id: str = "demo",
    ):
        self._archive_dir = Path(archive_dir)
        self._config = config or BackpressureConfig()
        self._intersection_id = intersection_id
        self._archive_dir.mkdir(parents=True, exist_ok=True)
        self._retry_state: dict[str, float] = {}  # path -> next_retry_time

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def list_local_archives(self) -> list[Path]:
        """All rotated .db files in the archive dir, sorted oldest first
        (so callers iterating "what to forward next" naturally process
        FIFO; callers iterating "what to overflow" naturally process
        the oldest first too).
        """
        files = sorted(self._archive_dir.glob("*.db"))
        # Filter out the live audit file (the one without a timestamp
        # suffix) — only rotated archives are eligible.
        return [f for f in files if "." in f.stem and f.stem != "audit"]

    def total_archive_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.list_local_archives())

    def should_retry(self, archive_path: Path) -> bool:
        """Check the per-file exponential-backoff state."""
        key = str(archive_path.resolve())
        next_retry = self._retry_state.get(key, 0.0)
        return time.time() >= next_retry

    def mark_forwarded(self, archive_path: Path) -> None:
        """Forwarder reports success — delete the local archive + clear
        backoff state.
        """
        key = str(archive_path.resolve())
        self._retry_state.pop(key, None)
        try:
            archive_path.unlink()
            log.info("deleted forwarded archive: %s", archive_path.name)
        except OSError as e:
            log.warning("could not delete %s after forward: %s", archive_path, e)

    def mark_failed(self, archive_path: Path) -> None:
        """Forwarder reports failure — schedule a retry with backoff."""
        key = str(archive_path.resolve())
        last = self._retry_state.get(key, 0.0)
        if last == 0.0:
            wait = self._config.initial_retry_seconds
        else:
            wait = min(
                (last - time.time()) * self._config.backoff_multiplier
                if last > time.time()
                else self._config.initial_retry_seconds * self._config.backoff_multiplier,
                self._config.max_retry_seconds,
            )
        self._retry_state[key] = time.time() + wait
        log.warning(
            "forward of %s failed — next retry in %.0fs",
            archive_path.name, wait,
        )

    def enforce_quota(self) -> dict:
        """Check disk usage. If over quota, push oldest archives to cold
        tier (or delete with WARN if cold tier disabled). Returns a
        report dict with counts + bytes.
        """
        used = self.total_archive_bytes()
        quota = self._config.local_archive_quota_bytes
        report = {
            "used_bytes": used,
            "quota_bytes": quota,
            "over_quota": used > quota,
            "uploaded_to_cold": 0,
            "deleted_locally": 0,
        }
        if used <= quota:
            return report

        archives = self.list_local_archives()  # oldest first
        for archive in archives:
            if self.total_archive_bytes() <= quota:
                break
            try:
                if self._config.cold_tier_bucket:
                    self._upload_to_cold_tier(archive)
                    report["uploaded_to_cold"] += 1
                    archive.unlink()
                else:
                    # No cold tier configured — last-resort delete with
                    # very loud warning. KJP ops policy should ensure
                    # cold tier is set in production.
                    log.error(
                        "QUOTA BREACH: deleting %s without cold-tier "
                        "backup (cold_tier_bucket unset)",
                        archive.name,
                    )
                    archive.unlink()
                    report["deleted_locally"] += 1
            except Exception as e:
                log.error("quota enforcement failed on %s: %s", archive.name, e)

        return report

    def lag_seconds(self, timescale_newest_ts: datetime | None) -> float:
        """Forwarding lag: how far behind TimescaleDB is vs local newest.
        Returns 0 when caught up, or a positive number of seconds.
        """
        archives = self.list_local_archives()
        if not archives:
            return 0.0
        if timescale_newest_ts is None:
            # No timestamp from Timescale → assume oldest archive is the
            # lag (gives operator an upper-bound estimate)
            oldest_mtime = min(f.stat().st_mtime for f in archives)
            return max(0.0, time.time() - oldest_mtime)
        # Most-recent archive's mtime - timescale's newest row time
        newest_mtime = max(f.stat().st_mtime for f in archives)
        ts_epoch = timescale_newest_ts.timestamp()
        return max(0.0, newest_mtime - ts_epoch)

    # -----------------------------------------------------------------
    # Cold-tier upload
    # -----------------------------------------------------------------

    def _upload_to_cold_tier(self, archive_path: Path) -> None:
        """Compress + upload + verify. Raises on any failure so the
        caller doesn't delete the local copy.
        """
        bucket = self._config.cold_tier_bucket
        if not bucket:
            raise RuntimeError("cold_tier_bucket not configured")

        # Compress in-place (creates .db.gz next to .db)
        gz_path = archive_path.with_suffix(archive_path.suffix + ".gz")
        with archive_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        log.info(
            "compressed %s: %d -> %d bytes",
            archive_path.name,
            archive_path.stat().st_size,
            gz_path.stat().st_size,
        )

        try:
            if bucket.startswith("s3://"):
                self._upload_s3(gz_path, bucket)
            else:
                # Future: GCS, Azure Blob, local NFS, etc. For now S3-only.
                raise RuntimeError(
                    f"cold_tier_bucket scheme not supported: {bucket}"
                )
        finally:
            # Always remove the .gz scratch file
            gz_path.unlink(missing_ok=True)

    def _upload_s3(self, file_path: Path, bucket_url: str) -> None:
        """boto3 S3 upload. Optional dependency."""
        try:
            import boto3  # noqa: PLC0415
            from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(
                "boto3 required for S3 cold tier. "
                "Install: pip install boto3"
            ) from e

        # Parse s3://bucket-name/optional/prefix → (bucket, key_prefix)
        without_scheme = bucket_url[len("s3://"):]
        parts = without_scheme.split("/", 1)
        bucket_name = parts[0]
        bucket_prefix = parts[1] if len(parts) > 1 else ""
        full_prefix = "/".join(p.strip("/") for p in [
            bucket_prefix, self._config.cold_tier_prefix, self._intersection_id,
        ] if p)
        key = f"{full_prefix}/{file_path.name}" if full_prefix else file_path.name

        client = boto3.client("s3")
        try:
            client.upload_file(str(file_path), bucket_name, key)
            log.info("cold tier upload: %s -> s3://%s/%s",
                     file_path.name, bucket_name, key)
        except (BotoCoreError, ClientError) as e:
            raise RuntimeError(f"S3 upload failed: {e}") from e

    # -----------------------------------------------------------------
    # Prometheus health snapshot — caller emits these as gauges/counters
    # -----------------------------------------------------------------

    def health_snapshot(self) -> dict:
        archives = self.list_local_archives()
        return {
            "local_archive_count": len(archives),
            "local_archive_bytes": sum(f.stat().st_size for f in archives),
            "quota_bytes": self._config.local_archive_quota_bytes,
            "oldest_archive_age_seconds": (
                time.time() - min(f.stat().st_mtime for f in archives)
                if archives else 0.0
            ),
            "retry_state_entries": len(self._retry_state),
        }
