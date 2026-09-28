# ADR-0053: Run authenticated native binaries in a bounded container profile

- Status: Accepted
- Date: 2026-09-27
- Related: #635, #636, #637, #638, #639, #640

## Context

The native installer qualifies a concrete Linux host and protected filesystem.
A container image cannot establish its host's pressure sources, kernel sandbox,
storage durability or orchestrator ownership. The integration feedback requested
an explicit container profile. The owner directed that no Azure resources be
used and no Azure results be simulated.

## Decision

Build a non-root Ubuntu 24.04 amd64 image from an independently authenticated
native release. Require root-owned exact executable bytes, UID/GID 10001,
read-only runtime/configuration, explicit private data/cache mounts and enforced
package admission. A finite preflight reuses the installer host and filesystem
checks and the real native security-profile checker. It then execs `latentd` as
PID 1, preserving native signal handling, resource ownership and bounded shutdown.

Qualify actual local Docker execution with real released binaries, signatures,
publications, GET/HEAD reads, clean restart and protected-identity rejection. Keep
the componentless static T0 profile distinct from T1 external capsule compilation:
T0 does not claim isolation from untrusted guests. Both still need pressure and
protected durable state. Never remove host prerequisites to pass a managed host.

The supported deployment alternative is a host-controlled Linux runtime with
verified local filesystem semantics and explicit edge/private management
composition. ACA and Azure Files remain unqualified, not proven incompatible.
Cloud resource creation and cloud simulation are out of this delivery scope.

## Ownership and bounds

The preflight has finite subprocesses and size/time bounds. It is replaced by the
native node, adding no per-publication worker or resident supervisor. The test
driver limits itself to 128 Docker calls and five minutes; runtime containers
drop all capabilities, prohibit privilege escalation, use read-only roots and
have explicit CPU, memory, process and log ceilings. Only disposable mount
initialization uses root with the minimum directory-ownership capabilities.
No privileged runtime or host-kernel workaround is permitted.

## Consequences and validation

Deployment owns persistent private configuration, credentials, state, image
identity and termination timing. Startup failures name an actionable prerequisite.
The maintained receipt distinguishes publisher authentication, image assembly,
local runtime checks and managed-platform qualification. The latter is always
false for this drill. Storage recovery, trusted proxy behavior, headless private
operations, probe translation and exclusive owner handover have dedicated work.
