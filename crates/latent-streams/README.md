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

### Original read-witness controls

The opt-in `development-read-witness` feature observes successful read-future
construction inside the original prepaid connection. `read_admissions` saturates
at three, `pending_reads` aggregates with a sentinel at two, and
`retired_read_delivered_bytes` samples delivered bytes when the original read
guard releases. Provisional guards whose later buffer/window preparation fails
do not count as constructed reads. The observations are inert: they do not add
an admission failure, ledger, executor, queue or serialized operator field.
Ordinary builds omit the witness; `development-outbound` alone does not select it.

The [real TCP controls](src/tests/read_progress.rs) use this same feature, not a
second observation implementation. They distinguish unpolled reads from writes,
refuse overlap, withhold future peer bytes until an actual short read completes,
and retain an actual lowering copy after dropping its source chunk and revoking
the provider. Failed window preparation, multiple live connections and provider
rotation have separate controls. Each control has a bounded outer deadline.
Run the registered library suite with its `workspace-all-features` recipe to
include these non-ignored feature-gated tests; a default-feature build alone
does not execute them.

The [signed Go harness](../latent-wasmtime/tests/go_outbound_streams.rs) selects
`development-go-network-read-witness` and isolates one original connection. Both
the fragmented-read case and the cancellation case require a successfully
constructed second read, its live read guard, and one byte observed at prior
guard retirement. A delivered byte and one pending operation alone cannot tell
whether the first read is finishing audit or the pending operation is a write.
The unchanged Go `io.ReadFull` source supplies the next read.

The [runtime controller](../../tools/qualify_go_network_runtime.py) writes new
`latent.go.network.runtime.v2` receipts using the dependency-free
[transcript decoder](../../tools/go_network_read_barrier.py). It requires both
ordered `GO_NETWORK_READ_EDGE` records and every current case/owner/completion
record. Reserved-prefix lines cannot silently disappear when malformed. The
reader rejects duplicates, unknown/private fields, numeric type substitutions,
extra failed native tests, excessive nesting and oversized output/records.
Historical receipts keep their original schema and narrower execution claims.
From a full checkout, run the decoder and source controls without a compiler:

```sh
python3 -m unittest tools.tests.test_go_network_read_barrier tools.tests.test_go_network_runtime -v
```

Snapshots describe currently retained owners, including retired generations,
not process-wide history or identities. Read-guard retirement does not refund
retained chunks/copies, the original IoCall, connection, activation or unproved
kernel tails. Source and parser tests do not establish native or signed-component
execution; those require fresh source-matched runs. Production, kernel and TLS
installation gates remain unchanged. See the
[Go source-port guide](../../docs/development/go-standard-network.md) for the
separate historical and current signed-execution boundaries.

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
| `development-read-witness` | No additional feature dependency; inert original read-future diagnostics. |

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
