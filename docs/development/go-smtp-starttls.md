# Ordinary Go SMTP and guest STARTTLS

This finite qualification candidate uses the standard `net/smtp.Dial` constructor,
`Client.StartTLS`, `Noop` and `Quit`, with the existing compiler-owned declared-TCP
connection. No supplied `net.Conn`, resolver, transport or application executor
is installed. [Go 1.27.2's implementation](https://github.com/golang/go/blob/go1.27.2/src/net/smtp/smtp.go)
connects through ordinary `net.Dial`; STARTTLS wraps that same connection with
the standard guest `crypto/tls` implementation and performs a new EHLO exchange.

Six mandatory candidate cases cover plaintext SMTP, verified TLS 1.3, hostname
refusal, an untrusted explicit root pool, verified TLS 1.2 and a fresh verified
connection after the refusals. All trust roots are explicit invocation input;
hostname and certificate verification stay enabled. The fixed owned peer checks
bounded public protocol commands and requires a failed handshake for both
certificate refusals. The fixture returns only closed result tokens, not
certificate errors or application data. It sends no email or credentials.

One fresh managed-v5 component and one targeted native signed harness exercise
the existing catalog, authority and broker, with original Task16/Executor2/
Queue2/Wait4/Timer2/Result2/Native2 limits. Every connection consumes its own
declared TCP dispatch, and every completed case must leave zero original
user-space owners before the next invocation. No retry, reconnect or protocol
replay is added. The strict receipt requires all six ordered cases, six peer
contacts, six zero-user-owner rows and clean logical-provider stop.

The first actual source `ca723d3c693eb1a8d62972ac96ae017b4d38e277`
constructed the component and passed plaintext SMTP, then failed its first TLS
1.3 handshake with `unreachable-code` in
[run 39437307701/job 118677626944](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39437307701/job/118677626944).
The [retained trap observation](../testing/evidence/go-smtp-tls-cache-trap-2026-10-20.json)
binds an exact-component private numeric-frame replay. All nine frames mapped, including
`runtime.AddCleanup` from `crypto/tls`'s private certificate cache during server
certificate verification. That callback is explicitly refused by the maintained
runtime; this is a source-backed cache integration defect, not a successful TLS
observation. The original failure and private replay remain separately retained.

The correction authenticates the complete
[Go 1.27.2 private cache source](https://github.com/golang/go/blob/go1.27.2/src/crypto/tls/cache.go)
before replacing only that cache in the declared-stream managed-v5 path. Its
fixed strong cache admits at most eight distinct certificates, at most 16 KiB per
DER value and 64 KiB aggregate DER. It checks capacity before copying a key or
calling the upstream x509 parser. Admitted parse errors pass through unchanged;
no certificate, chain, hostname, signature, trust or authentication check is
removed. Cache hits reuse the existing parsed object even when capacity is full.

The fixed entries, retained DER and parsed objects remain invocation-local Wasm
heap memory under the original 64 MiB heap/GC limit until Store destruction.
There is no eviction, cleanup callback, hidden task, early refund or persistent
cross-invocation cache. A fresh Store initializes an empty cache. The aggregate
DER limit is a finite guest cache admission bound, not a claim that parsed
objects consume only DER bytes or that it establishes a native/kernel quota.
Generic application `runtime.AddCleanup` remains explicitly refused.

The same lane first executes eight exact-production-cache Go reference controls:
GC retention, zero-allocation oversized refusal, ninth-entry refusal, exact
aggregate capacity/no eviction, unchanged parser errors, fresh-instance state,
concurrent cache-hit identity and exact per-DER boundary. Only its package
declaration changes in that reference. It then constructs one fresh ordinary Go
component and reruns the original six signed cases, with unchanged grants and
runtime/provider bounds. The [authenticated corrected observation](../testing/evidence/go-smtp-starttls-signed-2026-10-20.json)
records [run 39447505901/job 118713217150](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39447505901/job/118713217150)
at exact source `dcb4f99d9a10ca4c785c772c68a63bca0110c6af`: all eight native
cache reference cases and all six ordered signed guest cases passed, with six
real peer contacts, six zero-original-user-owner rows and clean logical-provider
stop. The fresh component is 9,422,932 bytes, SHA-256
`2913e0637d38cadb684b4d47686e039da90c50b9f54736b252788117a2a0f1fe`.
All 54 archive members passed CRC/SHA-256 checks, and all 5,451 source-input rows
(45,332,635 bytes) match that exercised Git source. The actual compiler transform
binds the complete upstream cache preimage to the exact reference-tested cache.

The cache-limit reference is distinct from signed oversized-certificate or full
TLS adversarial qualification. The signed six-case result remains attributed to
its original component/native source. Final source composition also includes the
separately tested bounded Write progression and unrelated reviewed HTTP/native
and TypeScript changes; it does not relabel that historical execution. This candidate
does not qualify ordinary `SendMail` with implicit system roots, authentication,
email delivery, arbitrary protocol clients, host TLS or full networking.
The explicit development logical provider remains distinct from a normal
installed provider. Peer close and zero user-space counters do not prove final
kernel free or complete physical accounting; those flags remain false.

This advances the finite networking/TLS portion of
[#742](https://github.com/KirilsTurkins/latent-service-fabric/issues/742) AC7 and
supplies future protocol controls for
[#738](https://github.com/KirilsTurkins/latent-service-fabric/issues/738).
Both issues remain open.
