# Stackup (KDL) electrical design

Stackup is a declarative electronics design tool written in Rust. A design in
[KDL v2](https://kdl.dev) states parts, reusable circuits (blocks), connections and constraints; the
CLI checks them together and exports a KiCad netlist. It **validates** choices; it never chooses a
part, pin, peripheral, or value for you.

- Engine and spec: https://github.com/stackup-eda/stackup (`SPEC.md` is the language spec,
  `OPEN.md` lists known gaps, `kicad-plugin/README.md` covers PCB sync)
- Parts library: https://github.com/stackup-eda/library (imported as `@stackup/...`)
- Crate: `stackup-eda` on crates.io

When unsure how a construct behaves, read `SPEC.md` and `OPEN.md` at the pinned version. The
language is young; check `OPEN.md` before treating a missing feature as a bug.

## Contents

1. Project setup
2. CLI
3. Writing a design
4. Parts and library blocks
5. Checks and findings
6. KiCad sync
7. Gotchas

## 1. Project setup

```
manifest.kdl                 # at the repo root
PCB/stackup/board.kdl        # the design
PCB/stackup/parts.kdl        # project-specific parts not in the library
PCB/<board>.kicad_pcb
PCB/<board>.stackup_sch      # one line: path to board.kdl relative to the PCB directory
ci/stackup/                  # Cargo-locked CLI so everyone runs the same version
```

`manifest.kdl` pins the library to a **full commit hash** (not a branch or tag):

```kdl
stackup "0.1"
library stackup git="https://github.com/stackup-eda/library" rev="<full commit sha>"
```

To work against a local library checkout, add a `manifest.local.kdl` beside it (keep it out of git):

```kdl
library stackup path="../stackup-library"
```

`--locked` ignores that local override; CI always uses `--locked`.

Pin the CLI with a tiny Cargo project so the version is locked. The skill currently targets
Stackup at commit `1acb9ba` on `main`, which adds MPN declarations with placement matching and
fixes `place` declaration order; the latest crates.io release (0.1.3) has neither. Move the pin to a
release once one includes them:

```toml
# ci/stackup/Cargo.toml
[package]
name = "<project>-stackup-check"
version = "0.0.0"
edition = "2024"
publish = false

[dependencies]
stackup = { package = "stackup-eda", git = "https://github.com/stackup-eda/stackup", rev = "1acb9ba" }
```

```rust
// ci/stackup/src/main.rs
fn main() {
    stackup::cli::run();
}
```

Run it with `cargo run --locked --manifest-path ci/stackup/Cargo.toml -- check PCB/stackup/board.kdl --locked`.
For daily use, install the same commit so `stackup` on `PATH` matches the pin:

```sh
cargo install --git https://github.com/stackup-eda/stackup --rev 1acb9ba stackup-eda --locked
```

## 2. CLI

