# ADR-0055: Project private HTTP readiness from authenticated observations

- Status: Accepted
- Date: 2026-09-27
- Related: #639

## Context

A supervisor may support HTTP probes without supporting native CLI execution.
TCP reachability and customer application routes are not authoritative node
readiness. An adapter's own survival must not mask an unavailable backend.
The project excludes cloud resources and simulated Azure qualification.

## Decision

Provide an optional loopback-only adapter in the authenticated native container
image. Sample the intended node with a fixed authenticated CLI operation. Require
the current identity, known successful result, bounded fresh observation,
available pressure and complete live HTTP listener/owner inventory. Readiness
also requires spare HTTP connection/exchange/buffer capacity and conservatively
retains native activation readiness. Liveness uses native health and ownership,
not spare capacity; startup latches the first ready state for this coupled
node/adapter lifetime while still requiring a current healthy observation.

Expose three exact GET/HEAD paths with an exact private peer/Host contract,
bounded status-only JSON, no-store and no control credentials. Do not call an
application, scan tenants/publications, grant authority from forwarded headers,
change native readiness or serve retained success after its monotonic age bound.
The sidecar must be recreated with the intended node network namespace.

## Resource and failure contract

Two node-fixed threads, one CLI child maximum, no overlapping samples and no
per-request tasks. CLI timeout1.5s/output256KiB; interval1s after completion;
observation maximum age3s. Serial HTTP handling uses backlog2, request4KiB,
16headers and read/write deadlines0.5s. SIGTERM stops and joins all owned work.
The deployment supplies an explicit memory/process limit and private read-only
client file; it does not expose the management listener. The finite test records
actual sampled resource overhead separately from these configured ceilings.

## Qualification boundary

Actual local HTTP, CLI, filled ingress connections, stopped/resumed backend,
clean shutdown, corrupted durable clock state, wrong node identity and elapsed
stale observations are tested. Recreate the adapter after a Docker restart changes
the node network namespace. Static publication
and durable recovery continue through the normal real-node workflow. No ACA
probe peer, host kernel, remote filesystem or revision behavior is implied.
