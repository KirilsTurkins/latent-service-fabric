"""A real elapsed-clock check: an old success is not current readiness."""
import json
import sys
import time

sys.path.insert(0, '/opt/lsf/runtime')
from probe import MAX_AGE, Projection, observe

projection = Projection()
assert not any(projection.status(path) for path in ('/startup', '/live', '/ready'))
projection.update(*observe('container-qualification'))
assert all(projection.status(path) for path in ('/startup', '/live', '/ready'))
time.sleep(MAX_AGE + 0.05)
assert not any(projection.status(path) for path in ('/startup', '/live', '/ready'))
print(json.dumps({'passed': True, 'realElapsedStaleSuccessRejected': True, 'maximumAgeSeconds': MAX_AGE}))
