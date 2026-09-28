"""Real commit followed by a bounded response delay for worker-cancellation tests."""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, '/opt/lsf/runtime')
from operator_receiver import input_document, receive
from native_runtime.common import encode
from native_runtime import files

value = receive(input_document())
assert value['category'] == 'success' and value['outcomeKnown'] is True
marker = Path('/var/cache/lsf/ci-cancel-complete.json')
files.replace(marker, encode({'actualNativeCommit': True, 'responseOwnerFinished': False}))
try:
    # No further native operation runs here. A closed transport ends the delay;
    # even a daemon retaining the exec pipe cannot keep this owner beyond 5s.
    until = time.monotonic() + 5
    while time.monotonic() < until:
        os.write(sys.stdout.fileno(), b' ')
        time.sleep(0.05)
    os.write(sys.stdout.fileno(), encode(value))
except BrokenPipeError:
    pass
finally:
    files.replace(marker, encode({'actualNativeCommit': True, 'responseOwnerFinished': True}))
