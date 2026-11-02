"""Serviced only with heater inhibited; timeouts do not bound DNS/firmware calls."""

try:
    import ujson as json
except ImportError:
    import json


class Telemetry:
    def __init__(self, cfg, clock, wlan=None, client_factory=None, device_id="bench"):
        self.cfg, self.clock = cfg, clock
        self.enabled = bool(cfg.WIFI_SSID and cfg.MQTT_BROKER)
        self.wlan, self.factory = wlan, client_factory
        self.client_id = (cfg.MQTT_CLIENT_ID + "-" + device_id).encode()
        self.client = None
        self.ready, self.error = False, None
        self.wifi_started = self.last_retry = self.last_publish = None
        if self.enabled:
            if cfg.MQTT_TIMEOUT_S <= 0 or cfg.MQTT_INTERVAL_MS <= 0 or cfg.NETWORK_RETRY_MS <= 0:
                raise ValueError("invalid network timing")
            wlan.active(True)

    def _close(self):
        if self.client is not None:
            try:
                if self.client.sock is not None:
                    self.client.sock.close()
            except Exception:
                pass
        self.client, self.ready = None, False

    def service(self, payload):
        if not self.enabled:
            return
        now = self.clock.ticks_ms()
        try:
            if not self.wlan.isconnected():
                self._close()
                if self.wifi_started is not None:
                    if self.clock.ticks_diff(now, self.wifi_started) >= self.cfg.WIFI_TIMEOUT_MS:
                        self.wlan.disconnect()
                        self.wifi_started = None
                        self.error = "wifi_timeout"
                    return
                if self.last_retry is None or self.clock.ticks_diff(now, self.last_retry) >= self.cfg.NETWORK_RETRY_MS:
                    self.last_retry = now
                    self.wlan.connect(self.cfg.WIFI_SSID, self.cfg.WIFI_PASSWORD)
                    self.wifi_started = now
                return
            self.wifi_started = None
            if self.client is None:
                if self.last_retry is not None and self.clock.ticks_diff(now, self.last_retry) < self.cfg.NETWORK_RETRY_MS:
                    return
                self.last_retry = now
                self.client = self.factory(
                    self.client_id, self.cfg.MQTT_BROKER, port=self.cfg.MQTT_PORT,
                    user=self.cfg.MQTT_USER, password=self.cfg.MQTT_PASSWORD, keepalive=60)
                self.client.set_last_will(self.cfg.MQTT_STATUS.encode(), b"offline", retain=True)
                self.client.connect(timeout=self.cfg.MQTT_TIMEOUT_S)
                self.client.sock.settimeout(self.cfg.MQTT_TIMEOUT_S)
                self.client.publish(self.cfg.MQTT_STATUS.encode(), b"online", retain=True, qos=1)
                self.last_publish = None
            if self.last_publish is None or self.clock.ticks_diff(now, self.last_publish) >= self.cfg.MQTT_INTERVAL_MS:
                self.client.sock.settimeout(self.cfg.MQTT_TIMEOUT_S)
                self.client.publish(self.cfg.MQTT_TOPIC.encode(), json.dumps(payload).encode(), qos=1)
                self.last_publish = self.clock.ticks_ms()
                self.ready, self.error = True, None
        except Exception:
            self.error = "mqtt_error"  # no credential-bearing exception text
            self.last_retry = self.clock.ticks_ms()
            self._close()
