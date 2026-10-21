# Maintained source inputs for the prepaid kernel consumer

The 2026-10-21 [kernel.org release snapshot](https://www.kernel.org/releases.json)
lists Linux 6.12.113, released 2026-10-15, as a maintained longterm release.
The [versioned source manifest](maintained-source-6.12.113.json) selects that
release, commit `7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e` and annotated tag
`0f6a69bb2f85d6da4dc81c32685143ee6c255348` from the
[upstream stable mirror](https://github.com/gregkh/linux/tree/7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e).
This is a source snapshot. It grants no kernel installation or stream authority.

The 148,686,048-byte archive matches the exact SHA256 published in the
[kernel.org checksum list](https://cdn.kernel.org/pub/linux/kernel/v6.x/sha256sums.asc).
All 92,471 archive members and 1,480,537,904 expanded bytes were traversed without
extracting the full tree. The 71 selected whole files, 5,117,172 bytes, each match
their independent Git blob/size identity at the selected commit. GitHub reports
the annotated upstream tag signature valid; local OpenPGP verification was not
performed and is not claimed.

The maintained source includes protocol, VFS, allocator, virtio/RX, cgroup,
security/SELinux and configuration definitions needed by the next private
consumer. Selection is a partial source graph, never complete allocator closure.
The historical `adc218676eef25575469234709c2d87185ca223a` preimages and recipes
remain immutable and retain their original limitations. Matching individual
function bodies does not make their old whole-file identities current.

## Authenticate an existing archive

The source helper accepts the exact local upstream archive and a new output
directory outside the checkout:

```sh
python3 -B tools/host_stream_kernel_maintained.py \
  --archive /owned/downloads/linux-6.12.113.tar.xz \
  --output /owned/maintained-kernel-source
```

It checks the byte-pinned manifest, archive checksum, fixed complete member and
expanded-byte counts, all 71 selected whole-file hashes and Git blob identities.
It refuses traversal, foreign prefixes, duplicate members, selected links,
changed inputs and original byte/time bounds. Only authenticated selected files
are written, followed by `SOURCE-COMPLETE.json`. No archive member can escape
the fresh output. The helper performs no download, configuration, compiler
execution, kernel build, provider installation or host change.

Up to 32 additional explicit `--extra-source relative/path` inputs can be read
from that same whole byte-authenticated archive, within the original 4MiB/file
and 16MiB selected-byte envelope. They cannot replace any of the original 71
pins. Their receipt records actual bytes/SHA256/Git blob identity and labels them
as archive-authenticated, without claiming independent GitHub corroboration.
This avoids a filename approval gate when the actual source graph needs another
header or callback. Additional inputs confer no execution or installation rights.

## Configuration and qualification still required

The original `arch/x86/configs/x86_64_defconfig` is an authenticated build seed,
not a resolved `.config`. Its security/network/SELinux selections remain intact.
No helper disables a configured mandatory security hook to satisfy the interim
outer allocator's refusal gate. The actual security/blob/cache path must be
closed before that profile can become usable.

The existing candidate keeps x86_64/4KiB pages, a dedicated one-queue virtio
network interface and the original TCP96KiB/DNS64KiB occupancy and fixed backing
limits. This source snapshot does not establish that compiled object geometry
fits them. Resolved configuration/compiler, actual image and running BTF,
protocol/security/RX/DNS allocation closure, trusted bootstrap, physical final
free and real-node qualification remain required. The selected factory consumer
remains unavailable and normal installation remains Unsupported.
