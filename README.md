# SUNLU S4 ESP32 controller base

Experimental MicroPython firmware for an ESP32-based filament dryer controller: four temperature/humidity sensors, an OLED display, heater and fan control signals, and MQTT telemetry.

**Status: prototype.** The code defines the ESP32 connections, but this repository does **not** contain a verified wiring diagram for the original SUNLU S4 electronics. It also has control and fault-handling defects that must be fixed before operating a heater. Start with the low-voltage bench setup below, with the dryer and power stages disconnected.

This guide describes firmware commit `09fa5d7`. Pin assignments and behaviour come from [main.py](main.py) and [ssd1306.py](ssd1306.py). The suggested bench components and wiring have not been physically tested with this project. See [CODE_REVIEW.md](CODE_REVIEW.md) for the review findings and validation limits.

**S4 Pro research:** the S4 and S4 Pro are separate hardware targets. The Pro has two independently heated chambers; this firmware exposes only one heater output. Neither appliance has verified compatibility here. See [S4 Pro hardware research and ESP32-C3 assessment](docs/HARDWARE_RESEARCH.md) for teardown timestamps, evidence requirements and proposed investigation steps, and [the open work checklist](ISSUES.md) for unresolved work. No firmware fixes or Pro conversion have been implemented.

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

On startup, the program initialises peripherals, connects to Wi-Fi, attempts NTP clock synchronisation, and connects to MQTT. The control loop starts only after Wi-Fi and MQTT connection succeed.

Each loop:

1. Attempts an MQTT ping, reconnecting if that call raises an exception.
2. Reads the DHT22 sensors and averages successful temperature and relative-humidity readings.
3. Calculates heater duty using a PID controller with a fixed **45 °C** target.
4. Requests full fan output when heater demand is above zero **or any readable sensor is above 30 °C**; otherwise requests fan off.
5. Displays readings and output demands on the OLED, with a warning if the **average** temperature exceeds **60 °C**.
6. Publishes sensor data to MQTT and sleeps for five seconds.

The actual interval exceeds five seconds because measurements and networking add time. Sensors are measured again for the fan check and telemetry, so these are not all the same measurement snapshot.

| Feature | Current implementation |
| --- | --- |
| Sensing | Four independent DHT22 inputs; averages successful reads |
| Temperature control | One heater output; fixed target in source |
| Fan control | One output; main loop requests 0% or 100% |
| Display | External 128 × 64 SSD1306 I²C OLED, with German labels |
| Networking | Wi-Fi, startup NTP attempt and MQTT publishing |
| Remote commands | None: no MQTT subscription, start/stop command or remote setpoint |
| Home Assistant | Telemetry can be consumed manually; no discovery or supplied configuration |
| Drying programmes | No material presets, duration timer or humidity-based completion |
| Original S4 controls | No implementation for its display, buttons, sensors or controller protocol |
| Safety shutdown | No complete software fail-safe or independent protection design |

The loop runs continuously after startup. There is no drying-cycle start button or automatic finish. Humidity is reported but does not control heating.

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
| 1 each | 2.4 GHz Wi-Fi network and reachable MQTT broker | Both are required to reach the unmodified control loop. |

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

Taken directly from `main.py`:

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

Work on the bench with **no heater, fan or power driver connected**. Copying `main.py` to the board enables execution after a normal boot.

### 1. Install MicroPython

