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

This supplies reusable encrypted fixture input for #688/#691/#692/#693 and
their shared HTTP tests. It executes no signed guest and certifies no provider,
kernel ownership bound or complete HTTP-client ticket. Existing plain peer
source and receipts remain unchanged; signed consumers must separately retain
their actual authority, result and physical-retirement evidence.
