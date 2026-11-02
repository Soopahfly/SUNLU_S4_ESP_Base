# Work checklist and validation status

Updated 2 November 2026 after the firmware refactor. Historical defects refer to original commit `09fa5d7`; current code and tests are described below. A checked software item means implementation plus host regression evidence, **not physical validation**.

The fork's GitHub Issues feature was disabled when this checklist was created. These remain file-based tasks, not numbered GitHub Issues. See [historical review and remediation status](CODE_REVIEW.md).

## 1. Fail-safe startup, shutdown and sensor interlocks

- [x] Explicit low heater pin and zero PWM duty before peripheral/network work.
- [x] Monitoring-only boot/reset, independent local permission and explicit per-run arming.
- [x] Idle/heating/cooling/fault states; all sensors required; invalid/future/stale readings fault.
- [x] Individual-sensor overtemperature latch; restored readings and network reconnection do not clear faults.
- [x] Heat-off/full-fan cleanup on Ctrl-C and unexpected exceptions; display failures latch heat off.
- [x] Host regressions for partial/total/invalid sensor failure, hotspot, threshold equality, boot, interruption and startup/display failures.
- [ ] Measure GPIO boot/reset/fault behaviour and driver polarity on a physical ESP32.
- [ ] Verify independent thermal/electrical protection, sensor placement and thresholds against the actual dryer.
- [ ] Validate physical cooling and power-stage shutdown; software fan demand is not an airflow measurement.

## 2. Sampling, PID timing and fan cooldown

- [x] One timestamped sensor snapshot reused by control, OLED and telemetry.
- [x] At least 2.5 seconds between rounds; no repeated fan/telemetry sensor measurement.
- [x] Elapsed-time PID, bounded/conditional integral, reset when disabled/faulted, zero demand at/above target.
- [x] Five-minute cooldown from last nonzero heat demand; hot-sensor and fault fan policy.
- [x] Host tests for the original windup example, integration time, saturation, cadence, cooldown and tick wrapping.
- [ ] Tune against the identified plant; account for heater pauses during peripheral/network I/O.
- [ ] Measure sensor timing/accuracy and establish fan feedback/interlocks if required.

## 3. Network recovery without leaving heat enabled during I/O

- [x] Polled Wi-Fi setup with attempt timeout and retry backoff; no infinite connection wait loop.
- [x] MQTT connect/socket timeout, QoS 1 acknowledgements, socket closure on error and delayed retry.
- [x] Heater inhibited and full fan demanded before sensor/display/network work; sample freshness rechecked before resuming outputs.
- [x] Network loss/error latches a requested heating run; recovery cannot rearm it.
- [x] Unique hardware-derived client ID and ignored local credentials.
- [x] Armed-only watchdog configured; ordinary boot is monitoring-only and does not start the watchdog.
- [x] Host injection tests for slow network work, disconnection, publish failure, reconnect and exceptions.
- [ ] Validate watchdog reset and safe boot electrically; DNS/firmware calls may still block, with heat inhibited.
- [ ] Test live broker/Wi-Fi failure, latency and recovery on the actual MicroPython version.
- [ ] Implement TLS if needed; present MQTT transport is plain TCP with optional byte-string credentials.

Network servicing is synchronous and interlocked; it is **not** an independent real-time task. No claim of hard sampling deadlines during blocked DNS is made.

## 4. Hardware blocker: S4 Pro and SuperMini integration

- [ ] Record exact appliance/PCB revisions, both board faces, component markings and full harness map.
- [ ] Establish supply/isolation boundaries, heater/fan topology, sensors, interlocks and protection.
- [ ] Investigate a read-only factory communications capture before choosing bridge or controller replacement.
- [ ] Identify the exact SuperMini; allocate pins with strapping/USB constraints and verify power arrangements.
- [ ] Implement two-zone Pro control only after the hardware/interface design is established.
- [ ] Publish a measured schematic, connector pinout, parts list and revision-specific wiring guide.
- [ ] Complete dummy-load and supervised physical fault tests.

The current firmware deliberately retains the original classic-ESP32 pin map and one heater interface. [Hardware research](docs/HARDWARE_RESEARCH.md) records the Pro teardown and required evidence.

## Validation levels

- Host: run `python -m unittest discover -s tests -v`; only the standard library is needed.
- CI: the same suite is configured for Python 3.11 and 3.14.
- Device: no ESP32 flashing, MicroPython runtime, live network, electrical, load or appliance tests have been performed.
