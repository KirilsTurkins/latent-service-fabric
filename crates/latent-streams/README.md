# latent-streams

Bounded outbound TCP/TLS stream implementation for explicit qualification. It owns exact destination configuration, socket/chunk lifetimes, current provider epochs and finite maintenance. General production enablement remains gated by the outbound-stream decision and qualification record.

An ordinary HTTP method/path grant cannot authorize opaque socket bytes. The stream provider requires its own exact endpoint and operation authority.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/config.rs](src/config.rs) | Explicit stream destinations, DNS/static resolution, TLS configuration and limits. |
| [src/provider.rs](src/provider.rs) | Broker-facing StreamProvider and checked operation execution. |
| [src/connection.rs](src/connection.rs) | Affine connection ownership shared safely with pending readiness handles. |
| [src/transport.rs](src/transport.rs) | Physical TCP/TLS owner without locks across external readiness awaits. |
| [src/lifecycle.rs](src/lifecycle.rs) | Stable invoker over explicitly replaced provider epochs. |
| [src/maintenance.rs](src/maintenance.rs) | Bounded node-owned maintenance future without per-connection tasks. |
| [src/tls.rs](src/tls.rs) | Direct TLS with protected explicit trust roots. |

## Execution and ownership

1. Select the qualification feature/profile and install exact stream endpoint/TLS/pool constraints.
2. Accept a broker-approved operation and reserve connection/buffer capacity before DNS or contact.
3. Recheck current authority before physical syscalls after waits; retain accepted I/O and chunks under original ownership.
4. Drain/retire provider epochs and actual sockets before refunding capacity or reporting shutdown.

### Local abort and half-close

`shutdown(Both)` is a local abort, not a graceful TLS shutdown or proof that a
peer rolled back earlier writes. It has one bounded control slot independent of
the ordinary write/send-shutdown slot. A held write, an accepted TCP send-shutdown,
or an already closed TCP send half does not by itself prevent admission of the
abort. Original authority, deadline and prepaid I/O admission gates still apply.

An accepted but unpolled abort blocks new writes and TCP send-shutdowns; a second
abort is rejected. Dropping that unpolled future releases only its slot and does
not stop the connection. Once the abort executes, existing read/readiness waits
are cancelled. The result can remain `Stopping` while accepted owners still hold
the original socket and reservations. Dropping the guest-facing handle is not a
refund proof: the final accepted owner must retire as well. Earlier application
write attempts retain their possible-write uncertainty; no reconnect or replay
is performed.

TCP supports send-only shutdown. TLS send-only shutdown and receive-only shutdown
remain unsupported. TLS `shutdown(Both)` does not send a close-notify record; it
can also retire a connection after the peer has sent its own close-notify.

### Original read-guard observations

Qualification builds expose `StreamUsage.read_progress` through the existing
provider/lifecycle snapshots. Its fixed-size state shares the original connection
mutex and checked prepaid owner envelope; it adds no queue, executor, activation
budget, guest operation or serialized operator field. Normal builds omit it.
`admitted()` counts original read guards, `released()` counts their releases, and
`released_bytes()` samples cumulative delivered bytes at that release boundary.
Admission and release include unpolled reads and failures of later buffer/window
admission. They do not by themselves establish transport dispatch or success.

The [real TCP controls](src/tests/read_progress.rs) hold future peer bytes until
an actual short-read result, distinguish read/write and overlapping guards,
exercise failed window admission, retain results after revocation, and observe
original read guards across provider rotation. These controls remain part of the
complete registered library suite, with no new ignored cases. Counter overflow
refuses admission/observation instead of wrapping or partially publishing a sum.

The [signed ordinary Go harness](../latent-wasmtime/tests/go_outbound_streams.rs)
isolates one original connection and requires two admissions, one release, one
pending read, and one byte already observed at the first release. This excludes
the earlier ambiguous tuple of one delivered byte and one pending operation,
which could still describe the first read finishing audit. The unchanged Go
`io.ReadFull` source supplies the next read, not an injected transport. The
[source-bound controller](../../tools/qualify_go_network_runtime.py) now emits
`latent.go.network.runtime.v2` and requires one closed typed
`GO_NETWORK_READ_BARRIER` record; missing/duplicate/old witnesses cannot pass.
Historical receipts retain their original schema and evidence scope.

