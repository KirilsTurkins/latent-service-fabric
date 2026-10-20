# Current native products for SDK qualification

`sdk-native-products.yml` builds the same five native products and managed-guest
Cargo profile used by the normal SDK pipeline. It retains one immutable copy of
the CLI, node, packager, contract exporter and demonstration signer. The
activation-runtime tenant-binding change needs a newly compiled node before
actual standalone calls can exercise those bindings; historical products do
not contain that feature.

The separate 25-minute lane uses the pinned compiler and lock, two build jobs,
original debug assertions and overflow checks, bounded owned commands, and
source identities checked before and after compilation. Every copied binary
is checked against its just-built source product. The public receipt declares
the selected profile, compiler, exact source/material/product identities and
commands. Failed build logs are retained within the same bounds.

This is a product build, not signed SDK qualification. It compiles no guest
components, performs no release publication, and does not relabel an earlier
normal receipt. Each consuming programme must authenticate the actual producer
job/artifact and independently execute its required signed cases.

The same source build executes the three bounded HTTP refusal observer controls.
The observer is disabled by default; its opt-in output uses fixed literals and
a maximum of 16 records. It preserves the original error and adds no request,
retry, grant or admission capacity. A consuming Java run must explicitly enable
it to distinguish active-dial refusal from the later typed HTTP conversion.

The current signer adds an explicit `demo-sign-neutral-resources` fixture
command for a fresh package around an original observed component. It preserves
world/export identity, embeds the original observation verbatim and a separate
packaging derivation, and verifies the new package for the two explicit test
tenants. It grants no authority and compiles no guest. The same hosted build
runs its three scoped source/guard controls before retaining products.

## Initial Wasmtime 48.0.7 tuple (historical)

[Run 39480948895](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39480948895),
job 118829053989, built the five normal managed-guest products at exact source
`724686748d39d84c86ac6ec053f615b887642e94`. Artifact 12292667379 is
66,110,576 bytes with SHA-256
`7cf353169b2cdffd240a5b58e87b63d1e4db46892654730197def581bfd05998`.
All 31 archive members were checked against their CRC and SHA-256; the two
receipts bind 3,315 native source files, 114 auxiliary inputs and all five products.
The twelve bounded commands passed, including thirty native controls with no
ignored tests. This producer compiled no guest components and provides no signed
guest qualification.

This first tuple predates the later test-fixture and trust-dependency repairs.
It remains historical evidence with its original source and product identities.

## Patched current Wasmtime 48.0.7 tuple

[Run 39495029026](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39495029026),
job 118877777415, built the five products at exact source
`fc9b44a6b8dce9effd6b490f1a169a7ad8edbf12`, including patched rustls-webpki
0.103.16 and webpki-roots/webpki-root-certs 1.0.10. Artifact 12298206858 is
66,152,643 bytes with SHA-256
`c29154ac4c9e44f6c29bf7524104832589152f03cfabfdb9a3f42e01eddb4486`.
Independent verification checked all 31 ZIP members' CRC and SHA-256, all 3,315
Git source files, 114 auxiliary inputs, the five product hashes and all twelve
commands. The ten native test stages passed exactly 30 controls with zero failures
or ignored tests. No guest component was compiled or signed by this producer.

`tools/wasmtime_48_0_7_native_products.py` selects only this final immutable tuple
and its explicit `workflow_dispatch` event. The shared reader retains `push` as
its default and refuses any other event or foreign source, workflow, branch, job
or artifact. Historical 48.0.6 wrappers, the earlier 48.0.7 tuple and their receipts
remain separate. Later source composition requires the complete native and
auxiliary input identities to match; unrelated metadata does not rewrite the
producer's source attribution. The native release candidate workflow builds three
release binaries and VM fixtures; its results do not substitute for these five
SDK products or their selected profile.
