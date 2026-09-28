"""Real syscall/process observations on the actual candidate volume, not a durability model."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

assert os.geteuid() == 10001 and sys.argv[1:] == ['/var/lib/lsf']
with tempfile.TemporaryDirectory(prefix='.storage-check-', dir=sys.argv[1]) as name:
    root = Path(name)
    original = root / 'current'
    original.write_bytes(b'v1')
    original.chmod(0o600)
    os.link(original, root / 'link')
    assert original.stat().st_ino == (root / 'link').stat().st_ino
    with original.open('r+b') as stream:
        os.fsync(stream.fileno())
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code = "import fcntl,sys; f=open(sys.argv[1],'r+b'); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)"
        child = subprocess.run([sys.executable, '-I', '-c', code, str(original)], capture_output=True, timeout=5)
        assert child.returncode != 0 and b'BlockingIOError' in child.stderr
        (root / 'next').write_bytes(b'v2')
        with (root / 'next').open('rb') as staged:
            os.fsync(staged.fileno())
        os.replace(root / 'next', original)
        assert stream.read() == b'v1' and original.read_bytes() == b'v2' and (root / 'link').read_bytes() == b'v1'
    (root / 'symlink').symlink_to(original)
    try:
        descriptor = os.open(root / 'symlink', os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        pass
    else:
        os.close(descriptor)
        raise AssertionError('no-follow did not reject symlink')
    # A separate writer exits after syncing its pending file, before replacement.
    code = "import os,sys; f=open(sys.argv[1],'xb'); f.write(b'v3'); f.flush(); os.fsync(f.fileno()); os._exit(77)"
    assert subprocess.run([sys.executable, '-I', '-c', code, str(root / 'interrupted')], timeout=5).returncode == 77
    assert original.read_bytes() == b'v2' and (root / 'interrupted').read_bytes() == b'v3'
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
        filesystem = os.fstatvfs(descriptor)
    finally:
        os.close(descriptor)
with open('/proc/self/mountinfo') as mounts:
    entries = mounts.read(131073)
assert len(entries) <= 131072
mounted = [line.split(' - ', 1)[1].split()[0] for line in entries.splitlines()
           if line.split()[4] == '/var/lib/lsf']
assert len(mounted) == 1 and mounted[0] in {'ext4', 'xfs'}
print(json.dumps({'passed': True, 'uid': os.geteuid(), 'filesystem': mounted[0], 'filesystemBlockSize': filesystem.f_frsize,
    'hardlinks': True, 'atomicReplacementAndHeldReader': True, 'fileAndDirectorySync': True,
    'crossProcessLockExclusion': True, 'noFollow': True, 'interruptedWriterPreservesCurrent': True,
    'powerLossQualified': False, 'remoteFilesystemQualified': False}))
