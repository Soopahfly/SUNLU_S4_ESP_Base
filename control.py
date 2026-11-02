"""Hardware-independent control and fault policy, shared with host tests."""


def finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and -float("inf") < value < float("inf"))


def valid_reading(reading):
    temp, humidity = reading.get("temp"), reading.get("humidity")
    return (finite(temp) and -40 <= temp <= 80
            and finite(humidity) and 0 <= humidity <= 100)


def sample_sensors(sensors, sampled_at_ms):
    """One measurement per sensor; timestamp starts before the first read."""
    readings = []
    for sensor in sensors:
        try:
            sensor.measure()
            reading = {"temp": sensor.temperature(), "humidity": sensor.humidity()}
            if not valid_reading(reading):
                raise ValueError("invalid reading")
        except Exception:
            reading = {"temp": None, "humidity": None}
        readings.append(reading)
    valid = [item for item in readings if valid_reading(item)]
    return {
        "sampled_at_ms": sampled_at_ms,
        "sensors": readings,
        "valid_count": len(valid),
        "avg_temp": sum(item["temp"] for item in valid) / len(valid) if valid else None,
        "avg_hum": sum(item["humidity"] for item in valid) / len(valid) if valid else None,
        "max_temp": max(item["temp"] for item in valid) if valid else None,
    }


class PID:
    def __init__(self, kp, ki, kd, target):
        if not all(finite(x) and x >= 0 for x in (kp, ki, kd)) or not finite(target):
            raise ValueError("invalid PID configuration")
        self.kp, self.ki, self.kd, self.target = kp, ki, kd, target
        self.reset()

    def reset(self):
        self.integral = 0.0  # output percentage points, not raw error samples
        self.previous_value = None

    def compute(self, value, dt):
        if not finite(value) or not finite(dt) or dt <= 0:
            raise ValueError("invalid PID input")
        if value >= self.target:
            self.reset()
            return 0.0
        error = self.target - value
        derivative = (0.0 if self.previous_value is None else
                      -(value - self.previous_value) / dt)
        self.previous_value = value
        proposed = max(0.0, min(100.0, self.integral + self.ki * error * dt))
        raw = self.kp * error + proposed + self.kd * derivative
        if raw <= 100.0:  # no integration further into upper saturation
            self.integral = proposed
        return max(0.0, min(100.0,
                   self.kp * error + self.integral + self.kd * derivative))


class Controller:
    def __init__(self, cfg, ticks_diff):
        timings = (cfg.SAMPLE_INTERVAL_MS, cfg.MAX_SAMPLE_AGE_MS,
                   cfg.MAX_CONTROL_GAP_MS, cfg.COOLDOWN_MS)
        if (not finite(cfg.TARGET_TEMP) or not finite(cfg.MAX_TEMP)
                or not -40 < cfg.TARGET_TEMP < cfg.MAX_TEMP <= 80
                or not finite(cfg.FAN_COOL_TEMP)
                or not -40 <= cfg.FAN_COOL_TEMP < cfg.TARGET_TEMP
                or not cfg.SENSOR_PINS or len(set(cfg.SENSOR_PINS)) != len(cfg.SENSOR_PINS)
                or not all(isinstance(value, int) and not isinstance(value, bool) for value in timings)
                or cfg.SAMPLE_INTERVAL_MS < 2000
                or cfg.MAX_SAMPLE_AGE_MS <= cfg.SAMPLE_INTERVAL_MS
                or cfg.MAX_CONTROL_GAP_MS < cfg.MAX_SAMPLE_AGE_MS
                or cfg.COOLDOWN_MS < 0):
            raise ValueError("invalid control configuration")
        self.cfg, self.diff = cfg, ticks_diff
        self.pid = PID(cfg.PID_KP, cfg.PID_KI, cfg.PID_KD, cfg.TARGET_TEMP)
        self.state, self.fault = "idle", None
        self.heater_power, self.fan_power = 0.0, 0
        self.last_step_ms, self.last_heat_ms = None, None

    def trip(self, reason):
        if self.fault is None:
            self.fault = reason
        self.pid.reset()
        self.state, self.heater_power, self.fan_power = "fault", 0.0, 100

    def check_snapshot(self, snapshot, now):
        age = self.diff(now, snapshot["sampled_at_ms"])
        if age < 0 or age > self.cfg.MAX_SAMPLE_AGE_MS:
            self.trip("stale_sensors")
        readings = snapshot["sensors"]
        if len(readings) != len(self.cfg.SENSOR_PINS) or not all(valid_reading(r) for r in readings):
            self.trip("sensor_failure")
        if any(finite(r.get("temp")) and r["temp"] >= self.cfg.MAX_TEMP for r in readings):
            self.trip("overtemperature")
        return self.fault is None

    def step(self, snapshot, now, enabled):
        previous_step = self.last_step_ms
        self.last_step_ms = now
        if not self.check_snapshot(snapshot, now):
            return
        elapsed = self.cfg.SAMPLE_INTERVAL_MS if previous_step is None else self.diff(now, previous_step)
        if elapsed <= 0 or elapsed > self.cfg.MAX_CONTROL_GAP_MS:
            self.trip("control_gap")
            return
        if enabled:
            temp = sum(r["temp"] for r in snapshot["sensors"]) / len(snapshot["sensors"])
            self.heater_power = self.pid.compute(temp, elapsed / 1000.0)
        else:
            self.pid.reset()
            self.heater_power = 0.0
        if self.heater_power > 0:
            self.last_heat_ms = now
        cooling = (self.last_heat_ms is not None
                   and self.diff(now, self.last_heat_ms) < self.cfg.COOLDOWN_MS)
        hot = any(r["temp"] > self.cfg.FAN_COOL_TEMP for r in snapshot["sensors"])
        self.fan_power = 100 if self.heater_power > 0 or cooling or hot else 0
        self.state = "heating" if self.heater_power > 0 else ("cooling" if self.fan_power else "idle")
