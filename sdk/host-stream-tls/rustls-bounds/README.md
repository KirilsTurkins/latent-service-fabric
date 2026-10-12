# Captured rustls parser bounds

This private direct TLS candidate retains the original rustls 0.23.45 archive
identity, exact original/modified file identities, upstream license texts and
the five-file patch in `PATCH.json`. `tools/host_stream_tls_patch.py` verifies
the upstream archive before applying only those five modified files to a fresh
owned tree. It neither edits nor adopts a shared Cargo source/target directory.

The captured profile bounds certificate lists to eight entries, certificate
authority-name lists to sixteen, other TLS list elements to sixty-four and owned
certificate extension bytes to 4,096 per entry. The list bound is checked before
decoding the next element and its owned extension/name allocation. The handshake
deframer accepts at most thirty-two fragment spans before allocating another
span, including coalescing. All original 256 KiB TLS connection and 64 KiB trust
reservations remain unchanged.

These are deliberate compatibility limits of the candidate host TLS profile.
They do not certify guest TLS, client authentication, STARTTLS or a complete TLS
implementation. The normal TCP profile, endpoint policy and production gates
remain unchanged. Direct TLS installation stays refused until the parser,
transport and actual allocator/retirement qualification pass.

`allocation-reference.rs` uses the actual pinned rustls `MessagePayload`
decoder. Its `System` allocator observer is restricted to the outside production
reference executable. Input generation and logging stay outside the observed
parser region; dropping every parsed result must return observed allocation to
zero. The original parser must fail the unchanged allocation ceiling on the
5,000 tiny-certificate vector, while the bounded decoder must reject that vector
and admit the reviewed normal chain/name vectors without exceeding the same
ceiling. Huge declared lengths and truncation are separate rejection cases.
Parser measurements alone do not prove a live encrypted TLS connection's full
allocation, native peak or physical owner retirement.

Run the maintained reference with explicit pinned tools and a fresh owned output:

```sh
python3.13 -m tools.qualify_host_stream_tls_parser \
  --archive /owned/public/rustls-0.23.45.crate --output /owned/reference \
  --cargo /pinned/bin/cargo --rustc /pinned/bin/rustc
```

The runner authenticates upstream bytes before creating either private source,
builds offline with captured locks, retains the original over-allocation failure,
and checks every bounded vector and post-drop allocation. Its receipt explicitly
leaves full TLS accounting and provider installation unqualified. The QUIC
deframer call site propagates the same new rejection result so this private
crate compiles without discarding the object bound; QUIC remains unavailable
in the LSF outbound profile.
