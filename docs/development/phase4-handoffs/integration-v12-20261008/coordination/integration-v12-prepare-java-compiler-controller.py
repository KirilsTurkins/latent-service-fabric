"""Prepare an exact maintained Java compiler campaign without changing limits."""
import hashlib
import json
from pathlib import Path

coord = Path(__file__).resolve().parent
base = '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data'
job = 'integration-v12-current-java-six-compiler-v1'
steps = []
for directory, mode in [('results', '--java-schema-put-once'), ('diagnostic', '--java-post-stage-diagnostic')]:
    steps.append(['python3', '-X', 'utf8', '-B', 'tools/compile_transaction_guests.py',
        '--language', 'java', '--output', f'{base}/jobs/{job}/{directory}',
        '--wasi-sdk', f'{base}/jobs/integration-v12-current-java-tools-v1/wasi-sdk', mode])
step_path = coord / 'integration-v12-union-review/current-java-six-compiler-steps.json'
step_path.write_text(json.dumps(steps, indent=2) + '\n', encoding='utf8')
source = (coord / 'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old = 'assert all(row[:2] == ["cargo", "+1.97.1"] for row in steps) if mode == "native" else all(row[0] == "python3" for row in steps)'
assert source.count(old) == 1
source = source.replace(old, 'assert mode == "native" and steps == ' + repr(steps))
marker = "env.pop('RUSTUP_TOOLCHAIN', None)"
assert source.count(marker) == 1
java = f'{base}/jobs/integration-v12-current-java-tools-v1'
tools = f'{base}/jobs/portable-v2-aggregate-compiler-tools-20261008-v114'
environment = '\n'.join([
    f"env['PATH'] = {repr(java + '/jdk/bin:' + java + '/gradle/bin:' + tools + '/bin:')} + env['PATH']",
    f"env['JAVA_HOME'] = {repr(java + '/jdk')}",
    f"env['GRADLE_USER_HOME'] = {repr(java + '/gradle-cache')}",
    "env.pop('LSF_GUEST_SDK_LANGUAGE', None)", "env.pop('LSF_GUEST_CAPSULES', None)"])
source = source.replace(marker, marker + '\n' + environment)
path = coord / 'integration-v12-current-java-six-compiler-controller.py'
path.write_text(source, encoding='utf8')
receipt = {'originalController': 'portable-v2-reconstructed-native-controller-20261007-v93.py',
    'controllerSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'changes': ['exact two maintained Java CLI commands allowlisted', 'authenticated private tool PATH/JAVA_HOME/Gradle cache'],
    'unchanged': ['1800-second absolute deadline', '16GiB original target growth', 'one heavy flock',
        'immutable checkout', 'kill and child reaping', 'source identity and raw failure retention'],
    'variantCount': 6, 'executed': False}
(coord / 'integration-v12-union-review/current-java-six-controller-review.json').write_text(
    json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
