# pcb-design skill

An agent skill for designing and validating printed circuit boards. It uses the open
[Agent Skills](https://agentskills.io) `SKILL.md` format, so it works in Claude Code, OpenAI Codex,
Gemini CLI and any other harness that supports skills (and, with one extra line, in those that
don't).

What it covers:

- **Stackup** ([stackup-eda/stackup](https://github.com/stackup-eda/stackup)) KDL as the electrical
  source of truth, checked with `stackup check`, instead of KiCad schematics
- **KiCad** for layout, routing, DRC and fab output, synced from Stackup
- **DC bias checks** across the full supply range against worst-case datasheet limits
- **SPICE** (ngspice through KiCad's bundled libngspice) for power, latch, sense and enable circuits
- **Common parts first**: JLCPCB Basic, then Preferred Extended, then Extended, with stock checks at
  JLCPCB/LCSC, Mouser, DigiKey and Adafruit
- **MCU pin restrictions** (flash, strapping, input-only, dedicated pins) checked before assignment
- **Unambiguous BOMs** so a fab can buy exactly the right part

## Layout

```
skills/pcb-design/
  SKILL.md                     workflow and core rules (loaded when the skill triggers)
  references/                  read on demand: stackup, dc-bias, spice, parts-sourcing,
                               mcu-pins, bom-and-fab, kicad, failure-patterns
  scripts/
    stackup_index.py           list the Stackup library's parts and blocks
    datasheet.py               fetch a datasheet once; read tables as text, render only drawings
    jlc_parts.py               JLCPCB part lookup: LCSC number, tier, stock
    spice_template.py          copy-and-edit SPICE checks for a power latch (insertion/press/shutdown)
    spice_lib.py               generic models, stimulus, measurements and a corner-matrix runner
    ngspice_harness.py         run ngspice from Python via ctypes
    bom_check.py               check a `stackup bom` export for blank or ambiguous lines
    footprint_geometry.py      measure a footprint (library or on the board) to compare with
                               the part's package drawing
    check_pcb_sync.py          CI check that the KiCad PCB matches the Stackup design
tests/                         unit tests for the scripts
evals/evals.json               test prompts for evaluating the skill
install.sh                     links the skill into each harness's skills directory
AGENTS.md                      notes for agents working on this repo (CLAUDE.md, GEMINI.md import it)
.claude-plugin/plugin.json     optional: install the repo as a Claude Code plugin
```

## Install

Run the install script from a checkout; it symlinks the skill so updates to the checkout apply
everywhere:

```sh
./install.sh                  # Claude Code + ~/.agents/skills (read by Codex and Gemini CLI)
./install.sh codex gemini     # or pick harnesses: claude, codex, gemini, agents
```

| Harness | Personal skills directory | Notes |
|---|---|---|
| Claude Code | `~/.claude/skills/` | Or install the repo as a plugin via `.claude-plugin/plugin.json` |
| OpenAI Codex CLI | `~/.codex/skills/` or `~/.agents/skills/` | Invoke explicitly with `$pcb-design` if needed |
| Gemini CLI | `~/.gemini/skills/` or `~/.agents/skills/` | |
| Other Agent Skills harnesses | their skills directory | Copy or link `skills/pcb-design/` |

Codex and Gemini CLI both read `~/.agents/skills/`, so linking into their own directory as well may
make the skill appear twice. For a single project, link it into that repo's `.claude/skills/`,
`.codex/skills/`, `.gemini/skills/` or `.agents/skills/` instead.

**Harnesses without skill support:** add a line like this to the global or project instruction file
the harness reads (`AGENTS.md`, `GEMINI.md`, `.cursorrules`, and so on):

```markdown
For any PCB or electronics hardware work, first read ~/repos/pcbskill/skills/pcb-design/SKILL.md and
follow it, reading its references/ and using its scripts/ as it directs.
```

## Develop

```sh
python3 -m unittest discover -s tests -v
python3 skills/pcb-design/scripts/ngspice_harness.py --selftest
```

The simulation tests run against KiCad's libngspice, the PDF tests against poppler, and the
documentation test (the Stackup example in `references/stackup.md`) against the `stackup` CLI; each
is skipped when its tool isn't installed. Network lookups (`jlc_parts.py`, `datasheet.py fetch`) are
tested with fixtures.
