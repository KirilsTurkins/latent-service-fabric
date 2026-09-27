"""One process-lifetime file fence shared by the node and stopped maintenance."""
import fcntl
import os
from pathlib import Path
import stat

from native_runtime import files
from native_runtime.common import require


def acquire(root: Path, *, inherit=False) -> int:
    require(os.geteuid() == 10001 and os.getegid() == 10001, 'run-as-uid-and-gid-10001')
    with files.directory(root, {0, 10001}) as directory:
        fd = os.open('.container-owner.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == 10001
                    and stat.S_IMODE(info.st_mode) == 0o600, 'unsafe-container-owner-fence')
            files.no_acl(fd)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                require(False, 'container-state-is-owned-stop-the-existing-node')
            os.fsync(directory)
            os.set_inheritable(fd, inherit)
            return fd
        except BaseException:
            os.close(fd)
            raise
