# Java HttpServer source profile

`lsf.java.httpserver.buffered.v1` compiles ordinary `com.sun.net.httpserver`
registration through the maintained TeaVM 0.15 C/component pipeline. Applications
select the profile in `capsule-project.json`; they supply their original public
static `main(String[])`, ordinary imports and source helpers. The compiler supplies
the `latent:web/application@0.1.0` bridge. There is no application-authored LSF
adapter, listener or deployed JVM.

This implementation has native AST/JDK/kernel conformance, normal component
compilation and signed normal-node routing/HEAD probes. The maintained Java
qualification also builds two outside-checkout server projects and exercises
authenticated route tooling, bounded responses and original-ledger retirement.
Complete failure, TLS, redeploy/rollback, cancellation/disconnect and packaged
frontend qualification remain required by #728. The profile is not a completed
milestone gate, general JDK networking support or an executor-enabled server
profile.

## Create and build

Run the maintained SDK commands with the exact compiler inputs described in the
[Java authoring guide](java-authoring.md):

```bash
python tools/java_capsule.py new-server /work/capsules/my-server --name my-server
python tools/java_capsule.py build /work/capsules/my-server \
  --output /work/capsules/my-server/target/build \
  --repository https://example.invalid/source/my-server \
  --wasi-sdk /tools/wasi-sdk-29.0-x86_64-linux \
  --gradle /tools/gradle-9.1.0/bin/gradle \
  --offline-cache /captured/gradle/modules-2
```

The compiler host is the pinned Linux x86-64 recipe from that guide. Build
execution, signing/admission and route authorization remain separate steps.
Keep `vendor/lsf` immutable and review a changed SDK lock explicitly.

The created source registers `/hey` on a logical wildcard endpoint, port 8080,
backlog 0, and returns `Hey!` with an exact positive response length. Port and
backlog are captured configuration values, not an OS socket observation. The
deployment operator explicitly selects the public hostname, listener and methods.

The build emits `server-analysis.json`, `server-profile.json` and
`server-source.json`. The latter two are signed package assets. Their identities
bind the selected original initializer, AST plan, captured source inventory,
compiler distributions/binaries, SDK adapter/runtime, recipe, component and final
complete WIT signature. Metadata grants no catalog or execution permission.

## Static registration and original initialization

The SDK-owned analyzer uses javac's parsed, attributed AST with `-proc:none` and
`analyze`, never `generate`, application class loading, static initialization or
startup execution. The application JAR classpath supplies symbols only. Its code
does not become the analyzer JVM's classpath or a TeaVM compiler extension.

This version captures one endpoint and at most 64 contexts. Supported discovery
uses straight-line registration and static source helpers with known arguments.
Addresses, port, backlog and context paths must be compile-time constants.
Independent helper names are unrestricted; there is no router package catalogue.
Recursive/dynamic helpers, conditional registration, source DNS, encoded paths,
duplicate contexts and unsupported members produce closed source-attributed
diagnostics. The finite analysis ceiling is 1,024 Java files, 16 MiB source,
32,768 visited nodes and 16 helper calls deep.

Every activation runs the original main to completion, including instructions
after `start`; the compiler does not delete code or force an infinite loop to
exit. Registration creates logical invocation-local objects. `start` requires
assigned handlers and finalizes registration. Before dispatch, the bridge checks
the actual bind, backlog and ordered contexts against the captured declaration.
Failure, trapping or a main that never returns does not produce a successful
response. Repeated start and live context mutation fail. Finally, the bridge
retires server/context references and zeroes owned request/response buffers.
Fresh guest instantiation remains necessary to prove fresh application statics.

## Member and behavior matrix

