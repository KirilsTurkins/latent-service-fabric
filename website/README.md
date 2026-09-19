# Isolated documentation website

The authoritative operator/author instructions are in
[`docs/development/website.md`](../docs/development/website.md), with the ownership
decision in [ADR-0041](../adr/0041-publish-single-source-version-bound-documentation.md).

Use Node 24.19.0 and npm 12.0.1. From this directory:

```text
npm ci --ignore-scripts --no-audit --no-fund
npm run check
npm test
npm run build
npm run build:root
npm run browser:install
npm run test:build
```

`npm run start` previews on loopback only. Builds consume `../docs` and `../adr`
without moving or duplicating them, and never compile Cargo/SDK code or start an
LSF node. Local outputs are development-only; #345's other children and #237
still own guide acceptance, versions, theme, search, Wiki migration and Pages.
