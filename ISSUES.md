# Open work checklist

Updated 2 November 2026. The original findings were recorded against firmware `09fa5d7`; see [CODE_REVIEW.md](CODE_REVIEW.md). Software changes below are implemented locally and exercised with CPython mocks. No Sunlu appliance or ESP32 hardware is available. A checked software item does not close its physical acceptance criteria.

## 1. Fail-safe startup, shutdown and sensor interlocks

- [x] Initialise active-high heater/fan GPIOs low and PWM explicitly off before configuration/display/network setup.
- [x] Define idle/heating/cooling/fault states; require all four valid sensors and fresh readings. Reject invalid values and detect late control iterations.
- [x] Shut heat off on any individual sensor at or above the bench overtemperature limit; latch faults until deliberate controller restart.
- [x] Add exception/interrupt cleanup, independent heater-off attempts and full-fan fault demand. Faults do not clear on sensor/network recovery.
- [x] Exercise startup, partial initialisation, configuration/display/network exceptions, Ctrl-C, total/partial/invalid/stale readings, slow acquisition, control gaps and hidden hotspots with host mocks.
- [ ] Measure boot/reset/output polarity and independent hardware default-off behaviour on the exact board/power stage.
- [ ] Establish actual thermal limits, fan cooling/interlock requirements and independent protection. Software cannot preempt a stuck driver/interpreter; assess watchdog and independent heater cutoff using actual hardware.
- [ ] Complete MicroPython runtime and supervised dummy-output/electrical fault checks.

Acceptance: host checks establish software transitions only. This issue remains open for physical startup/reset/fault proof and protection design.

## 2. Sampling, PID timing and fan cooldown

- [x] Acquire each sensor once per scheduled interval; reuse a timestamped snapshot for control, display and telemetry. Space acquisitions from previous completion.
- [x] Provide a two-second startup delay and at least five seconds between acquisition completion and the next start.
- [x] Implement elapsed-time PID, derivative on measurement, bounded conditional integration and reset rules. No positive heat demand at/above target.
- [x] Implement five-minute cooldown after the last positive heat request and full-fan demand while any valid reading exceeds 30 C.
- [x] Test elapsed-time equivalence, prolonged cold error, overshoot, cooldown, clock rollover, repeated-snapshot reuse, sampling count and sensor-fault transitions.
- [ ] Tune gains, temperatures and cooldown using the identified hardware; assess fan feedback/airflow protection.
- [ ] Verify actual DHT timing/accuracy and thermal/fan behaviour on the selected MicroPython build and bench setup.

Acceptance: original numerical windup and repeated-read cases have host regression coverage. Hardware tuning and thermal/fan acceptance remain open.

## 2a. SHT30/SHT31 sensor support

- [x] Add SHT3x single-shot driver with both CRC checks, explicit conversion delay and invalidated cached values on failed acquisitions.
- [x] Retain DHT22 support; select sensor family and an explicit one-to-four SHT inventory in local configuration.
- [x] Support direct addresses 0x44/0x45 or TCA9548A channels, rejecting duplicate/invalid routes. Deselect mux branches on success and failure before OLED access.
- [x] Reuse existing coverage, freshness and overtemperature interlocks without raising temperature limits. Missing configured sensors remain faults.
- [x] Test conversions, CRCs, short reads, missing sensors, partial writes, mux failures, configuration errors, latched faults and the shared display bus on the host.
- [ ] Check actual SHT module identity/address straps, 3.3 V supply/pull-ups, I2C timing and measurement accuracy on the ESP32 bench.
- [ ] Test physical sensor removal, CRC/bus errors, stuck branches and mux reset/recovery. Confirm sensor quantity/placement and hot/dry performance before appliance use.

Acceptance: host checks pass; no physical SHT/mux or MicroPython validation is claimed.

## 3. Network failures and control responsiveness

- [x] Replace blocking startup/reconnect/publish calls with a cooperative telemetry-only MQTT client: nonblocking socket/poll steps, bounded transfer sizes, per-phase deadlines and retry backoff.
- [x] Reject broker hostnames and require numeric IPv4, removing network DNS from the control path. Remove startup NTP dependency.
- [x] Define connectivity-loss policy: local control continues; failed telemetry retries independently. Unexpected adapter failures escaping its handler shut heat down.
- [x] Consume and validate CONNACK/PUBACK; use unique device IDs/topics, current control/fault state, non-retained telemetry and offline will. No retained online safety claim.
- [x] Add ignored local credentials configuration, optional MQTT authentication and explicit trusted-bench/plain-TCP transport limitation.
- [x] Inject missing Wi-Fi, connect/send/ack stalls, rejected connections, fragmented/wrong acknowledgements, failed publication, link loss and reconnect. Verify sensing continues during Wi-Fi failure and current fault state is published after reconnect.
- [ ] Validate on ESP32 MicroPython 1.26.0 and an actual MQTT broker, including nonblocking connect/poll error behaviour and Wi-Fi driver latency. Host socket mocks do not prove real-time deadlines or interoperability.
- [ ] Measure worst-case sensing/display/network driver latency, control cadence and shutdown timing. Define any required hardware watchdog response after measurement.
- [ ] Select secure transport/credentials policy before use beyond an isolated trusted bench. TLS is not implemented.

Acceptance: host protocol/fault-injection checks pass. Live network tests, runtime deadline measurements and deployment transport choices remain open.

## 4. Hardware blocker: identify S4 Pro interfaces and confirm SuperMini suitability

No hardware-dependent work is claimed complete. S4 Pro has two independent heating zones; the current software remains a single-zone bench controller.

- [ ] Record exact appliance/PCB revisions, both board faces, markings and harness map.
- [ ] Identify supplies/isolation, heater/fan topology, sensors, interlocks and protection.
- [ ] Investigate read-only factory communications before choosing bridge/replacement control.
- [ ] Identify exact ESP32 SuperMini chip/board, GPIO budget, strapping/USB conflicts and safe power.
- [ ] Design independent two-zone control/fault handling and fan channel requirements from evidence.
- [ ] Publish verified schematic, connector pinout, parts list and wiring procedure.
- [ ] Complete dummy-load and supervised physical faults while retaining factory protection.

Acceptance: supported revisions and observed/inferred/measured facts must be explicit. See [hardware research](docs/HARDWARE_RESEARCH.md).
