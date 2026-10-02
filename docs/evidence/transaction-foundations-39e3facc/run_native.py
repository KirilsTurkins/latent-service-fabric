from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
REPORT = Path(__file__).resolve().parent
IMAGE = 'sha256:808682d39104dc67ea35b407841aa8ecd4d5662bb8fa8df09e78cecdf4cacde7'
NAME = 'lsf-http409-native-20261001-r1'

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

source = sys.argv[1]
source = git('rev-parse', source).decode().strip()
tree = git('rev-parse', source + '^{tree}').decode().strip()
archive = REPORT / 'source.tar'
if archive.exists():
    raise SystemExit('Refusing to replace an existing qualification archive')
subprocess.run(['git', 'archive', '--format=tar', '--output', str(archive), source], cwd=ROOT, check=True)
archive_hash = hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest()
record = dict(source=source, tree=tree, sourceArchiveSha256=archive_hash, toolImage=IMAGE,
              scope=['latent-state', 'latent-protected-files', 'latent-commit', 'latent-effects', 'latent-http', 'latent-node', 'latent-ingress', 'latent-executor', 'latent-wasmtime'],
              qualification='Linux x86_64 ext4 combined ownership, physical recovery, actual HTTP effect and canonical Wasmtime primitives; not Java/signed installed HTTP transaction execution',
              resources=dict(cpus=4, memoryBytes=8589934592, pids=512, deadlineSeconds=1800))
(REPORT / 'source.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
command = ['docker', 'run', '--name', NAME, '--cpus', '4', '--memory', '8g', '--pids-limit', '512',
           '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
           '--mount', f'type=bind,source={REPORT.as_posix()},target=/reports',
           '--mount', 'type=volume,source=lsf-recovery399-native-cargo,target=/cargo',
           '--mount', 'type=volume,source=lsf-recovery399-native-target,target=/target',
           '--mount', 'type=volume,source=lsf-recovery399-native-fixtures,target=/fixtures']
environment = {'CARGO_HOME': '/cargo', 'CARGO_TARGET_DIR': '/target', 'CARGO_INCREMENTAL': '0',
               'CARGO_BUILD_JOBS': '2', 'CARGO_PROFILE_DEV_DEBUG': '0', 'CARGO_PROFILE_TEST_DEBUG': '0',
               'RUSTUP_TOOLCHAIN': '1.97.1-x86_64-unknown-linux-gnu', 'LSF_SOURCE': source}
for key, value in environment.items():
    command.extend(['--env', key + '=' + value])
command.extend([IMAGE, 'bash', '/reports/native.sh'])
start = time.monotonic()
print('START', NAME, source, archive_hash, flush=True)
with (REPORT / 'container.log').open('wb') as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    try:
        code = process.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        subprocess.run(['docker', 'stop', '--time', '10', NAME], check=False, capture_output=True)
        process.wait(timeout=30)
        code = 124
record['exitCode'] = code
record['elapsedSeconds'] = round(time.monotonic() - start, 3)
(REPORT / 'completion.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print((REPORT / 'container.log').read_text(encoding='utf-8', errors='replace')[-5000:], flush=True)
print('COMPLETE', code, record['elapsedSeconds'], flush=True)
sys.exit(code)
