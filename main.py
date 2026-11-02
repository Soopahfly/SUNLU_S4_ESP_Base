"""MicroPython entry point. Normal boot monitors only; it never arms heating."""


class MonitorWatchdog:
    def feed(self):
        pass


def run(enable_heat=False):
    import time
    from machine import Pin, PWM, I2C, WDT, unique_id
    from binascii import hexlify
    import config
    from hardware import Outputs, Display

    cfg = config.load()
    outputs = Outputs(Pin, PWM, cfg)
    try:
        outputs.pause()
        # A stalled peripheral/network call resets to monitoring-only run().
        # No watchdog in normal monitoring mode, so file uploads/REPL remain usable.
        watchdog = WDT(timeout=cfg.WATCHDOG_MS) if enable_heat else MonitorWatchdog()
        from control import Controller
        from runtime import Runner, run_loop
        from telemetry import Telemetry
        import dht
        import ssd1306
        import network

        controller = Controller(cfg, time.ticks_diff)
        sensors = [dht.DHT22(Pin(pin)) for pin in cfg.SENSOR_PINS]
        bus = I2C(0, scl=Pin(cfg.OLED_SCL), sda=Pin(cfg.OLED_SDA))
        display = Display(ssd1306.SSD1306_I2C(128, 64, bus, addr=cfg.OLED_ADDRESS))
        wlan, factory = None, None
        if cfg.WIFI_SSID and cfg.MQTT_BROKER:
            from umqtt.simple import MQTTClient
            wlan, factory = network.WLAN(network.STA_IF), MQTTClient
        telemetry = Telemetry(cfg, time, wlan, factory, hexlify(unique_id()).decode())
        runner = Runner(cfg, time, controller, outputs, sensors, display, telemetry,
                        enable_heat=enable_heat, log=print)
        watchdog.feed()
        time.sleep_ms(2000)  # sensor power-up, with heat inhibited
        run_loop(runner, time, watchdog)
    finally:
        # Keep heater deliberately low, not deinitialised to a floating pin.
        # Cooling is requested even on Ctrl-C; physical fan operation is unverified.
        outputs.shutdown()


if __name__ == "__main__":
    run()
