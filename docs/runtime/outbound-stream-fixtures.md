# Controlled outbound stream peer

`tools.outbound_stream_fixture.SmtpPeer` is a finite local SMTP mutation sink for
the operator and six-language stream qualification work in
[#739](https://github.com/KirilsTurkins/latent-service-fabric/issues/739) and
[#740](https://github.com/KirilsTurkins/latent-service-fabric/issues/740). It accepts
ordinary SMTP clients, including their normal dot escaping. It opens one
loopback listener and creates no thread, forwarding connection or retry.
The qualification owner drives its selector and calls `close()` in cleanup.

```python
import selectors
from tools.outbound_stream_fixture import SmtpPeer

with selectors.DefaultSelector() as selector:
    peer = SmtpPeer(selector, drop_mutation_reply=True, fragment_bytes=7)
    try:
        # The node operator explicitly grants this exact loopback destination.
        # The qualification owner runs its separately authenticated guest here.
        for key, events in selector.select(timeout=0.1):
            key.data.event(key, events)
        peer.check()
        observation = peer.observation()
    finally:
        cleanup = peer.close()
```

For a complete DATA command, the peer records the accepted connection ordinal,
normalized message length and SHA-256, and recipient count. It retains no
message, envelope address or AUTH input in its observations. With
`drop_mutation_reply=True`, it records that mutation and closes the connection
before sending its successful reply. Accepted mutations and sent replies
are separate counters. A sent reply means all reply bytes were submitted to
the local socket; it does not confirm client receipt or a remote outcome.
Client confirmation remains unobserved. The caller must preserve the guest's actual disposition
and inspect the independently observed connection count before making a replay
claim. The peer never infers a guest outcome.

Bounds are two concurrent connections, 32 accepted connection attempts, one
message per connection, 65,536 message bytes, 4,096 bytes per line, 128 commands,
and 4,096 pending reply bytes. A connection expires after two idle seconds or
ten absolute seconds. The listener retires at the attempt ceiling; its accepted
connections remain owned until closed. The qualification owner has at most
900 seconds for the peer lifetime. Output fragments are explicitly selected
between one and 1,024 bytes. These fixture limits do not replace or widen any
node, provider, guest or protocol limit.

The maintained Python controls use a real SMTP library and sockets to check
normal and lost replies, exact and exceeded message bounds, fragmented output,
truncated DATA, idle expiry, active connection and attempt ceilings, listener
ownership, and observation redaction. These are source controls for the peer.
Actual signed component execution, provider authority, rotation, quarantine,
TLS credentials and all six SDK ports still require their separate acceptance
observations. The peer installs no provider, grants no authority, and enables
no production stream profile. The architecture/security prerequisite in
[#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737) remains.
