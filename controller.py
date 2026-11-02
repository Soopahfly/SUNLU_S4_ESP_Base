"""Hardware-independent control; monotonic milliseconds, injected wrap-safe difference."""
import math


def valid(value, low, high):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


class PID:
    def __init__(self, kp=2.0, ki=0.1, kd=0.5, target=45.0):
        self.kp, self.ki, self.kd, self.target = kp, ki, kd, target
        self.reset()

    def reset(self):
        self.integral = 0.0
        self.previous = None

    def compute(self, temperature, dt):
        if dt <= 0:
            raise ValueError('PID requires positive elapsed time')
        error = self.target - temperature
        derivative = 0 if self.previous is None else -(temperature - self.previous) / dt
        self.previous = temperature
        candidate = max(-100.0, min(100.0, self.integral + self.ki * error * dt))
        raw = self.kp * error + candidate + self.kd * derivative
        if 0 <= raw <= 100 or (raw > 100 and error < 0) or (raw < 0 and error > 0):
            self.integral = candidate
        if error <= 0:
            self.integral = 0.0
            return 0.0
        return max(0.0, min(100.0, self.kp * error + self.integral + self.kd * derivative))


def sample_sensors(sensors, now):
    readings = []
    for sensor in sensors:
        try:
            sensor.measure()
            temp, humidity = sensor.temperature(), sensor.humidity()
            if not valid(temp, -40, 80) or not valid(humidity, 0, 100):
                raise ValueError('invalid sensor value')
            readings.append({'temp': temp, 'humidity': humidity})
        except Exception:
            readings.append({'temp': None, 'humidity': None})
    return {'sample_ms': now, 'sensors': readings}


class Controller:
    def __init__(self, required_sensors=4, target=45.0, limit=60.0,
                 max_age_ms=7000, cooldown_ms=300000, enabled=False):
        if required_sensors < 1 or not 0 < target < limit <= 80:
            raise ValueError('invalid controller configuration')
        if max_age_ms <= 0 or cooldown_ms < 0:
            raise ValueError('invalid timing configuration')
        self.required = required_sensors
        self.limit, self.max_age, self.cooldown = limit, max_age_ms, cooldown_ms
        self.enabled = enabled
        self.pid = PID(target=target)
        self.state, self.fault = 'idle', None
        self.heater = self.fan = 0.0
        self.last_control = self.last_heat = self.last_sample = None

    def trip(self, reason):
        if self.fault is None:
            self.fault = reason
        self.state, self.heater, self.fan = 'fault', 0.0, 100.0
        self.pid.reset()

    def update(self, snapshot, now, ticks_diff):
        if self.fault:
            return
        age = ticks_diff(now, snapshot['sample_ms'])
        readings = snapshot['sensors']
        if age < 0 or age > self.max_age:
            self.trip('stale sensors')
            return
        if len(readings) != self.required or any(
            not valid(r['temp'], -40, 80) or not valid(r['humidity'], 0, 100)
            for r in readings
        ):
            self.trip('sensor coverage')
            return
        maximum = max(r['temp'] for r in readings)
        if maximum >= self.limit:
            self.trip('overtemperature')
            return
        if snapshot['sample_ms'] == self.last_sample:
            return
        dt = 5.0 if self.last_control is None else ticks_diff(now, self.last_control) / 1000
        if dt <= 0 or dt * 1000 > self.max_age:
            self.trip('control deadline')
            return
        self.last_control, self.last_sample = now, snapshot['sample_ms']
        average = sum(r['temp'] for r in readings) / self.required
        self.heater = self.pid.compute(average, dt) if self.enabled else 0.0
        if not self.enabled:
            self.pid.reset()
        if self.heater > 0:
            self.last_heat = now
        cooling = (self.last_heat is not None and
                   ticks_diff(now, self.last_heat) < self.cooldown)
        self.fan = 100.0 if self.heater > 0 or maximum > 30 or cooling else 0.0
        self.state = 'heating' if self.heater > 0 else ('cooling' if self.fan else 'idle')

    def status(self, snapshot, now):
        readings = snapshot['sensors'] if snapshot else []
        good = [r for r in readings if r['temp'] is not None and r['humidity'] is not None]
        return {'uptime_ms': now, 'sample_ms': snapshot['sample_ms'] if snapshot else None,
                'state': self.state, 'fault': self.fault, 'heat_enabled': self.enabled,
                'sensors': readings,
                'avg_temp': sum(r['temp'] for r in good) / len(good) if good else None,
                'avg_hum': sum(r['humidity'] for r in good) / len(good) if good else None,
                'heater_power': self.heater, 'fan_power': self.fan}
