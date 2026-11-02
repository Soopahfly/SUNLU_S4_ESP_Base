import errno
import select
import unittest
from telemetry import Telemetry, field, packet, POLLIN, POLLOUT
from test_controller import Clock, Machine, DHT, Display
from main import run


class WLAN:
    def __init__(self, connected=True):
        self.connected = connected
        self.attempts = self.disconnects = 0
    def active(self, value):
        pass
    def isconnected(self):
        return self.connected
    def connect(self, *args):
        self.attempts += 1
    def disconnect(self):
        self.disconnects += 1


class Socket:
    def __init__(self):
        self.sent, self.incoming = bytearray(), bytearray()
        self.chunk, self.closed, self.ready = 512, False, True
        self.error = None
    def setblocking(self, value):
        assert value is False
    def connect(self, address):
        raise OSError(errno.EINPROGRESS)
    def send(self, data):
        if self.error:
            raise self.error
        count = min(self.chunk, len(data))
        self.sent.extend(data[:count])
        return count
    def recv(self, size):
        if self.error:
            raise self.error
        # Deliberately fragment every acknowledgement.
        data = bytes(self.incoming[:1])
        del self.incoming[:1]
        return data
    def close(self):
        self.closed = True


class Sockets:
    def __init__(self):
        self.created = []
    def getaddrinfo(self, host, port, *args):
        return [(None, None, None, None, (host, port))]
    def socket(self, *args):
        sock = Socket()
        self.created.append(sock)
        return sock


class Poll:
    def register(self, sock, mask):
        self.sock, self.mask = sock, mask
    modify = register
    def poll(self, timeout):
        assert timeout == 0
        if not self.sock.ready:
            return []
        if self.mask == POLLIN and not self.sock.incoming:
            return []
        return [(self.sock, self.mask)]


