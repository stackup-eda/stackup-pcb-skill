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

Pin the CLI with a tiny Cargo project so the version is locked:

```toml
# ci/stackup/Cargo.toml
[package]
name = "<project>-stackup-check"
version = "0.0.0"
edition = "2024"
publish = false

[dependencies]
stackup = { package = "stackup-eda", version = "=0.1.3" }
```

```rust
// ci/stackup/src/main.rs
fn main() {
    stackup::cli::run();
}
```

Run it with `cargo run --locked --manifest-path ci/stackup/Cargo.toml -- check PCB/stackup/board.kdl --locked`.
For daily use, `cargo install stackup-eda` (or `cargo install --path crates/stackup` from a
checkout) puts `stackup` on `PATH`. Check that the installed version matches the pin.

## 2. CLI

Run `stackup --help` for the pinned version's exact set. `check`, `bom` and `netlist` are known to
work at 0.1.3; `pin`, `import` and `check --symbols` come from the library README and may not exist
in every version. The main commands:

| Command | Purpose |
|---|---|
| `stackup check <board.kdl> [--locked]` | Elaborate and report every finding at once |
| `stackup tree <board.kdl>` | Instances and nets, for reading |
| `stackup netlist <board.kdl> [-o file]` | KiCad netlist (the plugin calls this) |
| `stackup bom <board.kdl> --locked [-o file.csv]` | Purchasing BOM with manufacturer, MPN and distributor columns |
| `stackup update [@lib]` | Move a library pin to its current head |
| `stackup pin @lib` / `stackup pin --check` | Pin to a pushed local checkout / verify the pin |
| `stackup import Lib:SYMBOL` | Generate a pin table from a KiCad symbol (verify it against the datasheet) |
| `stackup check --symbols` | Compare parts with KiCad symbols and footprints |

`--design NAME` selects one design when a file has several.

## 3. Writing a design

```kdl
use "@stackup/passives"
use "@stackup/power/buck/tlv62569"
use "./parts.kdl"

design my_board {
    stock { packages imperial="0402" }   // default package for generic passives

    place tlv62569 "U_BUCK1" designator="U_BUCK1" manufacturer="Texas Instruments" \
        mpn="TLV62569DBVR" lcsc="C141836" value="TLV62569DBVR"
    place pull-down "R_EN_PD1" value="100kΩ" manufacturer="UNI-ROYAL(Uniroyal Elec)" \
        mpn="0402WGF1003TCE" lcsc="C25741"
    place capacitor "C_OUT1" value="22µF" footprint="Capacitor_SMD:C_0805_2012Metric"

    circuit "Q_PWR1.DRAIN" "R_EN_PD1.node" "U_BUCK1.EN" name="PWR_EN"
    set "C_OUT1.A" net.voltage "3.3V"
    nc "U_MCU1.IO45"
}
```

Key ideas (SPEC sections in brackets):

- **Order carries no meaning.** Every statement is a fact about the circuit.
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

- Look in the library first (`connector/`, `discrete/`, `micro/`, `power/`, `sensor/`, …). Library
  parts carry pin requirements, strap roles and default support blocks (decoupling, pulls).
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

- KDL values can't start with a digit unless they are numbers: write `"2Hz"`, and prefix part names
  that start with a digit (`nfet-2n7002`).
- The public GitHub `main` and the crates.io release can differ; trust `stackup --help` and the
  SPEC at the pinned version.
- Commit `board.kdl`, `parts.kdl`, `manifest.kdl`, the Cargo lock, and the synced `.kicad_pcb`
  together, so the PCB never drifts from the design.
