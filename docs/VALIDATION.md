# Firmware remediation validation

Local run: 2 November 2026, Windows, CPython 3.14.4.

```sh
python -m unittest discover -s tests -v
```

Result: **40 tests passed**. Runtime modules and documentation snippets were also
parsed with host Python; relative links/contents anchors and whitespace checks
passed. The CI workflow is configured to run the same suite on CPython 3.11 and
3.14; its live status must be checked separately from this local report.

## What was exercised

- The actual control module with fake sensor readings and a wrapping fake clock.
- Explicit zero-duty construction and fan-before-heat ordering in the actual
  output adapter, using fake machine.Pin and machine.PWM implementations.
- A normal main.run() boot with mocked machine/display/sensors, including local
  heating permission True: no nonzero heater command and no watchdog startup.
- Sensor, display, output-initialisation, network and interruption fault paths.
- Interlocked peripheral/network/logging operations, freshness checks before
  resuming heat, and stale-data supervision during the inter-cycle wait.
- PID elapsed-time integration, bounded saturation and the original windup
  example; hotspot shutdown independent of average temperature.
- Single-snapshot reuse, measurement cadence, cooldown and latched fault recovery.
- MQTT adapter timeout arguments, QoS 1 calls, unique IDs, socket cleanup,
  initial Wi-Fi timeout, delayed retry and network-free monitoring.

## What this does not establish

No tests ran on MicroPython, ESP32 or the real umqtt.simple transport. There was
no device flashing, physical watchdog reset, electrical measurement, live broker,
sensor calibration, thermal tuning, fan/airflow test or S4/Pro appliance test.
Mocks can establish software commands and ordering; they cannot prove GPIO levels,
power-stage response, reset behaviour, electrical isolation or protection.

Networking is synchronous. Socket timeouts do not bound DNS or every firmware
call. Heat is inhibited before those calls; an explicitly armed run starts a
watchdog intended to reset a stalled device into unarmed monitoring. This reset
and the external default-off circuit still require physical verification.

## Before any powered load test

Complete the hardware investigation in [HARDWARE_RESEARCH.md](HARDWARE_RESEARCH.md)
and the unchecked physical tasks in [ISSUES.md](../ISSUES.md). Use dummy outputs
first. Record the exact chip/board, MicroPython/library versions, driver topology,
isolation, command waveform, thresholds and observed fault/reset behaviour.

The current software continues to use the classic-ESP32 single-heater bench pin
map. It is not a validated S4 Pro conversion or ESP32-C3 SuperMini firmware port.
