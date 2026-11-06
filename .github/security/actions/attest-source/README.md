# Source-verified attest dependency repairs

This fork keeps every locked package name, version, dependency declaration and
installation path. It replaces the bytes of 15 installed copies with six
reconstructed archives:

- `deepmerge` 4.3.1: the bounded prototype-key repair for
  GHSA-gcqx-w48m-w2h4.
- `glob` 10.5.0 and 13.0.6: the return-after-abort and `onResume` repairs
  from upstream commit `4682e8c9babee1b385202ede36389634e12076d7` for
  GHSA-3g3m-2fjr-6pw4. The glob 13 CommonJS and ESM minified exports also
  contain an embedded minimatch and receive its matching expansion bounds.
- `minimatch` 9.0.9, 10.2.5 and 10.2.6: the optimization bounds from
  upstream commit `77a0f5c4b80bdc641c3c930a1d9edf5ad2db57f8` for
  GHSA-g3hv-75wg-m249.

The original archives, exact source edits and deterministic repaired archives
are retained here. These are local backports, not upstream fixed releases.
The source inventory binds every upstream and repaired archive, every installed
member and the exact package lock. `npm ci` runs an installed-source guard;
production-only installs may omit development-only copies, but every installed
copy and every runtime copy is still checked. `npm run package` and `npm test`
require the full development graph and repeat the stricter check before building
or testing. The guard rejects unexpected duplicate and aliased affected copies.
Run `npm run test:security-source` for the focused controls.

A version-only advisory scanner will continue to report these six package
identities. Any recognition of the local repairs requires a separate exact
source, lock, bundle and advisory-revision verification. This fork does not
add an advisory exception. The ordinary tests use mocked attestation services;
they do not qualify a real signing or GitHub API operation.
