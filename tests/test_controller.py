import unittest
from controller import Controller, PID, sample_sensors
from main import run


def diff(a, b):
    return (a - b + 2**29) % 2**30 - 2**29


def snapshot(temps, now=0):
    return {'sample_ms': now, 'sensors': [{'temp': t, 'humidity': 50} for t in temps]}


class Sensor:
    def __init__(self, temp=20, humidity=50, fail=False):
        self.temp, self.hum, self.fail, self.calls = temp, humidity, fail, 0

    def measure(self):
        self.calls += 1
        if self.fail:
            raise OSError('disconnected')

    def temperature(self):
        return self.temp

    def humidity(self):
        return self.hum


class ControlTests(unittest.TestCase):
    def test_default_has_no_heat(self):
        c = Controller()
        c.update(snapshot([20]*4), 0, diff)
        self.assertEqual((c.state, c.heater), ('idle', 0))

    def test_sensor_faults_latch(self):
        cases = [[None]*4, [20, None, 20, 20], [float('nan')]*4,
                 [float('inf')]*4, [True]*4, [81]*4, [20]*3]
        for temps in cases:
            with self.subTest(temps=temps):
                c = Controller(enabled=True)
                c.update(snapshot([20]*4), 0, diff)
                self.assertGreater(c.heater, 0)
                c.update(snapshot(temps, 5000), 5000, diff)
                c.update(snapshot([20]*4, 10000), 10000, diff)
                self.assertEqual((c.state, c.heater, c.fan), ('fault', 0, 100))

    def test_individual_hotspot_and_boundary(self):
        for hot in (60, 80):
            c = Controller(enabled=True)
            c.update(snapshot([hot, 20, 20, 20]), 0, diff)
            self.assertEqual(c.fault, 'overtemperature')
            self.assertEqual(c.heater, 0)

    def test_bad_humidity_and_sampling_once(self):
        for humidity in (-1, 101, float('nan'), None):
            sensors = [Sensor(humidity=humidity) for _ in range(4)]
            sample = sample_sensors(sensors, 0)
            c = Controller(enabled=True)
            c.update(sample, 0, diff)
            c.status(sample, 0)
            self.assertEqual(c.fault, 'sensor coverage')
            self.assertEqual([s.calls for s in sensors], [1]*4)

    def test_stale_future_duplicate_and_deadline(self):
        for now in (7001, -1):
            c = Controller(enabled=True)
            c.update(snapshot([20]*4), now, diff)
            self.assertEqual(c.fault, 'stale sensors')
        c = Controller(enabled=True)
        c.update(snapshot([20]*4), 0, diff)
        integral = c.pid.integral
        c.update(snapshot([20]*4), 100, diff)
        self.assertEqual(c.pid.integral, integral)
        c.update(snapshot([20]*4, 8000), 8000, diff)
        self.assertEqual(c.fault, 'control deadline')

    def test_wraparound_and_cooldown(self):
        c = Controller(enabled=True, cooldown_ms=10000)
        start = 2**30 - 5000
        c.update(snapshot([20]*4, start), start, diff)
        c.update(snapshot([45]*4, 0), 0, diff)
        self.assertEqual((c.state, c.heater, c.fan), ('cooling', 0, 100))
        c.enabled = False
        c.update(snapshot([20]*4, 5000), 5000, diff)
        self.assertEqual((c.state, c.heater, c.fan), ('idle', 0, 0))

    def test_pid_elapsed_time_windup_reset(self):
        a, b = PID(kp=0, kd=0), PID(kp=0, kd=0)
        a.compute(40, 5)
        for _ in range(5):
            b.compute(40, 1)
        self.assertEqual(a.integral, b.integral)
        pid = PID()
        for _ in range(200):
            pid.compute(20, 5)
        self.assertLessEqual(abs(pid.integral), 100)
        self.assertEqual(pid.compute(65, 5), 0)
        self.assertEqual(pid.integral, 0)
        pid.reset()
        self.assertIsNone(pid.previous)
        with self.assertRaises(ValueError):
            pid.compute(20, 0)


class Clock:
    def __init__(self):
        self.now = 0
    def ticks_ms(self):
        return self.now
    ticks_diff = staticmethod(diff)
    def sleep_ms(self, delay):
        self.now += delay


