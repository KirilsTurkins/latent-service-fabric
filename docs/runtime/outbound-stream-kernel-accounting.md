# Current Linux stream kernel ownership

The source-bound [old witness](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39347494235/job/118383519954)
ran on Linux `7.0.0-1017-azure` at `d4a96268d374de979fafd14652033c2d50234203`.
Under actual send backpressure it retained 131,072 activation-native bytes and
one pool connection. The configured send/receive limits remained 32,768/65,536
bytes; the observed queued-write counter reached 51,045 bytes. These kernel
counters overlap and are not summed into an invented physical-memory peak.
After the original FD dropped, activation-native and pool connection charges
were zero while the controlled flow remained FIN-WAIT-2. After the passive peer
dropped it remained TIME-WAIT with those charges still zero. The actual receipt
SHA-256 is `07d134e2b91c6c2aa3e267a98374aec03c507d063dcdbfbb858bfedf59af6962`.
This is a demonstrated accounting failure, not successful kernel qualification.
The earlier compile-failed run is retained separately and receives no execution
credit. Historical 0.23.45 and later 23/25-case TLS evidence remains unchanged.

## Original-owner retention

The repair reuses the existing prepaid provider-client physical-owner table.
Reusable idle connections and quarantined dial/connection owners are distinct.
Only reusable entries can be checked out or removed by idle close/maintenance.
A quarantine entry retains the exact original client Arc, connection reservation,
IoLease and sealed StreamScope. That intentional bounded self-retention prevents
external provider/awaiter destruction from releasing uncertain ownership. Its
storage is prepaid before connection admission; existing connection, tenant,
provider, metadata and activation caps are unchanged. The existing VecDeque has
capacity at least the unchanged per-client connection maximum. Each table entry
owns one original connection quota, and an incoming affine owner is already
counted but not yet inserted. Thus before insertion table length is at most
maximum minus one: even the final allowed entry cannot grow the allocation. No new executor, admission
queue, retry or per-application driver is created.

The socket preparation owner exists before any DNS/TCP allocation. Cancellation,
failed connect, peer validation, TLS handshake or final registration failure
closes the actual owned future/transport, then retains its original allowances
when kernel retirement is unproved. Successful connection ownership carries the
same guard through close and pending I/O. The original 96 KiB TCP, 64 KiB DNS and
256 KiB TLS allowances remain unchanged. No replacement activation pays for a
tail. Per-epoch quarantine counts are included in existing stream owner and
connection observations, so drain/rotation cannot mistake an empty weak facade
registry for clean physical ownership. `failed_cleanup` and retained connections
prevent the provider-pool shutdown result from being clean.

There is no release path for an unproved quarantine owner. The current platform
can consume finite capacity and then refuse further work; a timeout, cancellation
acknowledgement, RST, missing ss row/inode/FD or zero logical count cannot certify
retirement. Quarantine survives external handle loss for the remaining process
lifetime. This is fail-closed retention, not successful cleanup or kernel support.

## Profile and evidence boundaries

Normal `StreamProvider::install` validates declared configuration, then refuses
with `unsupported` before protected roots, DNS/socket allocation or publication.
No current kernel profile is source-qualified. Operator strings, environment
variables, observed kernel release or a supplied boolean/certificate cannot
promote one. Existing explicitly selected nonproduction logical references remain
available for their historical library-semantics controls; they do not qualify
kernel accounting. A separate cfg(test)-only accounting constructor exercises the
actual retention path, without a production-installation bypass.

The current reference lists all 30 mandatory cases with no ignored/omitted cases
and executes the original 25 provider controls, old refund witness, retained
close-tail witness, cancelled DNS, failed connect and normal-install refusal.
Closed typed counters and real owned peer barriers distinguish each transition.
No address, port, inode, payload, credential, raw ss output or /proc listing is
published. Both TLS crates and all selected source/lock identities are bound
before and after execution. Focused source tests alone are not native execution.
The corrected actual lane remains pending until its exact receipt is retained.

A future supported kernel profile must authenticate the actual kernel/image,
allocator and relevant networking configuration; prove a complete worst-case
allocation bound within the unchanged reservations before socket creation; and
provide a sealed, non-reusable final-free fact covering the full original socket
and every derived close-tail/RCU owner. That fact must retain original activation,
provider and generation identity, and fail closed on missing or lost observations.
Neither a sampled plateau nor cgroup/socket buffer configuration alone supplies
that contract. No such profile or final-free producer is claimed by this repair.
`ACCOUNTING_QUALIFIED` and all kernel/full-TLS/production qualification flags
remain false. #738/#739/#740 remain open.

The finite ss vocabulary is checked against the [primary iproute2 format source](https://github.com/iproute2/iproute2/blob/v6.17.0/misc/ss.c).
The actual installed tool digest is retained independently; that format reference
is not an authenticated source binding for the runner kernel or tool binary.
