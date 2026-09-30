import copy

# Shaped like a real bridge's CLIP v2 resources, trimmed to what the bridge reads
_RESOURCES = {
    "bridge": [{"id": "br", "bridge_id": "ecb5fafffe000001", "type": "bridge"}],
    "device": [
        {"id": "dev-lamp", "type": "device", "metadata": {"name": "Floor lamp"}, "product_data": {"product_name": "Hue color lamp"},
         "services": [{"rid": "light-1", "rtype": "light"}, {"rid": "zc-lamp", "rtype": "zigbee_connectivity"}]},
        {"id": "dev-bulb", "type": "device", "metadata": {"name": "Ceiling"}, "product_data": {"product_name": "Hue white lamp"},
         "services": [{"rid": "light-2", "rtype": "light"}, {"rid": "zc-bulb", "rtype": "zigbee_connectivity"}]},
        {"id": "dev-dimmer", "type": "device", "metadata": {"name": "Bedroom dimmer"}, "product_data": {"product_name": "Hue dimmer switch"},
         "services": [{"rid": "btn-1", "rtype": "button"}, {"rid": "btn-4", "rtype": "button"}, {"rid": "power-1", "rtype": "device_power"}]},
    ],
    "light": [
        {"id": "light-1", "type": "light", "owner": {"rid": "dev-lamp", "rtype": "device"}, "metadata": {"name": "Floor lamp"},
         "on": {"on": True}, "dimming": {"brightness": 54.3},
         "color_temperature": {"mirek": 366, "mirek_valid": True, "mirek_schema": {"mirek_minimum": 153, "mirek_maximum": 500}},
         "color": {"xy": {"x": 0.45, "y": 0.41}}},
        {"id": "light-2", "type": "light", "owner": {"rid": "dev-bulb", "rtype": "device"}, "metadata": {"name": "Ceiling"},
         "on": {"on": False}, "dimming": {"brightness": 100.0}},
    ],
    "room": [
        {"id": "room-living", "type": "room", "metadata": {"name": "Living room"},
         "children": [{"rid": "dev-lamp", "rtype": "device"}, {"rid": "dev-bulb", "rtype": "device"}],
         "services": [{"rid": "gl-living", "rtype": "grouped_light"}]},
        {"id": "room-bed", "type": "room", "metadata": {"name": "Bedroom"},
         "children": [{"rid": "dev-dimmer", "rtype": "device"}],
         "services": [{"rid": "gl-bed", "rtype": "grouped_light"}]},
    ],
    "zone": [
        {"id": "zone-down", "type": "zone", "metadata": {"name": "Downstairs"},
         "children": [{"rid": "light-1", "rtype": "light"}],
         "services": [{"rid": "gl-down", "rtype": "grouped_light"}]},
    ],
    "grouped_light": [
        {"id": "gl-living", "type": "grouped_light", "owner": {"rid": "room-living", "rtype": "room"}, "on": {"on": True}, "dimming": {"brightness": 54.3}},
        {"id": "gl-bed", "type": "grouped_light", "owner": {"rid": "room-bed", "rtype": "room"}, "on": {"on": False}},
        {"id": "gl-down", "type": "grouped_light", "owner": {"rid": "zone-down", "rtype": "zone"}, "on": {"on": True}, "dimming": {"brightness": 54.3}},
    ],
    "zigbee_connectivity": [
        {"id": "zc-lamp", "type": "zigbee_connectivity", "owner": {"rid": "dev-lamp", "rtype": "device"}, "status": "connected"},
        {"id": "zc-bulb", "type": "zigbee_connectivity", "owner": {"rid": "dev-bulb", "rtype": "device"}, "status": "connectivity_issue"},
    ],
    "device_power": [
        {"id": "power-1", "type": "device_power", "owner": {"rid": "dev-dimmer", "rtype": "device"},
         "power_state": {"battery_state": "critical", "battery_level": 1}},
    ],
    "button": [
        {"id": "btn-1", "type": "button", "owner": {"rid": "dev-dimmer", "rtype": "device"}, "metadata": {"control_id": 1},
         "button": {"last_event": "short_release"}},
        {"id": "btn-4", "type": "button", "owner": {"rid": "dev-dimmer", "rtype": "device"}, "metadata": {"control_id": 4},
         "button": {"last_event": "short_release"}},
    ],
}


def resources() -> dict[str, list[dict]]:
    return copy.deepcopy(_RESOURCES)


def update(*items: dict, kind: str = "update") -> list[dict]:
    return [{"creationtime": "2026-09-30T18:00:00Z", "id": "event-1", "type": kind, "data": list(items)}]
