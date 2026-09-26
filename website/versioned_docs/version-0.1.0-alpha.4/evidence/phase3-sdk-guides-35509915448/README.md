# Six-client guide qualification

[CI run 35509915448, attempt 1](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35509915448)
passes the native provider matrix for PR #418. The tested merge revision is
`52819edceba07106ac94d6161fcdb5e561aafc0b`, with PR head
`8dfcc11583a718a9da2f65ff2f2b162d68a452d6`. Every registered snippet source
and its validation script have identical Git blob bytes at those two revisions.
The 18 example records bind those exact source and validation hashes to the
reachable PR head; they do not treat later edits as already executed.

The files in this directory preserve the seven original JSON receipts from the
run's `phase-1-bounded-conformance` artifact. [matrix.json](matrix.json) binds
each language receipt by SHA-256 and records the common CLI, node and signed
fixture hashes. Rust, TypeScript, Go, C, Java and C# each pass 18 assertions:
108 assertions, 54 activation IDs, six policy operation receipts, 24 physically
closed held requests, six clean node shutdowns and fully reaped client owners.
The controlled upstream records no unauthorized or unexpected requests.

These are real native clients against separately owned authenticated nodes,
executed HTTP/blob guests and a controlled HTTP provider. The evidence does not
qualify a browser client, installed release bundle, external provider vendor,
resource campaign or newcomer pedagogy review. The latter remains pending in
[#358](https://github.com/KirilsTurkins/latent-service-fabric/issues/358).
