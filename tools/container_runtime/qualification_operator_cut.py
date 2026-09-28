"""Execute a real native operation, then deliberately interrupt its response channel."""
import os
from pathlib import Path
import sys

sys.path.insert(0, '/opt/lsf/runtime')
from operator_receiver import input_document, receive
from native_runtime.common import encode
from native_runtime import files

value = receive(input_document())
assert value['category'] == 'success' and value['outcomeKnown'] is True
files.replace(Path('/var/cache/lsf/ci-cut-complete.json'), encode({'actualNativeCommit': True}))
os.write(sys.stdout.fileno(), encode(value)[:17])
raise SystemExit(0)