Use stable firmware for your exact board/chip. A conventional classic ESP32-WROOM development board normally uses [ESP32_GENERIC firmware](https://micropython.org/download/ESP32_GENERIC/). Follow its board-specific flashing instructions, including image address and bootloader procedure. Flash erasure removes existing files.

This is MicroPython, not Arduino or ESPHome; there is no PlatformIO build. No tested firmware version is pinned in this repository. See the [official ESP32 installation guide](https://docs.micropython.org/en/v1.26.0/esp32/tutorial/intro.html).

### 2. Get the project and host tool

```sh
git clone https://github.com/Soopahfly/SUNLU_S4_ESP_Base.git
cd SUNLU_S4_ESP_Base
python -m pip install mpremote
mpremote connect list
```

Examples use Windows port `COM5`: replace it with your board's port. Linux might use `/dev/ttyUSB0`, macOS `/dev/cu.usbserial-...`. Close other serial terminals before using the port.

If `mpremote` is not found after installation, use `python -m mpremote` in place of `mpremote` in these commands.

### 3. Install dependencies

```sh
mpremote connect COM5 mip install umqtt.simple
mpremote connect COM5 fs cp ssd1306.py :ssd1306.py
mpremote connect COM5 exec "import network, machine, dht, ujson, utime, ntptime, ssd1306; from umqtt.simple import MQTTClient; print('Imports OK')"
```

`mpremote mip` downloads through the host; the board need not already be on Wi-Fi. `umqtt.simple` comes from [micropython-lib](https://github.com/micropython/micropython-lib/tree/master/micropython/umqtt.simple). Other imports depend on the firmware. If `ntptime` is missing, use `mpremote connect COM5 mip install ntptime`, then repeat the check. Missing `machine` or `dht` usually indicates an unsuitable runtime/firmware.

See [mpremote](https://docs.micropython.org/en/v1.26.0/reference/mpremote.html) and [package management](https://docs.micropython.org/en/v1.26.0/reference/packages.html). Record firmware and dependency versions when validating hardware.

### 4. Configure and run manually

Edit your local `main.py` using the configuration section. Test the peripherals first, then run without installing an automatic startup file:

```sh
mpremote connect COM5 run main.py
```

This executes the real control program and **does not disable PWM**. Keep power drivers and loads disconnected.

### 5. Install automatic startup after bench checks

```sh
mpremote connect COM5 fs cp main.py :main.py
mpremote connect COM5 reset
mpremote connect COM5 repl
```

These install/start the prototype; they do not make it suitable for heater operation. A normal boot runs `main.py`; see the [boot sequence](https://docs.micropython.org/en/v1.26.0/reference/reset_boot.html).

## Configuration

Settings are embedded in `main.py`; no separate configuration file, web interface or captive portal exists. Keep real Wi-Fi credentials out of public commits.

| Setting | Current value | Where / what to change |
| --- | --- | --- |
| Wi-Fi | `Wokwi-GUEST`, empty password | Arguments to `sta_if.connect(...)` inside `connect_wifi()` |
| Broker | `mqtt.local` | `MQTT_BROKER`: resolvable hostname or broker IP |
| Client ID | `sunlu-controller` | `MQTT_CLIENT_ID`: unique per controller |
| Sensor topic | `sunlu/sensors` | `MQTT_TOPIC` |
| Availability topic | `sunlu/status` | `MQTT_STATUS`: use separate topics for separate devices |
| Target | `45.0` °C | `TARGET_TEMP`: code default, not a validated material profile |
| PID gains | `2.0`, `0.1`, `0.5` | `PID(Kp=..., Ki=..., Kd=...)`: not tuned for an identified heater |
| Sensors | `[15, 2, 4, 16]` | `SENSOR_PINS`: order also sets MQTT sensor order |
| OLED | SDA 21, SCL 22; 128 × 64; `0x3C` | I²C/display construction |
| Outputs | Heater 25, fan 26; 1000 Hz | `PWM(...)`: frequency changes require driver/load verification |
| Fan rule | Any sensor strictly above 30 °C | Default `threshold` in `any_sensor_over_threshold()` |
| Display warning | Average strictly above 60 °C | `warning = ...`: **does not switch heat off** |
| Loop sleep | 5 seconds | Final `time.sleep(5)`: actual interval is longer |

For example, replace the existing Wi-Fi connection line with:

```python
sta_if.connect('YOUR_WIFI_SSID', 'YOUR_WIFI_PASSWORD')
```

`Wokwi-GUEST` is a simulator-style default, not a setup access point provided by this firmware. No Wokwi circuit file is included.

The MQTT constructor supplies no authentication, TLS or custom port; the standard library defaults to plain MQTT on TCP 1883. An authenticated broker needs constructor changes and local credential handling. A `.local` name might not resolve; a known IP avoids that dependency.

NTP failure is printed and startup continues. After a successful standard NTP sync, timestamps are UTC; there is no timezone/daylight-saving conversion or timezone marker in the payload.

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

6. Run the configured program manually and inspect serial output, OLED readings and MQTT JSON. OLED labels include `Heizung` (heater), `Luefter` (fan), `Feuchte` (humidity) and `WARNUNG` (warning).
7. Optional dummy LEDs show output activity. Use suitable test equipment for PWM frequency/duty checks; LED activity does not establish driver compatibility.

The sensor-only check measures once per round. The full program currently repeats measurements too quickly, so passing this check does not establish main-loop reliability.

**Stopping:** remove load power independently before interrupting any future powered test. Ctrl-C interrupts the bench loop but does not guarantee output shutdown: no cleanup handler exists. To remove automatic startup with all loads disconnected:

```sh
mpremote connect COM5 fs rm :main.py
mpremote connect COM5 reset
```

## MQTT messages

### Sensor data: `sunlu/sensors`

The current `publish()` uses library defaults: QoS 0, not retained. This is an illustrative payload, not a captured hardware result:

```json
{
  "timestamp": "2026-11-02 06:30:00",
  "sensors": [
    {"temp": 43.0, "humidity": 30.0},
    {"temp": 44.0, "humidity": 32.0},
    {"temp": 45.0, "humidity": 31.0},
    {"temp": 44.0, "humidity": 31.0}
  ],
  "avg_temp": 44.0,
  "avg_hum": 31.0,
  "heater_power": 2.6
}
```

| Field | Meaning |
| --- | --- |
| `timestamp` | RTC time: UTC after successful standard NTP sync, potentially incorrect after failed sync |
| `sensors` | Four entries in `SENSOR_PINS` order; °C and %RH |
| `avg_temp`, `avg_hum` | Means of earlier successful reads, excluding failures |
| `heater_power` | Requested duty percentage, **not measured watts** |

Failed individual telemetry reads produce `{"temp": null, "humidity": null}`. Total failure in the earlier averaging step can crash the loop before publication. Repeated reads mean individual entries need not average to the published means. Fan demand and warning state are not included.

### Availability: `sunlu/status`

- Retained `online` is published on MQTT connection.
- Retained `offline` is configured as the Last Will, sent by the broker after it detects an ungraceful disconnection.
- Keepalive is 60 seconds.

Availability reports broker connection status, not proof of healthy control or a safe heater state. There is no explicit graceful-shutdown status publish. In `umqtt.simple`, `ping()` sends a packet; this application does not process responses with `check_msg()` or `wait_msg()`.

There is no command topic. Publishing a target or stop message does not change operation.

## Known limitations and faults

These issues are present in the reviewed code. **Documentation does not fix them.** See [the review](CODE_REVIEW.md) for reproduction details and proposed remedies.

| Issue | Consequence |
| --- | --- |
| PWM constructors omit explicit zero duty | Startup is not guaranteed off. The ESP32 MicroPython reference documents default duty 512/1023; verify the actual firmware and implement safe initialisation. |
| No outer fault handler or guaranteed cleanup | Exceptions from display, MQTT or sensor processing can leave an earlier command in effect. |
| All failed sensors return `None` averages | Formatting raises before a controlled shutdown. |
| Partial failures are excluded from means | Control continues with reduced sensor coverage and no explicit coverage fault. |
| 60 °C warning is display-only, based on average | Cooler readings can hide hotspots; warning does not override heat demand. |
| Unbounded PID integral; no elapsed-time handling | Demand can stay high after overshoot; varying loop time changes control behaviour. |
| Repeated DHT22 reads without two-second spacing | Fan checks and telemetry can encounter errors or unreliable readings. |
| Network operations share the control path | Startup/reconnection can block or raise without safe shutdown. |
| No timed cooldown | `fan_run_until = 300` is unused; actual fan logic uses heat demand / sensor temperature. |
| No fan/airflow feedback | A fan command does not establish airflow. |
| No watchdog or independent protection design | External protection and firmware fault handling remain necessary. |

`adapt_pid()` is never called: the PID uses fixed constructor gains. Humidity PID appears only in commented-out code.

Until corrected and physically validated, use this project for development on a disconnected bench, not unattended drying.

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| `No module named umqtt` | Install `umqtt.simple` onto the board, not with desktop `pip`. |
| `No module named ssd1306` | Copy the supplied driver to the board root. |
| Missing `machine` / `dht` | Use appropriate ESP32 MicroPython firmware, not desktop Python. |
| OLED error / no display | Check supply, SDA 21, SCL 22, module type and address. The display initialises before Wi-Fi. |
| Endless Wi-Fi dots | Replace `Wokwi-GUEST`; check password, 2.4 GHz network and signal. No timeout exists. |
| MQTT error | Check IP/DNS, TCP 1883, broker policy and authentication requirements. Successful connection is required before control begins. |
| DHT timeout/checksum errors | Check type, supply, GPIOs, separate data lines and pull-ups. Test individually; rapid repeat reads are also a code defect. |
| `NoneType` formatting error | All averaging reads failed. This path does not implement safe heater shutdown. |
| Flashing fails after wiring sensors | Disconnect peripherals, especially the GPIO 2 pull-up; check the board's boot/strapping procedure. |
| Invalid pins / peripheral conflict | Verify exact chip/module and schematic; the pin map assumes a classic ESP32 with those GPIOs free. |
| Controllers disconnect one another | Use unique client IDs and separate topic namespaces. |
| Wrong timestamp | Check NTP connectivity; local timezone conversion is absent. |
| Telemetry values differ from averages | Separate measurements are taken for averages and telemetry. |
| Warning displayed while heat demand stays high | Warning is not an interlock; PID windup is possible. Remove heater power independently. |

## Files and references

| File | Purpose |
| --- | --- |
| [main.py](main.py) | Hardware setup, networking, sensing, control and display updates |
| [ssd1306.py](ssd1306.py) | OLED driver; includes I²C and SPI classes, application uses I²C |
| [CODE_REVIEW.md](CODE_REVIEW.md) | Findings, proposed fixes and validation limits |
| [docs/HARDWARE_RESEARCH.md](docs/HARDWARE_RESEARCH.md) | S4 Pro teardown, hardware evidence needed and SuperMini assessment |
| [ISSUES.md](ISSUES.md) | Open, actionable work checklist; not completed fixes |
| [.gitignore](.gitignore) | General Python ignore rules |

There is no supplied schematic, PCB design, factory connector map, enclosure, simulation circuit, dependency lockfile or automated hardware test suite. No project licence file is present at the reviewed commit; public visibility does not establish a particular licence.

Technical references:

- [MicroPython ESP32 GPIO/PWM reference](https://docs.micropython.org/en/latest/esp32/quickref.html): GPIO numbering and PWM API/default duty.
- [Espressif ESP32-WROOM-32 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf): electrical limits and strapping. Check your exact module too.
- [MicroPython DHT interface](https://docs.micropython.org/en/latest/esp8266/tutorial/dht.html): pin functions, pull-ups and measurement spacing. Although under ESP8266 tutorials, the DHT22 interface information applies here.
- [MicroPython installation](https://docs.micropython.org/en/v1.26.0/esp32/tutorial/intro.html), [mpremote](https://docs.micropython.org/en/v1.26.0/reference/mpremote.html), [packages](https://docs.micropython.org/en/v1.26.0/reference/packages.html) and [boot sequence](https://docs.micropython.org/en/v1.26.0/reference/reset_boot.html): deployment guidance. These documentation links do not imply testing on that firmware version.
- [Official `umqtt.simple` source](https://github.com/micropython/micropython-lib/blob/master/micropython/umqtt.simple/umqtt/simple.py): MQTT defaults, publication and ping behaviour. Dependency version is not pinned here.
- [Official `ntptime` source](https://github.com/micropython/micropython-lib/blob/master/micropython/net/ntptime/ntptime.py): NTP clock synchronisation and UTC behaviour.

To contribute a verified S4 installation, supply its hardware revision, labelled photographs, schematic, load/driver ratings, supply/isolation details, firmware versions and test results. This evidence is needed to turn the documented ESP32 interfaces into a reproducible appliance conversion.
