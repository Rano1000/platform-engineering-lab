# ADR-0022: Prove and guard kindnet policy recovery

## Status

Accepted.

## Decision

Treat kindnet Pod readiness as necessary but insufficient. Application network tests first run bounded functional allow-and-deny checks from both workers. A separate `make kindnet-policy-recover` operation may sequentially replace only the three verified kindnet Pods after confirmation bound to the DaemonSet UID and original Pod UIDs.

The recovery never restarts nodes or Docker containers, never retries automatically, and waits for each replacement before continuing. It fails closed on watcher/API errors, identity changes, partial replacement, incomplete evidence, or failed enforcement tests.

## Consequences

Docker restarts can leave a Ready-looking CNI unable to watch policy state. Recovery is explicit and auditable, but causes brief node-local networking disruption and therefore requires separate runtime approval.
