# Evals

`evals.json` holds the test prompts for the `pcb-design` skill: each has a prompt, the fixture
files it needs, a description of a good result, and pass/fail assertions for grading.

| id | name | what it tests | fixture |
|---|---|---|---|
| 1 | soft-power-latch-design | a new circuit end to end | none |
| 2 | latch-fet-swap | a part change with a threshold problem | `files/latch/` |
| 3 | pre-fab-checklist | the board-to-fab checklist | none |
| 4 | review-latch | a design review with three planted bugs, two invisible to `stackup check` | `files/review-latch/` |
| 5 | pin-assign | MCU pin restrictions on an octal-PSRAM module (passes `stackup check` even when wrong) | `files/pin-assign/` |
| 6 | analyzer-claims | re-deriving outside findings: one true claim, two false | `files/analyzer-claims/` |
| 7 | footprint-check | footprint geometry vs package drawings: two wrong, two right | `files/footprint-check/` |
| 8 | bom-export | BOM completeness, including gaps the checker can't see | `files/bom-export/` |
| 9 | quick-question | the effort level for a question: short answer, no files | none |
| 10 | part-substitute | a stock-driven part swap at the part-change level | `files/latch/` |

## Planted bugs (the answer key)

- **review-latch:** the buck EN has no pull-down (`stackup check` reports it); R_BTN_PU1 pulls
  the IO2 button sense up to VSYS (up to 4.5 V); R_LATCH_G1 is 10 kΩ, so a press leaves the
  latch gate at roughly 0.24-0.37 V against the AO3400A's 0.65 V minimum threshold.
- **pin-assign:** the module is an N16R8, so GPIO35-37 belong to octal PSRAM. `stackup check`
  accepts a button wired to IO35.
- **analyzer-claims:** E1 is false (R_PWR_EN_PD1 exists); E2 is true (pull-up to VSYS on IO2;
  the real idle level is VSYS, not 4.6 V); W1 is false (the real diode drop at µA is ~0.3 V, so
  the gate reaches ~2.44 V at 3.0 V, and the FET is an AO3400A with a 1.45 V maximum threshold).
- **footprint-check:** D1 is an SK6812MINI-E on a 5 × 5 mm PLCC4 footprint; D2 is a BAT54W-7-F
  (SOT-323) on a 2-pad SOD-123 footprint. Q1 and R1 are correct.
- **bom-export:** `bom_check.py` finds R1's missing LCSC, C1's missing part and Q1's comma. It
  can't see that D1's library-default MPN (BAT54W-7-F, SOT-323) disagrees with its SOD-123
  footprint, or that J1's value doesn't say right-angle. The circuit itself is meant to be sound:
  R1 pulls the buck's EN up to VBAT (always on), and VBAT_SENSE goes to a divider on another sheet.

Each case also has depth checks that a found-the-bug check can't separate: datasheet numbers taken
from documents the run actually opened, side effects of the fixes, XBee3 SPI-mode enabling, the
reverse-mount LED's mirrored pad numbering, tier and stock, and not rejecting a correct alternative
fix without evidence (the pull-up to 3V3 in analyzer-claims is safe with R_INV_BASE1 at 100 kΩ).

Fixture fixes after the first run of these cases (2026-09-29): the pin-assign LED circuit no longer
names the 3V3 rail, and bom-export's buck EN is pulled up instead of held off by an MCU it powers.

The fixtures are checked by `tests/test_eval_fixtures.py`, so a library or CLI change that moves
a planted bug fails a test instead of silently changing an eval.

## Running a case

Give each run a fresh outputs folder and this preamble (fill in the paths), with the skill line
only for the with-skill configuration:

```
You are running one test case for a skill evaluation.
[Skill to use: read <repo>/skills/pcb-design/SKILL.md first and follow it.]
Task (from the user): "<prompt>"
[The user's design: copy <fixture files> into outputs/design/ and work on that copy.]
Environment: Stackup CLI 0.1.3 at ~/.cargo/bin/stackup; KiCad with libngspice; network access.
Rules:
- Write every file ONLY inside <outputs>/. Put temporary files in <outputs>/scratch/. Do not use
  /tmp, the system temp directory, or any other scratch location, and never edit the fixtures.
- Do not read other repositories except the skill directory and the fixture.
- Do not ask questions; state your assumptions.
- Save your reply to the user as <outputs>/response.md.
```

Grade each run against the case's `assertions`, re-running `stackup check` and
`bom_check.py` on any design a run produced rather than trusting its report. Results go in the
gitignored `pcb-design-workspace/`.
