from dataclasses import dataclass, field


def merge(target: dict, changes: dict) -> None:
    """Applies a partial update from the event stream, which only contains what changed."""
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value


def _percent(resource: dict) -> int:
    # Hue's lowest level is below 1 %; show a light that's on as at least 1 %
    brightness = resource["dimming"].get("brightness", 0)
    return max(round(brightness), 1) if (resource.get("on") or {}).get("on") else round(brightness)


def kelvin(mirek: int | float | None) -> int | None:
    return round(1_000_000 / mirek) if mirek else None


@dataclass(frozen=True)
class ButtonPress:
    switch: str
    switch_id: str
    room: str | None
    button: int
    event: str

    def to_json(self) -> dict:
        return {"switch": self.switch, "switch_id": self.switch_id, "room": self.room, "button": self.button, "event": self.event}


@dataclass
class Bridge:
    """Everything the bridge knows, keyed by resource type and id, kept current from the event stream."""

    resources: dict[str, dict[str, dict]] = field(default_factory=dict)

    def load(self, snapshot: dict[str, list[dict]]) -> None:
        self.resources = {kind: {item["id"]: item for item in items if "id" in item} for kind, items in snapshot.items()}

    def apply(self, messages: list[dict]) -> tuple[bool, list[ButtonPress]]:
        """Returns whether the published state changed, and any button presses."""
        changed, presses = False, []
        for message in messages:
            for item in message.get("data") or []:
                kind, id = item.get("type"), item.get("id")
                if not kind or not id:
                    continue
                items = self.resources.setdefault(kind, {})
                if message.get("type") == "delete":
                    changed |= items.pop(id, None) is not None
                elif message.get("type") == "add" or id not in items:
                    items[id] = item
                    changed = True
                else:
                    merge(items[id], item)
                    if kind == "button" and (report := (item.get("button") or {}).get("button_report")):
                        presses.append(self._press(items[id], report.get("event")))
                    else:
                        changed = True
        return changed, [press for press in presses if press]

    # --- lookups -------------------------------------------------------------

    def _all(self, kind: str) -> list[dict]:
        return list(self.resources.get(kind, {}).values())

    def _by_owner(self, kind: str) -> dict[str, dict]:
        return {item["owner"]["rid"]: item for item in self._all(kind) if item.get("owner")}

    def _room_of_device(self) -> dict[str, str]:
        rooms = {}
        for room in self._all("room"):
            for child in room.get("children", []):
                rooms[child["rid"]] = room["metadata"]["name"]
        return rooms

    def _grouped_light(self, group: dict) -> dict | None:
        rid = next((service["rid"] for service in group.get("services", []) if service["rtype"] == "grouped_light"), None)
        return self.resources.get("grouped_light", {}).get(rid) if rid else None

    def _press(self, button: dict, event: str | None) -> ButtonPress | None:
        device = self.resources.get("device", {}).get(button.get("owner", {}).get("rid"))
        if not device or not event:
            return None
        return ButtonPress(
            switch=device["metadata"]["name"],
            switch_id=device["id"],
            room=self._room_of_device().get(device["id"]),
            button=(button.get("metadata") or {}).get("control_id") or 0,
            event=event,
        )

    # --- state ---------------------------------------------------------------

    def to_state(self, stream_connected: bool) -> dict:
        rooms_of = self._room_of_device()
        connectivity = self._by_owner("zigbee_connectivity")
        power = self._by_owner("device_power")
        bridge = next(iter(self._all("bridge")), {})

        lights = []
        for light in self._all("light"):
            device_id = light.get("owner", {}).get("rid")
            temperature = light.get("color_temperature") or {}
            schema = temperature.get("mirek_schema") or {}
            reachable = (connectivity.get(device_id) or {}).get("status")
            lights.append({
                "id": light["id"],
                "name": light["metadata"]["name"],
                "room": rooms_of.get(device_id),
                "on": bool((light.get("on") or {}).get("on")),
                "brightness": _percent(light) if "dimming" in light else None,
                "kelvin": kelvin(temperature.get("mirek")) if temperature.get("mirek_valid") else None,
                "kelvin_range": [kelvin(schema.get("mirek_maximum")), kelvin(schema.get("mirek_minimum"))] if schema else None,
                "color": "color" in light,
                "reachable": reachable is None or reachable == "connected",
            })

        groups = []
        for kind in ("room", "zone"):
            for group in self._all(kind):
                grouped = self._grouped_light(group) or {}
                members = {child["rid"] for child in group.get("children", [])}
                groups.append({
                    "id": group["id"],
                    "type": kind,
                    "name": group["metadata"]["name"],
                    "on": bool((grouped.get("on") or {}).get("on")),
                    "brightness": _percent(grouped) if "dimming" in grouped else None,
                    "lights": [
                        light["id"] for light in self._all("light")
                        if light["id"] in members or light.get("owner", {}).get("rid") in members
                    ],
                })

        switches = []
        for device in self._all("device"):
            if not any(service["rtype"] == "button" for service in device.get("services", [])):
                continue
            battery = (power.get(device["id"]) or {}).get("power_state") or {}
            switches.append({
                "id": device["id"],
                "name": device["metadata"]["name"],
                "room": rooms_of.get(device["id"]),
                "battery": battery.get("battery_level"),
                "battery_state": battery.get("battery_state"),
            })

        return {
            "bridge": {"id": bridge.get("bridge_id"), "stream": "connected" if stream_connected else "disconnected"},
            "lights": sorted(lights, key=lambda light: (light["room"] or "", light["name"])),
            "rooms": sorted(groups, key=lambda group: (group["type"], group["name"])),
            "switches": sorted(switches, key=lambda switch: switch["name"]),
        }

    def target(self, kind: str, id: str) -> tuple[str, str] | None:
        """Which resource a command for a light, room or zone goes to (rooms and zones via their grouped light)."""
        if kind == "light":
            return ("light", id) if id in self.resources.get("light", {}) else None
        group = self.resources.get(kind, {}).get(id)
        grouped = self._grouped_light(group) if group else None
        return ("grouped_light", grouped["id"]) if grouped else None
