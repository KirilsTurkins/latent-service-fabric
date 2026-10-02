# Protected mutable state files

The Phase 4 storage owner opens an explicitly configured absolute local root
through `latent_protected_files::ProtectedRoot`. Its mutable engine descriptor
comes from `open_mutable_file`, and the owner retains the returned
`ProtectedMutableFile` fence. Opening and checking files belongs on the bounded
storage worker, before engine work, rather than the shared asynchronous poller.

The supported implementation is Linux x86-64. Every retained ancestor must
still identify the original directory. The final root must be private to the
current effective user. The engine leaf is a single ASCII name of at most 255
bytes, a regular file with one hard link, mode `0600`, no ACL extension, and a
declared length ceiling between one byte and 1 GiB. Symlinks, path components,
owner changes, unsafe modes, inode replacement, ancestor substitution and files
beyond the configured ceiling fail closed. Errors do not expose configured
paths or file contents.

Creation uses exclusive create, syncs the new file and parent directory, and
never creates parent directories. Opening an existing file never truncates it.
`check_mutable_file` rechecks the named inode, permissions, size and ancestry
before each storage job. The engine consumes the descriptor and owns exclusive
database locking. Filesystem qualification, persisted formats, bounded workers,
startup readiness and uncertain-write recovery remain the storage owner's
responsibility; a valid descriptor alone is not state readiness.

`create_mutable_file` is the separate exclusive initialization operation. It
refuses every existing leaf, including empty or malformed checkpoint files, and
uses the same anchored descriptor, permission and named-inode checks. The new
file and its directory are synchronized before publication. If initialization
fails after creation, the leaf remains for explicit recovery; it is never
removed or overwritten by a subsequent initialization. The existing
`open_mutable_file` operation continues to open valid existing files without
truncation.

`is_separate_from` compares retained actual ancestry before opening a separate
recovery root. It refuses equal roots and either root containing the other,
while allowing siblings with a shared protected parent. Both chains are checked
before and after comparison. The [transaction checkpoint](transaction-checkpoint.md)
uses this metadata operation without exposing native descriptors.

## Validation

The previous `latent-protected-files` library suite contained 18 tests. On
2026-09-30 the normal Linux run passed 17 tests, and the existing privileged
ownership test passed when selected explicitly with `--ignored`. Four new
tests verify creation/reopen without truncation, unsafe names/types/links/modes
and lengths, leaf replacement and foreign-root fences, and permission growth
and ancestor replacement. Strict Clippy passed for all targets.

These checks ran in the pinned Rust 1.97.1 Bookworm image
`sha256:0e2bcaef56d041a486784e54104a81aebe0da44bd03019bd70bc0401e42e4a97`.
The source and Cargo registry were read-only mounts, and each compilation used
a session-owned target volume. The security fixtures were created on the Linux
container filesystem. This is descriptor-security evidence; it does not claim
power-loss durability, disk-full behavior or complete storage-owner delivery.

Three additional exclusive-create cases are registered for existing empty and
malformed leaves, simultaneous creation with one winning inode, and unsafe
bounds or changed ancestors before creation. Native execution and strict lint
of these additions remain pending; compilation is paused for local disk space.
