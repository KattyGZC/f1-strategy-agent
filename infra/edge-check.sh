#!/usr/bin/env sh
# Checks the edge of a running stack against ADR 0016 and ADR 0017: request ids, error shape,
# limits and security headers, through nginx. The bursts run last, since each leaves the address
# throttled for a moment; the simulator's runs first, too small to reach the API's zone.
set -eu

base="$1"
logs="$2"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failures=0
client_id="client-chosen-$$-$(date +%s)"

fail() {
  echo "FAIL: $1"
  failures=$((failures + 1))
}

# Writes the headers to $work/headers and the body to $work/body; prints the status.
fetch() {
  curl --silent --output "$work/body" --dump-header "$work/headers" --write-out '%{http_code}' "$@"
}

header() {
  grep -i "^$1:" "$work/headers" | cut -d' ' -f2- | tr -d '\r'
}

expect_status() {
  [ "$1" = "$2" ] || fail "$3: status $1, expected $2"
}

expect_request_id() {
  ids="$(grep -ci '^x-request-id:' "$work/headers" || true)"
  [ "$ids" = "1" ] || fail "$1: $ids X-Request-ID headers, expected 1"
  header x-request-id | grep -qE '^[0-9a-f]{32}$' || fail "$1: X-Request-ID is not nginx's id"
}

expect_error_body() {
  id="$(header x-request-id)"
  body="$(cat "$work/body")"
  header content-type | grep -q '^application/json' || fail "$2: body is not JSON"
  echo "$body" | grep -q "\"code\":\"$1\"" || fail "$2: code is not $1 in $body"
  echo "$body" | grep -q "\"request_id\":\"$id\"" || fail "$2: request_id is not the header's id"
}

expect_security_headers() {
  for name in Content-Security-Policy X-Content-Type-Options Referrer-Policy X-Frame-Options \
    Cross-Origin-Opener-Policy Permissions-Policy; do
    [ -n "$(header "$name")" ] || fail "$1: no $name header"
  done
  [ "$(header content-security-policy)" = "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" ] \
    || fail "$1: Content-Security-Policy is $(header content-security-policy)"
  header server | grep -q '[0-9]' && fail "$1: Server header shows the version $(header server)"
  return 0
}

status="$(fetch --header "X-Request-ID: $client_id" "$base/api/health")"
expect_status "$status" 200 "health"
expect_request_id "health"
expect_security_headers "health"
health_id="$(header x-request-id)"
sleep 1
eval "$logs" | grep -q "\"request_id\": *\"$health_id\"" \
  || fail "health: the backend did not log nginx's id $health_id"
eval "$logs" | grep -q "$client_id" && fail "health: the client's id reached the backend"

status="$(fetch "$base/")"
expect_status "$status" 200 "screen"
expect_request_id "screen"
expect_security_headers "screen"

status="$(fetch "$base/api/no-such-route")"
expect_status "$status" 404 "unknown route"
expect_request_id "unknown route"
expect_error_body route_not_found "unknown route"

head -c 9000 /dev/zero | tr '\0' 'a' >"$work/large"
status="$(fetch --header 'Content-Type: application/json' --data-binary "@$work/large" \
  "$base/api/replays")"
expect_status "$status" 413 "large body"
expect_request_id "large body"
expect_error_body payload_too_large "large body"
expect_security_headers "large body"

# Sends $3 requests to $2 at once, with the body $4 when there is one, and checks the first
# that was rate limited; $1 names the burst.
burst() {
  rm -f "$work"/burst*
  i=0
  while [ "$i" -lt "$3" ]; do
    [ "$i" -eq 0 ] || echo next >>"$work/burst"
    printf 'url = "%s%s"\noutput = "burst-%s"\ndump-header = "burst-%s.headers"\n' \
      "$base" "$2" "$i" "$i" >>"$work/burst"
    printf 'silent\nwrite-out = "%%{http_code} %%{filename_effective}\\n"\n' >>"$work/burst"
    if [ -n "${4:-}" ]; then
      printf 'header = "Content-Type: application/json"\ndata = "%s"\n' "$4" >>"$work/burst"
    fi
    i=$((i + 1))
  done
  # Relative outputs, run from $work: a Windows curl does not map a POSIX path inside a config
  # file.
  (cd "$work" && curl --parallel --parallel-max 50 --config burst >statuses)
  limited="$(grep '^429 ' "$work/statuses" | head -n 1 | cut -d' ' -f2)"
  if [ -z "$limited" ]; then
    fail "$1: no request was rate limited"
  else
    cp "$work/$limited" "$work/body"
    cp "$work/$limited.headers" "$work/headers"
    expect_request_id "$1"
    expect_error_body rate_limited "$1"
    expect_security_headers "$1"
  fi
}

# Escaped for a curl config file; any body will do, since nginx limits before the API reads it.
simulation='{\"session_key\": 1, \"strategies\": []}'
burst "simulations burst" /api/simulations 20 "$simulation"
sleep 1
burst "api burst" /api/health 150

if [ "$failures" -gt 0 ]; then
  echo "$failures edge checks failed"
  exit 1
fi
echo "edge checks passed"
