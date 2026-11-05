#!/usr/bin/env sh
# Mutation testing of the domain (ADR 0010). mutmut needs fork(), so it runs on Linux in a
# throwaway container, on every host the same way. The zone is not UTC, so a conversion to the
# local zone instead of UTC shows. Fails when a mutant survives; one that hangs a test (timeout)
# was caught.
#
# The container runs detached and is polled: Docker Desktop on Windows drops a long attached
# stream ("error waiting for container: unexpected EOF") while the container keeps running.
set -eu

backend="$1"
image="ghcr.io/astral-sh/uv:0.13.5-python3.12-trixie-slim"
name="f1-mutation-$$"
export MSYS_NO_PATHCONV=1

steps='mkdir /work
tar -C /source --exclude=.venv --exclude=mutants --exclude=__pycache__ -cf - . | tar -C /work -xf -
cd /work
uv sync --locked --quiet
uv run mutmut run
uv run mutmut results | tee results.txt
! grep -qE ": (survived|suspicious|no tests|segfault)$" results.txt'

trap 'docker rm --force "$name" >/dev/null 2>&1 || true' EXIT
docker run --detach --name "$name" --env TZ=EST5 --volume "$backend:/source:ro" "$image" \
  sh -ec "$steps" >/dev/null
while [ "$(docker inspect --format '{{.State.Running}}' "$name")" = "true" ]; do
  sleep 5
done
# mutmut redraws one progress line per mutant; only the last one, the totals, is kept.
docker logs "$name" 2>&1 | tr '\r' '\n' \
  | awk '/[0-9]+\/[0-9]+  / { progress = $0; next } { print } END { print progress }'
exit "$(docker inspect --format '{{.State.ExitCode}}' "$name")"
