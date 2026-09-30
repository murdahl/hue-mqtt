import json
import logging
from collections.abc import Callable, Iterable, Iterator

import httpx

log = logging.getLogger(__name__)

# What the bridge model is built from
RESOURCES = ("bridge", "device", "light", "room", "zone", "grouped_light", "zigbee_connectivity", "device_power", "button")


class HueError(Exception):
    pass


def create_client(host: str, application_key: str, timeout: float | None = 10) -> httpx.Client:
    # The bridge serves HTTPS with its own certificate, issued for its bridge id rather than its IP, so it can't be
    # verified by hostname. It's only ever reached on the local network.
    return httpx.Client(base_url=f"https://{host}", headers={"hue-application-key": application_key}, verify=False, timeout=timeout)


class HueClient:
    """The Hue bridge's local CLIP v2 API."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def _check(self, response: httpx.Response) -> dict:
        if response.status_code in (401, 403):
            raise HueError("The bridge rejected the application key; pair again")
        response.raise_for_status()
        body = response.json()
        errors = [error.get("description") for error in body.get("errors") or []]
        if errors:
            raise HueError("; ".join(str(error) for error in errors))
        return body

    def resources(self, kind: str) -> list[dict]:
        return self._check(self.http.get(f"/clip/v2/resource/{kind}"))["data"]

    def everything(self) -> dict[str, list[dict]]:
        return {kind: self.resources(kind) for kind in RESOURCES}

    def update(self, kind: str, id: str, body: dict) -> None:
        self._check(self.http.put(f"/clip/v2/resource/{kind}/{id}", json=body))

    def events(self, on_open: Callable[[], None] = lambda: None) -> Iterator[list[dict]]:
        """Blocks and yields batches of changes from the bridge's event stream until the connection drops.
        The stream stays silent until something changes, so on_open signals that it's up."""
        with self.http.stream("GET", "/eventstream/clip/v2", headers={"Accept": "text/event-stream"}, timeout=httpx.Timeout(10, read=None)) as response:
            if response.status_code in (401, 403):
                raise HueError("The bridge rejected the application key; pair again")
            response.raise_for_status()
            on_open()
            yield from parse_event_stream(response.iter_lines())


def parse_event_stream(lines: Iterable[str]) -> Iterator[list[dict]]:
    """Server-sent events: each message's data is a JSON list of {type: update|add|delete, data: [...]}."""
    data: list[str] = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif line == "" and data:
            try:
                messages = json.loads("".join(data))
            except ValueError:
                log.debug("Skipping unreadable event: %s", data)
            else:
                if isinstance(messages, list):
                    yield [message for message in messages if isinstance(message, dict)]
            data = []
