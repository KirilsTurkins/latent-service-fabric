"""Initialize only fresh, disposable qualification volumes; never a production installer."""
import os
from pathlib import Path
import sys

assert os.geteuid() == 0 and sys.argv[1:] == ['fresh-test-volumes']
for name in ('/config', '/work', '/data', '/cache'):
    path = Path(name)
    assert not path.is_symlink() and not list(path.iterdir()), 'fresh empty qualification volume required'
    os.chown(path, 10001, 10001)
    os.chmod(path, 0o700)
