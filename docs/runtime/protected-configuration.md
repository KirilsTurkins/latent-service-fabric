# Protected standalone configuration files

Phase 3 hardens the two standalone inputs that carry security authority: the
credential-bearing node configuration and, when supply-chain admission is
`enforced`, its trust-policy document. This is one prerequisite of the planned
`external-capsule-v1` profile from [RFC-0001](../../rfcs/0001-minimum-execution-isolation-profiles.md).
It does not by itself enable that profile; #280 owns profile selection and must
fail closed where all prerequisites are unavailable.

## Linux x86_64 protected-file boundary

On the supported Linux x86_64 path, `latentd` walks an absolute path from an
opened root directory one component at a time. Every ancestor is opened with
`O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`; the leaf is opened read-only with
`O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`. Validation is performed on the opened file
descriptors rather than by a pathname `stat` followed by `open`.

Ancestors must be directories owned by root or the effective service UID.
Group-writable ancestors are accepted only for the effective service group.
Other-writable ancestors are rejected except for root-owned sticky directories
such as `/tmp`; the next opened descriptor still anchors each subsequent lookup.
Symlink ancestors and parent-directory components are rejected.

Protected leaves must be regular files, owned by root or the effective service
UID, have exactly one hard link, contain no executable/set-id permission bits,
and remain unchanged while their bounded contents are read. The reader compares
opened-descriptor identity, owner/mode/link count, size, modification time and
change time before and after the read. FIFOs and other special files are opened
nonblocking and rejected before content is consumed, so a malicious named pipe
cannot stall startup waiting for a writer.

The two policies intentionally differ:

- **Node configuration / credentials:** group or other write permission is
  rejected. Group reads are accepted only for the effective service group.
  Reads by other accounts are accepted only when an already-opened trusted
  ancestor prevents those accounts from traversing to the file. A conventional
  deployment should use `0600`, or root/service-group `0640` when that group is
  deliberately trusted.
- **Supply-chain trust policy:** confidentiality is not required, so public read
  permission is allowed. Group/other write permission is rejected because the
  file controls admission authority. `0644`, `0640`, `0600`, and read-only
  equivalents are typical choices under a trusted ancestor chain.

The node document remains limited to 64 KiB and the trust policy to 256 KiB.
Existing parser/depth/semantic bounds still apply after the protected descriptor
read. Relative policy paths continue to anchor to the node configuration
parent; this code does not create, chmod, chown, or otherwise repair configuration
files or ancestors.

## Links and concurrent replacement

Final-component and ancestor symlinks are rejected. Leaf hard links are rejected
because an alternate pathname could otherwise mutate the same authority-bearing
inode. Directory-descriptor traversal means renaming a pathname component after
it has been opened does not redirect later lookups through a different directory.
A mutation of the opened leaf during the read is rejected when its descriptor
snapshot changes. The runtime never silently retries under a weaker path policy.

## Non-Linux compatibility boundary

Other build targets retain the existing bounded regular-file loader so portable
configuration parsing and development tooling continue to compile. That fallback
does **not** establish protected trust configuration and is not evidence for
`external-capsule-v1`. #280 must reject a requested profile that requires this
boundary on a host where the Linux descriptor policy (or a separately reviewed
equivalent) is unavailable; it may not downgrade to the compatibility loader.

The isolated-AOT key and native-cache ownership rules remain separate. This
change does not weaken or reinterpret their existing authority checks.
