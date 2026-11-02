import unittest
from controller import Controller, sample_sensors
from sensors import SHT3x, TCA9548A, build_sensors, crc8
from main import run
from test_controller import Clock, Machine, Display, DHT, diff


# Fixed response words and CRCs, independent of the driver's CRC implementation.
# 0x6666 -> 25 C; 0x8000 -> approximately 50% RH.
NORMAL = b'\x66\x66\x93\x80\x00\xa2'


class Bus:
    def __init__(self):
        self.events, self.channel = [], None
        self.response = NORMAL
        self.fail_read = self.fail_disable = False
        self.short_write = False
        self.responses = {}
    def writeto(self, address, data):
        self.events.append(('write', address, bytes(data)))
        if self.short_write:
            return 0
        if address == 0x70:
            if self.fail_disable and data == b'\x00':
                raise OSError('mux stuck')
            self.channel = None if data == b'\x00' else data[0].bit_length() - 1
        return len(data)
    def readfrom(self, address, size):
        self.events.append(('read', address, size, self.channel))
        if self.fail_read:
            raise OSError('missing sensor')
        response = self.responses.get((address, self.channel), self.response)
        if isinstance(response, Exception):
            raise response
        return response


class SensorTests(unittest.TestCase):
    def test_datasheet_crc_vector(self):
        self.assertEqual(crc8(b'\xbe\xef'), 0x92)
        self.assertEqual(crc8(NORMAL[:2]), NORMAL[2])
        self.assertEqual(crc8(NORMAL[3:5]), NORMAL[5])

    def test_conversion_and_single_shot_command(self):
        bus, clock = Bus(), Clock()
        sensor = SHT3x(bus, clock=clock)
        sensor.measure()
        self.assertAlmostEqual(sensor.temperature(), 25.0)
        self.assertAlmostEqual(sensor.humidity(), 50.000762951, places=6)
        self.assertEqual(bus.events, [('write', 0x44, b'\x24\x00'),
                                      ('read', 0x44, 6, None)])
        self.assertEqual(clock.now, 20)

    def test_crc_short_read_missing_and_no_cached_values(self):
        for response in (NORMAL[:2] + b'\x00' + NORMAL[3:],
                         NORMAL[:5] + b'\x00', NORMAL[:5], b''):
            bus, clock = Bus(), Clock()
            sensor = SHT3x(bus, clock=clock)
            sensor.measure()
            bus.response = response
            with self.assertRaises(ValueError):
                sensor.measure()
            self.assertIsNone(sensor.temperature())
            self.assertIsNone(sensor.humidity())
        bus.fail_read = True
        with self.assertRaises(OSError):
            sensor.measure()

    def test_mux_isolation_success_failure_and_partial_write(self):
        bus, clock = Bus(), Clock()
        mux = TCA9548A(bus)
        sensor = SHT3x(bus, mux=mux, channel=3, clock=clock)
        sensor.measure()
        self.assertEqual(bus.events[0], ('write', 0x70, b'\x00'))
        self.assertEqual(bus.events[1], ('write', 0x70, b'\x08'))
        self.assertEqual(bus.events[-1], ('write', 0x70, b'\x00'))
        self.assertIsNone(bus.channel)
        bus.fail_read = True
        with self.assertRaises(OSError):
            sensor.measure()
        self.assertIsNone(bus.channel)
        bus.fail_read = False
        bus.fail_disable = True
        with self.assertRaises(OSError):
            sensor.measure()
        self.assertIsNone(sensor.temperature())
        bus.fail_disable = False
        bus.short_write = True
        with self.assertRaises(OSError):
            sensor.measure()
        self.assertIsNone(sensor.temperature())

    def test_direct_addresses_and_four_mux_channels(self):
        bus, machine, clock = Bus(), Machine(), Clock()
        for kind in ('SHT30', 'SHT31', 'SHT3X'):
            sensors = build_sensors({'SENSOR_TYPE': kind,
                                     'SHT_SENSORS': ((0x44, None), (0x45, None))},
                                    machine, bus, clock)
            sample = sample_sensors(sensors, clock.now)
            self.assertEqual(len(sample['sensors']), 2)
            self.assertEqual([s.address for s in sensors], [0x44, 0x45])
        bus.events.clear()
        sensors = build_sensors({'SENSOR_TYPE': 'SHT3X', 'SHT_MUX_ADDRESS': 0x70,
                                 'SHT_SENSORS': tuple((0x44, c) for c in range(4))},
                                machine, bus, clock)
        sample = sample_sensors(sensors, clock.now)
        reads = [e for e in bus.events if e[0] == 'read']
        self.assertEqual([e[3] for e in reads], [0, 1, 2, 3])
        self.assertTrue(all(r['temp'] == 25 for r in sample['sensors']))
        self.assertIsNone(bus.channel)

    def test_missing_config_duplicates_and_invalid_routes(self):
        cases = [{}, {'SHT_SENSORS': ()}, {'SHT_SENSORS': ((0x44, None),)*2},
                 {'SHT_SENSORS': ((0x46, None),)},
                 {'SHT_SENSORS': ((0x44, 0),)},
                 {'SHT_SENSORS': ((0x44, None),), 'SHT_MUX_ADDRESS': 0x70},
                 {'SHT_SENSORS': ((0x44, 8),), 'SHT_MUX_ADDRESS': 0x70},
                 {'SHT_SENSORS': ((0x44, True),), 'SHT_MUX_ADDRESS': 0x70},
                 {'SHT_SENSORS': ((0x44, 0),), 'SHT_MUX_ADDRESS': 0x69},
                 {'SHT_SENSORS': ((0x44,),)},
                 {'SHT_SENSORS': ((0x44, c) for c in range(4))}]
        for case in cases:
            case['SENSOR_TYPE'] = 'SHT3X'
            with self.subTest(case=case), self.assertRaises(ValueError):
                build_sensors(case, Machine(), Bus(), Clock())
        with self.assertRaises(ValueError):
            build_sensors({'SENSOR_TYPE': 'unknown'}, Machine(), Bus(), Clock())

    def test_fault_latches_after_one_mux_sensor_disappears(self):
        bus, clock = Bus(), Clock()
        settings = {'SENSOR_TYPE': 'SHT3X', 'SHT_MUX_ADDRESS': 0x70,
                    'SHT_SENSORS': tuple((0x44, c) for c in range(4))}
        sensors = build_sensors(settings, Machine(), bus, clock)
        control = Controller(enabled=True)
        control.update(sample_sensors(sensors, 0), clock.now, diff)
        self.assertGreater(control.heater, 0)
        bus.responses[(0x44, 2)] = OSError('sensor removed')
        sample = sample_sensors(sensors, 5000)
        control.update(sample, 5000, diff)
        self.assertEqual(control.fault, 'sensor coverage')
        self.assertEqual(control.heater, 0)
        bus.responses.clear()
        control.update(sample_sensors(sensors, 10000), 10000, diff)
        self.assertEqual(control.state, 'fault')

    def test_original_dht_inventory_is_unchanged(self):
        dht = DHT()
        sensors = build_sensors({}, Machine(), Bus(), Clock(), dht)
        self.assertEqual(sensors, dht.sensors)
        self.assertEqual(len(sensors), 4)

    def test_runtime_shared_oled_bus_and_single_sensor_bench(self):
        bus, machine, clock = Bus(), Machine(), Clock()
        machine.I2C = lambda *args, **kwargs: bus
        class CheckedDisplay(Display):
            def SSD1306_I2C(self, width, height, i2c):
                self.assert_bus = i2c
                return self
            def show(self):
                if bus.channel is not None:
                    raise AssertionError('mux branch left enabled during OLED update')
                super().show()
        display = CheckedDisplay()
        settings = {'SENSOR_TYPE': 'SHT31', 'SHT_MUX_ADDRESS': 0x70,
                    'SHT_SENSORS': ((0x44, 0),)}
        run(machine, None, display, settings, clock, 101)
        self.assertIs(display.assert_bus, bus)
        self.assertEqual(len([e for e in bus.events if e[0] == 'read']), 2)
        self.assertFalse(any(e[0] == 'duty' and e[1] == 25 and e[2] for e in machine.events))


if __name__ == '__main__':
    unittest.main()