Snapshots sum currently retained owners, including retired generations, and
forget their counters when those owners disappear. They are not process-wide
history or identities: a qualification must isolate its intended original owner.
Read-guard release does not refund retained chunks, the original IoCall, the
connection, activation, or unproved kernel tails. These diagnostics neither
qualify production/kernel/TLS retirement nor open any installation gate. Fresh
source-matched native execution is required before claiming the new controls
passed; source presence and parser tests alone are insufficient.

## Integration boundaries

ADR-0061's bounded design was accepted on October 16, 2026; production
installation remains disabled pending its implementation/qualification gates.
The selected rustls source is `latent-rustls-outbound` 0.23.46, but the current
`ACCOUNTING_QUALIFIED` guard still disables direct host TLS. Source/parser/VM
controls do not override that guard. Linux construction also uses the
[private factory leaf](../latent-stream-factory-native/README.md); descriptor
closure, kernel Root return and backing-bank reclamation are separate observed
boundaries. The [kernel accounting contract](../../docs/runtime/outbound-stream-kernel-accounting.md)
and [operator preparation](../../docs/runtime/outbound-stream-operator.md)
describe current evidence and protected installation, not general availability.

`development-outbound` is a deliberate feature boundary, not permission to enable streams in every deployment. Unsupported TLS modes must reject rather than fall back to plaintext. No listening socket, permanent application runtime or provider credential discovery is created. Finite maintenance is shared node work and does not retain a guest Store.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-network](../latent-network/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md), [latent-protected-files](../latent-protected-files/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | No additional feature dependency. |
| `development-outbound` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

The Linux x86-64 library suite `latent-streams.lib.latent-streams` is registered
in [the outbound suite fragment](../../tools/ci/suites.d/outbound-streams.json).
The [host TLS provider owner](../../tools/qualify_host_stream_tls_provider.py)
builds a source-matched executable, runs the complete library suite without
ignored or filtered cases, and retains source-bound evidence. From a clean
checkout with the pinned toolchain, run it from the repository root with a fresh
output directory:

```sh
python3 tools/qualify_host_stream_tls_provider.py \
  --output /tmp/lsf-host-tls-provider-reference \
  --source-commit "$(git rev-parse HEAD)"
```

The [TCP abort controls](src/tests/sockets.rs) and
[TLS abort controls](src/tests/tls/abort.rs) are required evidence, not optional
filtered smoke tests. The TLS controls pin and verify TLS 1.2 and TLS 1.3,
exercise read/readiness cancellation with an accepted unpolled write, distinguish
possible earlier writes from no application write, retain the original socket
through handle drop, and check unpolled-abort cancellation and peer close-notify.
An additional real non-reading peer forces an already-dispatched TLS write to
block while flushing ciphertext. Its abort control checks prompt cancellation,
nonzero accepted-plaintext uncertainty, original socket/charge retention, bounded
peer delivery without replay, and EOF without a local close-notify. These controls
do not claim an already-dispatched kernel FIN race, kernel final-free proof, or
production TLS qualification.

Representative source tests (not a complete coverage inventory):

- [`opaque_transport_requires_exact_special_address_authority`](src/tests.rs)
- [`unimplemented_host_tls_is_never_silently_replaced_with_tcp`](src/tests.rs)
- [`genuine_http_only_authority_denies_opaque_bytes_before_dns_and_contact`](src/tests/authority.rs)
- [`a_policy_change_while_readable_is_pending_is_checked_before_syscall`](src/tests/currentness.rs)

## Related documentation

- [Bounded standard outbound stream profile v1](../../docs/runtime/outbound-stream-profile.md)
- [Outbound stream implementation and qualification status](../../docs/runtime/outbound-stream-qualification.md)
- [Protected outbound stream administration](../../docs/runtime/outbound-stream-operator.md)
- [Development outbound TCP installation](../../docs/reference/standalone-streams.md)
- [ADR-0059: Defer general outbound streams; evaluate typed protocol boundaries first](../../adr/0059-defer-general-outbound-streams.md)
- [ADR-0061: Bound standard outbound streams beneath language runtimes](../../adr/0061-bound-standard-outbound-streams.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
