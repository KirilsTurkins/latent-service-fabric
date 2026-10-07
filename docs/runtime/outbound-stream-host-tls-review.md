# Direct host TLS source proposal and accounting gate

The private implementation adds only the direct host TLS option already
described by [ADR-0061](../../adr/0061-bound-standard-outbound-streams.md).
Production installation remains disabled. The candidate direct TLS installation
also returns `unsupported` until its exact parser allocation and native/component
controls establish the original 256 KiB connection and 64 KiB trust reservations.
Schema acceptance is neither provider readiness nor permission.

The security review must confirm protected trust ownership and failure
redaction, exact hostname/address/transport binding, finite pre-parser object
counts and allocation proof, handshake/application progress meanings, and
credential exposure/rotation boundaries. The implementation gate then requires
real positive and denial peers under the unchanged budgets, physical retirement
and authenticated current-generation grants. No source merge, schema check,
native reference parser or reviewer observation alone enables production.

Each TLS destination names the exact canonical endpoint hostname, a separate
`host-tls` transport, and 1–8 protected SHA-pinned DER root files. There are no
ambient roots, client keys, key logging, session resumption, early data,
certificate decompression, STARTTLS, verification override or cleartext fallback.
The existing protected-file loader checks owners, modes, ancestors, links and
size before root parsing. Missing/replaced/malformed inputs fail with a closed
error. Provider descriptors disclose a configuration digest and epoch, never
raw paths or certificate/protocol bytes.

The same `PoolCall`, original activation memory ledger, `IoCall`, transfer,
pending operation and physical socket own TCP and TLS. Trust configuration
retains its metadata reservation through every TLS connection clone. Locks never
span an external readiness await. The handshake retains one connection and its
original deadline/currentness; no failure restarts it. The candidate bounds
encrypted handshake input/output to 32 KiB in each direction and application
write buffering to 16 KiB. Positive writes count accepted plaintext, including
an accepted prefix before failure, without asserting remote protocol completion.
TLS send/receive half-close remains unsupported; close aborts without a protocol
command, and retained chunks/pending owners keep their original charges.

The wire limits alone are insufficient proof. The exact locked rustls 0.23.45
deframer grows from actual buffered input, in 4 KiB steps up to its 64 KiB
handshake cap. It does not allocate a 16 MiB buffer from a tiny declared length.
However, its generic `Vec<T>` decoder pushes every decoded certificate entry
before chain verification. TLS 1.3 entries include certificate and owned
extension state; many small entries can amplify wire bytes. Its public write
buffer limit does not cover these parser allocations. The source audit retains
the exact checksum-verified rustls/webpki archives and per-file identities.

Required next controls include an authenticated bounded parser slice or
equivalent pre-allocation enforcement for certificate/extension entry counts,
declared oversized/truncated messages, malformed DER, large root sets, retained
plaintext/ciphertext/errors and actual allocator/native peaks. These controls
must reject before excess allocation under the same reservations; raising
logical allowances or measuring only a benign handshake is insufficient.

Guest TLS, application credentials and client authentication remain owned by
their selected language profile. Stream authority never grants secret reads.
Use the existing protected secrets provider with independently scoped tenant,
service, publication and secret-reference grants; opaque stream providers do
not inject protocol credentials. Trust or secret rotation fences old generations
and retains physical charges without migrating authenticated sessions. The
current protected node reload permits only stream epoch/limits; trust identity
changes require an explicit new protected startup, preventing implicit authority
migration until a separately reviewed finite trust-rotation operation exists.

The source prepares real positive transfer, wrong-hostname, protected root
hash/link/mode failure, stalled handshake and live generation retirement tests.
They are not passing evidence until actually compiled and executed against the
qualified parser. Standard socket APIs and each language's guest TLS remain
separate #741–#746 obligations, not inferred from direct host TLS.
