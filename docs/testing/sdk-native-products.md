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
