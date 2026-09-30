import json
from dataclasses import dataclass

KINDS = ("light", "room", "zone")
MIN_KELVIN, MAX_KELVIN = 2000, 6500


class CommandError(Exception):
    pass


@dataclass(frozen=True)
class Command:
    kind: str  # light, room or zone
    id: str
    body: dict  # CLIP v2 update body

    def describe(self) -> str:
        return f"{self.kind} {self.id}: {json.dumps(self.body)}"


def parse_command(target: str, payload: str) -> Command:
    """Topic suffix `<light|room|zone>/<id>`; payload `on`, `off` or JSON
    {"on": bool, "brightness": 0-100, "kelvin": 2000-6500, "transition": seconds}."""
    kind, _, id = target.partition("/")
    if kind not in KINDS or not id:
        raise CommandError(f"Unknown target {target!r}; use light/<id>, room/<id> or zone/<id>")

    text = payload.strip()
    if text.lower() in ("on", "off"):
        return Command(kind, id, {"on": {"on": text.lower() == "on"}})
    try:
        request = json.loads(text)
    except ValueError:
        raise CommandError(f"Payload must be on, off or JSON, not {text!r}") from None
    if not isinstance(request, dict):
        raise CommandError("Payload must be a JSON object")

    body: dict = {}
    if "on" in request:
        if not isinstance(request["on"], bool):
            raise CommandError("on must be true or false")
        body["on"] = {"on": request["on"]}
    if "brightness" in request:
        brightness = request["brightness"]
        if isinstance(brightness, bool) or not isinstance(brightness, int | float) or not 0 <= brightness <= 100:
            raise CommandError("brightness must be 0-100")
        if brightness == 0:
            body["on"] = {"on": False}
        else:
            body["dimming"] = {"brightness": float(brightness)}
            body.setdefault("on", {"on": True})
    if "kelvin" in request:
        value = request["kelvin"]
        if isinstance(value, bool) or not isinstance(value, int | float) or not MIN_KELVIN <= value <= MAX_KELVIN:
            raise CommandError(f"kelvin must be {MIN_KELVIN}-{MAX_KELVIN}")
        body["color_temperature"] = {"mirek": round(1_000_000 / value)}
    if "transition" in request:
        seconds = request["transition"]
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or not 0 <= seconds <= 3600:
            raise CommandError("transition must be 0-3600 seconds")
        body["dynamics"] = {"duration": int(seconds * 1000)}
    if not set(body) - {"dynamics"}:
        raise CommandError("Nothing to change: send on, brightness or kelvin")
    return Command(kind, id, body)
