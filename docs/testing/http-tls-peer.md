# Controlled HTTPS peer

The additive `TLSPeer` uses the existing HTTP parser, credential checks, vectors,
gates and socket/contact limits over real TLS1.2/1.3 with HTTP/1.1 ALPN. Each
accepted socket occupies its original slot during the handshake too. Handshakes
have a five-second deadline inside the original peer lifetime. TLS readiness
resumes the pending read or write, retains an unaccepted write buffer unchanged,
and drives already-decrypted bytes without releasing an explicitly held gate.

Fixture origins are HTTPS loopback endpoints. A disposable certificate names
the loopback IP; its separately scoped trust root is an explicit operator test
input. Credentials remain private fixture inputs. Neither private keys nor
authorization values enter observations, guest packages or snapshots. This
transport fixture advertises JSON, error-status and held-header/body vectors;
the existing plain HTTP redirect vectors are explicitly unavailable here.

Ten portable controls cover readiness direction, exact pending buffers, bounds,
ALPN, held gates, CLI startup and typed receipts. The separate finite Linux lane
generates its disposable key outside the retained output and requires six real
controls: TLS1.2/1.3 parsed JSON, wrong hostname, untrusted issuer, stalled
handshake retirement and early TLS body close. Its receipt includes the public
certificate, source/tool identities, contacts and peer teardown. The same six
transport cases pass in a local Python/OpenSSL reference. The [hosted Linux run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39455143226)
passed the same six cases and ten portable controls. Independent review checked
the complete two-member artifact, public certificate and all nine Git source
materials; the [retained proof](evidence/http-tls-peer-reference-2026-10-20.json)
records the exact tested commit and artifact digest.

The owned `tools/standard_http/process_peer.py` CLI also accepts the explicit
`--certificate` and `--private-key` pair. Omitting both retains the ordinary
plain HTTP peer. Incomplete pairs, relative paths and oversized or nonregular
TLS inputs fail before opening a listener. A separate process reference runs
TLS1.2 and TLS1.3 domain requests and rejects a wrong hostname, then requires
the original peer's final observation and a reaped subprocess. The [hosted
process run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39474063983)
passed all eleven portable controls, the original six TLS cases and these three
process cases on source `7342a32034824bdae7547314e686e53685a672d3`.
The [original public receipt](evidence/http-tls-process-peer-reference-2026-10-20.json)
retains all eleven Git material identities, exact TLS1.2/TLS1.3 contacts and the
rejected handshake with zero HTTP requests. The historical six-case proof above
is unchanged.

This supplies reusable encrypted fixture input for #688/#691/#692/#693 and
their shared HTTP tests. It executes no signed guest and certifies no provider,
kernel ownership bound or complete HTTP-client ticket. Existing plain peer
class and historical receipts remain unchanged; signed consumers must separately retain
their actual authority, result and physical-retirement evidence.
