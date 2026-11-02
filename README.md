# SUNLU S4 ESP32 controller base

Experimental MicroPython firmware for an ESP32-based filament dryer controller: four temperature/humidity sensors, an OLED display, heater and fan control signals, and MQTT telemetry.

**Status: bench-development firmware, not validated for an appliance.** Software fault handling has been implemented and regression-tested with mocked hardware. There is still no verified S4/S4 Pro power-board wiring. Normal boot is monitoring-only and heater duty stays zero. Keep loads/power drivers disconnected until the hardware is identified and physically tested.

This guide describes the refactored bench firmware. [CODE_REVIEW.md](CODE_REVIEW.md) preserves the historical findings against original commit `09fa5d7` and records which software paths have been addressed. [Host tests](tests/README.md) exercise the new implementation; no ESP32, MicroPython runtime or physical dryer has been tested.

**S4 Pro research:** the S4 and S4 Pro are separate hardware targets. The Pro has two independently heated chambers; this firmware exposes only one heater output. Neither appliance has verified compatibility here. See [S4 Pro hardware research and ESP32-C3 assessment](docs/HARDWARE_RESEARCH.md) for teardown timestamps, evidence requirements and proposed investigation steps, and [the open work checklist](ISSUES.md) for unresolved work. Software fixes are implemented for the original single-heater bench interface. Pro conversion and SuperMini pin assignments remain unimplemented.

## Contents