| API or behavior | Initial profile |
| --- | --- |
| `HttpServer.create(address, backlog)` | Positive constant port; wildcard or explicit IPv4 loopback; backlog 0–65,535. No OS bind. |
| `createContext(path, handler)`, `createContext(path)` plus `setHandler` | Constant canonical paths; once before start; lambda, method reference or source handler initialization executes in the guest. |
| `start`, original code after start | Logical finalization and ordinary original control flow; no background accept worker. |
| `setExecutor(null)` before start | Declared simple default dispatch. |
| Custom/default executor task lifecycle | Planned #736/#741 integration and separate server lifecycle qualification; non-null executor currently fails. |
| `getExecutor` after start, `getAddress`, `bind`, `stop`, context removal | Unsupported; no fake bound address, shutdown or successful stub. |
| Request method, URI/query, headers, body; context/path/handler; response code | Bounded invocation-local views. No raw target or peer/local socket observation. |
| `Headers.add/set/put/get/getFirst`, read-only map views | Case-insensitive field names; repeated value order retained. Mutable list/entry views are outside this profile. |
| `sendResponseHeaders(status, positiveLength)` | Exact finite body length; over/underwrite, second headers and writing before headers are terminal failures. |
| `sendResponseHeaders(status, -1)` | Explicit no body; writing any body fails. |
| HEAD/304 representation length, 204/205 | Empty body; permitted representation metadata; 204/205 require `-1`. |
| Response body close and exchange close | Seal/check owned bytes; sealing is not delivery or remote receipt. Failed close cannot return success. |
| Chunked length 0, true streaming/`flush` | Unsupported and fails; no buffered success substitution. |
| Filters/authenticators, TLS configurators, upgrades/WebSockets, connection state | Unsupported. Host ingress owns TLS, authentication and public admission. |
| Principal, attributes, protocol and local/remote descriptor introspection | Unsupported source members; authoritative host context remains the typed context import, never request headers. |
| `java.net.InetSocketAddress` | Captured logical marker for wildcard/IPv4 loopback; DNS, unresolved/ephemeral ports and bound descriptor discovery fail. |
| General `java.net`, Spring, Servlet, Netty | No compatibility claim. |

The request and response limits follow the
[buffered web contract](../protocol/http-applications.md): 64/256 KiB bodies,
64 fields and 16 KiB aggregate header bytes. Values preserve opaque Latin-1 field
bytes and raw body bytes. Credentials, forwarding and trace metadata remain under
host policy. Reserved response fields fail. This initial facade narrows response
media types to token `type/subtype` without parameters and representation lengths
to its 256 KiB response bound; those restrictions are explicit profile gaps.

## Equivalent authorized routes

JDK context selection is case-sensitive longest literal prefix: `/hey` matches
`/heyday` as well as `/hey/child`. A host segment prefix `/hey` is not equivalent.
For `/hey`, explicitly authorize an enclosing root mount with guest dispatch, or
reject deployment. The toolkit never invents a root mount. `/api/hey` can use an
explicit `/api` enclosing mount. Canonical paths preserve case/trailing slash,
separate queries, decode unreserved bytes once and reject ambiguous separators,
percent aliases, dot segments and reserved host routes.

Use the [shared declaration/route toolkit](server-source.md) with the exact build's
profile and source inventory. It validates actual publication/revision/generation
pins and scopes original-operation recovery, redeploy, rollback and removal to
owned routes. Wrong tenant, stale component/profile/configuration or an
insufficient mount fails before granting broader exposure. Multi-route updates
remain non-atomic.

## Qualification and raw socket boundary

`tools/qualify_java_server_analysis.py --output <fresh-directory>` executes 16
native kernel cases, 15 real javac AST vectors and seven real JDK reference
requests. It observes that an application static initializer never executes on
the compiler host. Those checks do not prove signed component admission, real
LSF listener dispatch, dormant Store ownership, cancellation, disconnect or
cross-tenant isolation. Those node-level requirements remain tracked in #728.

The existing `tools/qualify_java_capsules.py` command retains its source-only,
direct SDK, signed-node and printed-guide checks and adds ordinary-source shared
listener cases. The helper project uses original Java source outside the runtime
checkout, checks that code after `start()` runs, and observes fresh static state
on each request. Its repeated-cookie case uses the normal node's TLS listener:
the current browser policy rejects cookies on cleartext HTTP and requires distinct
`__Host-` names with `Secure`, `HttpOnly`, `SameSite=Strict` and `Path=/`. POST
fixtures carry the matching same-origin header. The private fixture certificate
is verified against its exact ephemeral CA; no production trust is installed.

Receipts retain exact component, declaration, profile, source, CLI, node and
workflow identities, routing/security denials, raw bytes, repeated headers,
handler failures and observed owner/quota retirement. A failed case retains its
own receipt and audit observations. A passing native/source check or the addition
of this lane is not evidence that the complete signed-node lane passed; use the
actual `node-my-server*/conformance.json` artifacts from that exact CI source.

A literal `ServerSocket.accept` loop returns a byte connection, not a handler
registration. This profile cannot identify an arbitrary protocol boundary or
retain/escape an unmodified infinite accept loop without changing its observable
control flow. The exact blockers are missing finite HTTP handler association,
continuation lifetime and code after accept/request handling. The maintained AST
suite includes an explicitly identified HTTP `/hey` accept loop with response
bytes and a counter after each request. Its source-attributed diagnostic is
`raw-accept-loop-has-no-finite-http-handler-boundary`: identifying those bytes
does not supply a finite handler export or preserve the loop's continuation and
counter across fresh activations. An unused accept method does not block an
otherwise supported HttpServer registration. No socket loop is silently certified
by HttpServer compilation.
