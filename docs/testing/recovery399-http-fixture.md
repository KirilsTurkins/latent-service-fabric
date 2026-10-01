# Older backup after a remote HTTP effect

The maintained native test
`tests::effects::restore::older_protected_backup_keeps_applied_http_effect_paused_until_explicit_review_and_resume`
uses the common atomic command envelope, protected Linux/ext4 offline recovery
ports, fixed dispatcher and the synthetic TLS put-once endpoint from
[the qualified HTTP effect profile](../reference/qualified-http-effects.md).
Its source is a test fixture; execution requires a source-matched native receipt.

The common envelope commits an aggregate value, original command and result,
an inbox identity, pending effect and immutable payload together. After actual
normal storage-owner retirement, the offline worker exports one bounded logical
snapshot to a private operator directory. It validates command/result/inbox and
effect/payload links, schema and original source associations, and the installed
decoder/profile inventory. Missing required contract metadata refuses export;
a different runtime refuses restore before staging a root. The snapshot is
mode `0600` and remains inside the test's protected temporary directory.

After backup, the test explicitly resumes the original namespace and runs the
real dispatcher. The endpoint durably applies the effect, a controlled proxy
loses its reply, and the existing bounded lookup recovers its receipt. Restoring
the older snapshot preserves the original effect ID, request bytes, body hash,
business incarnation, command/result/inbox identities and remote horizon. It
increments the local recovery epoch and leaves the restored history paused.

An explicit recovery-window review alone leaves the namespace paused. The test
installs the actual unpaused dispatcher and checks its bounded candidate page,
zero accepted claims, physical shutdown and unchanged remote mutation counter.
Namespace resume separately rechecks present effect authority; revocation and
backward local time refuse it. Only explicit approved resume permits an equal-ID
delivery. The remote durable counter remains one, and the original receipt is
returned. An old view token fails the current minimum-view check, and historical
result policy metadata alone does not grant result access.

Run on the qualified Linux/x86-64 ext4 fixture root with the pinned repository
toolchain:

```sh
LATENT_STATE_TEST_ROOT=/owned/ext4/fixtures cargo test -p latent-http \
  --all-features --locked \
  tests::effects::restore::older_protected_backup_keeps_applied_http_effect_paused_until_explicit_review_and_resume \
  -- --exact
```

The ordinary maintained HTTP owner retains all existing cases and adds this
case to its exact native inventory. Do not publish snapshot payloads or credential
files as CI evidence. Record source, toolchain, test executable and bounded test
results separately. This fixture uses an installed synthetic operator review and
empty admitted component bytes; it makes no Java execution or production
publication/grant qualification claim. It does not certify arbitrary HTTP APIs,
rollback remote mutations, or cover unknown post-backup commands. The broader
management, retained rejection/expired-result, consumer replay and operational
reconciliation surfaces in #398/#399 remain separate acceptance work.
