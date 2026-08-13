#!/bin/sh
set -u

PASS_COUNT=0
WARN_COUNT=0
FAIL_COUNT=0

pass() { PASS_COUNT=$((PASS_COUNT + 1)); printf 'PASS  %s\n' "$*"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); printf 'WARN  %s\n' "$*"; }
fail() { FAIL_COUNT=$((FAIL_COUNT + 1)); printf 'FAIL  %s\n' "$*"; }

version_at_least() {
  awk -v actual="$1" -v minimum="$2" 'BEGIN {
    split(actual, a, "."); split(minimum, m, ".")
    for (i = 1; i <= 3; i++) {
      if ((a[i] + 0) > (m[i] + 0)) exit 0
      if ((a[i] + 0) < (m[i] + 0)) exit 1
    }
    exit 0
  }'
}

command_version() {
  name=$1
  minimum=$2
  shift 2
  if command -v "$name" >/dev/null 2>&1; then
    output=$("$@" 2>&1 | sed -n '1p')
    detected=$(printf '%s\n' "$output" | grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' | sed -n '1p')
    if [ -z "$detected" ]; then
      warn "$name is installed but its version could not be parsed (minimum: $minimum): $output"
    elif version_at_least "$detected" "$minimum"; then
      case "$output" in
        *alpha*|*beta*|*rc*) warn "$name $detected meets the numeric floor but is a prerelease build. Use a stable release for later phases: $output" ;;
        *) pass "$name $detected meets the recommended minimum $minimum." ;;
      esac
    else
      fail "$name $detected is below the recommended minimum $minimum. Upgrade using the official $name documentation."
    fi
  else
    fail "$name is not installed. Install $name >= $minimum using its official documentation."
  fi
}

printf '%s\n' 'Platform Engineering Lab environment doctor' 'Read-only: no software, configuration, or cluster resources will be changed.' ''

command_version git 2.30 git --version
command_version make 4.0 make --version
command_version docker 24.0 docker --version
command_version kubectl 1.30 kubectl version --client=true
command_version kind 0.23 kind version
command_version helm 3.14 helm version --short
command_version terraform 1.7 terraform version

if command -v ansible >/dev/null 2>&1; then
  detected=''
  if command -v python3 >/dev/null 2>&1; then
    detected=$(PYTHONDONTWRITEBYTECODE=1 python3 -c 'import importlib.metadata; print(importlib.metadata.version("ansible-core"))' 2>/dev/null || true)
  fi
  if [ -z "$detected" ] && command -v dpkg-query >/dev/null 2>&1; then
    detected=$(dpkg-query -W -f='${Version}' ansible-core 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' | sed -n '1p')
  fi
  if [ -n "$detected" ] && version_at_least "$detected" 2.16; then
    pass "ansible $detected meets the recommended minimum 2.16."
  elif [ -n "$detected" ]; then
    fail "ansible $detected is below the recommended minimum 2.16. Upgrade ansible-core."
  else
    warn "ansible exists but its version could not be read. Set ANSIBLE_LOCAL_TEMP to a writable private directory."
  fi
else
  fail 'ansible is not installed. Install ansible-core >= 2.16 using its official documentation.'
fi

if command -v awk >/dev/null 2>&1 && [ -r /proc/meminfo ]; then
  memory_kib=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
  memory_gib=$(awk -v kib="$memory_kib" 'BEGIN {printf "%.1f", kib / 1048576}')
  if [ "$memory_kib" -ge 8388608 ]; then
    pass "available host memory is suitable for later phases: ${memory_gib} GiB total"
  elif [ "$memory_kib" -ge 6291456 ]; then
    warn "host memory is ${memory_gib} GiB. Use lightweight profiles; 8 GiB or more is recommended."
  else
    fail "host memory is ${memory_gib} GiB. At least 6 GiB is required for the planned local platform."
  fi
else
  warn 'host memory could not be measured. Verify at least 8 GiB before Phase 1.'
fi

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    pass 'Docker daemon is reachable.'
  else
    warn 'Docker CLI is installed but the daemon is unreachable. Start Docker and verify access with: docker info'
  fi
fi

if command -v kubectl >/dev/null 2>&1; then
  context=$(kubectl config current-context 2>/dev/null || true)
  if [ -n "$context" ]; then
    pass "Kubernetes context is configured: $context"
    if kubectl --request-timeout=5s get --raw=/readyz >/dev/null 2>&1; then
      pass 'Kubernetes API is reachable and ready.'
    else
      warn "Kubernetes context '$context' is not reachable. Start the intended cluster or select a valid context; Phase 0 will not change it."
    fi
  else
    warn 'No Kubernetes context is configured. This is acceptable until Phase 1.'
  fi
fi

printf '\nSummary: %s PASS, %s WARN, %s FAIL\n' "$PASS_COUNT" "$WARN_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