class Machine:
    def __init__(self, fail_pwm=None):
        self.events, self.pwms = [], []
        machine = self
        class Pin:
            OUT = 1
            def __init__(self, number, mode=None, value=None):
                self.number = number
                machine.events.append(('pin', number, value))
            def init(self, mode, value):
                machine.events.append(('pin', self.number, value))
        self.Pin = Pin
        self.fail_pwm = fail_pwm
    def PWM(self, pin, **kwargs):
        machine = self
        if pin.number == self.fail_pwm:
            raise OSError('PWM init failed')
        class PWM:
            def __init__(self):
                self.value = kwargs['duty_u16']
            def duty_u16(self, value):
                self.value = value
                machine.events.append(('duty', pin.number, value))
            def deinit(self):
                machine.events.append(('deinit', pin.number))
        pwm = PWM()
        self.pwms.append(pwm)
        self.events.append(('pwm', pin.number, kwargs['duty_u16']))
        return pwm
    def I2C(self, *args, **kwargs):
        self.events.append(('i2c',))
        return None
    def unique_id(self):
        return b'123456'


class DHT:
    def __init__(self):
        self.sensors = []
    def DHT22(self, pin):
        sensor = Sensor()
        self.sensors.append(sensor)
        return sensor


class Display:
    def __init__(self, fail_at=None, exception=OSError):
        self.calls, self.fail_at, self.exception = 0, fail_at, exception
    def SSD1306_I2C(self, *args):
        if self.fail_at == 0:
            raise self.exception('display startup')
        return self
    def fill(self, value):
        pass
    def text(self, *args):
        pass
    def show(self):
        self.calls += 1
        if self.calls == self.fail_at:
            raise self.exception('display runtime')


class RuntimeTests(unittest.TestCase):
    def test_config_failure_after_outputs_off(self):
        m = Machine()
        def bad_config():
            self.assertEqual(m.events[-1], ('pwm', 26, 0))
            raise ValueError('bad config')
        with self.assertRaises(ValueError):
            run(m, DHT(), Display(), bad_config, Clock(), 1)
        self.assertEqual(m.pwms[0].value, 0)

    def test_slow_acquisition_cannot_enable_heat(self):
        clock, m = Clock(), Machine()
        class SlowDHT(DHT):
            def DHT22(self, pin):
                sensor = super().DHT22(pin)
                measure = sensor.measure
                def slow_measure():
                    clock.now += 2000
                    measure()
                sensor.measure = slow_measure
                return sensor
        run(m, SlowDHT(), Display(), {'HEAT_ENABLED': True}, clock, 1)
        self.assertFalse(any(e[0] == 'duty' and e[1] == 25 and e[2] > 0 for e in m.events))

    def test_startup_order_and_scheduled_sampling(self):
        m, d, clock = Machine(), DHT(), Clock()
        run(m, d, Display(), clock=clock, max_steps=201)
        self.assertEqual(m.events[:4], [('pin', 25, 0), ('pin', 26, 0),
                                        ('pwm', 25, 0), ('pwm', 26, 0)])
        self.assertEqual([s.calls for s in d.sensors], [3]*4)
        self.assertFalse(any(e[0] == 'duty' and e[1] == 25 and e[2] > 0 for e in m.events))
        self.assertEqual(m.events[-1], ('duty', 26, 65535))
        self.assertEqual(m.pwms[0].value, 0)

    def test_cleanup_init_runtime_interrupt_network(self):
        for display in (Display(0), Display(2), Display(2, KeyboardInterrupt)):
            m = Machine()
            with self.assertRaises(BaseException):
                run(m, DHT(), display, {'HEAT_ENABLED': True}, Clock(), 3)
            self.assertEqual(m.pwms[0].value, 0)
            self.assertIn(('pin', 25, 0), m.events[-3:])
            self.assertEqual(m.pwms[1].value, 65535)
        m = Machine(fail_pwm=26)
        with self.assertRaises(OSError):
            run(m, DHT(), Display(), clock=Clock(), max_steps=1)
        self.assertEqual(m.pwms[0].value, 0)
        class BrokenNetwork:
            def __init__(self, *args):
                pass
            def step(self, payload):
                raise RuntimeError('unexpected network code failure')
            def close(self):
                pass
        m = Machine()
        with self.assertRaises(RuntimeError):
            run(m, DHT(), Display(), {'HEAT_ENABLED': True, 'NETWORK_ENABLED': True},
                Clock(), 3, BrokenNetwork)
        self.assertEqual(m.pwms[0].value, 0)

    def test_delayed_loop_latches_before_new_sample(self):
        clock = Clock()
        class DelayedDisplay(Display):
            def show(self):
                super().show()
                if self.calls == 1:
                    clock.now += 8000
        m = Machine()
        display = DelayedDisplay()
        run(m, DHT(), display, {'HEAT_ENABLED': True}, clock, 2)
        duties = [e[2] for e in m.events if e[0:2] == ('duty', 25)]
        self.assertGreater(duties[0], 0)
        self.assertTrue(all(v == 0 for v in duties[1:]))


if __name__ == '__main__':
    unittest.main()
