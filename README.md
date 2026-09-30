# hue-mqtt

Publishes Philips Hue lights, rooms, zones and dimmer switches to MQTT, and optionally controls them. It talks to the Hue Bridge (v2, the square one) over its local API, so no Hue account or cloud is involved. Changes arrive live from the bridge's event stream, and a regular poll catches anything it missed.

## Pairing (one time)

The bridge only talks to apps it has paired with. Press the round button on top of the bridge, then within 30 seconds run:

```sh
curl -sk -X POST https://<bridge ip>/api -d '{"devicetype":"hue-mqtt#server","generateclientkey":true}'
```

The `username` in the answer is the application key. Before the button is pressed, the answer is "link button not pressed".

## Run

```sh
docker run -d --name hue-mqtt --restart unless-stopped \
  -e HUE_BRIDGE_HOST=192.168.1.20 -e HUE_APPLICATION_KEY=... \
  -e MQTT_HOST=192.168.1.10 -e MQTT_USERNAME=hue -e MQTT_PASSWORD=secret \
  -e ENABLE_CONTROL=true \
  ghcr.io/murdahl/hue-mqtt:latest
```

Give the bridge a fixed IP in your router.

## Configuration

| Variable              | Default    | Description |
|-----------------------|------------|-------------|
| `HUE_BRIDGE_HOST`     | (required) | Bridge IP or hostname |
| `HUE_APPLICATION_KEY` | (required) | From pairing |
| `MQTT_HOST`           | (required) | MQTT broker |
| `MQTT_PORT`           | `1883`     | |
| `MQTT_USERNAME`       |            | |
| `MQTT_PASSWORD`       |            | |
| `MQTT_TOPIC_PREFIX`   | `hue`      | |
| `POLL_INTERVAL`       | `300`      | Seconds between full refreshes (minimum 30). Changes come from the event stream in between |
| `ENABLE_CONTROL`      | `false`    | `true` to accept commands on `hue/set/...` |
| `LOG_LEVEL`           | `INFO`     | |

## Topics

| Topic        | Retained | Payload |
|--------------|----------|---------|
| `hue/status` | yes      | `online` / `offline` |
| `hue/state`  | yes      | JSON, see below. Republished on every change |
| `hue/event`  | no       | A dimmer button press: `{"switch", "switch_id", "room", "button": 1-4, "event"}` |

```json
{
  "bridge": {"id": "ecb5fafffe000001", "stream": "connected"},
  "lights": [
    {"id": "2f4e…", "name": "Floor lamp", "room": "Living room", "on": true, "brightness": 54,
     "kelvin": 2732, "kelvin_range": [2000, 6536], "color": true, "reachable": true}
  ],
  "rooms": [
    {"id": "9a1c…", "type": "room", "name": "Living room", "on": true, "brightness": 54, "lights": ["2f4e…"]}
  ],
  "switches": [
    {"id": "7324…", "name": "Bedroom dimmer", "room": "Bedroom", "battery": 66, "battery_state": "normal"}
  ]
}
```

- **Lights:**
  - `brightness` is 0–100 %, and `null` for lights that can't dim.
  - `kelvin` is `null` while a colour light shows a colour rather than a white.
  - `reachable` is `false` when the bridge can't reach the light, for example when it's switched off at the wall.
- **Rooms and zones:** `on` means any light in it is on.
- **Switches:** `battery_state` is `normal`, `low` or `critical`.
- **Button events:** `event` is `initial_press`, `repeat`, `short_release`, `long_press` or `long_release`.
- **Stream:** `stream` is `disconnected` while the live event stream is down; the bridge then reconnects and catches up.

## Control

With `ENABLE_CONTROL=true`:

| Topic                 | Payload |
|-----------------------|---------|
| `hue/set/light/<id>`  | `on`, `off`, or JSON `{"on": true, "brightness": 0-100, "kelvin": 2000-6500, "transition": seconds}` |
| `hue/set/room/<id>`   | same, for every light in the room |
| `hue/set/zone/<id>`   | same, for a zone |

```sh
mosquitto_pub -t hue/set/room/9a1c… -m off
mosquitto_pub -t hue/set/light/2f4e… -m '{"brightness": 30, "kelvin": 2700, "transition": 600}'
```

- **Brightness:** `0` turns the light off. Any other brightness turns it on.
- **Colour temperature:** clamped to what a light supports, and dropped for white-only lights, so the rest of the command still works.
- **Transition:** fades over that many seconds, e.g. 600 for a 10-minute wake-up light.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Notes

The bridge's HTTPS certificate is issued for its bridge id, not its IP, so it isn't verified. That's fine on a home network, but don't expose the bridge to the internet.
