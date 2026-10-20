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

Actual execution is pending. Local source/reader controls and a Rust protocol
peer are not an upstream native-Go execution or guest success. This candidate
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
