# Open work checklist

Recorded 2 November 2026 against firmware `09fa5d7`. All items remain open; this documentation update changes no firmware or hardware.

The fork's GitHub Issues feature was disabled when this record was prepared. This file preserves actionable findings and acceptance criteria; these are not numbered GitHub Issues. See [the review](CODE_REVIEW.md) for source locations and mock reproduction details.

## 1. Critical: establish fail-safe startup, shutdown and sensor interlocks

PWM currently has no explicit startup duty. All-sensor failure can crash formatting, partial failures reduce coverage silently, and the >60 °C display warning does not override heating. Exceptions or interruptions have no guaranteed heat shutdown.

- [ ] Initialise heat outputs explicitly off before display/network operations; verify polarity and hardware boot/reset default-off behaviour.
- [ ] Define idle/heating/cooling/fault states, required sensor coverage, freshness and invalid-value checks.
- [ ] Enforce individual-sensor overtemperature shutdown with an appropriate latched fault/reset policy.
- [ ] Guarantee heat shutdown on sensor, display, network and unexpected software failures, with a defined cooling policy.
- [ ] Preserve/verify independent thermal and electrical protection; document limits from actual hardware.
- [ ] Test cold boot, reset, Ctrl-C, exceptions, missing/stale/partial readings, hotspot and overtemperature cases using dummy outputs first.

Acceptance: automated/mock checks establish software state transitions; physical measurements separately demonstrate safe outputs during boot/reset/faults. Do not equate mock success with validated heater operation.

## 2. High: correct sampling, PID timing and fan cooldown

Sensors can be measured three times per iteration without appropriate spacing. PID has no elapsed-time handling or integral bound. `fan_run_until = 300` and `adapt_pid()` are unused.

- [ ] Take one validated sensor snapshot per scheduled interval and reuse it for control, display and telemetry.
- [ ] Respect DHT22 measurement spacing or replace the driver/sensor design with a verified alternative.
- [ ] Implement elapsed-time PID, anti-windup and reset behaviour; tune only for identified hardware.
- [ ] Implement and document actual fan cooldown; assess airflow feedback/interlock requirements.
- [ ] Test variable loop timing, prolonged cold error, overshoot, cooldown and sensor-failure transitions.

Acceptance: reproducible numerical tests eliminate the documented windup case, measurement-count checks confirm one sample per interval, and physical thermal/fan validation is reported separately.

## 3. High: prevent network failures from blocking safe control

Wi-Fi can wait indefinitely; MQTT startup, reconnect and publish can fail without output cleanup. `ping()` writes a packet without processing the reply in this application. Retained `online` is not proof of healthy control.

- [ ] Bound DNS/connect/retry/publish operations and define an explicit connectivity-loss policy.
- [ ] Separate telemetry/recovery from time-critical sensing and safe output control.
- [ ] Process broker responses and report actual connection/control/fault states.
- [ ] Support unique device IDs and local credential handling; document authentication/TLS choices.
- [ ] Test unavailable Wi-Fi/broker, dropped connections, failed publication and recovery without stale or unintended heater enable.

Acceptance: fault-injection checks demonstrate control deadlines and output policy; live network tests confirm reconnect and status behaviour. Software recovery must not silently clear a latched thermal fault.

## 4. Hardware blocker: identify S4 Pro interfaces and confirm SuperMini suitability

The Pro has two independent heating zones; the existing program provides one heater output. No verified factory connector map, power interface or controller supply exists here.

- [ ] Record the exact appliance and PCB revisions, both board faces, component markings and complete harness map.
- [ ] Identify supply/isolation boundaries, heater and fan topology, sensors, interlocks and protection.
- [ ] Investigate a read-only factory communication capture before selecting bridge or replacement control.
- [ ] Identify the exact ESP32 SuperMini chip/board; assess GPIO budget, strapping/USB conflicts and safe power arrangements.
- [ ] Design two-zone control/fault handling if replacing factory logic; establish fan channel requirements from hardware.
- [ ] Publish an evidence-backed schematic, connector pinout, parts list and validated wiring procedure.
- [ ] Complete dummy-load and supervised physical fault tests; retain factory protection.

Acceptance: the wiring guide names exact supported revisions and separates observed, inferred and measured facts. Video component close-ups and plausible C3 capability do not constitute verified compatibility. Required evidence and teardown references are in [hardware research](docs/HARDWARE_RESEARCH.md).
