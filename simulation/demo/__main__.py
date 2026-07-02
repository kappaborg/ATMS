"""ATMS live-demo orchestrator entrypoint.

    python -m simulation.demo [--gui] [--live]

Modes:

    (default)       Headless SUMO. Events still fire to stdout, but no HTTP
                    POSTs are made. Useful for rehearsal — verify the
                    timeline by reading the cue stream without standing up
                    the full docker-compose-demo stack.

    --gui           Launches sumo-gui. The runner sleeps between ticks to
                    keep the visual at a viewer-friendly pace (default
                    delay is also set in config.sumocfg's <gui_only>).

    --live          Fires HTTP POSTs to the live service stack as scripted
                    events come due. Requires docker compose -f
                    docker-compose.demo.yml up -d to be running. The demo
                    operator needs an `engineer`-role JWT (env: DEMO_TOKEN).

Run-of-show: docs/demos/pilot-pitch.md.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from simulation.demo.events import DEMO_TIMELINE, DemoEvent, events_due
from simulation.demo.state_emitter import StateEmitter

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

log = logging.getLogger("atms.demo")


# ---------------------------------------------------------------------------
# Side-effect dispatchers
# ---------------------------------------------------------------------------


def _post_json(url: str, body: dict, token: str | None, timeout_s: float = 3.0) -> None:
    """Fire-and-forget HTTP POST. Logs but never raises — the demo continues
    even if the live stack is mid-restart or unreachable."""
    import json  # noqa: PLC0415

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            log.info("demo POST %s -> %s", url, resp.status)
    except urllib.error.URLError as e:
        log.warning("demo POST %s failed: %s (continuing)", url, e)
    except Exception as e:
        log.warning("demo POST %s unexpected error: %s (continuing)", url, e)


_SERVICE_URLS = {
    "v2x": os.getenv("DEMO_V2X_URL", "http://localhost:8009"),
    "controller": os.getenv("DEMO_CONTROLLER_URL", "http://localhost:8001"),
}


def _fire_side_effect(event: DemoEvent, live: bool, token: str | None) -> None:
    """Carry out the side-effect for an event. No-op in non-live mode."""
    if not live:
        log.info("(dry-run) would fire %s with payload %s", event.kind, event.payload)
        return

    if event.kind == "v2x_inject":
        _post_json(f"{_SERVICE_URLS['v2x']}/admin/inject", event.payload, token)
    elif event.kind == "ped_call":
        _post_json(f"{_SERVICE_URLS['controller']}/ped_call/request", event.payload, token)
    elif event.kind == "force_mode":
        # The controller exposes /control/emergency for ALL_RED_FLASH.
        # See services/traffic-controller for the exact API shape.
        _post_json(
            f"{_SERVICE_URLS['controller']}/control/emergency",
            {"reason": event.payload.get("reason", "demo")},
            token,
        )
    elif event.kind == "recover":
        _post_json(f"{_SERVICE_URLS['controller']}/control/recover", event.payload, token)
    elif event.kind == "cue":
        pass  # cue is just stdout
    else:
        log.warning("unknown event kind: %s", event.kind)


# ---------------------------------------------------------------------------
# Runner — minimal direct TraCI loop, separate from harness/runner.py so
# the demo's pacing + event-injection layer stays self-contained.
# ---------------------------------------------------------------------------


def _emit_cue(event: DemoEvent) -> None:
    bar = "═" * 76
    print(f"\n{bar}\n{event.cue}\n{bar}\n", flush=True)


def run_demo(
    scenario_dir: Path,
    *,
    gui: bool = False,
    live: bool = False,
    token: str | None = None,
    max_steps: int = 300,
    step_length_s: float = 1.0,
) -> int:
    """Run the demo scenario. Returns 0 on clean completion, 1 on conflict."""
    try:
        import sumolib  # noqa: PLC0415, F401
        import traci  # noqa: PLC0415
    except ImportError as e:
        print(
            f"✗ SUMO Python bindings not importable: {e}\n"
            f"  Current Python: {sys.executable}\n"
            f"  Install matching this Python with:\n"
            f"    {sys.executable} -m pip install --break-system-packages "
            f"eclipse-sumo traci sumolib\n"
            f"  (Bare `pip install ...` can install into a *different* Python "
            f"than `python3 -m simulation.demo` uses — always prefer "
            f"`python3 -m pip` to keep them in sync.)",
            file=sys.stderr,
        )
        return 2

    # Lazy import — avoid coupling demo bring-up to legacy modules.
    from simulation.harness.runner import (  # noqa: PLC0415
        default_decision_fn,
        wire_to_tl_phase,
    )

    cfg_path = scenario_dir / "config.sumocfg"
    if not cfg_path.exists():
        print(f"✗ scenario config not found: {cfg_path}", file=sys.stderr)
        return 2

    binary = "sumo-gui" if gui else os.getenv("SUMO_BINARY", "sumo")
    cmd = [
        binary,
        "-c",
        str(cfg_path),
        "--step-length",
        str(step_length_s),
        "--no-step-log",
        "true",
        "--quit-on-end",
        "true",
    ]
    log.info("starting SUMO: %s", " ".join(cmd))
    try:
        # numRetries=2 keeps the failure mode fast — when sumo-gui can't open
        # a display (no X11 / no Wayland), the default 60-retry storm wastes
        # ~60s before surfacing the underlying error. Two retries is enough
        # for normal port-in-use contention without burying the real cause.
        traci.start(cmd, numRetries=2)
    except Exception as e:
        msg = f"✗ SUMO failed to start: {e}\n"
        if gui and sys.platform == "darwin":
            msg += (
                "\n  sumo-gui on macOS requires an X11 server because the\n"
                "  eclipse-sumo PyPI wheel is built against the FOX toolkit.\n"
                "  Install XQuartz once:\n"
                "      brew install --cask xquartz\n"
                "      # Then log out + back in so $DISPLAY gets set.\n"
                "  Alternative: drop --gui and run the headless demo — all\n"
                "  cues still fire, vehicles just don't draw on screen.\n"
            )
        elif gui:
            msg += (
                "\n  sumo-gui needs a display. If you're on a headless\n"
                "  host or in CI, drop --gui — the cue stream still works.\n"
            )
        print(msg, file=sys.stderr)
        return 2

    from shared.atms_common.emissions import EmissionEstimator  # noqa: PLC0415

    decide = default_decision_fn()
    estimator = EmissionEstimator()
    state_emitter = StateEmitter()
    # Edges that vehicles on each approach are travelling on. Reading vehicles
    # off the edge (instead of the induction-loop detectors) gives us speed +
    # vClass per vehicle, which is what the emission estimator needs.
    approach_edges = {"north_south": "ns_in", "east_west": "ew_in"}
    last_event_time = -1.0
    step = 0
    forced_mode: str | None = None
    current_wire = "all_red"

    # GUI auto-fit. The XML viewsettings `<viewport>` element interpretation
    # changed between SUMO versions — the most reliable way to centre the
    # view is via TraCI's setBoundary at startup. The demo network spans
    # roughly (-200, -200) to (200, 200), so set a boundary slightly larger
    # to give margin.
    if gui:
        try:
            traci.gui.setBoundary("View #0", -220, -220, 220, 220)
        except Exception as e:
            log.warning("could not set GUI boundary: %s", e)

    try:
        while step < max_steps:
            traci.simulationStep()
            step += 1
            sim_time = traci.simulation.getTime()

            for event in events_due(sim_time, last_event_time, DEMO_TIMELINE):
                _emit_cue(event)
                _fire_side_effect(event, live=live, token=token)
                state_emitter.append_event(kind=event.kind, message=event.cue, sim_time_s=sim_time)
                if event.kind == "force_mode":
                    forced_mode = event.payload.get("mode", "all_red_flash")
                elif event.kind == "recover":
                    forced_mode = None
            last_event_time = sim_time

            # Build per-direction metrics from REAL SUMO state. For each
            # approach edge, list the vehicles on it, read their class +
            # speed via TraCI, and aggregate via EmissionEstimator. This
            # replaces the placeholder "average_emission=100.0".
            per_direction_metrics: dict[str, dict] = {}
            per_direction_emissions: dict[str, dict] = {}
            for approach, edge in approach_edges.items():
                vehicles = _read_vehicles_on_edge(traci, edge)
                agg = estimator.aggregate_direction(approach, vehicles)
                per_direction_metrics[approach] = _build_decision_input(
                    vehicle_count=agg.vehicle_count,
                    average_emission=agg.average_emission_g_per_km,
                    mean_speed_kmh=_mean_speed(vehicles),
                )
                per_direction_emissions[approach] = agg.to_dict()

            if forced_mode == "all_red_flash":
                current_wire = "all_red"
                traci.trafficlight.setPhase("intersection", wire_to_tl_phase("all_red"))
            else:
                current_wire = decide(
                    per_direction_metrics["north_south"],
                    per_direction_metrics["east_west"],
                )
                traci.trafficlight.setPhase("intersection", wire_to_tl_phase(current_wire))

            # Emit state for the Streamlit operator console (and any other
            # observer). One write per tick — keeps the file small.
            state_emitter.emit(
                {
                    "sim_time_s": round(sim_time, 1),
                    "step": step,
                    "mode": "ALL_RED_FLASH" if forced_mode else "AI_ADAPTIVE",
                    "commanded_phase": current_wire,
                    "per_direction": {
                        approach: {
                            **per_direction_metrics[approach],
                            "emissions": per_direction_emissions[approach],
                        }
                        for approach in approach_edges
                    },
                }
            )

            if traci.simulation.getMinExpectedNumber() <= 0:
                log.info("SUMO finished at step %d", step)
                break

            if live:
                time.sleep(0.05)
    finally:
        try:
            traci.close()
        except Exception:
            pass

    print("\n✓ demo complete. Open Grafana http://localhost:3000 to review the trace.")
    return 0


def _read_vehicles_on_edge(traci_mod, edge_id: str) -> list[tuple[str, float, str | None]]:
    """Return `(vClass, speed_kmh, brand)` for every vehicle currently on edge.

    Brand is `None` because SUMO does not model brand; production deployments
    populate it from the trained car-brand classifier in
    `models/car_brand_classification/`.
    """
    try:
        veh_ids = traci_mod.edge.getLastStepVehicleIDs(edge_id)
    except Exception:
        return []
    out: list[tuple[str, float, str | None]] = []
    for vid in veh_ids:
        try:
            type_id = traci_mod.vehicle.getTypeID(vid)
            speed_mps = traci_mod.vehicle.getSpeed(vid)
            # The SUMO route file uses vType ids: "car", "bus", "emerg" — these
            # are the class labels we feed through VehicleClass.coerce. The
            # synonym table catches "emerg" via the legacy coerce path
            # (UNKNOWN -> emergency profile only if id is "emergency"); for the
            # demo's "emerg" type we relabel explicitly.
            if type_id == "emerg":
                type_id = "emergency"
            out.append((type_id, speed_mps * 3.6, None))  # m/s -> km/h
        except Exception:
            continue
    return out


def _mean_speed(vehicles: list[tuple[str, float, str | None]]) -> float:
    """Mean speed (km/h) over the fleet; 0.0 when empty."""
    if not vehicles:
        return 0.0
    return sum(v[1] for v in vehicles) / len(vehicles)


def _build_decision_input(
    vehicle_count: int, average_emission: float, mean_speed_kmh: float
) -> dict:
    """Shape the per-direction dict the legacy AIDecisionEngine consumes.

    The engine expects: vehicle_count, average_emission, average_waiting_time,
    average_velocity, total_emission, environmental_impact_score. We derive
    waiting time as a proxy from speed (slower means longer wait) and roll
    environmental_impact_score off the emission magnitude.
    """
    avg_velocity = mean_speed_kmh if mean_speed_kmh > 0 else 5.0
    avg_waiting = max(0.0, 30.0 - mean_speed_kmh)
    env_score = min(100.0, average_emission * 0.6)
    return {
        "vehicle_count": vehicle_count,
        "average_emission": round(average_emission, 2),
        "average_waiting_time": round(avg_waiting, 2),
        "average_velocity": round(avg_velocity, 2),
        "total_emission": round(average_emission * max(1, vehicle_count), 2),
        "environmental_impact_score": round(env_score, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="simulation.demo")
    parser.add_argument("--gui", action="store_true", help="launch sumo-gui (the projector view)")
    parser.add_argument(
        "--live",
        action="store_true",
        help="fire HTTP events to the live docker-compose-demo stack",
    )
    parser.add_argument(
        "--scenario",
        default="demo",
        help="scenario name under simulation/scenarios/ (default: demo)",
    )
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument(
        "--video",
        default=None,
        help=(
            "Path to a real-traffic video file. When set, the demo switches "
            "from SUMO to YOLOv8 → tracker → emission pipeline. Use any .mp4 "
            "under videos/ or Processed_Videos/. Real data, not simulated."
        ),
    )
    parser.add_argument(
        "--site-config",
        type=str,
        default=None,
        help=(
            "Path to a site YAML config (per-intersection deployment file). "
            "When provided, the chamber boots via build_chamber_from_site_config "
            "and inherits camera calibration, NTCIP target, MQTT broker, TSP "
            "feed, audit DB, and Prometheus port from the YAML. Production "
            "deployment pattern. Example template: "
            "services/observability/example-intersection.yaml"
        ),
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="With --video: open an OpenCV preview window with bbox + speed + emission overlay.",
    )
    parser.add_argument(
        "--save-video",
        type=str,
        default=None,
        help=(
            "With --video: ALSO record the annotated output (bbox + brand + "
            "speed + per-vehicle CO₂ overlay) to this mp4 path. Useful for "
            "demos — gives a guaranteed-working pre-recording you can play "
            "back if a live run hits a glitch. Can be combined with --show."
        ),
    )
    parser.add_argument(
        "--yolo-weights",
        default="models/yolov8n.pt",
        help="Path to YOLOv8 weights (default: models/yolov8n.pt).",
    )
    parser.add_argument(
        "--brand-weights",
        default="models/car_brand_classification/outputs/dvm_car_v1/weights/best.pt",
        help=(
            "Path to the trained brand detector. When the file exists, every "
            "vehicle the YOLOv8 detector finds is matched against this "
            "detector's per-frame outputs via IoU; brand-aware emission "
            "multipliers (Tesla 0.30, Porsche 1.20, etc.) then apply. Pass an "
            "empty string to disable: --brand-weights ''"
        ),
    )
    parser.add_argument(
        "--brand-model",
        choices=("trained", "clip"),
        default="trained",
        help=(
            "Which brand identifier to use. 'trained' (default) is the local "
            "YOLOv8 model at --brand-weights (13 classes, fast). 'clip' uses "
            "OpenAI CLIP zero-shot via transformers (70+ brands, slower)."
        ),
    )
    parser.add_argument(
        "--brand-conf",
        type=float,
        default=None,
        help=(
            "Override the brand identifier's confidence threshold. "
            "Default 0.20 (lowered after the traffic_realistic fine-tune + "
            "temperature calibration on 2026-06-09 made low-confidence "
            "commits trustworthy). Raise to 0.30 for stricter 'right or "
            "absent' posture; lower to 0.15 only for very small vehicles."
        ),
    )
    parser.add_argument(
        "--brand-margin",
        type=float,
        default=None,
        help=(
            "Override the top-1 vs top-2 confidence margin (CLIP only). "
            "Default 0.05; lower to 0.02 for noisier footage."
        ),
    )
    parser.add_argument(
        "--brand-vote-min-count",
        type=int,
        default=None,
        help=(
            "Override the multi-frame voter's minimum-count gate. Default 3 "
            "(strict: a track needs 3 consistent observations to commit). "
            "On short clips (< 30s) where tracks don't persist across "
            "3 classify-cycles, pass --brand-vote-min-count 1 to commit "
            "after a single observation."
        ),
    )
    parser.add_argument(
        "--brand-vote-min-total",
        type=float,
        default=None,
        help=(
            "Override the voter's summed-confidence floor. Default 1.0. "
            "Lower (e.g. 0.30) for wide-angle footage where CLIP confidences "
            "are individually small."
        ),
    )
    parser.add_argument(
        "--pixels-per-meter",
        type=float,
        default=8.0,
        help=(
            "Camera-calibration constant for speed estimation. Increase for "
            "more-zoomed-in cameras, decrease for wide-angle. Default 8.0 is "
            "a reasonable starting point for typical intersection footage."
        ),
    )
    parser.add_argument(
        "--frame-skip",
        type=int,
        default=3,
        help=(
            "Process every Nth frame (default 3). 1 = process every frame "
            "(slowest, most accurate); 5 = process every 5th (3x faster, "
            "still smooth visually). YOLOv8n inference on CPU is the bottleneck."
        ),
    )
    parser.add_argument(
        "--runtime",
        choices=("auto", "onnx", "pytorch"),
        default="auto",
        help=(
            "Detection runtime. 'auto' (default) prefers ONNX via the CoreML "
            "execution provider on Apple Silicon (1.5x faster than PyTorch). "
            "'onnx' requires models/yolov8n.onnx to exist; 'pytorch' uses "
            "ultralytics' default backend."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.live and not os.getenv("DEMO_TOKEN"):
        print(
            "⚠ --live requires DEMO_TOKEN env var (engineer-role JWT). "
            "See docs/demos/pilot-pitch.md §3 to mint one against the demo "
            "Keycloak instance.",
            file=sys.stderr,
        )
        return 2

    # --video routes to the real-video pipeline instead of SUMO. Same state
    # file format → the Streamlit operator console renders both identically.
    if args.video:
        from pathlib import Path  # noqa: PLC0415

        from simulation.demo.video_source import (  # noqa: PLC0415
            VideoConfig,
            VideoEmissionPipeline,
        )

        video_path = Path(args.video)
        if not video_path.exists():
            print(f"✗ video not found: {video_path}", file=sys.stderr)
            return 2
        brand_weights = Path(args.brand_weights) if args.brand_weights else None
        cfg_kwargs = dict(
            video_path=video_path,
            pixels_per_meter=args.pixels_per_meter,
            yolo_weights=Path(args.yolo_weights),
            show=args.show,
            brand_weights=brand_weights,
            frame_skip=args.frame_skip,
            brand_model=args.brand_model,
            runtime=args.runtime,
        )
        if args.brand_conf is not None:
            cfg_kwargs["brand_conf_threshold"] = args.brand_conf
        if args.save_video:
            cfg_kwargs["save_video_path"] = Path(args.save_video)
        # --site-config (Phase 5 production pattern): a YAML file describes
        # every per-intersection knob. Overrides relevant VideoConfig
        # defaults (currently camera.pixels_per_meter) and replaces the
        # pipeline's chamber with one fully wired from the YAML.
        site_chamber = None
        site_region = None
        if args.site_config:
            from simulation.decision_chamber import (  # noqa: PLC0415
                SiteConfig,
                build_chamber_from_site_config,
            )

            site = SiteConfig.load(args.site_config)
            cfg_kwargs["pixels_per_meter"] = site.camera.pixels_per_meter
            if site.camera.homography_path:
                cfg_kwargs["homography_path"] = site.camera.homography_path
            if site.region.emission_overlay:
                cfg_kwargs["emission_overlay_path"] = site.region.emission_overlay
            if site.region.operator_locale:
                cfg_kwargs["operator_locale"] = site.region.operator_locale
            site_chamber = build_chamber_from_site_config(args.site_config)
            site_region = site.region
            print(
                f"  ✓ site config loaded: {site.intersection_id}  "
                f"px/m={site.camera.pixels_per_meter}  "
                f"ntcip={site.ntcip.controller_host}:{site.ntcip.controller_port}  "
                f"mqtt={'enabled' if site.mqtt.broker_host else 'disabled'}  "
                f"tsp={'enabled' if site.transit.feed_url else 'disabled'}  "
                f"audit={'sqlite' if site.audit.db_path else 'jsonl'}  "
                f"region={site.region.country_code or 'global'}  "
                f"locale={site.region.operator_locale}",
                flush=True,
            )

        cfg = VideoConfig(**cfg_kwargs)
        pipeline = VideoEmissionPipeline(cfg)
        if site_chamber is not None:
            # Replace the pipeline's default chamber with the YAML-driven
            # one. Stop the default's background threads first so they
            # don't double-bind ports.
            try:
                if hasattr(pipeline.chamber, "_bridge") and hasattr(
                    pipeline.chamber._bridge, "close"
                ):
                    pipeline.chamber._bridge.close()
            except Exception:
                pass
            pipeline.chamber = site_chamber
        # Voter overrides — patch decide_brand at module level so the same
        # path the orchestrator uses sees the overridden defaults. This is
        # the canonical extension point per ADR-0020 §3.
        if (
            args.brand_margin is not None
            or args.brand_vote_min_count is not None
            or args.brand_vote_min_total is not None
        ):
            import simulation.demo.brand_voting as bv  # noqa: PLC0415

            _orig = bv.decide_brand
            overrides: dict = {}
            if args.brand_vote_min_count is not None:
                overrides["min_count"] = args.brand_vote_min_count
            if args.brand_vote_min_total is not None:
                overrides["min_total_confidence"] = args.brand_vote_min_total
            if args.brand_margin is not None:
                overrides["min_margin"] = args.brand_margin

            def _patched(obs, **kw):
                merged = {**overrides, **kw}
                return _orig(obs, **merged)

            bv.decide_brand = _patched
            print(f"voter overrides: {overrides}", flush=True)
            # If --brand-margin was set, also forward it into CLIP's per-call
            # top-1/top-2 margin gate. (Voter's min_margin is different from
            # the CLIP per-frame margin; we honour --brand-margin for both.)
            if args.brand_margin is not None and hasattr(pipeline.brand_identifier, "_min_margin"):
                pipeline.brand_identifier._min_margin = args.brand_margin
        return pipeline.run()

    scenario_dir = _REPO_ROOT / "simulation" / "scenarios" / args.scenario
    return run_demo(
        scenario_dir,
        gui=args.gui,
        live=args.live,
        token=os.getenv("DEMO_TOKEN"),
        max_steps=args.max_steps,
    )


if __name__ == "__main__":
    sys.exit(main())
