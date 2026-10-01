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

## Fresh transaction owner initialization

The protected mutable-file fence records whether the original `openat` actually
performed an exclusive create. A reopened zero-length file does not carry that
fact. The storage owner issues one affine `FreshStoreInitialization` only when
both its engine file and exclusive owner-lock file were newly created and the
actual shared records table is empty. The witness remains borrowed from that
same engine on the existing fixed writer; it cannot be constructed from a path,
configuration flag, clock sample or decoded record.

Dispatcher startup consumes this witness once. An initial protected checkpoint
must have owner epoch one, and the actual continuous time must cover its original
clock floor. A failed attempt does not restore the witness. Reopened, restored
or nonempty stores continue to require their original retained owner record and
checkpoint floors. A missing owner row or lost engine file under an existing
owner lock does not establish a fresh database. This initialization path grants
no namespace, caller, staging, dispatch or command authority.

The new native fixtures cover fresh start, physical retirement and reopening,
one-use consumption, retained family rows, lost anchors, missing owner rows,
higher checkpoint epochs, future floors and clock discontinuity. Their Linux
execution is tracked separately from portable compiler and engine checks.

## Validation

The registered `latent-protected-files` library suite contains 18 tests. On
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
