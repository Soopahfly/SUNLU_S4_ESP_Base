# Software fix record

Implementation: [`8ca81aa` - Fix bench controller faults and add SHT3x sensor support](https://github.com/Soopahfly/SUNLU_S4_ESP_Base/commit/8ca81aa), published 2 November 2026. Original findings refer to firmware `09fa5d7`. This record describes implemented software, not a validated Sunlu conversion.

## Startup and faults

`main.py` drives heater/fan GPIOs low and creates PWM with explicit zero duty before loading configuration or initialising the display/network. This assumes active-high output hardware; boot/reset behaviour and physical polarity are not established.

`controller.py` implements idle, heating, cooling and latched-fault states. Every configured sensor must provide valid temperature and humidity. Failed, missing, non-finite, out-of-range, future or stale readings inhibit heating. Samples older than seven seconds and control gaps over seven seconds fault the controller. Any individual valid temperature at or above the 60 C bench limit trips the controller, rather than relying on its average.

Fault demand is heater off and fan full. A fault persists until deliberate controller restart; restored sensors or networking do not clear it. Exceptions and Ctrl-C leave through cleanup that attempts zero heater duty, PWM deinitialisation and a low heater GPIO, then full fan demand. A stalled interpreter or driver is not preempted by this cleanup; physical protection is still required.

## Sampling, control and cooling

- Wait two seconds before the first acquisition; start subsequent acquisitions at least five seconds after the preceding acquisition completes.
- Measure each sensor once per acquisition and reuse the snapshot for PID, display and telemetry.
- Use elapsed seconds in the PID, derivative on measurement, bounded conditional integration and resets when faulted or disabled. Request no heat at or above the target.
- Run the fan while heating, when any valid temperature exceeds 30 C, or for five minutes after the last positive heat request. Faults request full fan indefinitely while the controller runs.

The 45 C target, 60 C limit, PID gains and cooling policy remain bench defaults pending hardware-specific tuning and measurements. Heating is disabled by default.

## SHT30/SHT31 support

`sensors.py` adds a shared SHT3x-DIS adapter while retaining the original four-DHT22 option. Local configuration selects one to four explicit SHT locations, either direct I2C addresses or TCA9548A channels. Duplicate and invalid routes are rejected; absent sensors never silently reduce required coverage.

Each SHT acquisition checks both CRCs and rejects short reads and incomplete writes. Cached readings are cleared before measuring. Mux branches are selected individually and deselected after acquisitions, including errors, before the shared OLED is accessed. Deselect failures invalidate the acquisition. Driver support does not establish factory-sensor compatibility or increase controller temperature limits.

See [README setup examples](../README.md#sht30sht31-setup) and [config.example.py](../config.example.py). An absent config keeps four DHT22 inputs; the supplied example selects four SHT sensors on mux channels 0..3. Both leave heat and networking disabled until explicitly configured.

## Networking and configuration

`telemetry.py` replaces the blocking `umqtt.simple` path with a telemetry-only cooperative MQTT 3.1.1 client. It uses nonblocking sockets and zero-wait polling, bounded transfers, three-second per-phase deadlines and ten-second retry backoff. Numeric broker IPv4 addresses avoid network DNS; startup NTP has been removed.

CONNACK and matching QoS1 PUBACK packets are consumed and validated. IDs/default topics are unique per device. Publications report control/fault state and output demands; normal data and the offline will are non-retained. Expected Wi-Fi/MQTT failure retries while local sensing/control continues. Recovery publishes current data rather than replaying a stale queue, and cannot clear a controller fault. Unexpected adapter exceptions that escape its handler trigger runtime cleanup.

Credentials belong in ignored local `config.py`. Optional username/password authentication is implemented; TLS is not. Plain TCP is documented for an isolated trusted bench network. Home Assistant MQTT discovery, remote commands, ESPHome firmware, drying-cycle timers, RFID, scales and time-of-flight sensors have not been implemented.

## Recorded validation and remaining work

The implementation passed **30 CPython 3.12.10 host tests**, source compilation and Git whitespace checks. These cover mocked startup/cleanup, faults, sampling, PID timing/windup, cooldown/clock rollover, SHT protocol/CRC/routing errors, MQTT framing/acknowledgements/timeouts and continued sampling during network loss.

Repeat the host suite from the repository root:

```powershell
python -m unittest discover -s tests -v
```

Still outstanding:

1. Execute on the selected ESP32/MicroPython build using sensors and dummy outputs; measure startup/reset levels, timing and fault response.
2. Test an actual MQTT broker, credentials, outages, Wi-Fi reconnection and runtime network latency.
3. Identify the Sunlu appliance/PCB revisions, factory interfaces, power stages, supply/isolation and independent protection. Reuse versus replacement of power electronics is undecided; no relay or heater-driver shopping list is verified.
4. Establish sensor placement/count, airflow, limits and thermal tuning. S4 Pro requires independent two-zone control; this implementation remains single-zone.

Detailed acceptance criteria remain in [ISSUES.md](../ISSUES.md). Hardware findings and investigation requirements remain in [HARDWARE_RESEARCH.md](HARDWARE_RESEARCH.md).
