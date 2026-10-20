# Ordinary .NET libraries over HTTPS

The pending `dotnet_https_node` controller reuses an ordinary Flurl/Refit
component produced by the [captured library programme](../development/dotnet-published-http.md).
It adds no guest handler, compiler adaptation or native host build. There is no
signed HTTPS result yet; source availability does not complete #693.

The trusted profile requires eleven real signed outcomes: both libraries parse
the domain body and 404/500 responses, both cancel genuinely held headers, an
ordinary body stream is disposed early, and fresh invocations use both default
clients. Two further nodes independently require both libraries to reject a
trusted certificate with the wrong name and a server whose issuer is absent
from the explicitly installed trust roots. Those four refused handshakes must
send no HTTP request or credential.

Certificates and private credentials are disposable fixture inputs. The public
receipt retains the server certificate and the actual operator trust bytes;
private keys and authorization values are excluded. Root inputs are installed
through the normal typed HTTP provider configuration, with public roots off.
The original request, root, activation, timer, queue, memory, fuel and cleanup
bounds remain in force. Each result must be charged, resolve the same signed
component and complete the original physical/provider retirement checks. All
three nodes and TLS peers must be reaped.

This finite typed HTTP profile supplies no raw socket grant, ambient trust,
retry/redirect guarantee, kernel accounting result or complete .NET runtime
qualification. The [controlled TLS peer](http-tls-peer.md) retains its own
separate transport evidence.
