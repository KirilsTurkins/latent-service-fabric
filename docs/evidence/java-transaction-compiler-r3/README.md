# Actual Java transaction compiler checkpoint

All five explicitly selected authored Java variants compiled with the maintained
TeaVM C backend, pinned JDK 25.0.4.1, Gradle 9.1.0, WASI SDK 29, wit-bindgen 0.62.0
and wasm-tools 1.254.0. The actual Component Model output passed validation and
its exact final WIT surface comparison. The three schema variants retain their
original application data codecs, opaque pre-write NV2/SV2 observations, one
27-byte deferred put-once intent, and exact original companion/requirements bytes.

The frozen compiler source is `ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6`.
The explicit five-variant recipe was introduced at `1f8944ca`; the subsequent
source fix stages the forbidden HTTP dependency under the same nominal package
directory as the compiler. Every project was captured before compilation and
remained unchanged. This is portable compilation evidence. The components are
unsigned, and signing, admission, forbidden-import rejection, atomic state/intent
commit, HTTP dispatch and schema migration have not been qualified by this run.
Both execution/admission qualification flags remain false.

The independently authenticated compiler bundle retains producer source
`761172002e4a4d02102f8c757235b888fe4859e1`, its approved candidate policy and its
original Phase 3 tool assembly ABI. That assembly is separate from the Phase 4
WIT source compiled here. The retained verification output checks the publisher
attestation with the independent pinned GitHub verifier and trusted root. The
large compiler/tool archives are identified by digest rather than duplicated.

`portable-receipts-r3.tar.gz` contains all actual components, complete captured
projects, source archives, source/recipe/compiler input inventories, generated
bindings and WIT, and bounded compiler command logs. Its exact 848-file inventory
is separately hashed. It also retains both earlier failed controllers: the first
rejected an oversized outer timeout before compilation; the second compiled the
ordinary aggregate but exposed duplicate `latent:http@0.2.0` package directories
in the real forbidden-import fixture. The successful third attempt used a fresh
output directory and the corrected published source, with no compiler limit change.

The archive's preliminary envelope checksum did not match its finalized bytes.
That preliminary descriptor is retained. Every final member's original digest,
full gzip CRC, and zero-only tar padding were checked before recording the final
archive digest; all 848 original file digests matched. This correction changes
only the archive envelope descriptor, not any component, input or compiler receipt.

The normal development merge was checked separately. Its 95 focused cases and
CI coverage passed. The 44 dependency/helper cases passed on Linux with no skips;
the Windows attempt retained its existing symlink privilege error and six
original platform skips. No test guards or skip conditions were weakened.

Original zero-byte streams are retained as [explicit empty-stream encodings](original-empty-streams.json).
Each record preserves its original name, zero-byte length, SHA256, original Git
blob identity and empty base64 content. Reconstructing that content yields the
exact original bytes; existing receipts, compiler archives and their identities
remain unchanged.
