# Isolated documentation website

The authoritative operator/author instructions are in
[`docs/development/website.md`](../docs/development/website.md), with the ownership
decision in [ADR-0041](../adr/0041-publish-single-source-version-bound-documentation.md).

Use Node 24.19.0 and the locally patched npm 11.19.1. Complete the
[security bootstrap](#package-manager-security-bootstrap) from the repository
root first, then run these commands from `website/`:

The separately locked `toolchain/` package selects npm 11.19.1 as its reviewed
base and replaces its vulnerable bundled `ip-address` before use. Both the
package-manager graph and website graph are included in the security inventory.
CI verifies every installed package-manager version against that lock and
disables dependency lifecycle scripts. The reviewed source and reason are in
`content/toolchain.json`; a higher npm major is not an automatic upgrade.

```text
node toolchain/node_modules/npm/bin/npm-cli.js run check
node toolchain/node_modules/npm/bin/npm-cli.js test
node toolchain/node_modules/npm/bin/npm-cli.js run build
node toolchain/node_modules/npm/bin/npm-cli.js run build:root
node toolchain/node_modules/npm/bin/npm-cli.js run browser:install
node toolchain/node_modules/npm/bin/npm-cli.js run test:build
```

`node toolchain/node_modules/npm/bin/npm-cli.js run start` previews on loopback only. Builds consume `../docs` and `../adr`
without moving or duplicating them, and never compile Cargo/SDK code or start an
LSF node. Local outputs are development-only; #345's other children and #237
still own guide acceptance, versions, theme, search, Wiki migration and Pages.

The [dated validation checkpoint](evidence/foundation-2026-09-19.json) records
the exact observed source and npm lock, not a perpetual passing badge. Rebuild
the current head using these commands; `.generated/build-evidence.json` records
that run's identity. Parent review owns ADR acceptance and merge. Coverage's
27 practical-guide reviews remain pending and its acceptance-mode failure is
intentional until their delegated owners provide reviewed execution evidence.

## Package-manager security bootstrap

From the repository root, install and verify the toolchain before invoking it:

```sh
npm ci --prefix website/toolchain --ignore-scripts --no-audit --no-fund
node website/scripts/patch-package-manager.mjs
node website/toolchain/node_modules/npm/bin/npm-cli.js ci --prefix website --ignore-scripts --no-audit --no-fund
```

The reviewed npm 11.19.1 tarball still bundles `ip-address` 10.5.0. A normal
npm override or a lockfile-only edit
does not replace bundled files. The explicit bootstrap therefore copies the
complete, separately installed and SHA-512-pinned upstream 10.7.2 package
over npm's bundled copy, removes stale hidden lock inventories, and verifies
every locked dependency before the selected npm performs any work. It never
enables dependency lifecycle scripts or downloads code itself.

The toolchain lock describes the final patched installation, including both
copies of 10.7.2. A bare `npm ci` is only the first bootstrap step: always run
the patch command after a clean reinstall. The read-only identity checker
rejects an unpatched installation. When refreshing this lock, retain the
separately pinned replacement entries and run the clean-install regression;
do not accept npm's regenerated 10.5.0 bundle record. Remove this replacement
only after reviewing an npm distribution whose actual bundle is patched.

The regression exercises the package resolved from npm's SOCKS dependency,
including local-use NAT64 boundaries, several prefix layouts, loopback,
metadata, private IPv4 destinations and public-address controls. It confirms
that the entire `64:ff9b:1::/48` range is private without guessing an embedded
IPv4 address. This addresses [GHSA-2vr4-cq9g-pvrc](https://github.com/advisories/GHSA-2vr4-cq9g-pvrc)
in build tooling; it is not evidence of a reachable LSF runtime SSRF exploit
or a replacement for DNS, connected-peer and redirect validation.

The same bootstrap replaces npm's bundled `brace-expansion` 5.0.9 with the
complete, separately SHA-512-pinned 5.0.12 package. Its `balanced-match`
dependency is locked for both the standalone source and npm's bundled graph.
The verifier checks the package actually resolved by npm's `minimatch`,
normal expansion, nesting limits and rewrite limits. A bounded child-process
regression covers chained comma parsing, nested groups and rewrite-heavy input.
This addresses GHSA-6j4f-fj2g-mc7p, GHSA-qhr7-859c-m2p7 and GHSA-q2hr-2g5m-vwhr
without suppressing advisory findings. Retain all separately pinned replacement
records, including Undici, when regenerating the toolchain lock.

The `ip-address` regression also checks cross-family subnet rejection and
pre-parser address length bounds for GHSA-j6r3-76f7-8jcv and GHSA-h3mg-xc3c-68pw.

## Additional security-baseline repair

The same bootstrap also replaces npm's bundled Undici 6.28.0 with the complete,
separately integrity-pinned Undici 6.28.1 package for
[GHSA-3wwx-pv8p-q78v](https://github.com/nodejs/undici/security/advisories/GHSA-3wwx-pv8p-q78v).
The lock describes both final patched packages, not the unmodified npm archive.
The checker verifies the installed Undici bytes and npm's module resolution;
a bounded child-process regression checks normal decompression and rejects an
oversized malformed compressed message without an unhandled zlib error. Run the
same patch command after every clean toolchain installation. No lifecycle hooks,
advisory exceptions or changes to Node's separately bundled global fetch are made.

The Java compiler recipes separately select Jackson 2.18.10 in both buildscript
and project configurations. Their three jar identities and Gradle module/POM
checksums are updated together; strict dependency verification remains enabled.
This removes the three Jackson advisory matches blocking this PR's security
baseline without treating the inventory as proof of runtime exploitability.

Jackson annotations 2.18.10's published Gradle module lists a different jar
checksum and size from the final Maven jar. The reviewed lock uses the final
jar, whose bytes match Maven's separate SHA-256 and SHA-512 checksum files;
it does not permit the module's alternative jar hash. The module itself is
independently SHA-256-pinned in Gradle verification metadata.
