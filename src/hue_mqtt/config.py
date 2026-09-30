import os
from collections.abc import Mapping
from dataclasses import dataclass

MIN_POLL_INTERVAL = 30


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    bridge_host: str
    application_key: str
    mqtt_host: str
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = "hue"
    # The event stream carries the changes; the poll only catches what it missed
    poll_interval: float = 300
    enable_control: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Config":
        missing = [name for name in ("HUE_BRIDGE_HOST", "HUE_APPLICATION_KEY", "MQTT_HOST") if not env.get(name)]
        if missing:
            raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")
        try:
            poll_interval = float(env.get("POLL_INTERVAL", cls.poll_interval))
            mqtt_port = int(env.get("MQTT_PORT", cls.mqtt_port))
        except ValueError as error:
            raise ConfigError(f"Invalid numeric setting: {error}") from error
        if poll_interval < MIN_POLL_INTERVAL:
            raise ConfigError(f"POLL_INTERVAL must be at least {MIN_POLL_INTERVAL} seconds")
        return cls(
            bridge_host=env["HUE_BRIDGE_HOST"],
            application_key=env["HUE_APPLICATION_KEY"],
            mqtt_host=env["MQTT_HOST"],
            mqtt_port=mqtt_port,
            mqtt_username=env.get("MQTT_USERNAME") or None,
            mqtt_password=env.get("MQTT_PASSWORD") or None,
            mqtt_topic_prefix=env.get("MQTT_TOPIC_PREFIX", cls.mqtt_topic_prefix).rstrip("/"),
            poll_interval=poll_interval,
            enable_control=env.get("ENABLE_CONTROL", "").strip().lower() in ("1", "true", "yes"),
        )
