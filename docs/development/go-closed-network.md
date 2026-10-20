# Refuse the upstream Go test-only socket network

Go 1.27.2's `net/net_fake.go` is selected for WASI and implements an in-memory
socket network for upstream tests. Its `socket` entry allocates a fake file
descriptor, then calls `fakeListen` or `fakeConnect`. This is not an authorized
LSF network provider. Before this correction the maintained compiler did not
replace that entry, so the closed WASI adapter alone could not prevent fake
socket success.

All maintained LSF Go runtime profiles now authenticate the complete upstream
file (`784b369c57be52fa87ace5f10e07e3c24b45d549639e1487734b793024188df3`)
and replace only that socket body with `errors.ErrUnsupported`. No fake socket,
buffer, listener or implicit connection queue is allocated by that entry.
Unknown preimages fail before any overlay output. GOROOT and the explicit
upstream WASI comparison remain unchanged. The already selected typed HTTP
backend remains independent; this change installs no raw-stream provider or
authority. A future declared-stream compiler port must use its owned backend
and cannot fall back to this fake network.

The old-source default-overlay control fails because its replacement map has
no `net/net_fake.go` entry. The corrected overlay and preimage/refusal controls
pass. The existing overlay fixture additionally supplies this exact pinned
input; all original test cases remain, with the strict replacement count
increased from nine to ten.

The small hosted reference builds the same ordinary `net.Listen` and
`net.ListenPacket` source twice with the pinned compiler: once upstream and
once with only this exact socket derivation. It requires the upstream TCP/UDP
fake listener successes and both corrected standard `errors.ErrUnsupported`
results. The owned reference runs under
[Node 24.19.0 WASI](https://nodejs.org/download/release/v24.19.0/docs/api/wasi.html)
with no directory preopens or guest environment. It is not an untrusted-code
sandbox or an LSF runtime/provider. The exact-source execution is recorded below. No LSF native host or original SDK programme is
rebuilt or repeated by this lane.

This advances a concrete closed-network boundary for
[#742](https://github.com/KirilsTurkins/latent-service-fabric/issues/742) and
[#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736).
It does not qualify standard networking, signed protocol clients, TLS, native
socket accounting or the missing maintained-kernel/final-free producer. Those
requirements remain open.


## Actual bounded reference

[Run 39410414538 / job 118586516177](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39410414538/job/118586516177)
passed on exact source `6757c7f6863cb1cce078e63899360d31223e6f08`.
The [independently checked observation](../testing/evidence/go-closed-network-reference-2026-10-20.json)
binds artifact 12258913361 (2,056,243 bytes,
SHA-256 `6b06948292b365fa3da437cc0a5a7649d12bffde7c5c4f9bbcae21d8beb60c45`),
all 19 member digests, both compiled Wasm modules, exact source/recipe inputs,
and Go 1.27.2 / Node 24.19.0 tool identities. Both builds had empty compiler
stdout/stderr. The raw upstream result was `tcp=fake-listener` and
`udp=fake-listener`; the corrected result was `tcp=unsupported` and
`udp=unsupported`. The same unchanged application exercised both builds.

This proves the upstream fake-success counterfactual and concrete standard
Unsupported replacement in that owned WASI reference. It is not a signed LSF
component execution or a network/provider/kernel qualification. No original
SDK programme or native host build was repeated for this observation.
