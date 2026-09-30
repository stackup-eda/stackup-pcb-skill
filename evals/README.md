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
  (SOT-323) on a 2-pad SOD-123 footprint. Q1 and R1 are correct. Every footprint carries MF and
  Manufacturer_Part_Number fields. KiCad's `LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount` has a
  3.4 × 3.0 mm Edge.Cuts cutout 0.35 mm from the pads along its sides; its 0.5 mm corner-relief
  arcs bring it to about 0.25 mm from pads 2 and 4 (`footprint_geometry.py` reports 0.248 mm).
- **bom-export:** `bom_check.py` finds R1's missing LCSC, C1's missing part and Q1's comma
  (`stackup bom` at the pinned commit also reports C1's missing MPN and exits 1). It
  can't see that D1's library-default MPN (BAT54W-7-F, SOT-323) disagrees with its SOD-123
  footprint, or that J1's value doesn't say right-angle. The circuit itself is meant to be sound:
  R1 pulls the buck's EN up to VBAT (always on), VBAT_SENSE goes to a divider on another sheet,
  and the buck's SW and FB leave as named nets for the inductor and divider on the buck sheet.

Each case also has depth checks that a found-the-bug check can't separate: datasheet numbers taken
from documents the run actually opened, side effects of the fixes, XBee3 SPI-mode enabling, the
reverse-mount LED's mirrored pad numbering, tier and stock, and not rejecting a correct alternative
fix without evidence (the pull-up to 3V3 in analyzer-claims is safe with R_INV_BASE1 at 100 kΩ).

Fixture fixes after the first run of these cases (2026-09-29): the pin-assign LED circuit no longer
names the 3V3 rail, and bom-export's buck EN is pulled up instead of held off by an MCU it powers.

After the second run (2026-09-30): the buck's SW and FB are named nets to the buck sheet instead of
`nc` (bom-export, review-latch, analyzer-claims), and review-latch and analyzer-claims give the
ESP32-S3 block's own support parts MPNs, so `stackup bom` runs clean on them. Assertions changed:
case 1's threshold check covers a design where the buck EN is the latch, case 2 splits PCB sync
from the simulation rerun, case 7 states the cutout gap and adds reading the footprints' fields,
case 9 allows fetched datasheets, and case 10 is graded from the transcript.

The fixtures are checked by `tests/test_eval_fixtures.py`, so a library or CLI change that moves
a planted bug fails a test instead of silently changing an eval.

## Running a case

Each case runs twice: once with the skill and once without it as a baseline. The baseline only
means something if nothing about the skill, this repo or the answer key reaches it, and in a
normal agent session a lot does: user instructions (a global CLAUDE.md or AGENTS.md), memory,
installed skills and plugins (including hardware-related ones), and the repo itself if the run can
see it. So every run gets its own clean session and its own directory outside the repo.

### Isolation

- **A clean session per run.** In Claude Code, run each case as a separate headless session with
  customizations off, and don't use subagents from a working session (they inherit its context):

  ```sh
  cd <case dir> && TMPDIR=<case dir>/scratch claude -p --safe-mode --model <model> \
    --no-session-persistence --strict-mcp-config --disable-slash-commands \
    --allowedTools "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch" \
    --disallowedTools "Agent" --settings <deny-rules.json> \
    --output-format stream-json --verbose < <prompt file> > <logs>/<config>-case-NN.jsonl
  ```

  `--safe-mode` turns off CLAUDE.md, memory, skills, plugins, hooks and MCP servers (an AGENTS.md or
  CLAUDE.md in the case folder or a parent is not loaded either). Disallow the Agent tool so the
  whole run stays in one transcript. Pass the prompt on stdin, not as an argument: an argument is
  visible to every other process through `ps`. Set `TMPDIR` to the case's scratch folder, since
  scripts such as `ngspice_harness.py` otherwise write to the shared system temp directory. Other
  harnesses need the equivalent: no user instructions, memory, skills or plugins. Before the first
  real run, start one session with the same flags and ask it to list its skills, plugins, MCP tools
  and any instructions or memory in its context; all should be empty.
- **Baselines first, then the skill, never both at once.** Run every baseline case to completion
  before creating the with-skill root. Then no baseline can see the skill snapshot, a with-skill
  run's command line or its temp files, whatever the deny rules miss. Runs within one
  configuration can go in parallel.
- **Neutral directories outside the repo.** Use two roots whose paths say nothing about skills or
  evaluations (e.g. `~/work-a/` for the baseline and `~/work-b/` for with-skill), one folder per
  case inside each, with new names for every iteration. Copy the fixture files into each case's
  `design/` before the run, so the prompt never names a path in this repo. Put a snapshot of
  `skills/pcb-design/` (without `__pycache__`) only in the with-skill root. Nothing else from the
  repo goes in either root, above all not this README. Keep prompts, settings and transcripts in a
  third directory. After the results are copied into the workspace, delete the roots, the logs
  directory and the agent's per-directory session folders (for Claude Code, `~/.claude/projects/`
  entries named after the case paths), so nothing from one iteration survives into the next.
