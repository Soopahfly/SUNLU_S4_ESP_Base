"""Small MQTT 3.1.1 telemetry-only client; bounded nonblocking steps, no DNS.

One QoS1 publication in flight, no subscriptions. A failed transaction is
abandoned and retried with a fresh clean session and current data.
"""
import errno
import socket
import select

# Windows CPython has no poll; tests inject a poller using standard poll masks.
POLLIN = getattr(select, 'POLLIN', 1)
POLLOUT = getattr(select, 'POLLOUT', 4)
POLLERR = getattr(select, 'POLLERR', 8)
POLLHUP = getattr(select, 'POLLHUP', 16)
try:
    import ujson as json
except ImportError:
    import json


def field(value):
    data = value.encode() if isinstance(value, str) else value
    if len(data) > 65535:
        raise ValueError('MQTT string too large')
    return bytes((len(data) >> 8, len(data) & 255)) + data


def packet(header, body):
    size, encoded = len(body), bytearray()
    while True:
        digit = size % 128
        size //= 128
        encoded.append(digit | (128 if size else 0))
        if not size:
            return bytes((header,)) + encoded + body


class Telemetry:
    TIMEOUT_MS = 3000
    RETRY_MS = 10000
    PUBLISH_MS = 5000

    def __init__(self, settings, device_id, clock, wlan=None, socket_module=socket,
                 poll_factory=None):
        self.clock, self.socket_module, self.poll_factory = clock, socket_module, poll_factory or select.poll
        self.settings = settings
        # Validate numeric IPv4 before getaddrinfo: never resolve an arbitrary name.
        host = settings.get('MQTT_BROKER_IP', '')
        parts = host.split('.')
        if len(parts) != 4 or any(not p.isdigit() or not 0 <= int(p) <= 255 for p in parts):
            raise ValueError('MQTT_BROKER_IP must be a numeric IPv4 address')
        self.host = host
        self.port = settings.get('MQTT_PORT', 1883)
        self.device = 'sunlu-' + ''.join('%02x' % b for b in device_id)
        self.topic = (settings.get('MQTT_TOPIC_PREFIX', self.device) + '/sensors').encode()
        if len(self.topic) > 256 or b'+' in self.topic or b'#' in self.topic:
            raise ValueError('invalid topic prefix')
        if wlan is None:
            import network
            wlan = network.WLAN(network.STA_IF)
        self.wlan = wlan
        self.sock = self.poller = None
        self.state = 'retry'
        self.mark = clock.ticks_ms()
        self.retry_delay = 0
        self.sent_at = self.last_ack = None
        self.error = None
        self.tx = b''
        self.rx = b''
        self.offset = 0

    def close(self):
        sock, self.sock = self.sock, None
        self.poller = None
        self.last_ack = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def fail(self, reason, now):
        self.close()
        self.error = str(reason)
        self.state, self.mark, self.retry_delay = 'retry', now, self.RETRY_MS

    def queue(self, data, next_state, now):
        self.tx, self.offset, self.after_send = data, 0, next_state
        self.state, self.mark = 'send', now
        self.poller.modify(self.sock, POLLOUT)

    def connect_packet(self):
        flags = 2 | 4  # clean session, QoS0 non-retained last will
        body = field(self.device) + field(self.topic) + field('{"state":"offline"}')
        user, password = self.settings.get('MQTT_USER'), self.settings.get('MQTT_PASSWORD')
        if password is not None and user is None:
            raise ValueError('MQTT password requires a username')
        if user is not None:
            flags |= 128
            body += field(user)
        if password is not None:
            flags |= 64
            body += field(password)
        return packet(0x10, field('MQTT') + bytes((4, flags, 0, 30)) + body)

    def step(self, payload):
        now = self.clock.ticks_ms()
        try:
            self._step(payload, now)
        except Exception as exc:
            self.fail(exc, now)

    def _step(self, payload, now):
        diff = self.clock.ticks_diff
        if self.state == 'retry':
            if diff(now, self.mark) < self.retry_delay:
                return
            self.wlan.active(True)
            if not self.wlan.isconnected():
                self.wlan.connect(self.settings['WIFI_SSID'], self.settings.get('WIFI_PASSWORD', ''))
                self.state, self.mark = 'wifi', now
                return
            self._open(now)
            return
        if self.state == 'wifi':
            if self.wlan.isconnected():
                self._open(now)
            elif diff(now, self.mark) >= self.TIMEOUT_MS:
                self.wlan.disconnect()
                self.fail('Wi-Fi timeout', now)
            return
        if not self.wlan.isconnected():
            self.fail('Wi-Fi lost', now)
            return
        if self.state != 'ready' and diff(now, self.mark) >= self.TIMEOUT_MS:
            self.fail('MQTT transaction timeout', now)
            return
        if self.state == 'ready':
            if self.sent_at is None or diff(now, self.sent_at) >= self.PUBLISH_MS:
                current = dict(payload)
                current['mqtt_ack_age_ms'] = (None if self.last_ack is None
                                              else diff(now, self.last_ack))
                data = json.dumps(current).encode()
                if len(data) > 4096:
                    raise ValueError('telemetry too large')
                self.sent_at = now
                self.queue(packet(0x32, field(self.topic) + b'\x00\x01' + data), 'puback', now)
            return
        events = self.poller.poll(0)
        if not events:
            return
        event = events[0][1]
        if event & (POLLERR | POLLHUP):
            raise OSError('socket closed/error')
        if self.state == 'tcp' and event & POLLOUT:
            self.queue(self.connect_packet(), 'connack', now)
        elif self.state == 'send' and event & POLLOUT:
            try:
                count = self.sock.send(self.tx[self.offset:self.offset + 512])
            except OSError as exc:
                if exc.args[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                    return
                raise
            if not count:
                raise OSError('socket send closed')
            self.offset += count
            if self.offset == len(self.tx):
                self.state, self.mark, self.rx = self.after_send, now, b''
                self.poller.modify(self.sock, POLLIN)
        elif self.state in ('connack', 'puback') and event & POLLIN:
            try:
                data = self.sock.recv(4 - len(self.rx))
            except OSError as exc:
                if exc.args[0] in (errno.EAGAIN, errno.EWOULDBLOCK):
                    return
                raise
            if not data:
                raise OSError('socket receive closed')
            self.rx += data
            if len(self.rx) == 4:
                expected = b'\x20\x02\x00\x00' if self.state == 'connack' else b'\x40\x02\x00\x01'
                if self.rx != expected:
                    raise ValueError('broker rejected/unexpected acknowledgement')
                if self.state == 'puback':
                    self.last_ack, self.error = now, None
                self.state = 'ready'

    def _open(self, now):
        # Numeric-only lookup avoids network DNS. Platform call latency still needs
        # measurement on the target MicroPython build.
        address = self.socket_module.getaddrinfo(self.host, self.port, socket.AF_INET,
                                                 socket.SOCK_STREAM)[0][-1]
        self.sock = self.socket_module.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(False)
        self.poller = self.poll_factory()
        self.poller.register(self.sock, POLLOUT)
        self.sent_at = None
        self.state, self.mark = 'tcp', now
        try:
            self.sock.connect(address)
        except OSError as exc:
            if exc.args[0] not in (errno.EINPROGRESS, errno.EALREADY, errno.EAGAIN,
                                   errno.EWOULDBLOCK):
                raise
