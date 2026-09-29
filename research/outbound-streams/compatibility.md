# Real library needs and compatibility boundaries

Review baseline: LSF development `a7b5d2088471b7368cd85ab74f3292afcdfca00e`.
Upstream API documentation was inspected on 28 September 2026. Only the exact
Go standard-library source in the receipt was executed. Other rows are
**source/API feasibility findings, not successful guest builds**. Package names
select representative evidence; they are not a package allowlist or admission
rule. Unregistered packages using the same supported API would need no privileged
package-specific exemption. Captured dependency/profile identity belongs to
[#678](https://github.com/KirilsTurkins/latent-service-fabric/issues/678), reachable
findings to [#679](https://github.com/KirilsTurkins/latent-service-fabric/issues/679),
and reusable adapter contracts to
[#680](https://github.com/KirilsTurkins/latent-service-fabric/issues/680).

## Six-language SMTP sample

| Guest language / real library | Actual non-HTTP need and transport seam | Separate compiler/runtime constraints and evidence |
| --- | --- | --- |
| Rust / lettre 0.11.23 | SMTP commands and replies; a custom `Transport` implementation can target a typed gateway, while `SmtpTransport` is a socket/TLS transport. | Selected Cargo features, TLS implementation, native dependencies and sync/async executor or pool choices must match the guest compiler. A pure MIME builder is a different reachable path. Documentation inspected; neither stock transport nor replacement was compiled into a capsule. |
| C / libcurl SMTP | SMTP submission; `CURLOPT_READFUNCTION` supplies message payload to libcurl. It is **not** a replacement for all network I/O. | A Wasm-compatible libcurl/TLS build, resolver choice, syscalls and event-loop integration are separate requirements. A native `.so` cannot be linked as a guest Wasm archive. No libcurl guest or arbitrary POSIX socket shim was built. |
| TypeScript / Nodemailer | SMTP uses Node networking/DNS/TLS; its custom transport extension can represent an explicit typed submission backend. | The guest engine is not a Node host. Reachable Node APIs, modules and event/pool lifetimes require bundler/compiler evidence or replacement. Merely injecting a destination does not eliminate Node dependencies. Source/API review only. |
| Go / standard `net/smtp` | `NewClient(net.Conn, host)` accepts an existing connected transport. This is the actual native library used by the local POC. | Native Go's sockets/runtime and its `net.Conn` callback are not proof that the maintained async guest compiler can lower the same path. No goroutines or connection state may survive activation cleanup. Host execution passes; guest compatibility remains unknown. |
| Java / Angus Jakarta Mail SMTP | `mail.smtp.socketFactory` accepts a socket factory; the documented fallback can reopen a normal `java.net.Socket`. A typed `Transport` replacement is a different seam. | TeaVM C is not a JVM. Reachable socket/JDK APIs, class/service discovery, resources, reflection and SASL must compile. The documented write-timeout path uses a scheduled executor/thread per connection. Disable fallback and replace that lifecycle before qualifying a guest; adding TCP cannot provide JNI or arbitrary reflection. No guest build performed. |
| C# / MailKit | `SmtpClient.Connect(Stream, host, port, SecureSocketOptions, CancellationToken)` accepts a supplied stream. This is an injection candidate, not an automatic `System.Net.Sockets` replacement. | NativeAOT/Componentize.NET reachability, transitive MIME/crypto libraries, task suspension, cancellation and stream disposal require real component evidence. P/Invoke/native assets and unsupported dynamic code are separate failures. Source/API review only. |

Primary sources supporting these API observations:

- [lettre SMTP 0.11.23](https://docs.rs/lettre/0.11.23/lettre/transport/smtp/index.html)
  and [transport trait](https://docs.rs/lettre/0.11.23/lettre/trait.Transport.html).
- [libcurl SMTP example](https://curl.se/libcurl/c/smtp-mail.html).
- [Nodemailer SMTP](https://nodemailer.com/smtp) and
  [custom transports](https://nodemailer.com/transports).
- [Go net/smtp](https://pkg.go.dev/net/smtp); the receipt additionally hashes the
  actually executed `smtp.go`/`auth.go` at the local GOROOT, not the moving web page.
- [Angus SMTP properties](https://eclipse-ee4j.github.io/angus-mail/docs/api/org.eclipse.angus.mail/org/eclipse/angus/mail/smtp/package-summary.html):
  socket factory, fallback, write-timeout executor and SSL configuration.
- [MailKit Connect overloads](https://mimekit.net/docs/html/Overload_MailKit_Net_Smtp_SmtpClient_Connect.htm).

The current guest execution/compiler boundaries come from LSF's maintained
[guest reference](../../docs/component-development/guest-sdk.md) and the
[SDK library epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/677).
The matrix deliberately does not assign a permanent compatible/incompatible label
to an entire package. Build failures, reachable unsupported APIs, unknown analysis,
missing imports, absent provider, denied grant, exhausted budget and uncertain
outcome must stay distinct in #679 reports. Supplying an unused networking class
is not sufficient reason to reject a package; proving its elimination is separate
compiler evidence. All linked libraries share capsule authority, not independent
security principals.

## PostgreSQL and custom binary protocols

[JDBC PostgreSQL connection configuration](https://jdbc.postgresql.org/documentation/use/)
and [Npgsql connection parameters](https://www.npgsql.org/doc/connection-string-parameters.html)
show separate transport, TLS, timeout and pool configuration concerns. A database
client additionally owns protocol negotiation, authentication, transaction/session
state and response parsing. A socket permits bytes; it does not create a trusted
query API or make native driver code compile. A server-side prepared query such as
`lookup-account(account-id)` can be a narrowly authorized typed operation. A generic
`execute-sql(string)` gateway is a much broader authority and is not recommended
merely because its transport is HTTP.

A protocol that negotiates TLS after an initial binary exchange is not supported
by the proposed *implicit host TLS at connect* profile. In particular, the traditional PostgreSQL
SSLRequest exchange and SMTP STARTTLS must not be disguised as immediate TLS.
PostgreSQL also documents an explicit
[direct TLS negotiation mode](https://www.postgresql.org/docs/18/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION);
that separate mode still needs exact client/server and host-TLS profile qualification. A
separate typed host provider can implement and qualify its known negotiation;
otherwise the candidate reports unsupported. An existing remote database
transaction is not an LSF Phase 4 transaction or atomic with LSF's future outbox.
Timeout after COMMIT, lost acknowledgement, or handle Drop cannot establish
rollback. Session reset is protocol-dependent, so raw connections are never
reused across activations in this candidate.

A custom binary codec built over explicit read/write callbacks is the strongest
case for an eventual byte stream: it may have no useful shared high-level API.
Its finite frame lengths, cancellation behavior, auth state and compiler profile
still need qualification. No protocol sniffing can infer a trustworthy method,
path, tenant, idempotency or transaction boundary from arbitrary byte writes;
TLS may conceal those bytes altogether. Recognizing PostgreSQL or HTTP-looking
prefixes would not constitute authorization.

## WASI comparison: exact source, not import renaming

The inspected source is
[`wasi:sockets/tcp@0.2.0`](https://github.com/WebAssembly/wasi-sockets/blob/v0.2.0/wit/tcp.wit),
using `wasi:io/streams@0.2.0`, `wasi:io/poll@0.2.0`, and the associated network
resource. Its `start-connect`/`finish-connect` state machine, socket address/network
arguments, pollables, stream pair, bind/listen/accept, socket options and separate
shutdown directions differ from the candidate's canonical async connect to an
approved alias/port and activation-owned bounded chunks.

A future closed composition slice would have to map one in-progress connect to
one owned future; retain socket/stream parent resources across pollable lifetime;
translate would-block, EOF, partial writes and sticky errors without fake success;
refuse bind/listen/accept, arbitrary options and unsupported half-close; and
preserve exact address grants, deadlines, byte ceilings and cancellation. The
WASI network resource cannot mint ambient host authority. Returning a success
stub or merely renaming imports would violate these contracts. Unknown imports
must still fail normal preparation. This PR implements **no WASI adapter** and
makes no claim about other WASI versions.

Language callbacks similarly need declared source API/version, thread/suspension
rules, returned-buffer ownership, closed-handle semantics and error mapping. An
application may provide unprivileged guest glue, but it cannot fabricate a broker
session, widen a grant, introduce automatic replay or hide an unsupported native
runtime. Injection-only paths must not be advertised as drop-in compatibility.
