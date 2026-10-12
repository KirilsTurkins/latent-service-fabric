# Executed native-cache profile restart regression

The complete registered `latent-wasmtime.test.native-aot-cache` suite passed at
source `6c0e6c1fb4645f72b7ecd6545bc4c34888236c89`: five passed, zero failed,
ignored or filtered. The unchanged 900-second suite bound includes the build;
the complete command took 183.445192 seconds and the tests took 17.05 seconds.
[The original log](original-native-aot-cache-suite.log) and
[verified suite receipt](verified-suite.json) retain all five actual outcomes.

`buffered_web_profile_change_after_restart_cannot_reuse_a_stale_native_image`
compiled and invoked the real signed component, released the old runtime and
catalog owners, then reopened the same persistent roots, source and signing key
with a changed buffered-web string bound. It observed no old cache hit and one
fresh isolated compilation; only the newly authenticated image reached the
loader. The other cases cover unchanged-profile persistent reuse, compiler
configuration changes, retained ownership/revocation, and tampered image bytes.

The Linux process ran as UID/GID 10001 with debug assertions, overflow checks
and required native process tests enabled. The entire committed source was
mounted read-only and stayed clean. A read-only retired build cache was copied
to a private target before this attempt; Cargo compiled the selected current
source and no previous test result was used as a pass. The executed test binary,
source tree, bounded command, cache ownership and original log digests are
recorded by [the independent review](review.json) and
[source identity](source-identity.json).

The preceding attempt has no passing suite receipt. Its compilation log and
later existing-output-log startup failure remain retained outside disposable
worktrees with their identities in the review. This successful attempt used a
new output directory and preserves those earlier results.

This is the separate Rust native-cache verification owner for criterion 5 of
issue #708. [The Java composition evidence](https://github.com/KirilsTurkins/latent-service-fabric/blob/83e5905cfed7f241449aafccfc38b5bdeb8bc22a/docs/evidence/java-composed-c4-3b7/README.md)
keeps its own original runtime, Java compiler and qualifier identities. This
receipt does not establish full repository CI, private reporting-application
execution or native-cache loading of the Java campaign's components.
