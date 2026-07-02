# ADR-0019: V2X (J2735 BSM over MQTT) stub interface

**Status:** Accepted
**Date:** 2026-05-30
**Closes:** PRODUCTION_GAPS.md gap #23 (Phase C8)

## Context

Connected-vehicle (V2X) data — Basic Safety Messages (BSM) sent by vehicles to roadside infrastructure — is the direction the industry is moving (SAE J2735, ETSI ITS-G5 in Europe, C-V2X PC5). Even before any production deployment, the system needs:

1. A schema for BSM ingestion that won't change when real V2X arrives.
2. A stub service that lets simulators feed simulated BSMs in, so we can validate "EV approach detected via V2X before camera" scenarios end-to-end (this is the C3 EV-preempt scenario's preferred path).
3. A clear non-merging boundary between V2X-reported vehicles and camera-detected vehicles, so the decision-engine can optionally weight them without losing observability.

## Decision

### Wire protocol: MQTT, topic `v2x/<intersection_id>/bsm`

MQTT chosen because:
- It's the de-facto V2X transport at the edge — Cohda, Kapsch, and most C-V2X OBUs publish to local MQTT brokers.
- Async-friendly, low-overhead, runs in-cluster (Mosquitto / EMQX).
- Easy to bridge to Kafka for downstream consumers (the v2x-interface service does this bridge).

In a real deployment the broker also runs at the edge co-located with the C2 edge agent; the v2x-interface service subscribes locally. In a cloud-only deployment, the OBU-to-cloud path goes through whatever the operator's V2X provider offers — the schema below is the contract.

### Message schema — `BSMMessage` (subset of SAE J2735)

```python
class BSMMessageType(str, Enum):
    REGULAR = "regular"          # standard 10 Hz BSM
    EVENT = "event"              # extended-data BSM (siren active, hazard, etc.)

class V2XVehicleClass(str, Enum):
    PASSENGER = "passenger"
    TRUCK = "truck"
    BUS = "bus"
    MOTORCYCLE = "motorcycle"
    EMERGENCY = "emergency"      # police / fire / ambulance — drives A7 preempt
    TRANSIT = "transit"          # bus rapid transit / tram — drives A7 transit preempt

@dataclass(frozen=True)
class BSMMessage:
    temporary_id: str             # rotates per SAE J2735 §6 (~5 min)
    intersection_id: int           # which intersection this BSM is approaching
    received_at: SyncedTimestamp   # C5 timestamp at the v2x-interface boundary
    message_type: BSMMessageType
    vehicle_class: V2XVehicleClass
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    speed_mps: float
    heading_deg: float             # 0-360, 0 = north
    acceleration_mps2: float
    approach: Approach             # derived: NS or EW
    distance_to_intersection_m: float
    # Emergency vehicles populate these fields.
    siren_active: bool = False
    light_bar_active: bool = False
    # Public-transit vehicles populate these.
    transit_route_id: str = ""
    # Identity attestation (Phase B5 mTLS + future PKI).
    signature_valid: bool = False
    transponder_id: str = ""
```

### Identity model

- Each BSM carries a `temporary_id` that rotates per SAE J2735 §6 (~5 min). The v2x-interface service does **not** stitch IDs across rotations — that would defeat the purpose.
- `transponder_id` is the persistent identifier of the EV / transit transponder, used for A7 preempt audit. Present only on `EMERGENCY` / `TRANSIT` messages.
- `signature_valid` indicates whether the BSM's cryptographic signature verified. In the stub it's always `false`; production verifies against the operator's PKI.

### Decision-engine integration (optional, behind a flag)

- The decision-engine subscribes to a Kafka topic `v2x.bsm.<intersection_id>` that the v2x-interface service publishes to.
- A `V2X_WEIGHT` setting (default 0.0, range 0–1) lets the operator gradually turn on V2X-informed decisions.
  - 0.0 (default): ignore BSMs entirely; camera-only decisions.
  - 0.5: average camera + V2X vehicle counts.
  - 1.0: V2X-only (cameras as backup).
- The failsafe controller (A1) is unaffected — it operates on the decision-engine's output regardless of V2X.

### Emergency-vehicle path

When a BSM with `vehicle_class=EMERGENCY` and `siren_active=true` arrives:
- The v2x-interface service translates it to an A7 `PreemptRequest` (already defined in `shared/atms_common/preempt.py`) and POSTs to `services/traffic-controller/control/preempt`.
- The `transponder_id` from the BSM becomes the `transponder_id` of the preempt request — the controller's audit log links the two.

This is the **preferred** path for EV preempt going forward (per ADR-0004: dedicated channel, not vision). C8 ships the stub; production rollout is per-pilot once the operator's EV fleet has V2X OBUs.

### Stub service: `services/v2x-interface/`

- B1 bootstrap: configure_logging + configure_tracing + HealthRouter + Kafka producer.
- MQTT consumer (paho-mqtt-async-friendly wrapper) reads from `v2x/<intersection_id>/bsm`, validates schema, republishes to Kafka.
- `POST /admin/inject` endpoint (engineer+ via A6) for operators to inject test BSMs without an MQTT broker. Useful for the C3 SUMO harness.

The "stub" qualifier means: the schema is real, the bridge is real, but the MQTT producer side is provider-specific and not implemented here. A real deployment substitutes the OBU's MQTT publisher; everything downstream stays unchanged.

## Out of scope for C8

- **Cryptographic signature verification.** Needs operator PKI / 1609.2 certificate chain. Stub accepts all messages.
- **ASN.1 BER/DER encoding of real J2735 messages.** Real V2X uses ASN.1; the stub uses JSON over MQTT for simplicity. A future ADR documents the ASN.1 ↔ JSON bridge.
- **MAP messages, SPaT messages** (other J2735 types). C8 is BSM-only.
- **Direct C-V2X PC5 (sidelink) ingestion.** That requires specific radios and kernel modules; far beyond Phase C scope.

## Consequences

- New service: `services/v2x-interface/`. Minimal — bridge code.
- New shared module: `shared/atms_common/v2x.py` — schema + validator.
- New runtime dep: `paho-mqtt` (production); pure-Python validation in the stub means tests don't need MQTT.
- The decision-engine gains a `V2X_WEIGHT` config; default 0.0 means existing behavior is unchanged.
- The A7 preempt path now has a "via V2X" trigger in addition to operator API.
- A future ADR (C8 follow-up) wires the real J2735/ASN.1 once a pilot operator's V2X provider is selected.
