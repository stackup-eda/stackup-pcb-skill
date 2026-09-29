# MCU and module pin restrictions

This applies to microcontrollers and to every module or peripheral IC with configurable pins
(radios, sensors, displays). Before assigning any MCU or module pin, find out which pins are restricted: used internally,
sampled at boot, input-only, reserved for a function, or not bonded out on this package or module.
Connecting to one of these can stop the board from booting, corrupt flash, or quietly lose a feature.
Most of these problems pass every connectivity check.

## Procedure

1. **Identify the exact part.** The chip, and if it's a module, the exact module and variant (flash
   and PSRAM size and type, antenna option). Modules use chip pins internally, and which ones
   depends on the variant. Put the full variant (e.g. `ESP32-S3-WROOM-1-N16R8`, not
   "ESP32-S3 module") in the MPN, BOM and docs: pin availability and the firmware's flash/PSRAM
   configuration both depend on it, and a board may need to support more than one variant.
2. **Read the manufacturer's documents for that exact part:** the chip datasheet's pin table and
   strapping section, the module datasheet's pin table ("not connected", "used internally",
   "do not use"), the technical reference manual for boot modes and pin muxing, and the errata.
   Don't rely on a dev-board pinout diagram or a forum post (see the datasheet rule in
   [parts-sourcing.md](parts-sourcing.md#datasheets)).
3. **Classify every pin:**

   | Class | Examples | What to do |
   |---|---|---|
   | Used internally | flash/PSRAM bus on a module | never connect; `nc` it in Stackup if it's brought out |
   | Strapping / boot | sampled at reset to pick boot mode or flash voltage | give it the required level at reset; no loads that fight it |
   | Input-only | no output driver, often no internal pull | inputs only, with an external pull if needed |
   | Dedicated function | USB D+/D-, SWD/JTAG, crystal pins, reset, BOOT0 | keep for that function unless you have deliberately given it up |
   | Boot-time activity | UART0 TX prints at boot, pins that glitch or pulse at reset | nothing that reacts badly to that activity (a power latch, a motor driver enable) |
   | Limited | low drive current, ADC blocked by the radio, analog-only | check the limit against the load |
   | Not bonded | absent on this package or module | don't assign it |

4. **Check every load on a strapping pin** at reset: pull-ups, pull-downs, LEDs, the input of another
   IC, a button. The pin must read its required level with all of them attached, across the supply
   range. An LED or a pull-down on a strap pin that must be high is a classic no-boot bug.
5. **Check what each pin does before firmware configures it:** its reset state (high-Z, pulled up or
   down, or driven) and any boot-time output. Anything that must stay off until firmware runs (a
   power switch, a heater, a motor) needs an external pull that holds it off through reset.
6. **Record the result in a GPIO table** (`PCB/GPIO_table.md` or the PCB README): every pin, its
   net, its class, and the reason for any restriction. Mark reserved pins "do not use" so later
   changes don't grab them.
7. **In Stackup**, confirm the library part carries these restrictions: `role strap` with
   `require net.rest …` on strap pins, `required` on pins that must be connected, and no pins that
   the module uses internally. If the library part is missing a restriction, add it to the part (or
   upstream), and `nc` every reserved or spare pin.

## Examples by family (confirm against the current datasheet for your exact part)

These are prompts for what to look for, not a substitute for the datasheet.

- **ESP32 (original):** GPIO6-11 connect to the module's SPI flash, so don't use them. GPIO34-39 are
  input-only with no internal pulls. Strapping pins are GPIO0, 2, 5, 12 and 15; GPIO12 (MTDI) sets
  the flash voltage, and pulling it high at reset on a 3.3 V-flash module stops it booting. ADC2 is
  unavailable while Wi-Fi is on. WROVER modules also use pins for PSRAM (GPIO16/17).
- **ESP32-S3:** GPIO26-32 are used for SPI flash and PSRAM. On octal-PSRAM (and some octal-flash)
  module variants, GPIO33-37 are used too. Strapping pins are GPIO0, 3, 45 and 46. GPIO19/20 are
  native USB D-/D+, GPIO39-42 default to JTAG, and GPIO43/44 are UART0 TX/RX (programming and boot
  log). ADC2 is unavailable while Wi-Fi is on, so put analog inputs on ADC1.
- **ESP32-C3:** flash uses GPIO12-17 on most parts and modules. Strapping pins are GPIO2, 8 and 9;
  GPIO18/19 are USB.
- **STM32:** BOOT0 (and BOOT1 or option bytes on some parts) needs a defined level; PA13/PA14 are SWD
  (keep them for debugging); PC13-PC15 have very limited drive current and PC14/PC15 double as the
  LSE crystal pins; check which pins are 5 V tolerant (FT) before connecting 5 V signals.
- **nRF52832/nRF52840:** P0.09/P0.10 are NFC antenna pins by default and need a UICR setting before
  they work as GPIO. Some pins are marked for low-frequency I/O only near the radio.
- **RP2040 / RP2350:** the QSPI pins are dedicated to external flash, and the bootloader samples the
  QSPI chip-select at reset for BOOTSEL, so don't load it.

## Peripheral modules have straps too

Radio modules, sensors and other modules often sample pins at power-up. For example, the XBee3's
SPI_ATTN pin doubles as its boot-mode strap and must not be held low during power-up. Read each
module's hardware reference manual for boot-sampled pins, and give them their required level at
power-up with a resistor, just as for the MCU. Also note which pins the module requires to be left
unconnected or reserved.

## Pull-ups that matter at boot belong on the board

Every open-drain or open-collector output (interrupt, attention, alert, status, I2C) needs a pull-up
somewhere. When the line matters during power-up or reset, use a real resistor, not the MCU's
internal pull-up enabled from firmware:
- the internal pull-up isn't active until firmware runs, so the line floats through reset and boot;
- enabling it later changes the line at a moment another chip may be sampling it. On one board, a
  firmware `INPUT_PULLUP` on a radio module's attention line reliably stopped the module from ever
  asserting it after a cold power-on, and only a board resistor fixed it;
- internal pulls are weak and loosely specified (often tens of kΩ, wide tolerance).

Firmware pulls are fine for buttons and other inputs that don't matter until firmware is running.

## Off-board connections

For a connector to an off-board module or breakout (a display, a sensor board, a Qwiic/STEMMA QT
device), confirm the pinout against the actual module being used: its silkscreen, its datasheet,
and ideally a continuity check. Breakout pinouts vary by vendor even for the "same" part. One OLED
module had VCC/GND swapped relative to the assumed pinout, and once that was fixed SDA/SCL turned
out to be swapped as well. For a standard connector (Qwiic: GND, 3V3, SDA, SCL on a JST-SH 4-pin),
follow the standard and state it on the silkscreen.

## Keep a recovery path

Keep a way to reprogram and recover each programmable device: the MCU's USB or UART boot path and
its boot/reset pins (a button or test pads), and for modules with their own firmware, either a
host-controlled path or a documented decision that the module is updated off-board.

If a pin must be used despite a restriction (for example a strap pin because the board ran out of
GPIO), state why, show the level at reset with every load attached, and add it to the bench checklist.
