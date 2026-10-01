# Outbound stream implementation and qualification status

The shared implementation remains restricted to explicit development features.
[ADR-0061](../../adr/0061-bound-standard-outbound-streams.md) and the
[profile](outbound-stream-profile.md) remain subject to #737 architecture/security
review. These results qualify a canonical TCP component and physical ownership;
they do not qualify ordinary language networking or a released node artifact.

The maintained `latent-streams` implementation installs exact immutable endpoint,
address and resolver configuration into the original capability broker, provider
pools and IoRuntime. TCP payload remains opaque. Host TLS installation explicitly
returns `unsupported`; it never substitutes cleartext TCP. Guest TLS, protocol
credentials, trust roots and client keys require the selected language runtime's
implementation and independent secret grants. No stream configuration accepts
application credentials or host key paths.

| Evidence | Executed source boundary | Result |
| --- | --- | --- |
| Native TCP/DNS owners | `latent-streams` real loopback sockets and UDP DNS peer, original sealed policy/catalog/budget | 13 passing cases: actual partial read/EOF/send half-close, chunk backpressure before copy, retained chunks after socket closure, dropped unpolled operation, alternate endpoint denial, revocation before write, revocation during pending read, provider retirement during pending read, explicit host TLS rejection, rotation/drain retaining actual old-generation owners, autonomous idle/DNS expiry of inactive sockets, and pending DNS cancellation with independently observed kernel descriptor retirement |
| Existing broker behavior | Existing `latent-capabilities` library suite | 125 passing cases, including HTTP/provider audit, cancellation, fair finite queues, delayed physical retirement and exact authority bookkeeping contention |
| Bounded DNS | `latent-network` real UDP/TCP resolver peers | 3 passing cases: truncated UDP to same explicit TCP resolver, preallocation TCP length rejection and exact special-address policy |
| Canonical component | Maintained encoded Component Model guest, package/WIT evidence, ordinary Wasmtime backend and actual TCP peer | 6 passing cases: partial owned chunks/EOF, three fresh activations on the same execution cell, oversized byte-list rejection before send, terminal trap/wrong kind/stale resources, root cancellation and policy revocation while a canonical read waits, 256 dormant deployments with zero Stores and socket owners |
| Signed node execution | Real signatures, SBOM/provenance, enforced package catalog, compiled deployment binding, normal local node admission/manager and actual TCP peers | 4 passing cases: three fresh activations on one execution cell; missing/stale provider binding denied before Store or contact; cancellation acknowledgement retaining original owners followed by actual physical retirement and fresh work; policy revocation at a pending peer barrier before the deadline |
| Protected node configuration | Normal Linux node configuration loading and derivation, explicit development feature | 3 passing cases: closed input without credential/key-path reflection, exact installed binding scope, protected input and finite exact-address policy before storage or network work |
| Normal node lifecycle | Protected configuration, ordinary standalone node startup and shutdown | 32 restarts in one maintained case: installation never dials the controlled peer, one prepaid maintenance owner is joined, and physical stream/maintenance owners are zero on each clean shutdown |
| Authenticated management | Existing capability RPC transport, original broker and actual maintained control future | 45 passing management cases, including additive operator-only stream counters, tenant/caller/spoofed-role denial, actual maintenance join and explicit unavailable status after its weakly observed owner is destroyed |
| Declarative configuration | Maintained node-provider schema and local stream-schema reference | 6 passing cases; all five existing provider-schema obligations retained, with additive closed stream configuration coverage |

The Linux checks use Rust 1.97.1 image
`rust@sha256:0e2bcaef56d041a486784e54104a81aebe0da44bd03019bd70bc0401e42e4a97`.
Tests observe actual peer FIN/reset, pool connections/running requests, original
host-memory charges and IoRuntime owner snapshots at controlled barriers. A
cancel acknowledgement or elapsed timeout is never counted as cleanup proof.

The provider prepays kernel socket allowance before allocation and rejects OS
send/receive sizes beyond its reservation. Original native-memory guards remain
with physical sockets, pending futures, resident payload and the canonical copy.
This is accounting evidence; RSS/allocator/kernel peak measurement is pending.
DNS prepays 64 KiB on the same original activation and provider ledgers, requests
4 KiB send/8 KiB receive buffers and inspects an actual 24 KiB combined ceiling
before UDP bind or TCP fallback connect. Real scratch/socket allocation confirms
the native peak reservation; cache hits create no new resolver socket. The
pending DNS case observes the controlled socket inode in `/proc/net/udp` and
`/proc/self/fd`: cancellation acknowledgement retains its original charge, and
only actual owned-future destruction removes that descriptor and refunds live
memory. The cumulative attempted-connect charge remains spent, with no TCP
peer contact.
No network operation is replayed by a currentness inspection. Accepted original
work checks its pinned authority every 10 milliseconds while suspended and again
before a socket syscall; changing the publication/policy/provider epoch closes
further work without minting a new ledger. A single prepaid node maintenance
future also closes inactive sockets at DNS or idle expiry without another guest
call. The peer observes actual FIN, a subsequent write retains the typed timeout,
and the retained facade keeps its original charges until real Drop. Stop handles
retain maintenance metadata through acknowledgement and actual future destruction.

The signed node cases bind their observed component digest, frozen network WIT,
binary builders, package source and exact provider configuration before signing.
They use the existing node composition, admission quotas, cancellation registry,
provider pools, IoRuntime and Wasmtime engine. Cancellation acknowledgement still
shows one active activation and retained stream owner. Completion requires the
peer's FIN/reset, zero actual Stores/instance reservations, cancellation probes,
broker session/call/result owners and stream I/O/pool owners. Missing or stale
provider bindings return permission denied before the first Store or peer
connection. These internal node tests do not replace packaged standalone-node
operator workflow qualification or ordinary language clients.

Open delivery gates include #737's explicit review, protected node/operator
end-to-end qualification and live rotation workflow (#739), full adversarial
socket/uncertainty and measured native
peaks (#740), and every ordinary standard-library and unchanged non-HTTP workload
for Rust/C/Go/Java/TypeScript/.NET. The ABI contains `host-tls` as an explicit
unsupported choice in this development TCP slice. No standard-language or host
TLS success is implied by the canonical fixture.
