"""Bench defaults. Put local overrides/credentials in ignored settings.py."""

SENSOR_PINS = (15, 2, 4, 16)
HEATER_PIN = 25
FAN_PIN = 26
PWM_FREQUENCY = 1000
OLED_SDA = 21
OLED_SCL = 22
OLED_ADDRESS = 0x3C

# Both this permission and run(enable_heat=True) are required. Boot never arms.
ALLOW_HEATING = False
TARGET_TEMP = 45.0
MAX_TEMP = 60.0
FAN_COOL_TEMP = 30.0
COOLDOWN_MS = 300000
SAMPLE_INTERVAL_MS = 2500
MAX_SAMPLE_AGE_MS = 4000
MAX_CONTROL_GAP_MS = 8000
PID_KP = 2.0
PID_KI = 0.1
PID_KD = 0.5

WIFI_SSID = ""
WIFI_PASSWORD = ""
WIFI_TIMEOUT_MS = 15000
NETWORK_RETRY_MS = 10000
MQTT_BROKER = ""
MQTT_PORT = 1883
MQTT_USER = None
MQTT_PASSWORD = None
MQTT_CLIENT_ID = "sunlu-controller"  # chip identifier is appended at runtime
MQTT_TOPIC = "sunlu/sensors"
MQTT_STATUS = "sunlu/status"
MQTT_TIMEOUT_S = 1
MQTT_INTERVAL_MS = 5000
WATCHDOG_MS = 8000


def load():
    try:
        import settings
    except ImportError as exc:
        if getattr(exc, "name", None) not in (None, "settings"):
            raise
        settings = None

    class Settings:
        pass

    result = Settings()
    for name, value in globals().items():
        if name.isupper():
            setattr(result, name, getattr(settings, name, value))
    return result
