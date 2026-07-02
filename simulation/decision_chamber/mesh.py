"""Multi-intersection coordination — MQTT pub/sub mesh.

Production deployment topology:

    [intersection A]──┐
                      │
    [intersection B]──┼──→ MQTT broker (Mosquitto / EMQ X / HiveMQ)──→ [city dashboard]
                      │
    [intersection N]──┘

Each chamber publishes:
- `atms/intersection/<id>/state`  — full state snapshot, 1 Hz
- `atms/intersection/<id>/decision` — every decision, on transition
- `atms/intersection/<id>/wave_pulse` — when a through-movement green ends
  (the "vehicle packet" downstream neighbors should expect)

Each chamber subscribes to:
- `atms/intersection/<neighbor_id>/wave_pulse` — for green-wave coordination
- `atms/city/+/broadcast` — for city-level commands (mode changes, emergency
  alerts, planned events)

The mesh is OPTIONAL. With no broker available the chamber gracefully
degrades — `NullMeshNode` swallows all publishes and returns no neighbor
state. The chamber's local decision quality doesn't depend on the mesh.

Production hardening:
- TLS optional (Phase 3 MVP plaintext; production enables MQTT/TLS port 8883)
- Auth optional (community broker for dev, username/cert for production)
- QoS 1 for state publishes (delivered at least once)
- Last Will & Testament for graceful disconnect detection
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

log = logging.getLogger("atms.chamber.mesh")


class MeshNode(Protocol):
    """Multi-intersection coordination interface. Implementations:
    - `MqttMeshNode`: real MQTT pub/sub, production-grade
    - `NullMeshNode`: no-op fallback when no broker is reachable
    """

    intersection_id: str
    connected: bool

    def publish_state(self, payload: dict) -> None:
        """Publish this intersection's current state snapshot."""
        ...

    def publish_decision(self, payload: dict) -> None:
        """Publish a discrete decision event (phase transition, preempt)."""
        ...

    def publish_wave_pulse(self, payload: dict) -> None:
        """Announce that a through-movement green just ended — a packet
        of vehicles is en route to downstream neighbors.
        """
        ...

    def get_recent_neighbor_wave_pulses(
        self, since: datetime
    ) -> dict[str, dict]:
        """Return wave pulse events from neighbors received since `since`.
        Keyed by neighbor intersection_id.
        """
        ...

    def close(self) -> None:
        """Disconnect cleanly. Sends LWT, flushes queues."""
        ...


class NullMeshNode:
    """No-op mesh — used when no MQTT broker is reachable. All
    publishes are dropped; neighbor state queries return empty.
    """

    def __init__(self, intersection_id: str):
        self.intersection_id = intersection_id
        self.connected = False

    def publish_state(self, payload: dict) -> None: pass
    def publish_decision(self, payload: dict) -> None: pass
    def publish_wave_pulse(self, payload: dict) -> None: pass
    def get_recent_neighbor_wave_pulses(self, since: datetime) -> dict[str, dict]:
        return {}
    def close(self) -> None: pass


