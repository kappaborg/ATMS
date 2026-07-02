"""ATMS live-demo orchestrator (Phase C3 demo extension).

Spins up the SUMO `demo` scenario in sumo-gui, drives the traffic light via
the same `default_decision_fn` the regression harness uses, and on a scripted
sim-time timeline fires presenter cues + (optionally) HTTP POSTs to the live
service stack so the audience sees Grafana / Loki / Tempo light up.

Runbook: docs/demos/pilot-pitch.md
"""
