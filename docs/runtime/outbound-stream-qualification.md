# Outbound stream implementation and qualification status

The shared implementation remains restricted to explicit development features.
[ADR-0061](../../adr/0061-bound-standard-outbound-streams.md) and the
[profile](outbound-stream-profile.md) remain subject to #737 architecture/security
review. The maintained suites define canonical TCP and physical-ownership controls.
Execution remains pending wherever no authenticated source-bound receipt is
linked below. Case presence and earlier count-only narratives do not establish
current success, ordinary language networking or a released node artifact.

The maintained `latent-streams` implementation installs exact immutable endpoint,
address and resolver configuration into the original capability broker, provider
pools and IoRuntime. TCP payload remains opaque. Host TLS installation explicitly
returns `unsupported`; it never substitutes cleartext TCP. Guest TLS, protocol
credentials, trust roots and client keys require the selected language runtime's
implementation and independent secret grants. No stream configuration accepts
application credentials or host key paths.

| Evidence | Maintained source boundary | Current authenticated execution |
| --- | --- | --- |
| Native TCP/DNS owners | `latent-streams` real loopback sockets and UDP DNS peer, original sealed policy/catalog/budget  Pending current-source execution and a linked source/artifact/receipt record. |
| Existing broker behavior | Existing `latent-capabilities` library suite  Pending current-source execution and a linked source/artifact/receipt record. |
| Bounded DNS | `latent-network` real UDP/TCP resolver peers  Pending current-source execution and a linked source/artifact/receipt record. |
| Canonical component | Maintained encoded Component Model guest, package/WIT evidence, ordinary Wasmtime backend and actual TCP peer  Pending current-source execution and a linked source/artifact/receipt record. |
| Signed node execution | Real signatures, SBOM/provenance, enforced package catalog, compiled deployment binding, normal local node admission/manager and actual TCP peers  Pending current-source execution and a linked source/artifact/receipt record. |
| Protected node configuration | Normal Linux node configuration loading and derivation, explicit development feature  Pending current-source execution and a linked source/artifact/receipt record. |
| Normal node lifecycle | Protected configuration, ordinary standalone node startup and shutdown  Pending current-source execution and a linked source/artifact/receipt record. |
| Authenticated management | Existing capability RPC transport, original broker and actual maintained control future  Pending current-source execution and a linked source/artifact/receipt record. |
| Declarative configuration | Maintained node-provider schema and local stream-schema reference  Pending current-source execution and a linked source/artifact/receipt record. |

The earlier narrative named Rust 1.97.1 image
`rust@sha256:0e2bcaef56d041a486784e54104a81aebe0da44bd03019bd70bc0401e42e4a97`
without per-row source or execution packets. That image reference does not
authenticate current results. Fresh receipts must identify the full source,
compiler/runtime/WIT/engine, actual binary, exact cases and controlled barriers.
Observe actual peer FIN/reset, pool connections/running requests, original
host-memory charges and IoRuntime owners; a cancellation acknowledgement or
elapsed timeout never proves cleanup.

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

The lost-reply case records connection attempts and business mutations separately.
The controlled peer commits one mutation and withholds its reply. The original
read returns a typed timeout with `may-have-applied`, and further writes fail
before copying payload. Actual peer retirement precedes the cleanup claim, while
the retained facade still holds its original memory charge. Finalizing the
original budget does not release that owner or permit its frozen report to change.
Only a distinct fresh activation opens the second connection, and it performs no
second mutation. Broader language middleware and protocol retry behavior remain
part of the unqualified workload matrix.

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

Operator inspection distinguishes a node with no stream installation from an
installed provider whose physical observer has been destroyed. HTTP-only nodes
omit stream counters and have no missing-stream observation. A destroyed
configured observer reports unavailable without fabricating zero counters. The
CLI accepts only the ten defined stream counters and that exact unavailable
reason; unknown fields and provider error text remain rejected.

The current provider PR's 2026-10-01 Go tool-bundle run tested merge source
`6bfe58c57920b3c0da09fa42b78490b4e2a3c409`. Its three ordinary greeting
scenarios passed. The missing-grant scenario then received an unresolved
`unavailable` response while switching the deployment; recovery observed an
unknown original receipt and retained that operation without another mutation.
The node subsequently reported clean physical provider shutdown. The uploaded
report retained a response digest but omitted its typed failure detail, so this
does not establish a clock-lease or authority-contention cause.

Future controller observations retain `failureDetail` only for one exact
`admission.currentness` detail with a recognized public reason and Boolean
retryability. Arbitrary messages, payloads, extra fields and unknown reasons are
excluded. Fresh source-bound recovery, HTTP-fixture and observation control receipts are
required, including all 12 currentness reasons and both retryability values. This
diagnostic neither settles the original operation nor authorizes a mutation
retry; the original pending identity and receipt-recovery rules are unchanged.

Open delivery gates include #737's explicit review, protected node/operator
end-to-end qualification and live rotation workflow (#739), full adversarial
socket/uncertainty and measured native
peaks (#740), and every ordinary standard-library and unchanged non-HTTP workload
for Rust/C/Go/Java/TypeScript/.NET. The ABI contains `host-tls` as an explicit
unsupported choice in this development TCP slice. No standard-language or host
TLS success is implied by the canonical fixture.
