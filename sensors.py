"""DHT22 and SHT3x-DIS adapters for the shared sampling interface.

SHT30/SHT31 use high-repeatability single-shot measurements without clock
stretching. Protocol: Sensirion SHT3x-DIS datasheet, sections 4.3/4.12/4.13.
"""
import time


def write_checked(i2c, address, data):
    if i2c.writeto(address, data) != len(data):
        raise OSError('incomplete I2C write')


def crc8(data):
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


class TCA9548A:
    def __init__(self, i2c, address=0x70):
        if type(address) is not int or not 0x70 <= address <= 0x77:
            raise ValueError('TCA9548A address must be 0x70..0x77')
        self.i2c, self.address = i2c, address
        self.disable()

    def select(self, channel):
        if type(channel) is not int or not 0 <= channel <= 7:
            raise ValueError('TCA9548A channel must be 0..7')
        # Never enable multiple branches with conflicting sensor addresses.
        write_checked(self.i2c, self.address, bytes((1 << channel,)))

    def disable(self):
        write_checked(self.i2c, self.address, b'\x00')


class SHT3x:
    def __init__(self, i2c, address=0x44, mux=None, channel=None, clock=time):
        if type(address) is not int or address not in (0x44, 0x45):
            raise ValueError('SHT3x address must be 0x44 or 0x45')
        if mux is None and channel is not None:
            raise ValueError('sensor channel requires a multiplexer')
        if mux is not None and (type(channel) is not int or not 0 <= channel <= 7):
            raise ValueError('multiplexed sensor requires channel 0..7')
        self.i2c, self.address = i2c, address
        self.mux, self.channel, self.clock = mux, channel, clock
        self._temperature = self._humidity = None

    def measure(self):
        # Failed acquisitions must not expose previous successful measurements.
        self._temperature = self._humidity = None
        try:
            if self.mux is not None:
                self.mux.select(self.channel)
            write_checked(self.i2c, self.address, b'\x24\x00')
            self.clock.sleep_ms(20)  # Datasheet worst case 15.5 ms.
            data = self.i2c.readfrom(self.address, 6)
            if len(data) != 6:
                raise ValueError('short SHT3x response')
            if crc8(data[:2]) != data[2] or crc8(data[3:5]) != data[5]:
                raise ValueError('SHT3x checksum failure')
            temperature = -45.0 + 175.0 * ((data[0] << 8) | data[1]) / 65535
            humidity = 100.0 * ((data[3] << 8) | data[4]) / 65535
        finally:
            # Also isolate faulty branches before the shared OLED is accessed.
            # If deselection fails, do not expose this acquisition as successful.
            if self.mux is not None:
                self.mux.disable()
        self._temperature, self._humidity = temperature, humidity

    def temperature(self):
        return self._temperature

    def humidity(self):
        return self._humidity


def build_sensors(settings, machine, i2c, clock, dht_driver=None):
    kind = settings.get('SENSOR_TYPE', 'DHT22')
    if kind == 'DHT22':
        if dht_driver is None:
            import dht as dht_driver
        return [dht_driver.DHT22(machine.Pin(pin)) for pin in (15, 2, 4, 16)]
    if kind not in ('SHT3X', 'SHT30', 'SHT31'):
        raise ValueError('SENSOR_TYPE must be DHT22, SHT3X, SHT30 or SHT31')
    # Explicit inventory, never scan and silently accept missing sensors.
    locations = settings.get('SHT_SENSORS')
    if not isinstance(locations, (list, tuple)) or not 1 <= len(locations) <= 4:
        raise ValueError('configure one to four SHT sensors')
    mux_address = settings.get('SHT_MUX_ADDRESS')
    seen = []
    for location in locations:
        if not isinstance(location, (list, tuple)) or len(location) != 2:
            raise ValueError('SHT_SENSORS entries must be (address, channel)')
        address, channel = location
        if type(address) is not int or address not in (0x44, 0x45):
            raise ValueError('SHT3x address must be 0x44 or 0x45')
        if mux_address is None:
            if channel is not None:
                raise ValueError('direct sensors must have channel None')
        elif type(channel) is not int or not 0 <= channel <= 7:
            raise ValueError('multiplexed sensors require channel 0..7')
        identity = (address, channel)
        if identity in seen:
            raise ValueError('duplicate SHT sensor location')
        seen.append(identity)
    mux = TCA9548A(i2c, mux_address) if mux_address is not None else None
    return [SHT3x(i2c, address, mux, channel, clock) for address, channel in locations]
