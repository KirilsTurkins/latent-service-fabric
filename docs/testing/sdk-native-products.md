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
