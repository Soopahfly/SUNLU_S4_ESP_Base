# Host regression tests

Run from the repository root with desktop Python 3.11 or newer:

```sh
python -m unittest discover -s tests -v
```

Only the Python standard library is required. Tests exercise the actual control,
output sequencing, runner and telemetry modules with fake pins, PWM, clock,
sensors, OLED, WLAN and MQTT. No test connects to a serial device or network.

Coverage includes explicit zero startup, monitor-only boot, missing/partial/
invalid readings, individual overtemperature, stale data, clock wrapping, PID
windup and elapsed time, cooldown, fan-before-heat ordering, display/startup
failures, MQTT timeouts/retries, network recovery preserving faults, Ctrl-C,
sampling cadence and heater inhibition during all peripheral/network work.

Tests assert software commands. They do not establish actual GPIO voltages,
MicroPython compatibility, watchdog reset operation, sensor accuracy, fan airflow,
electrical isolation or S4/S4 Pro safety. Those require physical bench work.
