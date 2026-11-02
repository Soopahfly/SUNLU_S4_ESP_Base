# SUNLU S4 ESP32 controller base

Experimental MicroPython controller for a **disconnected low-voltage bench**: DHT22 or SHT30/SHT31 sensors, an SSD1306 OLED, one heater command, one fan command, and optional MQTT telemetry. Neither SUNLU S4 nor S4 Pro factory wiring is established here. No appliance or ESP32 hardware has been tested with these changes.

The software faults identified in [the original review](CODE_REVIEW.md) now have implementations and host regression tests. Hardware-dependent acceptance remains open in [ISSUES.md](ISSUES.md). **Heating is disabled by default.** Software tests do not establish safe heater operation.

## Current behaviour

- GPIO 25/26 are driven low, then PWM is constructed with explicit zero duty, before configuration loading, display setup or networking. Signals assume active-high drivers.
- After a two-second sensor startup delay, each sensor is measured once. Subsequent acquisitions begin at least five seconds after the preceding acquisition completes. Control, display and telemetry reuse that snapshot.
- All configured temperature and humidity readings must be valid (four for DHT22; one to four explicitly listed for SHT3x). Missing, non-finite, out-of-range, future or older-than-seven-second data faults the controller. A control gap over seven seconds also faults, even if a new reading becomes available.
- Any individual sensor at **60 C or above** latches a fault; averaging cannot hide the hotspot. Defaults are a **45 C target**, a **60 C limit**, and a **30 C cooling threshold**. These are bench settings, not established appliance ratings.
- The PID uses elapsed seconds, derivative on measurement, bounded conditional integration, and resets on fault/disabled heat. At or above the target, heat demand is zero. Gains remain untuned.
- Fan demand is 100% while heating, above the cooling threshold, or for five minutes after the last positive heat request. Faults demand heat off and fan full indefinitely while the program continues.
- Faults latch for the lifetime of the controller. Inspect and correct the cause before a deliberate restart; there is no network fault-reset command. Restart reinitialises the latch and, if explicitly configured, permits heating again after fresh readings.
- Display/setup/unexpected software errors and Ctrl-C leave through cleanup that attempts zero PWM, deinitialisation and a low heater GPIO independently of the fan, then requests full fan output. The exception is re-raised. Power loss/reset can stop cooling; hardware behaviour remains unverified.
- Networking is optional. Expected Wi-Fi/MQTT failures mark telemetry offline and retry; **local control continues**. Network recovery cannot clear a thermal/sensor fault. An unexpected exception escaping the telemetry adapter triggers the same shutdown cleanup.

A stalled interpreter, driver call or failed output device cannot be corrected by a Python `finally` until execution resumes. Deadline checks detect a late loop after it returns; they do not preempt a blocked hardware driver. Boot/reset defaults, watchdog behaviour, independent thermal protection and actual airflow remain hardware validation work.

## Bench hardware and pins

Use a classic ESP32 board exposing these GPIOs. The existing map is not directly suitable for an ESP32-C3 SuperMini. No factory appliance connectors are implied.

| Function | GPIO | Notes |
| --- | --- | --- |
| DHT22 sensor 1/2/3/4 DATA | 15 / 2 / 4 / 16 | Separate data lines, 3.3 V-compatible sensors and pull-ups |
| SSD1306 OLED and SHT3x/mux SDA / SCL | 21 / 22 | Shared I2C(0), 100 kHz; OLED 128 x 64 at 0x3C |
| Heater command | 25 | Active-high, 1 kHz PWM; use a dummy indicator only |
| Fan command | 26 | Active-high, 1 kHz PWM; interface is unverified |

Bench parts: compatible ESP32 development board, USB data cable, configured SHT30/SHT31 modules (or four DHT22/AM2302 modules), 3.3 V-compatible I2C SSD1306 module, breadboard/jumpers and sensor pull-ups as specified by the modules (typically 4.7-10 kohm to 3.3 V for short bench wires). Optional output indicators: LEDs with 1 kohm series resistors from output to ground. Use common low-voltage ground; check each module's actual pin labels and supply requirements. Do not attach dryer power stages.

GPIO 2 and 15 are strapping pins; GPIO 16 can be reserved on PSRAM boards. Check the exact board schematic. PWM is not suitable for mechanical relays or an arbitrary AC SSR. Supply, isolation, output polarity, power electronics, independent protection and factory sensor compatibility are all unresolved.

S4 Pro has two independently heated zones; this program still has one heater channel. See [hardware research](docs/HARDWARE_RESEARCH.md) for the evidence needed before designing a conversion.

## Installation and configuration

API target: ESP32 MicroPython **1.26.0**, not yet tested on a physical board or MicroPython VM. No external MQTT or NTP packages are needed. `machine`, `dht`, `network`, `socket` and `select.poll` come from the target firmware. `ssd1306.py` is supplied here.

