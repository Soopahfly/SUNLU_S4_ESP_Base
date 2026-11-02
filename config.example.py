# Copy to config.py on the board. Never commit real credentials.
# Both defaults are deliberately suitable only for a disconnected bench.
HEAT_ENABLED = False
NETWORK_ENABLED = False
# SHT30 and SHT31 share this driver. Default example: four sensors on mux channels
# 0..3, all at 0x44. Change this explicit inventory to match your bench wiring.
SENSOR_TYPE = 'SHT3X'
SHT_MUX_ADDRESS = 0x70
SHT_SENSORS = ((0x44, 0), (0x44, 1), (0x44, 2), (0x44, 3))
# One sensor without a mux:
# SHT_MUX_ADDRESS = None
# SHT_SENSORS = ((0x44, None),)
# Two direct sensors: ((0x44, None), (0x45, None))
# Original four DHT22 sensors: SENSOR_TYPE = 'DHT22'
WIFI_SSID = ''
WIFI_PASSWORD = ''
MQTT_BROKER_IP = '192.0.2.1'  # Replace with your broker's numeric IPv4 address.
MQTT_PORT = 1883
# MQTT_USER = 'local-user'
# MQTT_PASSWORD = 'local-password'
# MQTT_TOPIC_PREFIX = 'sunlu-bench'  # Default is unique per machine.unique_id().
# Plain TCP only. Use only on an isolated trusted bench network; no TLS support.
