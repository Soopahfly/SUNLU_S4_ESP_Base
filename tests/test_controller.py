import importlib
import json
import math
import sys
import types
import unittest
from unittest.mock import patch

import config
from control import Controller, PID, sample_sensors
from hardware import Display, Outputs
from runtime import Runner, run_loop
from telemetry import Telemetry


def settings(**overrides):
    result = types.SimpleNamespace(**{k: v for k, v in vars(config).items() if k.isupper()})
    for name, value in overrides.items():
        setattr(result, name, value)
    return result


class Clock:
    def __init__(self, now=0):
        self.now = now
        self.sleeps = 0
        self.stop_after = None

    def ticks_ms(self):
        return self.now

    @staticmethod
    def ticks_diff(new, old):
        period = 1 << 30
        return ((new - old + period // 2) % period) - period // 2

    def sleep_ms(self, ms):
        self.now = (self.now + ms) % (1 << 30)
        self.sleeps += 1
        if self.stop_after is not None and self.sleeps >= self.stop_after:
            raise KeyboardInterrupt


class Sensor:
    def __init__(self, temp=20, humidity=40, error=False, check=None):
        self.temp, self.hum, self.error, self.check = temp, humidity, error, check
        self.calls = 0

    def measure(self):
        if self.check:
            self.check()
        self.calls += 1
        if self.error:
            raise OSError("disconnected")

    def temperature(self):
        return self.temp

    def humidity(self):
        return self.hum


class FakePin:
    OUT = 1

    def __init__(self, pin, mode=None, value=None):
        self.pin, self.mode, self.value = pin, mode, value


class PWMFactory:
    def __init__(self):
        self.channels = {}
        self.events = []
        self.fail_pin = None

    def __call__(self, pin, **kwargs):
        if pin.pin == self.fail_pin:
            raise OSError("PWM init failure")
        assert kwargs["duty"] == 0
        assert pin.mode == FakePin.OUT and pin.value == 0
        factory = self

        class PWM:
            value = kwargs["duty"]
            fail_next = False

            def duty(self, value):
                if self.fail_next:
                    self.fail_next = False
                    raise OSError("PWM write failure")
                self.value = value
                factory.events.append((pin.pin, value))

        channel = PWM()
        self.channels[pin.pin] = channel
        return channel


class Network:
    enabled = True
    ready = True
    error = None

    def __init__(self, callback=None):
        self.callback = callback
        self.payloads = []

    def service(self, payload):
        self.payloads.append(payload)
        if self.callback:
            self.callback(self)


class Fixture:
    def __init__(self, armed=True, network=None, display=None):
        self.cfg = settings(ALLOW_HEATING=True)
        self.clock = Clock()
        self.controller = Controller(self.cfg, self.clock.ticks_diff)
        self.pwm = PWMFactory()
        self.outputs = Outputs(FakePin, self.pwm, self.cfg)
        self.sensors = [Sensor() for _ in range(4)]
        self.net = network or Network()
        self.runner = Runner(self.cfg, self.clock, self.controller, self.outputs,
                             self.sensors, display, self.net, armed)

    def next(self, ms=2500):
        self.clock.now += ms
        return self.runner.cycle()


class ControlTests(unittest.TestCase):
    def test_partial_and_total_failures_latch(self):
        for failed in (1, 4):
            with self.subTest(failed=failed):
                f = Fixture()
                f.runner.cycle()
                self.assertGreater(f.outputs.heater_power, 0)
                for sensor in f.sensors[:failed]:
                    sensor.error = True
                f.next()
                self.assertEqual(f.controller.fault, "sensor_failure")
                self.assertEqual((f.outputs.heater_power, f.outputs.fan_power), (0, 100))
                for sensor in f.sensors:
                    sensor.error = False
                f.next()
                self.assertEqual(f.controller.state, "fault")
                self.assertEqual(f.outputs.heater_power, 0)

    def test_hotspot_and_exact_cutoff_override_average(self):
        for temp in (60, 80):
            f = Fixture()
            f.sensors[0].temp = temp
            f.runner.cycle()
            self.assertEqual(f.controller.fault, "overtemperature")
            self.assertEqual(f.outputs.heater_power, 0)

    def test_invalid_measurements_never_enter_json_or_control(self):
        for temp, humidity in ((math.nan, 40), (math.inf, 40), (20, math.nan),
                               (20, -1), (20, 101), (81, 40), (True, 40)):
            with self.subTest(temp=temp, humidity=humidity):
                f = Fixture()
                f.sensors[0].temp, f.sensors[0].hum = temp, humidity
                payload = f.runner.cycle()
                json.dumps(payload, allow_nan=False)
                self.assertEqual(payload["sensors"][0], {"temp": None, "humidity": None})
                self.assertEqual(f.outputs.heater_power, 0)

    def test_all_consumers_share_one_measurement(self):
        seen = []
        display = types.SimpleNamespace(update=lambda snapshot, ctrl, armed: seen.append(snapshot))
        f = Fixture(display=display)
        payload = f.runner.cycle()
        self.assertEqual([s.calls for s in f.sensors], [1] * 4)
        self.assertIs(payload["sensors"], seen[0]["sensors"])
        self.assertEqual(payload["avg_temp"], 20)

    def test_pid_regression_no_windup_above_target(self):
        pid = PID(2, .1, .5, 45)
        for _ in range(200):
            self.assertLessEqual(pid.compute(20, 5), 100)
        self.assertEqual(pid.compute(65, 5), 0)
        self.assertEqual(pid.integral, 0)
        self.assertEqual(pid.compute(45, 5), 0)

    def test_pid_elapsed_time_and_saturation(self):
        a, b = PID(0, 1, 0, 45), PID(0, 1, 0, 45)
        self.assertEqual(a.compute(44, 2), 2)
        b.compute(44, 1)
        self.assertEqual(b.compute(44, 1), 2)
        saturated = PID(10, 1, 0, 45)
        for _ in range(100):
            self.assertEqual(saturated.compute(20, 2), 100)
        self.assertEqual(saturated.integral, 0)

    def test_monitor_only_does_not_heat_even_with_allow_permission(self):
        f = Fixture(armed=False)
        f.runner.cycle()
        self.assertIsNone(f.controller.fault)
        self.assertEqual(f.outputs.heater_power, 0)

    def test_cooldown_starts_at_last_heat_and_expires(self):
        f = Fixture()
        f.runner.cycle()
        f.runner.enable_heat = False
        f.next()
        self.assertEqual(f.controller.state, "cooling")
        for _ in range(118):
            f.next()
        self.assertEqual(f.outputs.fan_power, 100)
        f.next()
        self.assertEqual(f.controller.state, "idle")
        self.assertEqual(f.outputs.fan_power, 0)

    def test_hot_sensor_keeps_fan_on_without_heat(self):
        f = Fixture(armed=False)
        f.sensors[0].temp = 35
        f.runner.cycle()
        self.assertEqual((f.outputs.heater_power, f.outputs.fan_power), (0, 100))

    def test_stale_reading_during_wait_trips_immediately(self):
        f = Fixture()
        f.runner.cycle()
        f.clock.now = f.cfg.MAX_SAMPLE_AGE_MS + 1
        f.runner.supervise()
        self.assertEqual(f.controller.fault, "stale_sensors")
        self.assertEqual(f.outputs.heater_power, 0)

    def test_delayed_network_cannot_reenable_stale_heat(self):
        f = Fixture()
        f.net.callback = lambda net: setattr(f.clock, "now", 5000)
        f.runner.cycle()
        self.assertEqual(f.controller.fault, "stale_sensors")
        self.assertEqual(f.outputs.heater_power, 0)

    def test_control_gap_fault_even_with_fresh_new_sample(self):
        f = Fixture()
        f.runner.cycle()
        f.next(10000)
        self.assertEqual(f.controller.fault, "control_gap")
        self.assertEqual(f.outputs.heater_power, 0)

    def test_ticks_wrap_does_not_look_stale(self):
        f = Fixture()
        f.clock.now = (1 << 30) - 1000
        f.runner.cycle()
        f.clock.now = 1500
        f.runner.cycle()
        self.assertIsNone(f.controller.fault)
        self.assertGreater(f.outputs.heater_power, 0)

    def test_invalid_configurations_rejected(self):
        for overrides in ({"TARGET_TEMP": 60}, {"MAX_TEMP": math.nan},
                          {"COOLDOWN_MS": math.nan}, {"SAMPLE_INTERVAL_MS": 1000},
                          {"SENSOR_PINS": (2, 2)}, {"PID_KI": -1}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                Controller(settings(**overrides), Clock.ticks_diff)


class RuntimeTests(unittest.TestCase):
    def test_all_peripheral_io_happens_with_heat_off(self):
        f = Fixture()
        f.runner.cycle()
        observations = []

        def check():
            observations.append(f.outputs.heater_power)
            self.assertEqual(f.pwm.channels[25].value, 0)
            self.assertEqual(f.outputs.fan_power, 100)

        for sensor in f.sensors:
            sensor.check = check
        f.runner.display = types.SimpleNamespace(update=lambda *args: check())
        f.net.callback = lambda net: check()
        f.next()
        self.assertEqual(len(observations), 6)
        self.assertGreater(f.outputs.heater_power, 0)

    def test_network_loss_latches_and_recovery_does_not_clear(self):
        f = Fixture()
        f.runner.cycle()
        f.net.callback = lambda net: setattr(net, "ready", False)
        f.next()
        self.assertEqual(f.controller.fault, "network_lost")
        f.net.callback = lambda net: setattr(net, "ready", True)
        f.next()
        self.assertEqual(f.outputs.heater_power, 0)

    def test_network_error_during_initial_connection_faults_requested_heat(self):
        f = Fixture()
        f.net.ready = False
        f.net.callback = lambda net: setattr(net, "error", "mqtt_error")
        f.runner.cycle()
        self.assertEqual(f.controller.fault, "mqtt_error")
        self.assertEqual(f.outputs.heater_power, 0)

    def test_initial_network_wait_never_heats(self):
        f = Fixture()
        f.net.ready = False
        f.runner.cycle()
        self.assertEqual(f.outputs.heater_power, 0)
        self.assertIsNone(f.controller.fault)

    def test_display_failure_latches_but_sampling_continues(self):
        def broken(*args):
            raise OSError("display disconnected")
        f = Fixture(display=types.SimpleNamespace(update=broken))
        f.runner.cycle()
        f.next()
        self.assertEqual(f.controller.fault, "display_error")
        self.assertEqual([s.calls for s in f.sensors], [2] * 4)
        self.assertEqual(f.outputs.heater_power, 0)

    def test_ctrl_c_and_unexpected_exception_force_heat_off(self):
        for exc in (KeyboardInterrupt, RuntimeError):
            f = Fixture()
            f.runner.cycle()
            def fail(net):
                raise exc()
            f.net.callback = fail
            with self.assertRaises(exc):
                f.next()
            self.assertEqual((f.outputs.heater_power, f.outputs.fan_power), (0, 100))

    def test_permission_and_network_configuration_required_to_arm(self):
        f = Fixture(armed=False)
        for cfg, net in ((settings(), f.net), (f.cfg, types.SimpleNamespace(enabled=False))):
            with self.assertRaises(ValueError):
                Runner(cfg, f.clock, f.controller, f.outputs, f.sensors, None, net, True)

    def test_string_false_does_not_grant_heating_permission(self):
        f = Fixture(armed=False)
        for cfg, arm in ((settings(ALLOW_HEATING="False"), True), (f.cfg, "False")):
            with self.assertRaises(ValueError):
                Runner(cfg, f.clock, f.controller, f.outputs, f.sensors, None, f.net, arm)

    def test_slow_serial_logging_cannot_reenable_stale_heat(self):
        f = Fixture()
        def slow_log(message):
            self.assertEqual(f.outputs.heater_power, 0)
            f.clock.now = 5000
        f.runner.log = slow_log
        f.runner.cycle()
        self.assertEqual(f.controller.fault, "stale_sensors")
        self.assertEqual(f.outputs.heater_power, 0)

    def test_sample_spacing_and_cleanup_on_interrupt(self):
        f = Fixture(armed=False)
        times = []
        f.sensors[0].check = lambda: times.append(f.clock.now)
        f.clock.stop_after = 110
        watchdog = types.SimpleNamespace(feed=lambda: None)
        with self.assertRaises(KeyboardInterrupt):
            run_loop(f.runner, f.clock, watchdog)
        self.assertEqual(times, [0, 2500, 5000])
        self.assertEqual((f.outputs.heater_power, f.outputs.fan_power), (0, 100))


class OutputTests(unittest.TestCase):
    def test_explicit_zero_startup_and_fan_before_heat(self):
        f = Fixture()
        self.assertEqual([channel.value for channel in f.pwm.channels.values()], [0, 0])
        f.outputs.apply(50, 100)
        self.assertEqual(f.pwm.events[-3:], [(25, 0), (26, 1023), (25, 511)])
        f.outputs.apply(0, 0)
        self.assertEqual(f.pwm.events[-3:], [(25, 0), (26, 0), (25, 0)])

    def test_fan_pwm_initialisation_failure_leaves_heat_off(self):
        pwm = PWMFactory()
        pwm.fail_pin = 26
        with self.assertRaises(OSError):
            Outputs(FakePin, pwm, settings())
        self.assertEqual(pwm.channels[25].value, 0)

    def test_fan_write_failure_cannot_leave_existing_heat_on(self):
        f = Fixture()
        f.outputs.apply(50, 100)
        f.pwm.channels[26].fail_next = True
        with self.assertRaises(OSError):
            f.outputs.apply(0, 0)
        self.assertEqual(f.pwm.channels[25].value, 0)

    def test_invalid_output_and_heat_without_fan_rejected(self):
        for heat, fan in ((math.nan, 100), (101, 100), (50, 0)):
            f = Fixture()
            with self.assertRaises(ValueError):
                f.outputs.apply(heat, fan)
            self.assertEqual(f.outputs.heater_power, 0)

    def test_pin_conflicts_rejected(self):
        with self.assertRaises(ValueError):
            Outputs(FakePin, PWMFactory(), settings(HEATER_PIN=21))

    def test_missing_readings_render_without_formatting_error(self):
        lines = []
        oled = types.SimpleNamespace(fill=lambda value: None, show=lambda: None,
                                    text=lambda text, x, y: lines.append(text))
        f = Fixture(armed=False)
        for s in f.sensors:
            s.error = True
        snapshot = sample_sensors(f.sensors, 0)
        f.controller.step(snapshot, 0, False)
        Display(oled).update(snapshot, f.controller, False)
        self.assertIn("FAULT - HEAT OFF", lines)


class WLAN:
    def __init__(self):
        self.connected = True
        self.connects, self.disconnects = 0, 0

    def active(self, enabled):
        pass

    def isconnected(self):
        return self.connected

    def connect(self, ssid, password):
        self.connects += 1

    def disconnect(self):
        self.disconnects += 1


class MQTT:
    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.timeouts, self.published = [], []
        self.closed, self.fail_publish = False, False
        self.sock = types.SimpleNamespace(settimeout=self.timeouts.append, close=self.close)

    def close(self):
        self.closed = True

    def set_last_will(self, *args, **kwargs):
        self.will = (args, kwargs)

    def connect(self, timeout):
        self.connect_timeout = timeout

    def publish(self, topic, message, **kwargs):
        if self.fail_publish:
            raise OSError("missing acknowledgement")
        self.published.append((topic, message, kwargs))


class TelemetryTests(unittest.TestCase):
    def setup_network(self):
        self.clock, self.wlan, self.clients = Clock(), WLAN(), []
        def factory(*args, **kwargs):
            client = MQTT(*args, **kwargs)
            self.clients.append(client)
            return client
        self.cfg = settings(WIFI_SSID="bench", MQTT_BROKER="192.0.2.1")
        return Telemetry(self.cfg, self.clock, self.wlan, factory, "chip123")

    def test_acknowledged_publish_with_timeout_and_unique_client_id(self):
        net = self.setup_network()
        net.service({"state": "idle"})
        client = self.clients[0]
        self.assertTrue(net.ready)
        self.assertEqual(client.connect_timeout, 1)
        self.assertEqual(client.args[0], b"sunlu-controller-chip123")
        self.assertTrue(all(message[2]["qos"] == 1 for message in client.published))
        self.assertEqual(client.will[0], (b"sunlu/status", b"offline"))
        self.assertEqual(client.published[-1][0], b"sunlu/sensors")

    def test_publish_failure_closes_socket_and_retry_is_delayed(self):
        net = self.setup_network()
        net.service({})
        self.clients[0].fail_publish = True
        self.clock.now = 5000
        net.service({})
        self.assertFalse(net.ready)
        self.assertEqual(net.error, "mqtt_error")
        self.assertTrue(self.clients[0].closed)
        self.clock.now = 7500
        net.service({})
        self.assertEqual(len(self.clients), 1)
        self.clock.now = 15000
        net.service({})
        self.assertTrue(net.ready)
        self.assertIsNone(net.error)

    def test_wifi_timeout_uses_no_wait_loop(self):
        net = self.setup_network()
        self.wlan.connected = False
        net.service({})
        self.assertEqual(self.wlan.connects, 1)
        self.clock.now = 5000
        net.service({})
        self.assertEqual(self.wlan.connects, 1)
        self.clock.now = 15000
        net.service({})
        self.assertEqual(net.error, "wifi_timeout")
        self.assertEqual(self.wlan.disconnects, 1)

    def test_connection_failure_does_not_escape_service(self):
        net = self.setup_network()
        net.factory = lambda *args, **kwargs: (_ for _ in ()).throw(OSError("unavailable"))
        net.service({})
        self.assertEqual(net.error, "mqtt_error")
        self.assertFalse(net.ready)

    def test_network_disabled_without_credentials(self):
        net = Telemetry(settings(), Clock())
        net.service({})
        self.assertFalse(net.enabled)
        self.assertFalse(net.ready)


class BootTests(unittest.TestCase):
    def test_normal_boot_cannot_arm_even_when_local_permission_is_true(self):
        import main
        pwm, clock = PWMFactory(), Clock()
        clock.stop_after = 4
        oled = types.SimpleNamespace(fill=lambda value: None, show=lambda: None,
                                     text=lambda *args: None)
        modules = {
            "machine": types.SimpleNamespace(Pin=FakePin, PWM=pwm,
                I2C=lambda *args, **kwargs: None,
                WDT=lambda **kwargs: self.fail("monitoring boot must not start a watchdog"),
                unique_id=lambda: b"test"),
            "time": clock,
            "dht": types.SimpleNamespace(DHT22=lambda pin: Sensor()),
            "network": types.SimpleNamespace(),
            "ssd1306": types.SimpleNamespace(SSD1306_I2C=lambda *args, **kwargs: oled),
        }
        with patch.dict(sys.modules, modules), patch.object(config, "load", return_value=settings(ALLOW_HEATING=True)):
            with self.assertRaises(KeyboardInterrupt):
                main.run()
        self.assertTrue(all(duty == 0 for pin, duty in pwm.events if pin == 25))
        self.assertEqual(pwm.channels[26].value, 1023)

    def test_importing_main_does_not_import_machine_or_run(self):
        import main
        with patch.dict(sys.modules, {"machine": None}):
            importlib.reload(main)

    def test_startup_display_failure_still_turns_heat_off(self):
        import main
        pwm = PWMFactory()
        clock = Clock()
        def broken_display(*args, **kwargs):
            raise OSError("missing OLED")
        modules = {
            "machine": types.SimpleNamespace(Pin=FakePin, PWM=pwm,
                I2C=lambda *args, **kwargs: None,
                WDT=lambda **kwargs: types.SimpleNamespace(feed=lambda: None),
                unique_id=lambda: b"test"),
            "time": clock,
            "dht": types.SimpleNamespace(DHT22=lambda pin: Sensor()),
            "network": types.SimpleNamespace(),
            "ssd1306": types.SimpleNamespace(SSD1306_I2C=broken_display),
        }
        with patch.dict(sys.modules, modules), patch.object(config, "load", return_value=settings()):
            with self.assertRaises(OSError):
                main.run()
        self.assertEqual(pwm.channels[25].value, 0)
        self.assertEqual(pwm.channels[26].value, 1023)


class SettingsTests(unittest.TestCase):
    def test_missing_settings_uses_safe_defaults(self):
        with patch.dict(sys.modules, {"settings": None}):
            loaded = config.load()
        self.assertFalse(loaded.ALLOW_HEATING)
        self.assertEqual(loaded.SENSOR_PINS, (15, 2, 4, 16))

    def test_settings_overrides_do_not_mutate_defaults(self):
        with patch.dict(sys.modules, {"settings": types.SimpleNamespace(WIFI_SSID="private-network")}):
            loaded = config.load()
        self.assertEqual(loaded.WIFI_SSID, "private-network")
        self.assertEqual(config.WIFI_SSID, "")


if __name__ == "__main__":
    unittest.main()