Install an appropriate MicroPython image using the board's official procedure. With desktop Python and `mpremote` installed, upload helper files **before** the entry point:

```powershell
python -m pip install mpremote
mpremote connect COM5 fs cp controller.py :controller.py
mpremote connect COM5 fs cp sensors.py :sensors.py
mpremote connect COM5 fs cp telemetry.py :telemetry.py
mpremote connect COM5 fs cp ssd1306.py :ssd1306.py
Copy-Item config.example.py config.py
# Edit config.py locally; leave HEAT_ENABLED=False for initial bench checks.
mpremote connect COM5 fs cp config.py :config.py
mpremote connect COM5 fs cp main.py :main.py
mpremote connect COM5 reset
```

Replace COM5 with the actual port. Stop the running application before later file updates. A missing `config.py` preserves the original four-DHT22 inventory and leaves both heat and networking disabled. The supplied example instead selects four SHT3x sensors through a TCA9548A; edit the inventory to match your wiring. Local `config.py` is ignored by Git. Do not commit passwords.

To test telemetry, set `NETWORK_ENABLED=True`, Wi-Fi credentials and a numeric `MQTT_BROKER_IP`. Hostnames are deliberately rejected, avoiding network DNS waits. `HEAT_ENABLED=True` permits dummy heater output only after valid readings; it is not approval for appliance operation. Configuration currently exposes heat enable and networking; control thresholds/gains remain explicit constructor defaults in `controller.py`.

## SHT30/SHT31 setup

The included `sensors.py` driver supports both SHT30-DIS and SHT31-DIS with the same commands. Select `SHT3X`, `SHT30` or `SHT31`; no sensor-model autodetection is performed. DHT22 support remains available with `SENSOR_TYPE = 'DHT22'`.

For **one SHT sensor directly on the bus**, use:

```python
HEAT_ENABLED = False
SENSOR_TYPE = 'SHT3X'
SHT_MUX_ADDRESS = None
SHT_SENSORS = ((0x44, None),)
```

For two direct sensors, use `((0x44, None), (0x45, None))` and set the modules' address selectors accordingly. Direct sensors must have unique addresses. Do not connect multiple modules at the same address directly to the bus.

For **four sensors using a TCA9548A** (the supplied example):

```python
HEAT_ENABLED = False
SENSOR_TYPE = 'SHT3X'
SHT_MUX_ADDRESS = 0x70
SHT_SENSORS = ((0x44, 0), (0x44, 1), (0x44, 2), (0x44, 3))
```

Each entry is `(sensor_address, mux_channel)`. Sensor addresses may be `0x44` or `0x45`; mux channels are 0..7 and the mux address may be 0x70..0x77. Entries must be unique. Configure one to four physical sensors explicitly; the controller requires every listed sensor and never reduces coverage because one is absent. A one-sensor configuration is for initial bench development, not proof of adequate appliance coverage. Mixing direct and multiplexed sensors in the same configuration is not supported.

Suggested low-voltage wiring for the existing **classic ESP32 pin map**:

| Connection | Wiring |
| --- | --- |
| ESP32 GPIO 21 / GPIO 22 | Main-bus SDA / SCL, shared by OLED and mux input (or direct sensors) |
| Sensor/mux/OLED supply and ground | Suitable 3.3 V-compatible modules powered at 3.3 V, common ground |
| Mux channel 0 SD0 / SC0 | Sensor 1 SDA / SCL |
| Mux channel 1 SD1 / SC1 | Sensor 2 SDA / SCL |
| Mux channel 2 SD2 / SC2 | Sensor 3 SDA / SCL |
| Mux channel 3 SD3 / SC3 | Sensor 4 SDA / SCL |
| Mux A0 / A1 / A2 | Low for address 0x70; check the breakout's fitted address straps |

Check pin labels, fitted pull-ups and reset wiring on the actual breakout. SDA/SCL pull-ups on the main bus and enabled branches must go to 3.3 V for this setup. Keep bench leads short; a mux is not a long-cable bus extender. The OLED stays on the upstream bus. The driver enables only one mux branch at a time and deselects all branches after each acquisition, including failures. A failed deselection invalidates the reading. Hardware bus lockups still require bench testing.

SHT measurements use high-repeatability single-shot mode without clock stretching (`0x2400`), a 20 ms conversion wait and a six-byte response. Both temperature and humidity CRCs are checked before either result is exposed. Each acquisition clears the previous cached values. CRC/I2C/short-read errors feed the existing latched sensor-coverage fault. The sensor's internal heater is never enabled by this driver. The five-second sampling schedule, 45 C target, 60 C cutoff and heat-disabled default are unchanged; the new sensor's wider measurement range does not raise operating limits.

