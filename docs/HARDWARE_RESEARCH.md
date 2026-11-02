# S4 Pro hardware research and ESP32 integration

Research status: 2 November 2026. This document records findings and investigation requirements, not a validated wiring procedure. The original firmware at `09fa5d7` has since been refactored for bench fault handling. GPIOs and the single-heater interface remain unchanged; no S4 Pro conversion or C3 pin map is implemented.

## S4 and S4 Pro are different targets

The [manufacturer's S4 Pro page](https://www.sunlu.com/products/347) specifies two independently controlled heating systems, separate chambers and a 45–85 °C range. The bench program still has one heater output, one fan output and a configurable 45 °C default target. Its name does not establish compatibility with either factory PCB.

A Pro implementation needs independent zone control and fault handling. Fan channels, sensor interfaces and interlocks must be identified on the actual unit. Do not transfer original-S4 connector assumptions to the Pro.

## Verified teardown lead

[SUNLU FilaDryer S4 Pro Unboxing / Review / Teardown — Windy](https://www.youtube.com/watch?v=o_AbyymrLSk), published 19 May 2026. The narration and on-screen captions are Chinese. The following scenes were visually inspected:

| Timestamp | Visible evidence |
| --- | --- |
| [4:47](https://www.youtube.com/watch?v=o_AbyymrLSk&t=287s) | Rear-cover access and four rear screws |
| [4:52](https://www.youtube.com/watch?v=o_AbyymrLSk&t=292s) | Power PCB close-up, including relay and surrounding parts |
| [4:57](https://www.youtube.com/watch?v=o_AbyymrLSk&t=297s) | Heatsinks and heater-switching power devices |
| [5:00](https://www.youtube.com/watch?v=o_AbyymrLSk&t=300s) | Close-up of optical-isolation components |

These are component/layout observations from video. No connector pinout, complete schematic, safe supply tap, isolation rating, switching topology or ESP32 wiring has been established. An optical component on a PCB does not prove that a particular connector or ground is safe to connect to a USB device. Exact part markings and both PCB faces are still needed.

The upstream [S4 wiring issue](https://github.com/HTRiepe/SUNLU_S4_ESP_Base/issues/2) was checked, including comments; it contains no wiring answer. No verified Pro conversion guide was found in the search so far. This is not a claim that none exists.

## Additional photograph observations: 2 November 2026

Three user-supplied teardown screenshots were inspected: two views of a small PCB and one of the power PCB. These are not photographs or measurements of the owner's unit, which has not arrived yet. The screenshots remain in the chat; the observations are transcribed here rather than treating them as a verified schematic.

| Observation | Interpretation and remaining uncertainty |
| --- | --- |
| Small-board revision appears to read `S4_Pro_Test_V1.2` | Tentative transcription; confirm with a sharper photograph. The word Test does not establish the board's function. |
| Small-board labels include `SDA`, `SCL`, `CLK`, `DIO`, `5V`, `GND` | SDA/SCL suggest I2C, but protocol, signal direction, pull-up voltage and device identity remain unverified. CLK/DIO do not establish UART TX/RX or a particular programming interface. |
| Component designated `U1` lies within a PCB cut-out | A sensor and thermal-isolation layout is a working hypothesis only. Its part marking is unreadable; no DHT22 or other sensor identification is established. |
| Two small-board views appear to show opposite faces of the same board | Do not infer connector pin numbering or cable order from perspective alone. |
| Power PCB shows relay, two heatsinks and a wired connector; apparent `12V`, `GND`, `5V` labels | Remaining labels need a straight-on close-up. Supply capacity, mains isolation, load allocation and control waveform are unknown. |

No ESP32 wiring or GPIO assignment follows from these labels. A 5 V supply label does not establish data-line voltage; any ESP32 connection needs verified electrical levels and suitable translation where necessary. Passive observation of sensor traffic, if feasible, would provide monitoring evidence, not automatically remote start/stop or setpoint control.

Priority photographs are both faces of the controller/display PCB with readable MCU markings, the power connector labels and the far end of its cable, and a macro of U1. Confirm all observations against the delivered appliance revision.

## Available equipment and agreed investigation plan

- Owner has a multimeter and a **Rigol DS1054Z** bench oscilloscope. Differential-probe ownership is unconfirmed; do not assume one is available.
- No differential-probe purchase is planned for this project. Start with photographs, component identification and unpowered continuity mapping. Reassess the approach if subsequent measurements require equipment that is unavailable.
- Treat the DS1054Z probe grounds as earth-connected and shared between channels. Two-channel subtraction does not provide isolation. Never disconnect protective earth to float the scope.
- Existing passive probes may be usable only after the relevant circuit's isolation, reference and voltage levels are established. A continuity beep or absence of continuity alone is not proof of safe mains isolation.
- On arrival, check normal operation before disassembly and record both zones' behaviour. Internal photography and continuity work require mains disconnected and stored energy made safe. Do not attach scope grounds, USB analysers or a USB-powered ESP32 to an unidentified reference.
- First investigate retaining factory regulation and protection through a usable interface. Neither a suitable communications interface nor compatibility with the current firmware has been demonstrated.

No powered captures, physical continuity checks, sensor identification or appliance modification have yet been performed.

## Evidence needed from the actual unit

Start with photographs and markings. No powered measurements are needed for this first stage.

| Evidence | Purpose |
| --- | --- |
| Product rating label and exact model/revision | Establish which appliance is being investigated |
| Overall internal photograph before unplugging cables | Preserve cable routing and connector relationships |
| Sharp, straight-on photographs of both sides of every PCB | Trace power, control, sensing and isolation boundaries |
| Macro photographs of the main MCU, regulators, relays, optical components and power switches | Read full part numbers and obtain the correct datasheets |
| Connector labels, pin counts and orientation, with cables still fitted | Build a pin-numbered harness map without relying on wire colours |
| Both ends of the display/control-board cable | Identify whether there is a separate low-voltage communications interface |
| Fan/heater labels and thermal switch/fuse markings | Establish load ratings, channel count and independent protection |
| Sensor bodies, markings and connectors | Determine whether the factory sensors are digital, analogue or something else |
| Both sides of the proposed ESP32 board and its product link | Confirm chip variant, exposed pins, regulator and power arrangements |

Retain full-resolution originals. Label boards and connectors consistently (for example power board J1, pin 1 identified in the photograph). Include a ruler where mechanical fit matters. Do not detach or flip a board merely to obtain a picture if doing so would risk damaging wiring or exposing unsafe circuitry.

Photographs can support a preliminary schematic; they cannot establish electrical safety or a full protocol by themselves.

## Measurement stages

1. **Unpowered mapping:** with mains disconnected and stored energy made safe, use continuity/resistance checks to establish connector-to-component relationships and suspected ground/reference networks. Record measurements against explicit connector pin numbers. A multimeter is useful; a continuity beep alone does not establish isolation.
2. **Supply and isolation assessment:** establish how the control electronics are powered and whether their signal reference is isolated from mains. Review component datasheets and the traced circuit. Powered appliance measurements require appropriate competence and equipment; no live probing instructions are supplied here.
3. **Signal identification:** only on an established safe interface, record voltage levels, timing and signal direction during boot, idle, each zone heating, temperature changes, button presses and stopping. A logic analyser can identify UART/I²C/SPI candidates; no such protocol is currently confirmed.
4. **Read-only capture:** if a factory communications link exists, capture traffic without driving the bus. Infer packet framing, checksums, commands, telemetry and failure handling from repeatable observations.
5. **Interface design:** choose suitable buffering/isolation/level translation, output polarity, default-off behaviour and power arrangements. Keep the factory and ESP32 outputs from driving the same line simultaneously.
6. **Bench verification:** test dummy loads and fault injection before any supervised heater trial. Record exact hardware and software versions.

Do not attach an ordinary USB logic analyser, USB-powered ESP32 or earthed oscilloscope ground to an unknown appliance reference. Keep USB and appliance supply paths separate until an explicit safe power/interface design is established.

## Integration approaches to assess

| Approach | Benefit | Missing evidence |
| --- | --- | --- |
| Add a communications bridge while retaining factory control | Could retain display, buttons and existing control/protection behaviour | A usable interface, protocol, electrical levels, isolation and the behaviour of remote commands are unverified |
| Replace the control logic and use a verified power interface | Allows fully custom control and Home Assistant integration | Requires reconstructing both zones, sensors, fan operation and all relevant safety/interlock behaviour |
| Independent monitoring only | Provides temperature/humidity telemetry without controlling factory outputs | Does not provide remote drying control; sensor placement and power still need design |

A communications bridge is the first approach worth investigating. This is a proposed investigation priority, not evidence that the S4 Pro exposes a usable serial interface. Do not start by replacing the power stage or bypassing protection.

## Can an ESP32 SuperMini be used?

**An ESP32-C3 SuperMini is a plausible controller or bridge candidate, subject to identifying the exact board. It is not a drop-in replacement for this firmware's classic-ESP32 pin map.** SuperMini is a board name used for different designs; confirm the chip marking and exposed pins.

The [ESP32-C3 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf) documents Wi-Fi, I²C, UART and PWM peripherals. GPIO 22, 25 and 26 from the existing application do not exist on the C3; other original GPIOs may be occupied by flash or absent from the board headers. GPIO 2/8/9 have boot-strapping roles, and 18/19 normally serve USB Serial/JTAG. Check onboard LEDs/buttons and boot behaviour before allocating signals.

The C3's [LEDC peripheral](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/peripherals/ledc.html) provides six PWM channels. That supports the basic premise of multiple control outputs, but does not establish the waveform needed by the S4 Pro drivers. A heater may require on/off or slow time-proportional switching instead of the prototype's 1 kHz PWM.

| Intended use | Preliminary assessment |
| --- | --- |
| Wi-Fi telemetry / Home Assistant bridge | Plausible; confirm protocol and electrical interface |
| UART bridge | Generally a modest pin requirement; factory UART is not yet confirmed |
| Two-zone controller with added digital sensors | Likely within C3 capabilities; complete GPIO and fault-handling budget still needed |
| Retain factory touchscreen/buttons/sensors | Cannot assess until interfaces and protocol are identified |
| Run existing `main.py` unchanged | No: wrong pin map and only one heater channel |
| Drive heaters or fans directly | No: GPIOs are logic outputs, requiring appropriate verified interfaces |

[ESPHome supports ESP32 variants including the C3](https://esphome.io/components/esp32/). That is a candidate software foundation, not an implemented port or safety guarantee. No final GPIO assignment is proposed until the board and required interfaces are known.

Any appliance-derived supply must have verified voltage, isolation and current capacity for Wi-Fi operation. Do not join USB power and appliance power unless the design prevents backfeeding. No supply tap is approved by this research.

## Related projects considered

| Project | Useful material | Applicability / qualification |
| --- | --- | --- |
| [SiloCityLabs Multi Dryer](https://github.com/SiloCityLabs/esp32-dikale-dryer) | ESPHome configuration, GPIO table, PCB upgrade and installation-video link | Targets Dikale/Firos/3DGenius-style dryers, not the S4 Pro. Calibration/fan testing remains on its TODO list; its safety logic needs separate review. |
| [itarozzi DIY filament dryer](https://github.com/itarozzi/diy_filament_dryer) | PlatformIO project, touchscreen UI, MQTT commands and Node-RED dashboard | Generic DIY controller; no demonstrated S4/Pro wiring compatibility. |
| [Sovol SH03 ESP/Wi-Fi reconstruction](https://github.com/aizerin/sh03-esp-wifi) | Detailed board identification, photographs, backup/installation guidance and ESPHome bridge | Different appliance and experimental reconstructed firmware; explicitly incomplete physical safety validation. |

Documentation maturity is not proof of code quality, electrical compatibility or thermal safety. None of these projects was built or physically validated during this research.

## Current deliverables and next milestone

- Existing ESP32 bench interfaces and operation are documented in [README.md](../README.md).
- Firmware faults and mock reproduction evidence are in [CODE_REVIEW.md](../CODE_REVIEW.md).
- Unresolved work and acceptance criteria are in [ISSUES.md](../ISSUES.md).
- Next milestone: identify the exact Pro PCB revision and SuperMini variant, then produce an evidence-labelled connector map and preliminary schematic. Do not publish a final wiring diagram until it is verified.
