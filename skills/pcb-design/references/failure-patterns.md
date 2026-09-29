# Common failure patterns

Each of these has passed ERC/DRC/netlist checks on a real board. Repeat the check on every design.

| Failure | Why connectivity checks miss it | Check that catches it |
|---|---|---|
| A gate pull-down forms a divider with the drive's pull-up, leaving the gate far below threshold | The nets are wired as intended | Compute every resistor pair meeting at a gate or input ([dc-bias.md](dc-bias.md)) |
| A FET with ~2.5 V max Vgs(th) driven with ~2.4 V at the bottom of the battery range | Typical Vth and nominal supply look fine | Worst-case Vgs(th) at the lowest supply, with the real diode drop |
| A regulator EN pin floats whenever its driver is off | Every pin is connected to something | Every enable/reset input gets a pull in both driver states |
| A new circuit borrows current from a node the MCU reads, sagging the reading | The net is "correctly connected" | Recompute any node that gains a load |
| A pull-up to the battery rail puts a GPIO above its 3.3 V rail, and back-feeds the dead rail when the MCU is off | ERC doesn't know rail voltages | Pin abs-max against every rail, in every supply state |
| A power latch briefly enables on battery insertion because a debounce cap hasn't charged yet | Only a transient shows it | SPICE insertion scenario at several rise times and supply levels |
| A part name the fab read as a different package | MPN/manufacturer never reached the fab's BOM | Unambiguous BOM value or columns ([bom-and-fab.md](bom-and-fab.md)) |
| An LED was assigned a 5 × 5 mm PLCC4 footprint for a 3.2 × 2.8 mm reverse-mount part; the assembler rejected it | The name looked plausible, and a stale assignment survived a design fix | Measure the footprint on the board and compare it with the package drawing ([kicad.md](kicad.md#footprints)) |
| An off-board display's connector had power and ground swapped, then SDA/SCL swapped | The symbol matched an assumed pinout | Confirm off-board pinouts against the real module ([mcu-pins.md](mcu-pins.md)) |
| A firmware-enabled internal pull-up on a module's attention/strap line stopped the module from starting on cold power-up | The line looked "pulled up" | A real resistor for any pull that matters at boot ([mcu-pins.md](mcu-pins.md)) |
| A stock KiCad footprint was larger than the manufacturer's land pattern | It's from the official library | Check every footprint against the datasheet ([kicad.md](kicad.md)) |
| Parts matched at design time were out of stock at order time | Stock was checked once | Re-check stock when ordering ([parts-sourcing.md](parts-sourcing.md)) |
| An assembler mounted a right-angle connector vertically from a correct BOM | Nothing in the design was wrong | Orientation in the description, inspect first articles ([bom-and-fab.md](bom-and-fab.md)) |
| Firmware's low-battery shutdown threshold sat 60 mV above the charger's hardware cutoff | No check compares firmware to hardware | Battery and power-path checks ([dc-bias.md](dc-bias.md)) |
| Layout diagrams and README tables still name the old part after a swap | Docs aren't checked | Update docs in the same change as the part |

A good power-latch simulation covers battery insertion, a button press at the lowest supply with
worst-case FET thresholds, and shutdown, and has a flag that removes the fix so the fix's effect is
visible. See [spice.md](spice.md).

## Microcontroller pins

Strap pins with a load that fights their boot level, flash pins wired to a peripheral, and a power
latch held by a pin that toggles during boot or programming are all common. See
[mcu-pins.md](mcu-pins.md) for the procedure and per-family examples. Features should degrade
gracefully when their hardware is absent; firmware must not assume a part is fitted.
