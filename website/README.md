# Isolated documentation website

The authoritative operator/author instructions are in
[`docs/development/website.md`](../docs/development/website.md), with the ownership
decision in [ADR-0041](../adr/0041-publish-single-source-version-bound-documentation.md).

Use Node 24.19.0 and Python 3.11 or newer. The separately locked `toolchain/`
selects npm 11.19.1 with the explicitly named `npm-11.19.1-lsf-bundle-v1`
security derivation. It replaces the complete bundled `ip-address`, `undici`, and `brace-expansion`
packages with 10.7.2, 6.28.1, and 5.0.12 **before executing npm**; ordinary npm overrides
cannot replace bundled bytes. This is not an upstream npm release or an advisory
waiver. The input archives, derived TAR and complete package inventory are pinned;
no downloaded package code runs during preparation. Outputs stay in `target/`.

From this directory in a POSIX shell:

```sh
python3 toolchain/prepare.py
npm ci --prefix toolchain --ignore-scripts --no-audit --no-fund
node scripts/check-package-manager.mjs
export PATH="$PWD/toolchain/node_modules/.bin:$PATH"
npm ci --ignore-scripts --no-audit --no-fund
npm run check
npm test
npm run build
npm run build:root
npm run browser:install
npm run test:build
```

Preparation rejects altered inputs or a derived archive that differs from the
reviewed lock. `--offline` uses only already cached, authenticated inputs.
Maintainers can explicitly use `--refresh` to generate an unlocked candidate,
then regenerate/review the toolchain lock and its security-inventory pins; normal
installation must never use that flag. Re-run preparation without `--refresh`,
perform a clean `npm ci`, and run the installed-package checker before acceptance.
Both package graphs remain in the security inventory. Lifecycle scripts stay off.

`npm run start` previews on loopback only. Builds consume `../docs` and `../adr`
without moving or duplicating them, and never compile Cargo/SDK code or start an
LSF node. Local outputs are development-only; #345's other children and #237
still own guide acceptance, versions, theme, search, Wiki migration and Pages.

The [dated validation checkpoint](evidence/foundation-2026-09-19.json) records
the exact observed source and npm lock, not a perpetual passing badge. Rebuild
the current head using these commands; `.generated/build-evidence.json` records
that run's identity. Parent review owns ADR acceptance and merge. Coverage's
27 practical-guide reviews remain pending and its acceptance-mode failure is
intentional until their delegated owners provide reviewed execution evidence.