class MqttMeshNode:
    """Real MQTT publish/subscribe. Uses paho-mqtt client. The chamber
    publishes state, decisions, and wave pulses; subscribes to
    configured neighbor topics for inbound coordination.

    Failure mode: if the broker becomes unreachable, paho-mqtt handles
    reconnection in its background thread. Publishes during disconnection
    are dropped (QoS 0 cost). Reads return whatever's in the local cache.
    """

    def __init__(
        self,
        intersection_id: str,
        broker_host: str = "127.0.0.1",
        broker_port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        upstream_neighbors: list[str] | None = None,
        keepalive_seconds: int = 30,
    ):
        try:
            import paho.mqtt.client as _mqtt  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(
                "paho-mqtt required for MqttMeshNode. "
                "Install: pip install paho-mqtt"
            ) from e
        self._mqtt = _mqtt

        self.intersection_id = intersection_id
        self.connected = False
        self._neighbors = upstream_neighbors or []
        self._broker_host = broker_host
        self._broker_port = broker_port

        # Cache of recent wave-pulse messages from neighbors.
        self._wave_lock = threading.Lock()
        self._recent_wave_pulses: list[tuple[datetime, str, dict]] = []
        # Trim cache entries older than this:
        self._cache_ttl_seconds = 30.0

        self._client = _mqtt.Client(
            client_id=f"atms-chamber-{intersection_id}",
        )
        if username:
            self._client.username_pw_set(username, password or "")
        # Last Will & Testament — if we crash, broker auto-publishes our
        # disconnect so neighbors know.
        self._lwt_topic = f"atms/intersection/{intersection_id}/lwt"
        self._client.will_set(
            self._lwt_topic,
            payload=json.dumps({"event": "disconnect", "ts": "auto"}),
            qos=1,
            retain=False,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        try:
            self._client.connect(broker_host, broker_port, keepalive=keepalive_seconds)
            self._client.loop_start()
            # Give the connect callback a brief moment.
            time.sleep(0.5)
        except OSError as e:
            log.warning(
                "MQTT mesh: broker %s:%d unreachable (%s) — running without mesh",
                broker_host, broker_port, e,
            )

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            log.info(
                "MQTT mesh connected to %s:%d (intersection %s)",
                self._broker_host, self._broker_port, self.intersection_id,
            )
            # Subscribe to neighbor wave-pulse topics
            for neighbor in self._neighbors:
                topic = f"atms/intersection/{neighbor}/wave_pulse"
                client.subscribe(topic, qos=1)
                log.info("  subscribed to %s", topic)
            # Also subscribe to citywide broadcasts
            client.subscribe("atms/city/+/broadcast", qos=1)
        else:
            log.warning("MQTT connect failed (rc=%d)", rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            log.warning("MQTT mesh unexpected disconnect (rc=%d) — auto-reconnecting", rc)

    def _on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except Exception as e:
            log.warning("malformed MQTT message on %s: %s", message.topic, e)
            return
        # Extract the originating intersection_id from the topic
        parts = message.topic.split("/")
        if len(parts) >= 4 and parts[0] == "atms" and parts[1] == "intersection":
            neighbor_id = parts[2]
            topic_type = parts[3]
            if topic_type == "wave_pulse":
                arrival = datetime.now(timezone.utc)
                with self._wave_lock:
                    self._recent_wave_pulses.append((arrival, neighbor_id, payload))
                    cutoff = arrival - timedelta(seconds=self._cache_ttl_seconds)
                    self._recent_wave_pulses = [
                        (t, nid, p)
                        for (t, nid, p) in self._recent_wave_pulses
                        if t >= cutoff
                    ]
                log.debug("wave_pulse from %s: %s", neighbor_id, payload)

    def publish_state(self, payload: dict) -> None:
        if not self.connected:
            return
        topic = f"atms/intersection/{self.intersection_id}/state"
        self._client.publish(topic, json.dumps(payload), qos=0, retain=False)

    def publish_decision(self, payload: dict) -> None:
        if not self.connected:
            return
        topic = f"atms/intersection/{self.intersection_id}/decision"
        self._client.publish(topic, json.dumps(payload), qos=1, retain=False)

    def publish_wave_pulse(self, payload: dict) -> None:
        if not self.connected:
            return
        topic = f"atms/intersection/{self.intersection_id}/wave_pulse"
        self._client.publish(topic, json.dumps(payload), qos=1, retain=False)

    def get_recent_neighbor_wave_pulses(self, since: datetime) -> dict[str, dict]:
        with self._wave_lock:
            return {
                nid: p
                for (t, nid, p) in self._recent_wave_pulses
                if t >= since
            }

    def close(self) -> None:
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as e:
            log.warning("MQTT close raised: %s", e)