- [What it does](#what-it-does)
- [Parts needed](#parts-needed)
- [ESP32 pin assignments](#esp32-pin-assignments)
- [Low-voltage wiring](#low-voltage-wiring)
- [Connecting to an actual SUNLU S4](#connecting-to-an-actual-sunlu-s4)
- [Software installation](#software-installation)
- [Configuration](#configuration)
- [First bench run](#first-bench-run)
- [MQTT messages](#mqtt-messages)
- [Known limitations and faults](#known-limitations-and-faults)
- [Troubleshooting](#troubleshooting)
- [Files and references](#files-and-references)

## What it does

Normal boot monitors four DHT22 sensors and an external 128 × 64 SSD1306 OLED. With local Wi-Fi/broker settings it also publishes MQTT telemetry. Networking is optional for monitoring; it is required for an explicitly armed bench heating run.

Each cycle:

1. Commands heater duty **zero** and fan demand **100%** before sensor, display or network work.
2. Measures each configured DHT22 exactly once and shares that snapshot across control, display and telemetry.
3. Rejects failed, non-finite, out-of-range or stale readings; **all configured sensors are required**.
4. Latches a fault if any individual sensor reaches **60 °C**, regardless of the mean.
5. Updates display/telemetry while the heater remains inhibited.
6. Checks sample freshness again before allowing output; a requested heating run also needs healthy networking.
7. Applies fan demand before heater demand, then waits at least 2.5 seconds before the next measurement round. A supervisor checks freshness every 50 ms during that wait.

An explicitly armed run uses elapsed-time PID at a **45 °C** target, bounded/conditional integral accumulation and zero demand at or above target. This is not hardware-tuned. Fan demand is full during heating, whenever any sensor is above 30 °C, and for **five minutes from the last nonzero heater demand**. A fault or interruption commands heat off and full fan demand.

Faults latch for the current run: restored readings or MQTT reconnection do not clear them. A fresh run starts a new controller, but must be deliberately armed again. A normal boot/reset never arms, even if local heating permission is True.

| Feature | Current implementation |
| --- | --- |
| Sensor coverage | Four separate DHT22 inputs; one snapshot per cycle; all required |
| Heater control | One active-high PWM interface; bench PID, gated by explicit permission and per-run arming |
| Fan control | One active-high output; full demand for heat/hot readings/cooldown/faults |
| OLED | External 128 × 64 SSD1306 I²C display with English state/fault labels |
| MQTT | Optional monitoring; QoS 1 telemetry/availability with socket timeout and retry backoff |
| Remote commands | None; no MQTT arming, start/stop or setpoint subscription |
| Home Assistant | Manual telemetry consumption; no discovery/dashboard supplied |
| Drying programmes | No material presets, cycle duration or humidity-based finish |
| Original S4/Pro electronics | No verified connector map, protocol or factory display/sensor support |
| Pro zones | Not implemented; existing bench interface has only one heater channel |

**Network policy:** this is an interlocked synchronous design, not an independent network thread. Heater output is deliberately paused during every peripheral/network operation. Socket calls have a one-second timeout, but DNS and some firmware calls may still stall. An armed run starts an eight-second watchdog; a stall should reboot into monitoring only. The actual watchdog and GPIO reset behaviour require an ESP32 test. Monitoring mode does not start a watchdog, preserving REPL/file-upload usability.

This interruption changes effective heater duty and must be considered during physical tuning. It does not establish that 1 kHz PWM is suitable for the appliance's power stage.

## Parts needed

### Low-voltage bench setup

These parts match the software interfaces. They are not a verified shopping list for converting an S4.

| Quantity | Part | Selection notes |
| --- | --- | --- |
| 1 | Classic ESP32 development board with USB, based on an ESP32-WROOM-32-family module | Must expose GPIO 2, 4, 15, 16, 21, 22, 25 and 26. Check its schematic. ESP32-C3/S3 boards are not direct substitutes for this pin map. |
| 4 | DHT22 / AM2302 temperature and humidity sensors | Use devices/modules specified for 3.3 V operation. Each needs its own data wire. Existing SUNLU sensors are not established as compatible. |
| 1 | 128 × 64 SSD1306 I²C OLED module | VCC, GND, SDA, SCL; 3.3 V-compatible module and bus levels; default address `0x3C`. SH1106 or SPI-only modules need different code. |
| Up to 4 | DHT data pull-up resistors | One per data line unless already fitted on the module. Typical short-wire bench choice: 4.7–10 kΩ to **3.3 V**; follow the module/sensor datasheet. |
| As needed | I²C pull-ups | Check the OLED module first; many include them. Pull-ups must go to 3.3 V. |
| 1 | USB data cable and suitable USB supply/computer | Cable must carry data for programming; power the board via its documented USB input. |
| 1 set | Prototyping board, jumper wires and connectors | Low-voltage bench work only. |
| Optional: 2 each | LEDs and 1 kΩ series resistors | Dummy indicators for the heater/fan output pins, instead of power drivers. |
| 1 | Computer with Python, Git and serial access | Installation examples use `mpremote`. |
| 1 each | 2.4 GHz Wi-Fi network and reachable MQTT broker | Optional for monitoring; both required for explicit heating arming. |

GPIO numbers are chip numbers, not physical header positions or arbitrary `D` labels. GPIO 2 and 15 are strapping pins; attached circuitry can affect reset/programming. GPIO 16 can be reserved on PSRAM-equipped boards. Check the exact board/module, or change the pin assignments and wiring together. See the [Espressif module datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf).

### Additional hardware for a real dryer

Select these only after identifying the actual loads and electronics. The repository supplies no corresponding part numbers or load ratings.

| Item | What must be established |
| --- | --- |
| Heater power stage | Load voltage, AC/DC type, operating/inrush current, isolation, cooling, protection and 3.3 V-compatible control input. Must support the chosen control method. |
| Fan power stage | Voltage/current and fan interface. Two-wire supply switching, three-wire tachometer fans and four-wire PWM fans are different interfaces. |
| Controller supply | Verified isolated low-voltage supply and suitable regulation. No safe S4 supply tap is documented here. |
| Independent protection | Thermal cutoff, electrical fusing, suitable wiring/enclosure and a means of removing heater power independently of software. Preserve existing protection. |
| Mechanical hardware | Heat-rated wiring, connectors, sensor mounts, strain relief and enclosure suited to the installation. |

**A generic relay module is not a drop-in solution.** Both outputs generate **1 kHz PWM**. Mechanical relays cannot follow this signal; typical AC zero-cross SSRs are not equivalent to DC PWM drivers. A selected power stage may require a different control strategy and firmware changes. No heater or fan driver is validated by this project.

## ESP32 pin assignments

Configured in [config.py](config.py); these are the unchanged classic-ESP32 bench assignments:

| Function | ESP32 GPIO | Connection / signal |
| --- | --- | --- |
| Sensor 1 | 15 | DHT22 DATA; MQTT `sensors[0]` |
| Sensor 2 | 2 | DHT22 DATA; MQTT `sensors[1]` |
| Sensor 3 | 4 | DHT22 DATA; MQTT `sensors[2]` |
| Sensor 4 | 16 | DHT22 DATA; MQTT `sensors[3]` |
| OLED SDA | 21 | I²C data, controller `I2C(0)` |
| OLED SCL | 22 | I²C clock, controller `I2C(0)` |
| Heater demand | 25 | 3.3 V logic PWM, 1 kHz; duty command 0–1023 |
| Fan demand | 26 | 3.3 V logic PWM, 1 kHz; main loop requests 0 or 1023 |
| Peripheral supply | 3V3 | Compatible bench sensors and OLED |
| Peripheral return | GND | Common ground for bench peripherals |

Heater and fan pins carry **control signals, not load power**. The code assumes a larger high-time duty means more output. An active-low driver reverses that behaviour and requires explicit handling.

## Low-voltage wiring

Disconnect all power before changing connections. Leave the SUNLU S4 disconnected and power the ESP32 by USB. Do not connect an unknown appliance ground, supply or signal to the USB-powered board.

```text
USB-powered ESP32                  Bench peripherals
================                  =================
3V3 ----------------------------> OLED VCC
GND ----------------------------> OLED GND
GPIO21 -------------------------> OLED SDA
GPIO22 -------------------------> OLED SCL

3V3 ----------------------------> VDD of all four DHT22 sensors
GND ----------------------------> GND of all four DHT22 sensors
GPIO15 -------------------------> DHT22 #1 DATA
GPIO2  -------------------------> DHT22 #2 DATA
GPIO4  -------------------------> DHT22 #3 DATA
GPIO16 -------------------------> DHT22 #4 DATA

Each DHT DATA line --[pull-up]---> 3V3

Optional dummy output indicators, no power stages attached:
GPIO25 ----[1 kohm]---- LED anode; LED cathode ---- GND
GPIO26 ----[1 kohm]---- LED anode; LED cathode ---- GND
```

This is a **bench wiring diagram**, not a SUNLU connector diagram.

### DHT22 sensors

For a conventional bare four-pin DHT22:

| Sensor pin | Function | Bench connection |
| --- | --- | --- |
| 1 | VDD | ESP32 3V3 |
| 2 | DATA | Assigned GPIO, plus pull-up to 3V3 |
| 3 | Not connected | Leave unconnected |
| 4 | GND | ESP32 GND |

Confirm physical orientation against the exact sensor's datasheet. Three-pin breakout boards arrange `+`, `OUT` and `-` differently; follow their labels instead of transferring four-pin numbering. See the [MicroPython DHT interface documentation](https://docs.micropython.org/en/latest/esp8266/tutorial/dht.html).

Use **one data wire and one pull-up per sensor**. Do not join the data wires. DHT22 uses a proprietary single-data-wire protocol, not I²C or Dallas/Maxim 1-Wire.

Keep bench leads short and away from switching loads. For an eventual dryer installation, position sensors to represent the controlled air, avoid direct heater radiation and remain within their specified limits. No physical bay positions are assigned in the code: label and record your sensor locations.

### OLED

Follow printed module labels; header order varies. The supplied driver defaults to address `0x3C`. If a bus scan finds `0x3D`, change construction to:

```python
oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3D)
```

Keep all GPIO bus levels at **3.3 V**. A module that pulls DATA, SDA or SCL up to 5 V needs suitable level translation. The ESP32 3V3 pin is not a supply for a heater or motor.

### Heater and fan interfaces

Only the following interface can be established from source:

```text
GPIO25 --> verified 3.3 V-compatible heater-driver control input
GPIO26 --> verified 3.3 V-compatible fan-driver control input
```

These arrows do not identify S4 connectors or specify a driver circuit. Common ground applies to the bench peripherals above; whether a power interface shares a reference or uses isolation depends on its design. Do not bridge an isolation barrier or attach ESP32 ground to an unverified appliance circuit. Direct connection to an element, motor, mains conductor or unknown factory control pin is not supported.

## Connecting to an actual SUNLU S4

**No reproducible, verified S4 installation procedure is supplied.** The code resembles a standalone controller prototype. It does not establish whether the original author intended to replace the factory controller, interface with its power board or use separate loads.

The upstream [hardware wiring issue](https://github.com/HTRiepe/SUNLU_S4_ESP_Base/issues/2) and its comments contained no schematic or wiring answer when checked on 2 November 2026.

An S4-specific guide still needs:

- Exact hardware revision, labelled PCB/connector photographs and connector orientation.
- Verified pinout, voltage levels and isolation boundaries for every proposed connection.
- Heater/fan ratings, number of loads, existing driver circuits and supported switching method.
- Identification of factory sensors and independent thermal protection.
- A decision on retaining or replacing the controller, display and buttons, with a schematic preventing conflicting drive signals.
- Verified controller power arrangements, including what happens when USB is attached.
- Startup, shutdown, sensor-fault, network-fault and overtemperature test results after the firmware defects are fixed.

Treat appliance power circuitry as potentially mains-referenced until established otherwise. Tracing or modifying mains-powered sections requires appropriate competence and equipment. A guessed connector pinout is not an installation guide.

## Software installation

Use a disconnected low-voltage bench with **no heater, fan or power driver attached**. Normal boot inhibits the heater, but fan-control signals are still driven. This is MicroPython, not Arduino/ESPHome; there is no PlatformIO build.

### 1. Install the board's MicroPython firmware

For a conventional classic ESP32-WROOM board, start at [ESP32_GENERIC](https://micropython.org/download/ESP32_GENERIC/). Follow the exact board's flashing instructions and image address; flash erasure removes existing files. See the [installation guide](https://docs.micropython.org/en/v1.26.0/esp32/tutorial/intro.html). No firmware version has been physically validated here.

### 2. Get the project and tools

~~~sh
git clone https://github.com/Soopahfly/SUNLU_S4_ESP_Base.git
cd SUNLU_S4_ESP_Base
python -m pip install mpremote
mpremote connect list
~~~

If reviewing a firmware-fix PR, check out its branch before copying files. Examples use Windows port COM5; substitute the real port (Linux might use /dev/ttyUSB0). If the command is not on PATH, use python -m mpremote. Close other serial sessions first.

### 3. Copy every runtime module

~~~sh
mpremote connect COM5 fs cp config.py control.py hardware.py runtime.py telemetry.py ssd1306.py :
mpremote connect COM5 fs cp main.py :main.py
mpremote connect COM5 exec "import config, control, hardware, runtime, telemetry, ssd1306; print('Imports OK')"
~~~

Importing main as a module does not start hardware. Copying only main.py is insufficient after this refactor. The original monolithic installation is incompatible with the new module layout.

To enable networking, install the official MQTT library:

~~~sh
mpremote connect COM5 mip install umqtt.simple
~~~

Use umqtt.simple 1.8.1 or a compatible implementation providing connect(timeout=...) and acknowledged QoS 1 publication. An incompatible API faults rather than falling back to unbounded connections. The library has not been tested on a board here. The host-side installer fetches packages without requiring board Wi-Fi. See [mpremote](https://docs.micropython.org/en/v1.26.0/reference/mpremote.html) and [package management](https://docs.micropython.org/en/v1.26.0/reference/packages.html).

### 4. Supply optional private settings

Copy settings.example.py to settings.py **locally**, edit it and upload:

~~~sh
mpremote connect COM5 fs cp settings.py :settings.py
~~~

settings.py is ignored by Git. Defaults need no credentials for local monitoring. NTP is no longer imported or run: scheduling uses wrap-safe ticks, and telemetry uses a sample tick counter rather than claiming a UTC timestamp.

### 5. Run monitoring

~~~sh
mpremote connect COM5 run main.py
~~~

For normal startup from the installed file:

~~~sh
mpremote connect COM5 reset
mpremote connect COM5 repl
~~~

Normal boot is always monitoring-only. See the [MicroPython boot sequence](https://docs.micropython.org/en/v1.26.0/reference/reset_boot.html).

### 6. Explicit heating mode is for supervised dummy-output testing

Keep power stages/loads disconnected. The two gates are a local ALLOW_HEATING=True override **and** an explicit per-run argument:

~~~sh
mpremote connect COM5 exec "import main; main.run(enable_heat=True)"
~~~

This command can drive the bench heater-control GPIO, not merely simulate it. Configured Wi-Fi and MQTT must become healthy before nonzero heater output. The physical power interface, protection and PID tuning remain unverified. Do not use this as an S4 installation procedure.

An armed run enables a watchdog that cannot be stopped once started. After an interruption or fatal exception it may reset the board; normal reboot returns to unarmed monitoring. Monitoring itself does not start the watchdog. See [MicroPython WDT](https://docs.micropython.org/en/v1.26.0/library/machine.WDT.html).

## Configuration

Tracked defaults live in [config.py](config.py); private overrides belong in ignored settings.py. There is no web setup or remote arming command. GPIO numbers are unchanged from the original classic-ESP32 prototype.

| Setting | Default | Meaning |
| --- | --- | --- |
| ALLOW_HEATING | False | Local permission only; normal boot still never arms |
| TARGET_TEMP / MAX_TEMP | 45 / 60 °C | PID target and individual-sensor fault threshold; not validated material/safety limits |
| SENSOR_PINS | (15, 2, 4, 16) | All configured sensors are required; order also sets telemetry order |
| HEATER_PIN / FAN_PIN | 25 / 26 | Active-high bench control interfaces |
| PWM_FREQUENCY | 1000 Hz | Must be matched to identified power electronics before physical use |
| OLED_SDA / OLED_SCL / OLED_ADDRESS | 21 / 22 / 0x3C | External SSD1306 |
| SAMPLE_INTERVAL_MS | 2500 | Minimum wait after each cycle, ensuring DHT measurement spacing |
| MAX_SAMPLE_AGE_MS | 4000 | Maximum age from the start of the sampling round |
| MAX_CONTROL_GAP_MS | 8000 | Longer gaps latch a fault even if the next sample is fresh |
| FAN_COOL_TEMP / COOLDOWN_MS | 30 °C / 300000 | Hot-sensor rule and cooldown from last nonzero heat demand |
| PID_KP / PID_KI / PID_KD | 2 / 0.1 / 0.5 | Now elapsed-time based; old gains must not be treated as physically tuned |
| WIFI_SSID / WIFI_PASSWORD | empty | Leave unset for network-free monitoring |
| MQTT_BROKER / MQTT_PORT | empty / 1883 | Broker address; numeric IP avoids hostname-resolution dependency |
| MQTT_USER / MQTT_PASSWORD | None | Optional local byte-string credentials, as shown in the example settings |
| MQTT_CLIENT_ID | sunlu-controller | Hardware identifier appended automatically |
| MQTT_TOPIC / MQTT_STATUS | sunlu/sensors / sunlu/status | Give each device a unique topic namespace |
| MQTT_TIMEOUT_S / MQTT_INTERVAL_MS | 1 / 5000 | Socket timeout and telemetry interval |
| WIFI_TIMEOUT_MS / NETWORK_RETRY_MS | 15000 / 10000 | Polled Wi-Fi attempt timeout and retry backoff |
| WATCHDOG_MS | 8000 | Used only for explicitly armed runs; physical reset operation untested |

Pin conflicts, invalid targets and invalid control timing are rejected. Data must be finite: DHT22 temperatures in -40…80 °C and humidity in 0…100 %RH. A failure or invalid value at **any** required sensor faults the run.

MQTT currently uses plain TCP; TLS is not implemented. Username/password support does not encrypt traffic. Keep credential files private. A successful QoS 1 PUBACK establishes the last acknowledged broker interaction, not continuous proof of connectivity or physical heater state.

## First bench run

For the interactive Python snippets below, open `mpremote connect COM5 repl`. At the `>>>` prompt, Ctrl-E enters paste mode; paste the snippet and press Ctrl-D to execute it. Ctrl-] exits `mpremote`. Close this session before running another command against the same port.

1. Leave the S4 and all loads/power stages disconnected. Connect the ESP32, sensors and OLED using the bench diagram.
2. Complete the dependency import check before installing automatic startup.
3. Check the OLED bus from the MicroPython REPL:

   ```python
   from machine import Pin, I2C
   bus = I2C(0, scl=Pin(22), sda=Pin(21))
   print([hex(address) for address in bus.scan()])
   ```

   Expect `0x3c` for the default display. An empty list means no device was detected.

4. Read sensors independently, leaving at least two seconds between measurement rounds:

   ```python
   import dht, time
   from machine import Pin
   sensors = [dht.DHT22(Pin(p)) for p in (15, 2, 4, 16)]
   time.sleep(2)
   for number, sensor in enumerate(sensors, 1):
       sensor.measure()
       print(number, sensor.temperature(), sensor.humidity())
   time.sleep(2)
   ```

5. Check broker access from your computer. If Mosquitto client tools are installed, subscribe before starting the controller:

   ```sh
   mosquitto_sub -h YOUR_BROKER_IP -t "sunlu/#" -v
   ```

6. Run the configured program manually and inspect serial output, OLED readings and MQTT JSON. The OLED reports MONITOR ONLY or the current control state; faults show FAULT - HEAT OFF and the latched reason.
7. Optional dummy LEDs show output activity. Use suitable test equipment for PWM frequency/duty checks; LED activity does not establish driver compatibility.

The full program also measures once per round and shares those readings. Validate command timing and actual sensor behaviour on the board before drawing hardware conclusions.

**Stopping:** remove load power independently before interrupting any future powered test. Ctrl-C runs cleanup that commands heat off and full fan demand. An armed watchdog can subsequently reset into monitoring only. Neither software cleanup nor these tests prove that an external power stage switches off. To remove automatic startup with all loads disconnected:

```sh
mpremote connect COM5 fs rm :main.py
mpremote connect COM5 reset
```

## MQTT messages

### Sensor data: sunlu/sensors

Telemetry now uses **QoS 1**, not retained. An illustrative monitoring payload:

~~~json
{
  "sampled_at_ms": 2500,
  "sensors": [
    {"temp": 20, "humidity": 40},
    {"temp": 20, "humidity": 40},
    {"temp": 20, "humidity": 40},
    {"temp": 20, "humidity": 40}
  ],
  "valid_count": 4,
  "avg_temp": 20,
  "avg_hum": 40,
  "max_temp": 20,
  "state": "idle",
  "fault": null,
  "heater_power": 0,
  "fan_power": 0,
  "armed": false,
  "network_ready": true,
  "heater_inhibited": true
}
~~~

Temperatures are °C; humidity is %RH. All readings and summaries use one sampling round. Failed/invalid readings become null; valid_count makes reduced coverage visible, but reduced coverage never permits heating.

sampled_at_ms is the board's wrapping tick counter, **not UTC or permanent uptime**. The old timestamp field was removed. Consumers should use reception time for a wall-clock history.

heater_power and fan_power are control demands, not measured power, airflow or GPIO duty averaged over a cycle. heater_inhibited is True because MQTT work occurs while heater output is zero. State/demand fields describe the controller's pre-publication decision; a fault during that very publication or the post-I/O freshness check may be reported only on a later successful publish. Never use telemetry as the physical safety interlock.

### Availability: sunlu/status

Retained online is published after connection; retained offline is the configured broker Last Will. Both use QoS 1, with a 60-second keepalive. Regular acknowledged publications consume broker responses without relying on a write-only ping. A failed connection/publication closes the socket and schedules retry.

An explicitly armed run latches a network error/loss; reconnecting cannot clear it. Monitoring can reconnect automatically. Availability remains broker connection status, not proof of healthy control. There is no guaranteed graceful offline publish during fault cleanup, which deliberately avoids network I/O.

There is no command topic. MQTT cannot arm, reset faults, start/stop a cycle or change the target.

## Known limitations and faults

| Safeguard | Current software behaviour / remaining limit |
| --- | --- |
| Startup | Explicit low pin level and zero PWM duty; normal boot never arms. Pre-firmware/reset electrical behaviour is unverified. |
| Sensor faults | Any missing, invalid, partial or stale coverage latches heat off and full fan demand. Physical sensor accuracy/placement remains unverified. |
| Overtemperature | Any individual reading at or above MAX_TEMP faults; threshold still needs hardware validation and independent protection. |
| Cleanup | Exceptions/Ctrl-C command heat off/full fan. A broken driver, API or power component cannot be made safe by software alone. |
| PID | Elapsed-time terms, conditional/bounded integral and zero at/above target; gains and thermal behaviour are not physically tuned. |
| Sampling | One shared snapshot; at least 2.5 seconds between sampling rounds. Physical bus/sensor timing has not been measured. |
| Networking | Heater inhibited around I/O; socket timeout/backoff; armed watchdog intended to reset into monitoring. DNS may still block; no independent real-time network task. |
| Fan | Five-minute cooldown, hot-sensor rule and full demand on faults/I/O. No measured rotation/airflow feedback or hardware interlock. |
| OLED | Startup failure exits through heat-off cleanup; runtime display failure latches a fault and sampling continues without display. |
| Hardware | One bench heater channel; no verified S4/Pro driver, supply, protection, connector map or C3 pin map. |

The software regressions are covered by [host tests](tests/README.md). MicroPython execution, watchdog reset, actual PWM levels, networking, cooling and thermal shutdown must still be tested on hardware. Two-zone Pro control is intentionally pending PCB evidence.

To run host verification:

~~~sh
python -m unittest discover -s tests -v
~~~

A GitHub Actions workflow runs the same standard-library suite on Python 3.11 and 3.14. Host tests do not establish safe appliance operation.

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| Missing config/control/hardware/runtime/telemetry module | Upload every runtime module, not only main.py. |
| Missing umqtt | Install umqtt.simple onto the board; local monitoring does not need it. |
| Missing machine / dht | Use appropriate ESP32 MicroPython firmware, not desktop Python. |
| Missing OLED / I²C failure | Check 3.3 V supply, SDA 21, SCL 22, SSD1306 module type and address. |
| No Wi-Fi/MQTT data | Supply settings.py; check SSID, broker, port and byte-string credentials. Monitoring still works without configured networking. |
| No heat at boot | Expected: boot is monitoring-only, regardless of ALLOW_HEATING. |
| Arming is rejected | Both explicit per-run arming and local permission are required, with configured Wi-Fi/MQTT. |
| sensor_failure | Check every configured sensor, separate data lines, pull-ups and sensor type. Restoring readings does not clear the fault. |
| overtemperature | Individual sensor reached MAX_TEMP; identify the cause before any fresh run. |
| stale_sensors / control_gap | Sampling or peripheral/network work exceeded timing limits. Heat stays off. |
| display_error | Display failed during a run; heat is latched off and sampling continues. |
| mqtt_error / network_lost / wifi_timeout | Inspect network/API compatibility; reconnection does not rearm a faulted heating run. |
| Unexpected reset after an armed interruption | The watchdog cannot be stopped once started; reboot returns to monitoring-only. |
| Flashing fails after sensors are wired | Disconnect peripherals, especially GPIO 2 pull-up; verify board strapping/boot procedure. |
| Invalid/conflicting pins | Check config.py and the exact chip; classic ESP32 assignments cannot be used unchanged on a C3. |
| No UTC timestamp | Intentional: tick-based scheduling/telemetry replaced blocking NTP. Use broker/consumer reception time. |

## Files and references

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Monitoring-only boot entry, hardware setup, arming gate and cleanup |
| [config.py](config.py), [settings.example.py](settings.example.py) | Defaults and private-override example |
| [control.py](control.py) | Sensor snapshot, PID, states and latched interlocks |
| [hardware.py](hardware.py) | Explicit-zero PWM and display adapters |
| [runtime.py](runtime.py) | I/O sequencing, sample freshness and watchdog supervision |
| [telemetry.py](telemetry.py) | Polled Wi-Fi setup, acknowledged MQTT and retry policy |
| [tests](tests/README.md) | Host regression suite with mocked hardware |
| [ssd1306.py](ssd1306.py) | OLED driver; includes I²C and SPI classes, application uses I²C |
| [CODE_REVIEW.md](CODE_REVIEW.md) | Findings, proposed fixes and validation limits |
| [docs/HARDWARE_RESEARCH.md](docs/HARDWARE_RESEARCH.md) | S4 Pro teardown, hardware evidence needed and SuperMini assessment |
| [ISSUES.md](ISSUES.md) | Open, actionable work checklist; not completed fixes |
| [.gitignore](.gitignore) | General Python ignore rules |

There is no supplied schematic, PCB design, factory connector map, enclosure, simulation circuit, dependency lockfile or automated hardware test suite. No project licence file was present at the original reviewed commit; public visibility does not establish a particular licence.

Technical references:

- [MicroPython ESP32 GPIO/PWM reference](https://docs.micropython.org/en/latest/esp32/quickref.html): GPIO numbering and PWM API/default duty.
- [Espressif ESP32-WROOM-32 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf): electrical limits and strapping. Check your exact module too.
- [MicroPython DHT interface](https://docs.micropython.org/en/latest/esp8266/tutorial/dht.html): pin functions, pull-ups and measurement spacing. Although under ESP8266 tutorials, the DHT22 interface information applies here.
- [MicroPython installation](https://docs.micropython.org/en/v1.26.0/esp32/tutorial/intro.html), [mpremote](https://docs.micropython.org/en/v1.26.0/reference/mpremote.html), [packages](https://docs.micropython.org/en/v1.26.0/reference/packages.html) and [boot sequence](https://docs.micropython.org/en/v1.26.0/reference/reset_boot.html): deployment guidance. These documentation links do not imply testing on that firmware version.
- [Official `umqtt.simple` source](https://github.com/micropython/micropython-lib/blob/master/micropython/umqtt.simple/umqtt/simple.py): MQTT defaults, publication and ping behaviour. Dependency version is not pinned here.
- [MicroPython WDT](https://docs.micropython.org/en/v1.26.0/library/machine.WDT.html): watchdog operation and inability to stop it once started.

To contribute a verified S4 installation, supply its hardware revision, labelled photographs, schematic, load/driver ratings, supply/isolation details, firmware versions and test results. This evidence is needed to turn the documented ESP32 interfaces into a reproducible appliance conversion.
