"""MicroPython entry point. Default configuration is a disconnected bench setup."""
import time
from controller import Controller, sample_sensors
from sensors import build_sensors


class Outputs:
    def __init__(self, machine):
        self.heat_pin = machine.Pin(25, machine.Pin.OUT, value=0)
        self.fan_pin = machine.Pin(26, machine.Pin.OUT, value=0)
        self.heat = self.fan = None
        self.machine = machine

    def initialise(self):
        self.heat = self.machine.PWM(self.heat_pin, freq=1000, duty_u16=0)
        self.fan = self.machine.PWM(self.fan_pin, freq=1000, duty_u16=0)

    def apply(self, controller):
        if controller.heater == 0:
            self.heat.duty_u16(0)
        self.fan.duty_u16(int(controller.fan * 65535 / 100))
        self.heat.duty_u16(int(controller.heater * 65535 / 100))

    def emergency(self):
        try:
            if self.heat is not None:
                self.heat.duty_u16(0)
        finally:
            try:
                if self.heat is not None:
                    self.heat.deinit()
            finally:
                self.heat_pin.init(self.machine.Pin.OUT, value=0)

    def fault_cooling(self):
        if self.fan is not None:
            self.fan.duty_u16(65535)


def display_status(oled, payload):
    oled.fill(0)
    oled.text('SUNLU bench', 0, 0)
    oled.text(payload['state'], 0, 12)
    temp = payload['avg_temp']
    oled.text('Temp: --' if temp is None else 'Temp: %.1f C' % temp, 0, 24)
    oled.text('Heat: %d%%' % payload['heater_power'], 0, 36)
    oled.text('Fan: %d%%' % payload['fan_power'], 0, 48)
    oled.show()


def run(machine, dht, display_driver, config=None, clock=time, max_steps=None,
        telemetry_factory=None):
    outputs = Outputs(machine)
    control = Controller()
    telemetry = None
    try:
        outputs.initialise()
        settings = config() if callable(config) else (config or {})
        i2c = machine.I2C(0, scl=machine.Pin(22), sda=machine.Pin(21), freq=100000)
        sensors = build_sensors(settings, machine, i2c, clock, dht)
        control = Controller(required_sensors=len(sensors),
                             enabled=settings.get('HEAT_ENABLED', False))
        oled = display_driver.SSD1306_I2C(
            128, 64, i2c)
        if settings.get('NETWORK_ENABLED', False):
            if telemetry_factory is None:
                from telemetry import Telemetry
                telemetry_factory = Telemetry
            telemetry = telemetry_factory(settings, machine.unique_id(), clock)
        snapshot, last_sample = None, None
        started = clock.ticks_ms()
        steps = 0
        while max_steps is None or steps < max_steps:
            now = clock.ticks_ms()
            if snapshot is None:
                if clock.ticks_diff(now, started) < 2000:
                    clock.sleep_ms(50)
                    continue
            elif clock.ticks_diff(now, snapshot['sample_ms']) > control.max_age:
                control.trip('control deadline')
                outputs.apply(control)
            if last_sample is None or clock.ticks_diff(now, last_sample) >= 5000:
                snapshot = sample_sensors(sensors, now)
                # Space from completion, so a slow previous sensor read cannot
                # shorten the next sensor's measurement interval.
                last_sample = clock.ticks_ms()
            now = clock.ticks_ms()
            control.update(snapshot, now, clock.ticks_diff)
            outputs.apply(control)
            payload = control.status(snapshot, now)
            display_status(oled, payload)
            if telemetry is not None:
                telemetry.step(payload)
            steps += 1
            clock.sleep_ms(50)
    except BaseException:
        control.trip('software failure or interruption')
        raise
    finally:
        try:
            outputs.emergency()
        finally:
            try:
                outputs.fault_cooling()
            finally:
                if telemetry is not None:
                    telemetry.close()


def load_config():
    # config.py is optional. Avoid swallowing ImportErrors inside an existing config.
    import os
    settings = {}
    if 'config.py' in os.listdir():
        import config
        settings = {name: getattr(config, name) for name in dir(config) if name.isupper()}
    return settings


def main():
    import machine
    import ssd1306
    run(machine, None, ssd1306, load_config)


if __name__ == '__main__':
    main()