The pinned CLI has `check`, `tree`, `netlist`, `bom` and `update`; run `stackup` with no
arguments for its usage line. (The library README also mentions `pin`, `import` and
`check --symbols`; the pinned CLI doesn't have them.)

| Command | Purpose |
|---|---|
| `stackup check <board.kdl> [--locked]` | Elaborate and report every finding at once |
| `stackup tree <board.kdl>` | Instances and nets, for reading |
| `stackup netlist <board.kdl> [-o file]` | KiCad netlist (the plugin calls this) |
| `stackup bom <board.kdl> --locked [-o file.csv]` | Purchasing BOM with manufacturer, MPN and distributor columns; reports each part with no MPN and exits 1, but still writes the CSV |
| `stackup update [@lib]` | Move a library pin to its current head |

`--design NAME` selects one design when a file has several.

## 3. Writing a design

This example passes `stackup check --locked` with 0 errors, 0 warnings and 0 notes against the
library pinned at `9120a03` (a test in this skill's repo checks it):

```kdl
use "@stackup/passives"
use "@stackup/discrete/fet/ao3401a"
use "@stackup/power/buck/tlv62569"
use "@stackup/connector/jst-ph"

design example {
    stock { packages imperial="0402" }   // default package for generic passives

    place jst-ph-2 "BT1" footprint="Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal" \
        manufacturer="JST" mpn="S2B-PH-K(LF)(SN)" lcsc="C265016" value="PH 2-pin RIGHT-ANGLE" hand=#true
    place ao3401a "Q_PWR1" footprint="Package_TO_SOT_SMD:SOT-23" \
        manufacturer="Alpha & Omega Semicon" mpn="AO3401A" lcsc="C15127" value="AO3401A"
    place pull-down "R_EN_PD1" footprint="Resistor_SMD:R_0402_1005Metric" \
        manufacturer="UNI-ROYAL(Uniroyal Elec)" mpn="0402WGF1003TCE" lcsc="C25741" value="100kΩ"
    place tlv62569 "U_BUCK1" footprint="Package_TO_SOT_SMD:SOT-23-5" \
        manufacturer="Texas Instruments" mpn="TLV62569DBVR" lcsc="C141836" value="TLV62569DBVR"

    circuit "BT1.1" "Q_PWR1.SOURCE" "U_BUCK1.VIN" name="VBAT"
    set "U_BUCK1.VIN" net.voltage min="3.0V" max="4.2V"   // checked against the buck's VIN range
    circuit "Q_PWR1.DRAIN" "R_EN_PD1.node" "U_BUCK1.EN" name="PWR_EN"
    circuit "BT1.2" "R_EN_PD1.rail.gnd" "U_BUCK1.GND" name="GND"   // a shunt block's return: rail.gnd
    circuit "Q_PWR1.GATE" name="PWR_GATE"
    nc "U_BUCK1.SW" "U_BUCK1.FB" note="example only: the inductor and divider are left out"
}
```

Key ideas (SPEC sections in brackets):

- **Order carries no meaning.** A statement, including a port argument on `place`
  (`vcc=V5.out`), may name a placement declared later. (Before `b98481c`, port arguments couldn't;
  see stackup-eda/stackup#1.)
- **Facts stay on their net.** A voltage stated on the battery net doesn't pass through a switch or
  series part, so `set … net.voltage` goes on the net whose requirement should read it.
- **Shunt blocks** (`pull-up`, `pull-down`, `decouple`) connect through `.node` and their return
  through `.rail.gnd` (or `rail=` as a port argument).
- **`place <part-or-block> <name> key=value…`** instantiates. Generic parts take `value=`,
  `intent=` (`decouple`, `bypass`, `bulk`, `filter`, `pull-up`, `pull-down`, `timing`, `series`,
  `divider`) and `note=`. `package=` selects a non-default package. `hand=#true` marks a
  hand-installed part (stays in the BOM, marked DNP for the assembler).
- **References:** `/` is hierarchy (`timer/u`), `.` is a pin or port (`u.OUT`), `@` is a pad
  (`mcu.VDD@A1`). Names with `/` must be quoted.
- **`circuit a b c`** joins terminals; a series element (a resistor, a diode) is entered at `a` and
  left at `b`, so `circuit src R dest` puts `R` between them. `name=` names the net at the head.
- **`connect <type>`** makes typed links (`i2c`, `spi`, `uart`, `power`, `output`, `analog`…) and
  checks the pins against the MCU's peripheral table.
- **`nc`** declares a pin deliberately unconnected; joining it later is a finding. A pin that
  nothing mentions is merely unconnected, so `nc` every spare on purpose.
- **Quantities are quoted with units** (`"100nF"`, `"4.7kΩ"`) and every quantity is a range;
  comparisons hold only if they hold for every value in the range.
- **Values are stated, facts are derived** (§4.5). A value is chosen by a parameter or literal;
  what it does in the circuit is a fact; an `assert` holds the fact to a bound. A block bound to the
  wrong rail fails an assertion rather than silently changing the BOM.
- **Unknown is not zero** (§9.7). A rail feeding an MCU with no stated draw is a lower bound, and a
  check reports "holds for what is stated". That is a note, not a pass: say what was not stated.
- **Straps:** pins with `role strap` and `require net.rest high|low|not=high` are checked against
  what actually sits on the net (pull-ups, rails, outputs). A push-pull output on the net makes the
  rest level unknown.

## 4. Parts and library blocks

- Look in the library first. List what it offers instead of reading its files:
  ```sh
  python3 <skill>/scripts/stackup_index.py buck      # parts/blocks whose path, name or description match
  ```
  It prints each part's packages, orderable MPN and features (`*` = on by default), and each
  block's parameters with defaults, from the library pinned in `manifest.kdl` (run `stackup check`
  once first so it's in the cache). Library parts carry pin requirements, strap roles and default
  support blocks (decoupling, pulls).
- **Give every placed part an MPN, including the parts inside library blocks,** with `mpn`
  declarations and `match placement` rules (SPEC §6.6; see [bom-and-fab.md](bom-and-fab.md)). A
  board rule reaches a block's children (`tlv62569-buck`'s inductor, capacitors and divider), so
  there's no need to copy blocks into the project or turn off default support blocks to add
  purchasing details. `stackup bom` names every part still without one.
- Turn off a default support block with `{ without <feature> }` only when the board provides that
  function another way, and say which way in a comment.
- `ignore "<fact>" reason="…"` suppresses a specific check. Use it only with a real reason that can
  be checked (e.g. the SK6812MINI-E: library minimum is 3.7 V, the board runs it at 3.3 V, verified
  on hardware). Every `ignore` is a claim someone must be able to audit.
- A project-specific part goes in `parts.kdl`: `part`, `reference`, `symbol`, `value`,
  `description`, pins named as the datasheet names them with their electrical kind, and a `package`
  mapping pins to pads. Verify every pad against the manufacturer's pinout drawing.
- If a part is generally useful, it belongs in the library (upstream PR) rather than the project;
  follow the library README conventions (family files, functional directories, header comment with
  constraints and unverified details).

## 5. Checks and findings

`stackup check` reports everything at once: unmet requirements, failed assertions, conflicting
`set`s (e.g. two names on one net), duplicate I²C addresses, unconnected required pins, connected
`nc` pins, pins used twice, illegal peripheral answers, and loops. Warnings: incomplete links. Notes:
checks that hold only for what is stated.

Stackup checks voltages and rest levels only as far as the facts in the parts go. It does not replace
the DC bias pass in [dc-bias.md](dc-bias.md) or a simulation: it does not know a divider is starving a
gate or that a transient lifts a latch.

## 6. KiCad sync

- Link the board with a `.stackup_sch` file beside the `.kicad_pcb` (same stem). It holds the path to
  the KDL design, relative to the PCB directory.
- Install the plugin: `python3 kicad-plugin/install.py` from a Stackup checkout (`--replace` to
  update, `--cli /path/to/stackup` to pick the CLI). Then **Tools → External Plugins → Refresh**.
- **Sync PCB from stackup** updates footprints, pads and nets and keeps placement and routing.
- **Headless sync** (board closed in KiCad):
  `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 kicad-plugin/sync_headless.py PCB/<board>.kicad_pcb`
  (check the Python path for the installed KiCad version). It refuses to write a board that is open.
- `anchor=host.PIN` (and optional `spot="dx dy rot"`) on a placement records where a decoupling
  cap belongs; the **Place at anchor pad** action uses it.
- CI should fail when syncing would change the committed PCB. Copy
  [../scripts/check_pcb_sync.py](../scripts/check_pcb_sync.py) into the project's `ci/` and run it
  with KiCad's Python. It applies the sync in memory and never saves.

## 7. Gotchas

- `stackup check` downloads the pinned library into `.stackup/cache/` beside the manifest: add
  `.stackup/` to `.gitignore`.
- `stackup update` rewrites the manifest's pinned commit to the library's head. Don't run it just to
  fetch the library; `stackup check` does that without changing the pin.

- KDL values can't start with a digit unless they are numbers: write `"2Hz"`, and prefix part names
  that start with a digit (`nfet-2n7002`).
- The public GitHub `main` and the crates.io release can differ; trust `stackup --help` and the
  SPEC at the pinned version.
- Commit `board.kdl`, `parts.kdl`, `manifest.kdl`, the Cargo lock, and the synced `.kicad_pcb`
  together, so the PCB never drifts from the design.
