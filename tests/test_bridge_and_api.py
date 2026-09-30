import json

import httpx
import pytest
from fixtures import resources, update

from hue_mqtt.api import HueClient, HueError
from hue_mqtt.bridge import Bridge
from hue_mqtt.config import Config, ConfigError

ENV = {"HUE_BRIDGE_HOST": "192.168.1.2", "HUE_APPLICATION_KEY": "key", "MQTT_HOST": "mosquitto"}


class FakeBridgeApi:
    """Answers like a Hue bridge and records updates."""

    def __init__(self) -> None:
        self.updates: list[tuple[str, dict]] = []
        self.key = "key"

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("hue-application-key") != self.key:
            return httpx.Response(403)
        kind = request.url.path.removeprefix("/clip/v2/resource/")
        if request.method == "PUT":
            body = json.loads(request.content)
            if body.get("color_temperature", {}).get("mirek", 300) > 500:
                return httpx.Response(400, json={"errors": [{"description": "invalid value"}], "data": []})
            self.updates.append((kind, body))
            return httpx.Response(200, json={"errors": [], "data": [{"rid": kind.split("/")[1]}]})
        return httpx.Response(200, json={"errors": [], "data": resources().get(kind, [])})


class FakeMqtt:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload))

    def last(self, topic):
        return next((payload for t, payload in reversed(self.published) if t == topic), None)


@pytest.fixture
def api():
    return FakeBridgeApi()


@pytest.fixture
def bridge(api):
    client = HueClient(httpx.Client(base_url="https://bridge", headers={"hue-application-key": "key"}, transport=httpx.MockTransport(api.handler)))
    bridge = Bridge(Config.from_env({**ENV, "ENABLE_CONTROL": "true"}), client, client)
    bridge.mqtt = FakeMqtt()
    bridge.refresh()
    return bridge


def test_refresh_publishes_state_and_status(bridge):
    assert bridge.mqtt.last("hue/status") == "online"
    state = json.loads(bridge.mqtt.last("hue/state"))
    assert [light["name"] for light in state["lights"]] == ["Ceiling", "Floor lamp"]
    assert state["bridge"]["stream"] == "disconnected"


def test_stream_events_update_state_and_publish_presses(bridge):
    bridge.handle("stream", True)
    bridge.handle("events", update({"id": "gl-bed", "type": "grouped_light", "on": {"on": True}}))
    room = next(room for room in json.loads(bridge.mqtt.last("hue/state"))["rooms"] if room["id"] == "room-bed")
    assert room["on"] is True

    bridge.handle("events", update({"id": "btn-1", "type": "button", "button": {"button_report": {"event": "long_press"}}}))
    assert json.loads(bridge.mqtt.last("hue/event")) == {"switch": "Bedroom dimmer", "switch_id": "dev-dimmer", "room": "Bedroom", "button": 1, "event": "long_press"}


def test_commands_go_to_the_right_resource(bridge, api):
    bridge.handle("command", ("room/room-living", "off"))
    bridge.handle("command", ("light/light-1", '{"kelvin": 2000}'))
    # A white-only lamp can't do colour temperature: that part is dropped, the brightness still applies
    bridge.handle("command", ("light/light-2", '{"brightness": 20, "kelvin": 3000}'))
    assert api.updates == [
        ("grouped_light/gl-living", {"on": {"on": False}}),
        ("light/light-1", {"color_temperature": {"mirek": 500}}),
        ("light/light-2", {"dimming": {"brightness": 20.0}, "on": {"on": True}}),
    ]


def test_bad_or_unknown_commands_are_ignored(bridge, api):
    bridge.handle("command", ("light/nope", "on"))
    bridge.handle("command", ("light/light-1", "sideways"))
    assert api.updates == []


def test_unreachable_bridge_goes_offline(api):
    def down(request):
        raise httpx.ConnectError("no route")

    client = HueClient(httpx.Client(base_url="https://bridge", transport=httpx.MockTransport(down)))
    bridge = Bridge(Config.from_env(ENV), client, client)
    bridge.mqtt = FakeMqtt()
    bridge.refresh()
    assert bridge.mqtt.last("hue/status") == "offline"


def test_wrong_key(api):
    api.key = "other"
    client = HueClient(httpx.Client(base_url="https://bridge", headers={"hue-application-key": "key"}, transport=httpx.MockTransport(api.handler)))
    with pytest.raises(HueError, match="pair again"):
        client.resources("light")


def test_config():
    config = Config.from_env(ENV)
    assert (config.mqtt_topic_prefix, config.poll_interval, config.enable_control) == ("hue", 300, False)
    with pytest.raises(ConfigError, match="HUE_APPLICATION_KEY"):
        Config.from_env({"HUE_BRIDGE_HOST": "x", "MQTT_HOST": "y"})
    with pytest.raises(ConfigError):
        Config.from_env({**ENV, "POLL_INTERVAL": "5"})
