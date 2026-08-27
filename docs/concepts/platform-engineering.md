# Platform engineering

Platform engineering applies product thinking to the shared systems that software teams use to build, deliver, and operate services. Its goal is not to hide infrastructure completely. It provides a supported path that removes repeated decisions while retaining clear ownership and escape hatches.

## Platform contract

A platform contract describes what application teams provide and what the platform guarantees. Phase 2 defines health, resource, deployment, metrics-endpoint, security-context, and ownership contracts. Later phases add telemetry infrastructure and broader policy enforcement that consume those contracts.

## Golden path

A golden path is the maintained default for common work. It should be easier and safer than assembling the same capability independently, but it is not an absolute restriction. Exceptions need an explicit reason, owner, and operational model.

## Control plane and developer experience

The control plane reconciles declared intent with infrastructure. Developer experience is how users discover and invoke that capability. A portal can improve discovery, but it does not replace sound APIs, documentation, Git workflows, or operational boundaries.

## Measuring value

A useful platform reduces lead time and cognitive load without transferring hidden risk to a central team. Relevant measures include adoption, deployment reliability, recovery time, support demand, and the time required to create and operate a conforming service.
