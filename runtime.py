"""Application sequencing with injectable dependencies for fault tests."""

from control import sample_sensors


class Runner:
    def __init__(self, cfg, clock, controller, outputs, sensors, display, telemetry, enable_heat=False, log=None):
        if enable_heat is not True and enable_heat is not False:
            raise ValueError("enable_heat must be a boolean")
        if enable_heat and cfg.ALLOW_HEATING is not True:
            raise ValueError("local ALLOW_HEATING permission is required")
        if enable_heat and not telemetry.enabled:
            raise ValueError("configured Wi-Fi and MQTT are required to arm")
        self.cfg, self.clock, self.controller, self.outputs = cfg, clock, controller, outputs
        self.sensors, self.display, self.telemetry = sensors, display, telemetry
        self.enable_heat, self.was_ready, self.snapshot = enable_heat, False, None
        self.log, self.last_report = log, None

    def cycle(self):
        try:
            self.outputs.pause()
            snapshot = sample_sensors(self.sensors, self.clock.ticks_ms())
            self.snapshot = snapshot
            ctrl, net = self.controller, self.telemetry
            ctrl.step(snapshot, self.clock.ticks_ms(), self.enable_heat and net.ready)
            if self.display is not None:
                try:
                    self.display.update(snapshot, ctrl, self.enable_heat)
                except Exception:
                    ctrl.trip("display_error")
                    self.display = None
            payload = dict(snapshot)
            payload.update({
                "state": ctrl.state, "fault": ctrl.fault,
                "heater_power": ctrl.heater_power, "fan_power": ctrl.fan_power,
                "armed": self.enable_heat, "network_ready": net.ready,
                "heater_inhibited": True,
            })
            net.service(payload)
            if self.enable_heat and (net.error or (self.was_ready and not net.ready)):
                ctrl.trip(net.error or "network_lost")
            self.was_ready = self.was_ready or net.ready
            ctrl.check_snapshot(snapshot, self.clock.ticks_ms())
            report = (ctrl.state, ctrl.fault, net.ready, net.error)
            if self.log is not None and report != self.last_report:
                self.log("state=%s fault=%s network_ready=%s network_error=%s" % report)
                self.last_report = report
            # Serial logging can also take time; it too occurs with heat off.
            ctrl.check_snapshot(snapshot, self.clock.ticks_ms())
            self.outputs.apply(ctrl.heater_power, ctrl.fan_power)
            return payload
        except BaseException:
            self.controller.trip("runtime_error")
            self.outputs.shutdown()
            raise

    def supervise(self):
        if self.snapshot is not None and self.controller.heater_power > 0:
            if not self.controller.check_snapshot(self.snapshot, self.clock.ticks_ms()):
                self.outputs.shutdown()


def run_loop(runner, clock, watchdog):
    try:
        while True:
            runner.cycle()
            completed = clock.ticks_ms()
            while clock.ticks_diff(clock.ticks_ms(), completed) < runner.cfg.SAMPLE_INTERVAL_MS:
                runner.supervise()
                watchdog.feed()
                clock.sleep_ms(50)
    finally:
        runner.outputs.shutdown()