class TelemetryTests(unittest.TestCase):
    def make_client(self, connected=True):
        clock, sockets, wlan = Clock(), Sockets(), WLAN(connected)
        settings = {'MQTT_BROKER_IP': '192.0.2.1', 'WIFI_SSID': 'bench'}
        client = Telemetry(settings, b'\x01\x02', clock, wlan, sockets, Poll)
        return client, clock, sockets, wlan

    def advance(self, client, clock, count=1, payload=None):
        for _ in range(count):
            client.step(payload or {'state': 'fault', 'fault': 'overtemperature'})
            clock.now += 50

    def handshake(self, client, clock, sockets):
        self.advance(client, clock, 3)
        self.assertEqual(client.state, 'connack')
        sock = sockets.created[-1]
        self.assertEqual(bytes(sock.sent), client.connect_packet())
        sock.incoming.extend(b'\x20\x02\x00\x00')
        self.advance(client, clock, 4)
        self.assertEqual(client.state, 'ready')
        return sock

    def test_fragmented_handshake_and_matching_puback(self):
        c, clock, sockets, wlan = self.make_client()
        sock = self.handshake(c, clock, sockets)
        before = len(sock.sent)
        self.advance(c, clock, 2)
        self.assertEqual(c.state, 'puback')
        wire = bytes(sock.sent[before:])
        self.assertEqual(wire[0], 0x32)  # QoS1, non-retained
        self.assertIn(b'overtemperature', wire)
        self.assertIn(b'\x00\x01', wire)
        self.assertIsNone(c.last_ack)
        sock.incoming.extend(b'\x40\x02\x00\x01')
        self.advance(c, clock, 4)
        self.assertIsNotNone(c.last_ack)
        self.assertEqual(c.state, 'ready')
        self.assertIsNone(c.error)

    def test_timeout_each_transaction_phase(self):
        for phase in ('tcp', 'send', 'connack', 'puback'):
            with self.subTest(phase=phase):
                c, clock, sockets, _ = self.make_client()
                self.advance(c, clock)
                sock = sockets.created[-1]
                c.state = phase
                c.mark = clock.now
                sock.ready = False
                clock.now += 3000
                self.advance(c, clock)
                self.assertEqual(c.state, 'retry')
                self.assertTrue(sock.closed)
                self.assertIsNone(c.last_ack)

    def test_partial_send_cannot_extend_deadline(self):
        c, clock, sockets, _ = self.make_client()
        self.advance(c, clock, 2)
        sockets.created[-1].chunk = 1
        for _ in range(4):
            self.advance(c, clock)
            clock.now += 1000
        self.assertEqual(c.state, 'retry')

    def test_rejected_connack_and_wrong_puback(self):
        for response, phase in ((b'\x20\x02\x00\x05', 'connack'),
                                (b'\x40\x02\x00\x02', 'puback')):
            c, clock, sockets, _ = self.make_client()
            self.advance(c, clock, 3)
            c.state = phase
            sockets.created[-1].incoming.extend(response)
            self.advance(c, clock, 4)
            self.assertEqual(c.state, 'retry')
            self.assertIsNotNone(c.error)

    def test_wifi_timeout_retry_recovery_and_unique_ids(self):
        c, clock, sockets, wlan = self.make_client(False)
        self.advance(c, clock)
        self.assertEqual(wlan.attempts, 1)
        clock.now += 3000
        self.advance(c, clock)
        self.assertEqual(c.state, 'retry')
        self.assertEqual(wlan.disconnects, 1)
        self.advance(c, clock)
        self.assertEqual(wlan.attempts, 1)
        clock.now += 10000
        wlan.connected = True
        self.handshake(c, clock, sockets)
        self.assertEqual(c.device, 'sunlu-0102')
        self.assertEqual(c.topic, b'sunlu-0102/sensors')

    def test_disconnect_publish_error_and_reconnect_current_data(self):
        c, clock, sockets, wlan = self.make_client()
        sock = self.handshake(c, clock, sockets)
        self.advance(c, clock)
        sock.error = OSError('write failed')
        self.advance(c, clock)
        self.assertEqual(c.state, 'retry')
        clock.now += 10000
        new_sock = self.handshake(c, clock, sockets)
        self.advance(c, clock, 2, {'state': 'fault', 'fault': 'latched'})
        self.assertIn(b'latched', new_sock.sent)
        wlan.connected = False
        self.advance(c, clock)
        self.assertEqual(c.state, 'retry')
        self.assertTrue(new_sock.closed)

    def test_network_loss_does_not_block_sampling(self):
        clock, dht = Clock(), DHT()
        wlan, sockets = WLAN(False), Sockets()
        def factory(settings, device, runtime_clock):
            return Telemetry(settings, device, runtime_clock, wlan, sockets, Poll)
        settings = {'HEAT_ENABLED': True, 'NETWORK_ENABLED': True,
                    'MQTT_BROKER_IP': '192.0.2.1', 'WIFI_SSID': 'bench'}
        run(Machine(), dht, Display(), settings, clock, 301, factory)
        self.assertEqual([s.calls for s in dht.sensors], [4]*4)
        self.assertGreaterEqual(wlan.attempts, 2)

    def test_reject_dns_and_malformed_host(self):
        for host in ('mqtt.local', '256.1.1.1', '1.2.3', '1.2.3.-1'):
            with self.assertRaises(ValueError):
                Telemetry({'MQTT_BROKER_IP': host}, b'1', Clock(), WLAN(), Sockets(), Poll)

    def test_mqtt_encoding_auth_and_length(self):
        self.assertEqual(field('MQTT'), b'\x00\x04MQTT')
        self.assertEqual(packet(0x30, b'x'*128)[:3], b'\x30\x80\x01')
        c, _, _, _ = self.make_client()
        c.settings.update(MQTT_USER='user', MQTT_PASSWORD='secret')
        data = c.connect_packet()
        self.assertIn(field('user') + field('secret'), data)
        # Flags: username, password, clean session, will; keepalive 30.
        self.assertIn(b'\x04\xc6\x00\x1e', data)
        self.assertIn(b'{"state":"offline"}', data)


if __name__ == '__main__':
    unittest.main()
