"""Own only fresh empty volumes created by the finite edge qualification driver."""
import os
from pathlib import Path
import sys

assert os.geteuid() == 0 and sys.argv[1:] == ['fresh-edge-volumes']
for name in ('config', 'work', 'data', 'cache', 'edge'):
    path = Path('/' + name)
    assert not path.is_symlink() and not list(path.iterdir())
    os.chown(path, 10001, 10001)
    path.chmod(0o700)
print('{"freshOwnedVolumes":5}')
