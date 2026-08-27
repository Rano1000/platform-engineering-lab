#!/bin/sh
set -eu

GH_VERSION=2.98.0
GH_ARCHIVE=gh_${GH_VERSION}_linux_amd64.tar.gz
GH_ARCHIVE_SHA256=3b8ac6b30336802fc1a858d7c084e11cdf24ac1a761ca90b68022d7d729208de
GH_URL=https://github.com/cli/cli/releases/download/v${GH_VERSION}/${GH_ARCHIVE}

destination=${1:-}
[ -n "$destination" ] || { printf 'usage: %s DESTINATION\n' "$0" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { printf '%s\n' 'ERROR curl is required.' >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { printf '%s\n' 'ERROR sha256sum is required.' >&2; exit 1; }
command -v tar >/dev/null 2>&1 || { printf '%s\n' 'ERROR tar is required.' >&2; exit 1; }

mkdir -p "$destination"
archive=$destination/$GH_ARCHIVE
curl --fail --location --silent --show-error --output "$archive" "$GH_URL"
printf '%s  %s\n' "$GH_ARCHIVE_SHA256" "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$destination"
printf '%s\n' "$destination/gh_${GH_VERSION}_linux_amd64/bin/gh"
