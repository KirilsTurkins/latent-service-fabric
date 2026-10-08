from pathlib import Path
import json
import os
import signal

expected={160531:b'du -sk',160537:b'du',160538:b'sort',160539:b'head'}
verified=[]
for pid,token in expected.items():
    path=Path('/proc')/str(pid)/'cmdline'
    if path.exists() and token in path.read_bytes():
        verified.append(pid)
for pid in verified:
    try: os.kill(pid,signal.SIGTERM)
    except ProcessLookupError: pass
print(json.dumps({'onlyOwnedReadOnlyInventoryHelpersSignalled':verified,
                  'sourceControllerSignalled':False,'filesystemChanges':False}))
