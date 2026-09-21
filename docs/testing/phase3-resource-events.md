# Event resource checkpoint

The bounded Rust checkpoint passed at source
`5b0d074ecf3b84e4b9bfca7d4d6ac6dd4c3bea4d`, with **84 actual observations**
across HTTP, blob, secret, event and child-call populations. Its exact
[run receipt](phase3-resource-evidence/2026-09-20-event-run-06.json) and
[observations](phase3-resource-evidence/2026-09-20-event-observations-06.json)
retain binary, compiler, Cargo profile, source-input digest and host conditions.
Adjacent `.sha256` files bind the unchanged raw bytes.

Fourteen observations cover the event provider at configured running ceilings
one and two. Each ceiling executes four acknowledged real guest publications:
one cold connection followed by three connection reuses. Preparation and each
cold/warm latency are recorded separately. A second population holds actual
TLS publications after peer receipt, measures active owners, cancels the guests,
and observes reclamation before shutdown. The next cold connection starts only
after the first connection is established, respecting the separate bound on
concurrent dials.

| Held publications | Active connections / running requests | Process threads | Sockets including controlled peer | RSS bytes |
| --- | --- | --- | --- | --- |
| 1 | 1 / 1 | 9 | 3 | 61,280,256 |
| 2 | 2 / 2 | 9 | 5 | 62,349,312 |

After cancellation, both populations report zero active connections, running
requests, I/O calls/buffers and live guest Stores. The broker retains bounded
provider/plan metadata; those fixed registrations are not active guest owners.
Each peer and provider pool is explicitly shut down. A lost acknowledgement
remains an uncertain effect; it is not automatically replayed.

The controlled TLS peer implements the maintained protocol fixture. These
numbers do not claim durable JetStream acceptance, standalone node density or
renderer-heap measurement. The shared Docker Desktop host allowed three CPUs
and 6 GiB while other bounded qualification ran; non-atomic OS snapshots include
the in-process peer. RSS and retained allocator bytes are different quantities.
The OCI token/resolver/redirect, publication-deduplication and renderer-heap
measurements remain required by #239.
