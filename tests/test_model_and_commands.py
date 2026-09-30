import json

import pytest
from fixtures import resources, update

from hue_mqtt.api import parse_event_stream
from hue_mqtt.commands import CommandError, parse_command
from hue_mqtt.model import Bridge


@pytest.fixture
def bridge():
    bridge = Bridge()
    bridge.load(resources())
    return bridge


def test_state(bridge):
    state = bridge.to_state(stream_connected=True)
    assert state["bridge"] == {"id": "ecb5fafffe000001", "stream": "connected"}
    assert state["lights"] == [
        {"id": "light-2", "name": "Ceiling", "room": "Living room", "on": False, "brightness": 100, "kelvin": None,
         "kelvin_range": None, "color": False, "reachable": False},
        {"id": "light-1", "name": "Floor lamp", "room": "Living room", "on": True, "brightness": 54, "kelvin": 2732,
         "kelvin_range": [2000, 6536], "color": True, "reachable": True},
    ]
    assert state["rooms"] == [
        {"id": "room-bed", "type": "room", "name": "Bedroom", "on": False, "brightness": None, "lights": []},
        {"id": "room-living", "type": "room", "name": "Living room", "on": True, "brightness": 54, "lights": ["light-1", "light-2"]},
        {"id": "zone-down", "type": "zone", "name": "Downstairs", "on": True, "brightness": 54, "lights": ["light-1"]},
    ]
    assert state["switches"] == [{"id": "dev-dimmer", "name": "Bedroom dimmer", "room": "Bedroom", "battery": 1, "battery_state": "critical"}]


def test_partial_updates_merge(bridge):
    changed, presses = bridge.apply(update({"id": "light-2", "type": "light", "on": {"on": True}, "dimming": {"brightness": 30.0}}))
    assert changed and presses == []
    light = next(light for light in bridge.to_state(True)["lights"] if light["id"] == "light-2")
    assert (light["on"], light["brightness"]) == (True, 30)
    # Untouched fields survive a partial update
    assert bridge.resources["light"]["light-2"]["metadata"]["name"] == "Ceiling"


def test_button_presses_become_events(bridge):
    changed, presses = bridge.apply(update({
        "id": "btn-4", "type": "button",
        "button": {"button_report": {"event": "initial_press", "updated": "2026-09-30T18:00:00Z"}, "last_event": "initial_press"},
    }))
    assert not changed
    assert [press.to_json() for press in presses] == [
        {"switch": "Bedroom dimmer", "switch_id": "dev-dimmer", "room": "Bedroom", "button": 4, "event": "initial_press"}
    ]


def test_add_and_delete(bridge):
    bridge.apply(update({"id": "light-3", "type": "light", "owner": {"rid": "dev-x", "rtype": "device"}, "metadata": {"name": "New"}, "on": {"on": False}}, kind="add"))
    assert "light-3" in bridge.resources["light"]
    bridge.apply(update({"id": "light-3", "type": "light"}, kind="delete"))
    assert "light-3" not in bridge.resources["light"]


def test_targets(bridge):
    assert bridge.target("light", "light-1") == ("light", "light-1")
    assert bridge.target("room", "room-living") == ("grouped_light", "gl-living")
    assert bridge.target("zone", "zone-down") == ("grouped_light", "gl-down")
    assert bridge.target("room", "nope") is None
    assert bridge.target("light", "nope") is None


def test_parse_event_stream():
    batch = [{"type": "update", "data": [{"id": "light-1", "type": "light", "on": {"on": False}}]}]
    lines = [": hi", "", "id: 1:0", f"data: {json.dumps(batch)}", "", "data: not json", ""]
    assert list(parse_event_stream(lines)) == [batch]


@pytest.mark.parametrize("target, payload, body", [
    ("light/l1", "on", {"on": {"on": True}}),
    ("room/r1", " OFF ", {"on": {"on": False}}),
    ("light/l1", '{"brightness": 40}', {"dimming": {"brightness": 40.0}, "on": {"on": True}}),
    ("light/l1", '{"brightness": 0}', {"on": {"on": False}}),
    ("zone/z1", '{"on": true, "kelvin": 2700, "transition": 1.5}',
     {"on": {"on": True}, "color_temperature": {"mirek": 370}, "dynamics": {"duration": 1500}}),
])
def test_commands(target, payload, body):
    command = parse_command(target, payload)
    assert (command.kind, command.id, command.body) == (target.split("/")[0], target.split("/")[1], body)


@pytest.mark.parametrize("target, payload", [
    ("scene/s1", "on"),
    ("light/", "on"),
    ("light/l1", "maybe"),
    ("light/l1", "[1]"),
    ("light/l1", '{"brightness": 120}'),
    ("light/l1", '{"kelvin": 9000}'),
    ("light/l1", '{"on": "yes"}'),
    ("light/l1", '{"transition": 2}'),
])
def test_bad_commands(target, payload):
    with pytest.raises(CommandError):
        parse_command(target, payload)
