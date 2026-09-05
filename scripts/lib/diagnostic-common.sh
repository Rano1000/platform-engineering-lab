#!/bin/sh

# Return the sole canonical basename for a Pod diagnostic. The subshell prevents
# helper state from changing caller variables in POSIX shells without local(1).
diagnostic_artifact_name() (
  diagnostic_name_prefix=$1
  diagnostic_name_kind=$2
  case $diagnostic_name_kind in
    created) diagnostic_name_suffix=created.json ;;
    log) diagnostic_name_suffix=pod.log ;;
    pod) diagnostic_name_suffix=pod.json ;;
    describe) diagnostic_name_suffix=describe.txt ;;
    events) diagnostic_name_suffix=events.json ;;
    cleanup) diagnostic_name_suffix=cleanup.json ;;
    *) printf 'Unknown diagnostic artifact kind: %s\n' "$diagnostic_name_kind" >&2; exit 1 ;;
  esac
  case $diagnostic_name_prefix in
    '') printf '%s\n' "$diagnostic_name_suffix" ;;
    *[!A-Za-z0-9._+-]*) printf 'Unsafe diagnostic artifact prefix: %s\n' "$diagnostic_name_prefix" >&2; exit 1 ;;
    *) printf '%s.%s\n' "$diagnostic_name_prefix" "$diagnostic_name_suffix" ;;
  esac
)
