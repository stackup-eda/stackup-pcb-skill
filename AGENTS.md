# pcbskill — Agent Notes

This repo holds the `pcb-design` agent skill (`skills/pcb-design/`), in the Agent Skills
(`SKILL.md`) format so it works in any harness that supports it: Claude Code, Codex, Gemini CLI
and others. `CLAUDE.md` and `GEMINI.md` just import this file; edit this one.

- Keep the skill **generic**. No project names, designators, or repo-specific history in
  `SKILL.md`, `references/` or `scripts/`. A lesson from a specific board goes in as a general
  failure pattern with the check that catches it (`references/failure-patterns.md`).
- Keep `SKILL.md` short (workflow and core rules); detail goes in `references/`, linked from SKILL.md
  with a note on when to read it.
- Scripts use only the Python standard library, so they run anywhere KiCad's Python or a system
  Python runs.
- New script logic gets unit tests in `tests/`. Run `python3 -m unittest discover -s tests -v`
  before opening a PR. Network lookups are tested with fixtures, not live calls.
- Keep documented examples runnable: `tests/test_docs.py` checks the Stackup example in
  `references/stackup.md` with the real CLI. Change the example and the test together.
- Test prompts for evaluating the skill live in `evals/evals.json`; results go in the gitignored
  `pcb-design-workspace/`.
- Keep the skill **harness-neutral**. No harness-specific tool names (say "a web search tool", not a
  product's tool name), no instructions that assume one agent. Harness-specific packaging (e.g.
  `.claude-plugin/`) lives outside `skills/`.
- The frontmatter follows the Agent Skills spec: `name` matches the directory, `description` stays
  under 1024 characters.
