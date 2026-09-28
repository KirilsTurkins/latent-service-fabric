"""Exercise a real authenticated invocation-only identity at private management."""
from pathlib import Path
import sys

sys.path.insert(0, '/opt/lsf/runtime')
import operator_receiver as receiver
from native_runtime import files
from native_runtime.common import encode

receiver.CLIENT = Path('/etc/lsf/invoke-client.json')
result = receiver.call('tests', 'node', 'get', 'container-qualification')
assert result['category'] == 'platform-failure' and result['outcomeKnown'] is True
assert result['error']['code'] == 'permission-denied'
files.create(Path('/var/cache/lsf/ci-permission-denied.json'), encode({'actualNativePermissionDenied': True}))
raise SystemExit(receiver.main())
