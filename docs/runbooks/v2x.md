# Runbook: V2X interface (Phase C8)

**Audience:** Operator, integration engineer for a V2X-equipped pilot.
**Design:** [ADR-0019](../adr/0019-v2x-bsm-stub.md).
**Code:** [`shared/atms_common/v2x.py`](../../shared/atms_common/v2x.py), [`services/v2x-interface/`](../../services/v2x-interface/).

---

## 1. What the stub does

- Defines the SAE J2735 BSM subset ATMS consumes (`shared/atms_common/v2x.py`).
- Runs an `v2x-interface` service that:
  - Accepts simulated BSMs via `POST /admin/inject` (engineer+ JWT).
  - Will subscribe to MQTT in production deployments (the bridge code is per-OBU and per-deployment).
  - Translates EV / transit BSMs to A7 `PreemptRequest`s and forwards them to traffic-controller (the HTTP POST itself is a follow-up — needs in-cluster service URLs and mTLS).

## 2. Local injection example

```bash
TOKEN="<engineer-JWT>"
curl -X POST http://localhost:8009/admin/inject \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "temporary_id": "TMP-001",
        "intersection_id": 1,
        "message_type": "regular",
        "vehicle_class": "emergency",
        "latitude_deg": 52.5,
        "longitude_deg": 13.4,
        "speed_mps": 14.0,
        "heading_deg": 90.0,
        "approach": "east_west",
        "distance_to_intersection_m": 80.0,
        "siren_active": true,
        "transponder_id": "EV-7"
      }'
```

Response (preempt-eligible):

```json
{
  "accepted": true,
  "temporary_id": "TMP-001",
  "intersection_id": 1,
  "vehicle_class": "emergency",
  "principal_sub": "alice",
  "preempt_request": {
    "approach": "east_west",
    "priority": "fire_rescue",
    "transponder_id": "EV-7",
    "valid_until_ns": 1735000000000000000
  }
}
```

The traffic-controller side accepts this `PreemptRequest` via the A7 endpoint and arms the preempt. In the simulator (C3) this lets us exercise the EV-preempt scenario end-to-end without a real OBU.

## 3. Production deployment

When a pilot has real V2X OBUs:

1. Choose the OBU's MQTT broker (or substitute provider-specific transport).
2. Configure topic per ADR-0019: `v2x/<intersection_id>/bsm`.
3. The v2x-interface service subscribes locally (paho-mqtt). Bridge code: each MQTT payload is decoded via `BSMMessage.from_dict()` and forwarded to Kafka topic `v2x.bsm.<intersection_id>`.
4. Cryptographic signature verification (J2735 §SecMessage) lands when the operator's PKI is wired (a separate ADR).

## 4. Decision-engine integration

`V2X_WEIGHT` env var (default `0.0`) on decision-engine controls blending:

- `0.0`: ignore V2X.
- `0.5`: average camera + V2X vehicle counts per approach.
- `1.0`: V2X-only (cameras as fallback).

Operator should ramp this gradually after a 7-day observation period showing V2X counts track camera counts to within ±10%.

## 5. EV preempt — preferred path

ADR-0004 §EV preempt: this is the **dedicated-channel** alternative to vision-based siren/strobe detection. When V2X-equipped EVs become available in the pilot region, this path replaces any vision-based heuristic.

The audit chain:
1. EV OBU emits BSM with `siren_active=true`, `vehicle_class=emergency`.
2. v2x-interface receives → `BSMMessage` → `bsm_to_preempt_request()`.
3. Forwarded as `PreemptRequest` to traffic-controller's A7 path.
4. Failsafe controller arms preempt, emits structured `preempt_arm` event.
5. Loki + Tempo (B2/B3) link the BSM → preempt → mode-transition chain by `trace_id`.

## 6. Identity model

- Each BSM carries a **rotating** `temporary_id` (J2735 §6). The bridge does NOT stitch identity across rotations.
- EV / transit BSMs additionally carry a persistent `transponder_id` — used for the preempt's audit trail.
- `signature_valid` is `false` in the stub. Production: `true` only after the operator's PKI chain verifies the BSM's 1609.2 certificate.

## 7. Out of scope here

- ASN.1 BER/DER decoding of real J2735 wire-format. Stub uses JSON.
- C-V2X PC5 sidelink. Cellular operator-specific.
- MAP/SPaT messages. C8 is BSM-only.
- Persistent vehicle re-identification across `temporary_id` rotations. By design — defeats J2735's privacy model.
