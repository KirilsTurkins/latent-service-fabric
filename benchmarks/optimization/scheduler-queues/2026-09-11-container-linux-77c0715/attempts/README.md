# Separate smoke and regression witnesses

These diagnostics are separate from the qualified full archive. The original
neutral and matched smoke each completed 14 collectors and 1,344 offers, with
nonzero selected allocation coverage in both arms. Their inspection receipts
are retained under `neutral-smoke/` and `matched-smoke/`.

The before-fix final-owner Drop regression intentionally failed while the state
mutex was held; the after-fix check passed. The first selected-cancellation race
test incorrectly expected same-ID admission before the old permit was disposed.
Its retained failure showed `AlreadyExists`. The corrected test respects that
ownership and passed both pool outcomes; no product admission bypass was added.

The [manifest](manifest.json) describes each attempt. The
[supporting manifest](../validation/supporting-manifest.json) records exact
original paths, hashes and sizes, including quiet zero-byte wrapper logs that
are inventoried but not published. Original raw smoke roots were stored separately at publication;
these small diagnostics are not a replayable full-population package.