- **Deny rules** (the `--settings` file), for both the Read tool and Bash: this repo, the user's
  agent config directory (`~/.claude`), the other configuration's root and the logs directory. Under
  `--safe-mode` these still apply. Write Bash patterns against specific paths, not common words: a
  `Bash(*repos*)` rule also blocked a run's call to GitHub's `api.github.com/repos/...`. Add a Bash
  rule on this repo's GitHub owner and name, so `curl` can't fetch it. Bash deny rules match the
  command text, so they are a guard, not a sandbox; the audit below is what proves isolation.
- **This repo is public.** A baseline's web search for Stackup or KDL help could find `SKILL.md`
  or this README's answer key. A WebFetch rule can only block a whole domain, and the Stackup
  library itself is fetched from GitHub, so no rule covers it; the audit has to.
- **Same model and settings for both configurations**, and a newer CLI if the one on the path
  doesn't support the model.

### Prompt

Both configurations get the same prompt; the with-skill one adds only the first line. Nothing in
the baseline prompt mentions a skill, a test or an evaluation.

```
[Skill to use: read <skill snapshot>/SKILL.md first and follow it. Its references/ and scripts/ are beside it.]
Task (from the user): "<prompt>"
[The user's design is in <case dir>/design/; work on it there.]
Environment: Stackup CLI 0.2.0 at ~/.cargo/bin/stackup; KiCad with its bundled libngspice; network access.
Rules:
- Write every file only inside <case dir>/. Put temporary files in <case dir>/scratch/. Do not use
  /tmp, the system temp directory, or any other location.
- Do not read files outside <case dir>/ [and the skill directory <skill snapshot>/], other than
  installed tools and their libraries (KiCad, Stackup, Python).
- Do not ask questions; state your assumptions.
- Save your reply to the user as <case dir>/response.md.
```

### Audit, then grade

Before grading, check every transcript:

- **The session's first record** (`"subtype": "init"`): empty `skills` and `mcp_servers`, and
  only the harness's built-in plugins. Check this for every run, not just the first probe.
- **Every tool call:** any path outside the run's own case folder (and the skill snapshot, for
  with-skill runs), any listing of the home directory or the other root, any process listing, and
  any permission denial.
- **Every web search and fetch, and its result:** any hit on this repo's GitHub URL.
- **Every baseline tool result:** the skill's name, this repo's name, `SKILL.md`, `evals.json` or
  the other root.

A run that saw any of these is contaminated; rerun it. Tool paths inside the agent's own session
folder (large outputs it saved for itself) are expected.

Grade each run against the case's `assertions`, re-running `stackup check` and `bom_check.py` on
any design a run produced rather than trusting its report. Grade tool-call counts (case 9) and
lookup batching (case 10) from the run's transcript; the outputs folder doesn't show them. Copy
each run's outputs, prompt and transcript into the next unused `iteration-N/` in the gitignored
`pcb-design-workspace/` (list the folder first and never write into an existing iteration),
with a `grading.json` (each assertion, pass or fail, and the evidence) beside them and the score
table in `benchmark.md`.
