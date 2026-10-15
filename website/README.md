# Documentation website

The website builds the authoritative `docs/` and `adr/` sources directly. It has
no separately edited copy of current guides. Released documentation snapshots
retain their recorded source and bytes.

Follow [Website development and validation](../docs/development/website.md) for
the pinned Node/npm toolchain, authenticated preparation, clean installation,
checks, builds and browser review. Its commands are the maintained installation
sequence. The npm derivation's source, offline mode and explicit maintainer-only
refresh behavior are defined in [the preparer](toolchain/prepare.py); normal
installation authenticates the committed lock and executes no dependency
lifecycle scripts.

For a documentation change:

- Edit current guides under `docs/` and decisions under `adr/`.
- Keep task navigation in [the sidebar builder](lib/navigation.mjs) and task
  discovery in [the catalogue plugin](plugins/discovery.mjs). Application tasks
  belong in the guides; dated acceptance and handoff records belong in
  [engineering records](../docs/development/engineering-records.md).
- Run `python tools/validate_docs.py` from the repository root, then the website
  check, tests and both project/root builds from the website guide. Select the
  browser checks for the changed navigation, examples or version behavior.
- Keep published snapshots unchanged. Use
  [versioned publication](../docs/development/website-versions.md) and
  [Pages publication](../docs/development/website-publication.md) when preparing
  an explicitly authorized release.

The [coverage matrix](content/coverage.json) retains its reviewed guide and
execution evidence. Adding a catalogue task does not approve a coverage row or
qualify guest/runtime execution. Fresh build identities are generated under
`.generated/`; historical checkpoints describe only their original runs.
