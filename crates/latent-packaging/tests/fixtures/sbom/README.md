# Small SBOM format fixtures

`browser-inputs.json` inventories the existing browser example's two actual asset
files. `browser.cdx.json` is the exact 1575-byte output of the Rust SBOM generator,
with SHA-256
`e7f5b4cdf632c4c664bd718529ab8df636599c7447276ed9b1bd045a8855e2c9`.
No package, compiler output or private path is retained here.

The normalized input and generated output pass their LSF schemas; the output also
passes the pinned offline CycloneDX 1.6 schema. The byte fixture keeps encoder
and interoperability checks tied to the same real output. It contains no signing
authority or complete dependency/license claim.

To regenerate deliberately, build the maintained browser source recipe with
`build-with-sbom` and this normalized input, using a fresh temporary output
directory. Copy only `layers/package/sbom.cdx.json` after validation; do not retain
the package directory as another fixture.
