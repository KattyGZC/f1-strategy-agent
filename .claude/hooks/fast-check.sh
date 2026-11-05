#!/usr/bin/env bash
# Runs `make fast-check` for Claude Code. Exit 2 blocks the commit or the stop and hands the
# output back to the agent. A stop already blocked once is let through with a message to the
# user instead, so a check the agent cannot fix does not loop forever.
set -u
event="$1"
input="$(cat)"
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

if [ "$event" = "commit" ] && ! printf '%s' "$input" | grep -qE 'git( -[cC] [^ ]+)* commit'; then
  exit 0
fi

if [ "$event" = "stop" ] && [ -z "$(git status --porcelain -- backend frontend Makefile)" ]; then
  exit 0
fi

if output="$(make fast-check 2>&1)"; then
  exit 0
fi

if [ "$event" = "stop" ] && printf '%s' "$input" | grep -qE '"stop_hook_active": ?true'; then
  echo '{"systemMessage": "make fast-check still fails; the agent stopped without fixing it."}'
  exit 0
fi

printf 'make fast-check failed:\n%s\n' "$(printf '%s\n' "$output" | tail -n 40)" >&2
exit 2