Protocol references: [Sensirion SHT3x-DIS datasheet, sections 4.3, 4.12 and 4.13](https://admin.sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf), and [TI TCA9548A datasheet](https://www.ti.com/lit/ds/symlink/tca9548a.pdf). Driver and wiring are host-tested proposals pending physical validation.

## MQTT

`telemetry.py` is a small cooperative MQTT 3.1.1 publisher, not a general MQTT library. It uses nonblocking sockets, `poll(0)`, at most 512 bytes written and four bytes read per step, three-second per-phase deadlines, and ten-second retry backoff. Wi-Fi association is polled with a three-second deadline. Numeric address lookup does not require network DNS; target driver/API latency still requires measurement.

Device IDs and default topic prefixes are `sunlu-<machine.unique_id() in hex>`. Set `MQTT_TOPIC_PREFIX` to override the prefix; ensure overrides remain unique.

Every five seconds, `<prefix>/sensors` receives a non-retained QoS1 JSON snapshot including `state`, `fault`, `heat_enabled`, `sensors`, `avg_temp`, `avg_hum`, `heater_power`, `fan_power`, `sample_ms`, `uptime_ms`, and `mqtt_ack_age_ms`. The two `*_ms` time fields are wrapping monotonic ticks, not UTC wall time or persistent uptime. Average fields may describe surviving sensors during a fault; `state` and `fault` determine control validity.

A matching PUBACK establishes acknowledgement of the preceding publication, not validation of appliance operation. There is one publication in flight. Rejected connections, incorrect acknowledgements, dropped links, send failures and timeouts close the socket and retry with a clean session and current data. No stale telemetry queue is replayed. The non-retained last will on the same topic is `{"state":"offline"}`. Consumers must also use their own reception timeout: will delivery is not immediate and normal data is never retained. The old shared `sunlu/status` retained `online` message is no longer used; remove any retained legacy status manually if migrating a broker.

Optional `MQTT_USER`/`MQTT_PASSWORD` supply authentication. Transport is **plain TCP with no TLS**, for an isolated trusted bench network only. There are no remote commands, subscriptions, discovery messages, drying presets or timed drying-cycle completion. NTP was removed from the control startup path.

## Host validation

```powershell
python -m unittest discover -s tests -v
```

SHT-specific tests additionally cover the datasheet CRC vector, fixed conversion data, both CRC failures, short reads, missing sensors, stale-cache rejection, partial writes, mux isolation/deselection errors, explicit inventory validation and a shared-OLED runtime. Tests use injected clocks, sensors, GPIO/PWM, display, Wi-Fi, sockets and pollers. They exercise startup ordering, shutdown/interruptions, sensor validity/coverage/freshness, hotspot limits, PID timing/windup, cooldown/clock wrap, one acquisition per interval, loop delays, MQTT framing/authentication, fragmented acknowledgements, timeouts, retries and continued sampling during connectivity loss.

These are CPython host tests. They do not demonstrate MicroPython runtime compatibility, broker interoperability, live Wi-Fi recovery, electrical output levels, airflow or thermal safety. See [the issue checklist](ISSUES.md) for remaining acceptance work.

## Files and references

| File | Purpose |
| --- | --- |
| `main.py` | Safe-output setup, scheduled acquisition, display, runtime cleanup |
| `controller.py` | Host-testable sensor validation, state machine, PID, cooldown |
| `sensors.py` | DHT22/SHT3x adapters, CRC checks, optional TCA9548A routing |
| `telemetry.py` | Cooperative telemetry-only MQTT transport |
| `config.example.py` | Local configuration template without real credentials |
| `ssd1306.py` | Existing OLED driver, unchanged |
| `tests/` | Host fault-injection and regression checks |
| [ISSUES.md](ISSUES.md) | Current progress and remaining acceptance criteria |
| [CODE_REVIEW.md](CODE_REVIEW.md) | Historical findings against firmware 09fa5d7 |
| [Hardware research](docs/HARDWARE_RESEARCH.md) | S4 Pro investigation and evidence requirements |

Implementation references: [MicroPython PWM](https://docs.micropython.org/en/v1.26.0/library/machine.PWM.html), [DHT interface and spacing](https://docs.micropython.org/en/v1.26.0/esp8266/tutorial/dht.html), [socket API](https://docs.micropython.org/en/v1.26.0/library/socket.html), [nonblocking polling](https://docs.micropython.org/en/v1.26.0/library/select.html), [WLAN API](https://docs.micropython.org/en/v1.26.0/library/network.WLAN.html), and [OASIS MQTT 3.1.1](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/os/mqtt-v3.1.1-os.html).

No project licence file or verified schematic, PCB design, factory connector map or appliance wiring procedure is supplied.
