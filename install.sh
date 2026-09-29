#!/bin/sh
# Link the pcb-design skill into one or more agent harnesses' personal skills directories.
#
#   ./install.sh                 # Claude Code + the shared ~/.agents/skills (Codex, Gemini CLI)
#   ./install.sh claude codex    # just these
#
# Codex and Gemini CLI both read ~/.agents/skills, so the default covers them; linking the same
# skill into their own directories as well may make it appear twice.
#
# A symlink keeps the installed skill in sync with this checkout. An existing directory
# (not a link) at the target is left alone and reported.
set -eu

SKILL_DIR="$(cd "$(dirname "$0")" && pwd)/skills/pcb-design"

target_for() {
    case "$1" in
        claude) echo "$HOME/.claude/skills" ;;   # Claude Code
        codex)  echo "$HOME/.codex/skills" ;;    # OpenAI Codex CLI
        gemini) echo "$HOME/.gemini/skills" ;;   # Gemini CLI
        agents) echo "$HOME/.agents/skills" ;;   # shared location read by Codex and Gemini CLI
        *) return 1 ;;
    esac
}

[ "$#" -gt 0 ] || set -- claude agents

status=0
for harness in "$@"; do
    if ! dir="$(target_for "$harness")"; then
        echo "unknown harness: $harness (use claude, codex, gemini or agents)" >&2
        status=1
        continue
    fi
    link="$dir/pcb-design"
    mkdir -p "$dir"
    if [ -L "$link" ]; then
        ln -sfn "$SKILL_DIR" "$link"
        echo "updated  $link"
    elif [ -e "$link" ]; then
        echo "skipped  $link (exists and is not a symlink)" >&2
        status=1
    else
        ln -s "$SKILL_DIR" "$link"
        echo "linked   $link"
    fi
done
exit "$status"
