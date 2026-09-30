import json
import logging
import queue
import threading
import time

import httpx
import paho.mqtt.client as mqtt

from .api import HueClient, HueError
from .commands import Command, CommandError, parse_command
from .config import Config
from .model import Bridge as HueModel

log = logging.getLogger(__name__)

# Reconnect the event stream quickly a few times, then back off
STREAM_DELAYS = (2, 5, 10, 30, 60)


class Bridge:
    def __init__(self, config: Config, client: HueClient, stream_client: HueClient) -> None:
        self.config = config
        self.client = client
        self.stream_client = stream_client
        self.status_topic = f"{config.mqtt_topic_prefix}/status"
        self.state_topic = f"{config.mqtt_topic_prefix}/state"
        self.event_topic = f"{config.mqtt_topic_prefix}/event"
        self.command_prefix = f"{config.mqtt_topic_prefix}/set/"
        # Commands (MQTT thread) and stream events (stream thread) are handled one at a time by the main loop
        self.inbox: queue.Queue[tuple[str, object]] = queue.Queue()
        self.model = HueModel()
        self.loaded = False
        self.stream_connected = False
        self.last_status: str | None = None
        self.last_state: str | None = None
        self.stopping = threading.Event()
        self.mqtt = self._create_mqtt_client()

    def _create_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="hue-mqtt")
        if self.config.mqtt_username:
            client.username_pw_set(self.config.mqtt_username, self.config.mqtt_password)
        client.will_set(self.status_topic, "offline", retain=True)
        client.on_connect = self._on_connect
        client.on_disconnect = lambda _client, _userdata, _flags, reason, _props: log.warning("MQTT disconnected: %s", reason)
        client.on_message = lambda _client, _userdata, message: self.inbox.put(
            ("command", (message.topic.removeprefix(self.command_prefix), message.payload.decode(errors="replace")))
        )
        return client

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, reason, _props) -> None:
        log.info("MQTT connected: %s", reason)
        # Re-publish on reconnect, since the broker may have fired our will in the meantime
        if self.last_status:
            client.publish(self.status_topic, self.last_status, retain=True)
        if self.config.enable_control:
            client.subscribe(f"{self.command_prefix}#")
            log.info("Control enabled, listening on %s#", self.command_prefix)

    def _set_status(self, status: str) -> None:
        if status != self.last_status:
            self.mqtt.publish(self.status_topic, status, retain=True)
            self.last_status = status

    def _publish(self) -> None:
        state = json.dumps(self.model.to_state(self.stream_connected))
        if state != self.last_state:
            self.mqtt.publish(self.state_topic, state, retain=True)
            self.last_state = state

    def refresh(self) -> None:
        try:
            self.model.load(self.client.everything())
        except (httpx.HTTPError, HueError, ValueError) as error:
            log.warning("Hue bridge unreachable: %s", error)
            self._set_status("offline")
            return
        self.loaded = True
        self._publish()
        self._set_status("online")

    # --- event stream (own thread) ---------------------------------------------

    def _stream(self) -> None:
        attempt = 0
        while not self.stopping.is_set():
            try:
                for batch in self.stream_client.events(on_open=lambda: self.inbox.put(("stream", True))):
                    attempt = 0
                    self.inbox.put(("events", batch))
                # The bridge closed the stream; reconnect
            except (httpx.HTTPError, HueError) as error:
                log.warning("Hue event stream: %s", error)
            self.inbox.put(("stream", False))
            delay = STREAM_DELAYS[min(attempt, len(STREAM_DELAYS) - 1)]
            attempt += 1
            self.stopping.wait(delay)

    # --- main loop ---------------------------------------------------------------

    def handle(self, kind: str, data) -> None:
        if kind == "events":
            changed, presses = self.model.apply(data)
            for press in presses:
                log.info("Button %s on %s: %s", press.button, press.switch, press.event)
                self.mqtt.publish(self.event_topic, json.dumps(press.to_json()))
            if changed:
                self._publish()
        elif kind == "stream":
            if data and not self.stream_connected:
                log.info("Hue event stream connected")
                # Catch up on whatever changed while it was down
                self.refresh()
            self.stream_connected = bool(data)
            self._publish()
        elif kind == "command":
            self.execute(*data)

    def execute(self, target: str, payload: str) -> None:
        try:
            command = parse_command(target, payload)
        except CommandError as error:
            log.warning("Ignoring command: %s", error)
            return
        resource = self.model.target(command.kind, command.id)
        if resource is None:
            log.warning("Ignoring command for unknown %s %s", command.kind, command.id)
            return
        body = self._fit(resource, command)
        try:
            self.client.update(*resource, body)
        except (httpx.HTTPError, HueError) as error:
            log.error("Command %s failed: %s", command.describe(), error)
            return
        log.info("Executed %s", command.describe())

    def _fit(self, resource: tuple[str, str], command: Command) -> dict:
        """Drops or clamps what a single light can't do; the bridge rejects the whole command otherwise."""
        body = dict(command.body)
        if resource[0] != "light" or "color_temperature" not in body:
            return body
        light = self.model.resources["light"][resource[1]]
        schema = (light.get("color_temperature") or {}).get("mirek_schema")
        if not schema:
            body.pop("color_temperature")
        else:
            mirek = body["color_temperature"]["mirek"]
            body["color_temperature"] = {"mirek": min(max(mirek, schema["mirek_minimum"]), schema["mirek_maximum"])}
        return body

    def run(self) -> None:
        self.mqtt.connect_async(self.config.mqtt_host, self.config.mqtt_port)
        self.mqtt.loop_start()
        self.refresh()
        threading.Thread(target=self._stream, name="hue-events", daemon=True).start()
        next_poll = time.monotonic() + self.config.poll_interval
        try:
            while True:
                try:
                    kind, data = self.inbox.get(timeout=max(0.0, next_poll - time.monotonic()))
                except queue.Empty:
                    self.refresh()
                    next_poll = time.monotonic() + self.config.poll_interval
                    continue
                self.handle(kind, data)
        finally:
            self.stopping.set()
            self.mqtt.publish(self.status_topic, "offline", retain=True).wait_for_publish(timeout=2)
            self.mqtt.loop_stop()
            self.mqtt.disconnect()
