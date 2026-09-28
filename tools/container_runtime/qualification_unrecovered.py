"""Create only a fresh disposable volume with genuinely unrecoverable clock state."""
import json
import os
from pathlib import Path

root = Path('/bad')
assert os.geteuid() == 0 and not root.is_symlink() and not list(root.iterdir())
for path in (root, root / 'data', root / 'cache', root / 'data/supply-chain'):
    if path != root:
        path.mkdir(mode=0o700)
    os.chown(path, 10001, 10001)
    path.chmod(0o700)
floor = root / 'data/supply-chain/floor.json'
with floor.open('xb') as stream:
    stream.write(b'{"formatVersion":')
    stream.flush()
    os.fsync(stream.fileno())
os.chown(floor, 10001, 10001)
floor.chmod(0o600)
print(json.dumps({'disposableCorruptClockStateCreated': True}))
