"""MicroPython adapters. Importing this module does not initialise hardware."""

from control import finite


class Outputs:
    def __init__(self, Pin, PWM, cfg):
        self.heater, self.fan = None, None
        pins = tuple(cfg.SENSOR_PINS) + (cfg.HEATER_PIN, cfg.FAN_PIN, cfg.OLED_SDA, cfg.OLED_SCL)
        if (not all(isinstance(pin, int) and not isinstance(pin, bool) and pin >= 0 for pin in pins)
                or len(set(pins)) != len(pins)):
            raise ValueError("invalid or conflicting pin assignments")
        heater_pin = Pin(cfg.HEATER_PIN, Pin.OUT, value=0)
        try:
            self.heater = PWM(heater_pin, freq=cfg.PWM_FREQUENCY, duty=0)
            fan_pin = Pin(cfg.FAN_PIN, Pin.OUT, value=0)
            self.fan = PWM(fan_pin, freq=cfg.PWM_FREQUENCY, duty=0)
        except BaseException:
            self.shutdown()
            raise
        self.heater_power, self.fan_power = 0.0, 0

    def pause(self):
        try:
            self.heater.duty(0)
            self.heater_power = 0.0
        finally:
            self.fan.duty(1023)
            self.fan_power = 100

    def apply(self, heat, fan):
        if not finite(heat) or not finite(fan) or not 0 <= heat <= 100 or not 0 <= fan <= 100:
            self.shutdown()
            raise ValueError("invalid output")
        if heat > 0 and fan != 100:
            self.shutdown()
            raise ValueError("heat requires full fan demand")
        self.heater.duty(0)
        self.heater_power = 0.0
        self.fan.duty(int(fan / 100 * 1023))  # fan command before heat
        self.fan_power = fan
        self.heater.duty(int(heat / 100 * 1023))
        self.heater_power = heat

    def shutdown(self):
        try:
            if self.heater is not None:
                self.heater.duty(0)
                self.heater_power = 0.0
        finally:
            if self.fan is not None:
                self.fan.duty(1023)
                self.fan_power = 100


class Display:
    def __init__(self, oled):
        self.oled = oled

    def update(self, snapshot, controller, armed):
        oled = self.oled
        oled.fill(0)
        temp, humidity = snapshot["avg_temp"], snapshot["avg_hum"]
        oled.text("SUNLU BENCH", 0, 0)
        oled.text("T: --" if temp is None else "T: %.1f C" % temp, 0, 10)
        oled.text("RH: --" if humidity is None else "RH: %.1f %%" % humidity, 0, 20)
        oled.text("Heat: %.0f %%" % controller.heater_power, 0, 30)
        oled.text("Fan: %d %%" % controller.fan_power, 0, 40)
        oled.text(controller.state.upper() if armed else "MONITOR ONLY", 0, 50)
        if controller.fault:
            oled.fill(0)
            oled.text("FAULT - HEAT OFF", 0, 0)
            oled.text(controller.fault[:16], 0, 20)
            oled.text(controller.fault[16:32], 0, 30)
            oled.text("Fan: 100%", 0, 50)
        oled.show()
