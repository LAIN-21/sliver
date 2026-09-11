#!/bin/sh
# Host checks for Sliver local development. POSIX sh.

failed=0

pass() {
	printf 'PASS %s\n' "$1"
}

fail() {
	printf 'FAIL %s\n' "$1"
	failed=1
}

if command -v git >/dev/null 2>&1; then
	pass git
else
	fail git
fi

if command -v make >/dev/null 2>&1; then
	pass make
else
	fail make
fi

if command -v docker >/dev/null 2>&1; then
	pass docker
else
	fail docker
fi

if docker info >/dev/null 2>&1; then
	pass "docker daemon"
else
	fail "docker daemon"
fi

if docker compose version >/dev/null 2>&1; then
	pass "docker compose"
else
	fail "docker compose"
fi

if docker compose up --help 2>/dev/null | grep -q -- '--wait'; then
	pass "docker compose up --wait"
else
	fail "docker compose up --wait"
fi

exit "$failed"
