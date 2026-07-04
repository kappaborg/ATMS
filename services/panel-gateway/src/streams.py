"""
Live web-stream resolution (YouTube Live and friends).

A YouTube page URL can't be opened by OpenCV directly — it must be resolved
to the underlying HLS manifest. Those googlevideo manifest URLs also EXPIRE
(hours), so resolution happens at capture-open time: every reconnect gets a
fresh URL, making a 24/7 live camera self-healing.

Resolution uses yt-dlp (Python module if importable, else the CLI). Supported
pages = whatever yt-dlp supports (YouTube live/VOD, many webcam portals).
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger("panel.streams")

_PAGE_HOSTS = (
    "youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com",
    "twitch.tv", "www.twitch.tv", "dailymotion.com", "www.dailymotion.com",
    "skylinewebcams.com", "www.skylinewebcams.com",
)


def is_web_page_stream(source: str) -> bool:
    """True for page URLs that need yt-dlp resolution (vs direct media URLs)."""
    s = str(source).lower()
    if not s.startswith(("http://", "https://")):
        return False
    host = s.split("//", 1)[1].split("/", 1)[0].split(":")[0]
    return any(host == h or host.endswith("." + h) for h in _PAGE_HOSTS)


def resolve_stream_url(page_url: str, max_height: int = 720) -> str | None:
    """Resolve a page URL to a direct HLS/media URL, or None."""
    fmt = f"b[height<={max_height}]/bv*[height<={max_height}]+ba/b"
    # Prefer the yt_dlp module (same process, no PATH issues).
    try:
        import yt_dlp  # type: ignore

        with yt_dlp.YoutubeDL({"format": fmt, "quiet": True, "no_warnings": True}) as y:
            info = y.extract_info(page_url, download=False)
            url = info.get("url")
            if not url and info.get("formats"):
                url = info["formats"][-1].get("url")
            if url:
                return str(url)
    except Exception as e:  # noqa: BLE001 — fall through to the CLI
        log.debug("yt_dlp module resolve failed: %s", e)
    exe = shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
    try:
        out = subprocess.run(
            [exe, "-g", "-f", fmt, page_url],
            capture_output=True, text=True, timeout=45,
        )
        for line in out.stdout.splitlines():
            if line.startswith("http"):
                return line.strip()
        log.warning("stream resolve failed for %s: %s", page_url, out.stderr.strip()[:200])
    except Exception as e:  # noqa: BLE001
        log.warning("stream resolve error for %s: %s", page_url, e)
    return None
