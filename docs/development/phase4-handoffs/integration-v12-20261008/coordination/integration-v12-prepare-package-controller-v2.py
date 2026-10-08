"""Allow one reviewed package command under the unchanged native controller."""
import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
base = '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data'
input_job = f'{base}/jobs/integration-v12-current329-package-v1'
steps = [['python3', '-X', 'utf8', '-B', f'{input_job}/package.py',
    f'{input_job}/inputs', f'{input_job}/manifest-v2.json',
    f'{base}/jobs/integration-v12-current329-package-execution-v2/packaged']]
script = (coord / 'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old = 'assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert script.count(old) == 1
script = script.replace(old, 'assert mode == "native" and steps == ' + repr(steps))
path = coord / 'integration-v12-current329-package-controller.py'
path.write_text(script, encoding='utf8')
step_path = coord / 'integration-v12-union-review/current329-package-steps.json'
step_path.write_text(json.dumps(steps, indent=2) + '\n', encoding='utf8')
print(json.dumps({'controllerSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'stepSha256': hashlib.sha256(step_path.read_bytes()).hexdigest(),
    'unchangedBounds': ['1800 absolute outer', '600 actual package deadline', 'native heavy flock',
        'kill/reap', 'clean exact source', 'raw failure retention']}))
