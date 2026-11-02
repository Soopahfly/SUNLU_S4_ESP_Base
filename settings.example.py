"""Copy to settings.py locally; never commit credentials."""

WIFI_SSID = "YOUR_WIFI_SSID"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
MQTT_BROKER = "192.0.2.1"  # replace this documentation example address
# MQTT_USER = b"your-user"
# MQTT_PASSWORD = b"your-password"

# Leave False until dummy-load tests and hardware verification are complete.
# Even True never arms at boot: explicit main.run(enable_heat=True) is required.
ALLOW_HEATING = False
