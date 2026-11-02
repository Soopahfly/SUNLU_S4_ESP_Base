# Code review

Historical review of firmware `09fa5d7`. Commit [`8ca81aa`](https://github.com/Soopahfly/SUNLU_S4_ESP_Base/commit/8ca81aa) implements software remedies for shutdown/interlocks, sampling, PID/cooldown and cooperative networking, and adds SHT30/SHT31 support with host regression tests. The findings below preserve the original evidence and line numbers; they are not a description of the current code. See [ISSUES.md](ISSUES.md) for current progress and remaining runtime/hardware acceptance.

Reviewed on 2 November 2026 against commit `09fa5d7`: `main.py` (219 lines) and `ssd1306.py`. The original review did not change firmware; the later implementation is summarised below.

## Assessment

This is a standalone MicroPython controller prototype, not a complete SUNLU S4 conversion. Sensor/display connections can be recovered from code; factory appliance connections and power electronics cannot.

Severity below reflects potential consequences with a power driver attached, not evidence of a physical incident.

## Resolution status after commit 8ca81aa

| Original finding | Implemented software remedy | Acceptance still pending |
| --- | --- | --- |
| Unspecified startup PWM duty | GPIOs low, then explicit zero-duty PWM before configuration/display/network setup | Measured boot/reset levels, active-high polarity and hardware default-off |
| Faults can leave heat commanded on | Latched faults, required sensor coverage/freshness, exception/interrupt cleanup, independent heater-off attempts and full-fan fault demand | Physical fault injection, output-stage behaviour and independent protection |
| Average-temperature warning hides hotspots | Any individual valid sensor at or above 60 C trips the bench controller | Hardware-derived limits, placement and independent thermal cutoff |
| PID integral windup and missing elapsed time | Elapsed-time PID, derivative on measurement, bounded conditional integration and reset rules; zero heat at/above target | Thermal tuning on identified hardware |
| Repeated sensor measurements | One acquisition per interval, reused for control/display/telemetry; next acquisition at least five seconds after previous completion | Actual DHT/SHT timing, wiring and driver latency |
| Blocking/unhandled network operations | Cooperative nonblocking MQTT steps, phase deadlines/backoff, numeric IPv4 only, validated CONNACK/PUBACK; local control continues during expected connectivity loss | ESP32 network latency, real broker interoperability and live recovery |
| Missing coverage policy and cooldown | Every configured sensor required; five-minute cooldown after the last heat request; full-fan demand on fault | Airflow/rotation feedback, cooling effectiveness and reset/power-loss behaviour |

Additional changes: SHT30/SHT31 adapters with both CRC checks and optional TCA9548A routing; ignored local configuration; unique MQTT IDs/topics and optional username/password authentication. The example selects four multiplexed SHT sensors, while an absent config preserves four DHT22 inputs. Heating and networking are disabled by default.

Validation recorded for the implementation: **30 passing CPython 3.12.10 host tests**, Python compilation and clean Git whitespace checks. Tests use mocked peripherals, clocks, Wi-Fi and sockets. No MicroPython execution, ESP32 flashing, live broker/network tests, electrical measurements, appliance operation or physical safety validation has been completed. See [the fix record](docs/SOFTWARE_FIXES.md) and [current checklist](ISSUES.md).

## Historical findings against 09fa5d7


### Critical: no explicit safe startup duty

**Location:** `main.py:33–40`, before network setup at `159–161`.

Both PWM constructors specify frequency but no duty. The ESP32 MicroPython reference documents default duty as 512/1023. Startup can then wait indefinitely for Wi-Fi, or fail at MQTT connection, before deliberate output values are set. An active-high driver could therefore energise a load before a successful measurement. Actual electrical behaviour depends on firmware and hardware and has not been measured here.

**Remedy:** initialise outputs explicitly off before blocking operations, verify polarity, and provide hardware default-off behaviour during boot/reset. Software cannot protect the period before it runs.

### Critical: faults do not guarantee heater shutdown

**Location:** `main.py:143–155`, `175–219`, particularly `184–187`, `214`, `218`.

When all sensors fail, averaging returns `(None, None)`. The following formatted print raises `TypeError`; no `try/finally` commands heat off. Display and MQTT operations can also raise or stall after an earlier duty was set.

**Host reproduction:** four failing mock sensors returned `(None, None)`; formatting failed, leaving a mock heater previously set to 50% at 511/1023. This establishes a missing shutdown command, not the physical lifetime of ESP32 PWM after an exception.

**Remedy:** validate sensor coverage/freshness, define fault states, shut heat down reliably and bound network operations outside the control path. Define appropriate cooling behaviour too: blindly clearing every output is not a complete thermal safety policy. Use independent hardware protection.

### Critical: overtemperature warning cannot stop heat

**Location:** `main.py:118–124`, `184–198`, `213–214`.

The >60 °C check only changes display text. It neither overrides heat demand nor latches a fault, and averaging can hide a hot sensor.

**Host reproduction:** `[80, 20, 20, 20]` °C averages to 35 °C. Warning is false and the initial PID requests heat.

**Remedy:** check individual maximum temperatures and sensor health before enabling heat; implement a suitable latched fault and independent thermal protection. Derive limits from identified hardware, not unvalidated source defaults.

### High: PID integral windup

**Location:** `main.py:109–124`, configuration `163–164`.

The integral is unbounded; clamping the final output does not prevent windup. Integral and derivative ignore elapsed time despite variable loop duration.

**Host reproduction:** with supplied gains and 45 °C target, 200 calls at 20 °C cause the following call at 65 °C to request 100% heat. This is a numerical demonstration, not a simulation of S4 thermal behaviour.

**Remedy:** anti-windup, elapsed-time handling and reset rules, followed by tuning for actual hardware after shutdown mechanisms are in place.

### High: repeated DHT22 sampling without sufficient spacing

**Location:** `main.py:184`, `192`, `206`.

Averaging, fan checks and telemetry each call `measure()` again. The fan pass short-circuits on a hot sensor; below threshold, all four can be read three times per iteration without a deliberate two-second gap. Sleeping at the loop end does not space these reads.

**Host reproduction:** cool mock sensors each received three measurement calls in the iteration's measurement sequence. MicroPython recommends no more than one DHT22 measurement every two seconds for accurate results.

**Remedy:** read each sensor once per scheduled interval and reuse a timestamped, validated snapshot.

### High: networking can interrupt control

**Location:** `main.py:64–81`, `159–161`, `177–180`, `218`.

Wi-Fi waits without a timeout. MQTT startup, in-loop reconnect and final publication can fail without output cleanup. In official `umqtt.simple`, `ping()` writes a packet without waiting for the response; the application never calls `check_msg()` or `wait_msg()` to consume incoming MQTT packets. A successful write does not establish broker responsiveness.

**Remedy:** bounded retry/response handling and explicit network-fault policy; broker/DNS failure must not block safe control. Retained `online` is not a safety signal.

### Medium: sensor coverage and fan behaviour are unverified

**Location:** `main.py:98–106`, `143–155`, `192–198`.

Partial sensor failures are excluded from means without a coverage fault. Fan-check exceptions are ignored, and there is no airflow/rotation feedback. `fan_run_until = 300` at line 43 is unused: no five-minute cooldown is implemented.

**Remedy:** define required sensor coverage, fault reporting, cooldown policy and an appropriate fan/airflow interlock for the identified heater.

### Integration gaps

- No S4 revision, schematic, connector map, load ratings, driver selection or safe controller supply.
- No evidence that added DHT22 sensors match the factory sensors.
- No demonstrated firmware/dependency version or physical validation.
- No MQTT authentication/TLS configuration, command handling, discovery or drying-cycle completion.
- `adapt_pid()` is unused; humidity PID is commented out. Neither is an implemented feature.
- OLED initialisation is mandatory and happens before networking. The I²C display defaults to `0x3C`; the driver's SPI support is unused.
- No project licence file at the reviewed commit; preserve driver provenance and establish licensing for redistribution.

## Validation performed for the original review

- Read all tracked source files and checked README facts against them.
- Parsed both Python files with host Python 3.14.4.
- Executed only AST-extracted control/helper definitions with mock sensors/output; did not run hardware initialisation or import the main loop on the host.
- Confirmed total-sensor failure, hidden hotspot, PID windup, repeated reads and omitted initial duty as described above.
- Checked peripheral/deployment guidance against official MicroPython documentation, Espressif documentation and the official MQTT library source, linked in [README.md](README.md#files-and-references).
- Read the upstream wiring issue and its comments: no schematic or connector answer was present.

**Not performed:** ESP32 flashing, MicroPython runtime tests, live MQTT/network fault tests, electrical measurements, S4 inspection/wiring, load operation or physical safety validation. Mock checks establish software paths only.

## Original suggested implementation order

1. Identify hardware, power interfaces, isolation and independent thermal/electrical protection.
2. Implement safe startup, explicit fault states, maximum-temperature interlock and reliable heat shutdown.
3. Sample sensors once per scheduled interval and reuse validated readings.
4. Separate bounded networking from control; implement tested recovery and fault telemetry.
5. Correct/tune PID and define fan cooldown/interlock behaviour.
6. Exercise faults with dummy loads before supervised physical installation, and document the evidence.

This was the original implementation plan. Its software remedies are now implemented as summarised above; hardware identification, runtime validation, thermal tuning and physical acceptance remain open.
