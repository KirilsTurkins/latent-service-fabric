"""Bounded validation of an immutable head in Root's existing owned container."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

COORD = Path(__file__).resolve().parent
OWNER = "latent-p4-root-native-20261007-v6"
BASE = "/var/lib/docker/volumes/" + OWNER + "/_data"
job, head, step_file, mode = sys.argv[1:]
assert mode in {"native", "source"}
assert job.isascii() and all(c.isalnum() or c == "-" for c in job)
assert len(head) == 40 and all(c in "0123456789abcdef" for c in head)
steps = json.loads(Path(step_file).read_text(encoding="utf8"))
assert steps and all(isinstance(row, list) and row for row in steps)
assert mode == "native" and steps == [['python3', '-X', 'utf8', '-B', 'tools/compile_transaction_guests.py', '--language', 'java', '--output', '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-six-compiler-v7/results', '--wasi-sdk', '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-tools-v1/wasi-sdk', '--java-schema-put-once'], ['python3', '-X', 'utf8', '-B', 'tools/compile_transaction_guests.py', '--language', 'java', '--output', '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-six-compiler-v7/diagnostic', '--wasi-sdk', '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-tools-v1/wasi-sdk', '--java-post-stage-diagnostic']]
out = COORD / job
out.mkdir()
cfg = dict(job=job, head=head, base=BASE, steps=steps, mode=mode,
           deadlineSeconds=1800, maximumTargetGrowthBytes=16 * 1024 ** 3)
(out / "invocation.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf8")
body = r'''
from datetime import datetime, timezone
import fcntl, hashlib, json, os, signal, subprocess, time
from pathlib import Path
cfg = CONFIGURATION_PLACEHOLDER
base = Path(cfg['base']); head = cfg['head']; start = time.monotonic()
out = base / 'jobs' / cfg['job']; target = base / 'target'
assert os.getuid() == 10001 and os.getgid() == 10001 and not out.exists()
out.mkdir(mode=0o700)
env = dict(os.environ, CARGO_HOME=str(base / 'cargo'), CARGO_TARGET_DIR=str(target),
           CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
           CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
           CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true',
           TMPDIR=str(base / 'tmp'), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
           GIT_CONFIG_GLOBAL=str(base / 'jobs/gitconfig'), LSF_REQUIRE_NATIVE_PROCESS_TESTS='1')
env.pop('RUSTUP_TOOLCHAIN', None)
env['PATH'] = '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-tools-v1/jdk/bin:/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-tools-v1/gradle/bin:/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/portable-v2-aggregate-compiler-tools-20261008-v114/bin:' + env['PATH']
env['JAVA_HOME'] = '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-tools-v1/jdk'
env['GRADLE_USER_HOME'] = '/var/lib/docker/volumes/latent-p4-root-native-20261007-v6/_data/jobs/integration-v12-current-java-tools-v1/gradle-cache'
env.pop('LSF_GUEST_SDK_LANGUAGE', None)
env.pop('LSF_GUEST_CAPSULES', None)
def emit(value):
    try:
        print(json.dumps(value), flush=True)
    except (BrokenPipeError, OSError):
        pass
def call(argv, cwd=None, custody=False):
    remaining = 120 if custody else cfg['deadlineSeconds'] - (time.monotonic() - start)
    assert remaining > 0, 'original-deadline-before-launch'
    return subprocess.check_output(argv, cwd=cwd, env=env, text=True, timeout=min(120, remaining)).strip()
if cfg['mode'] == 'native':
    lock = (base / 'jobs' / 'root-native-active-v2.lock').open('a+')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # The lock and all-reaped receipt make sequential checkout reuse safe. Each
    # prior immutable candidate still exists in gitmeta and its owned worktree.
    source = base / 'native-active-portable-v3'
else:
    source = base / ('source-' + head[:16])
if not source.exists():
    cache = base / 'root-source-object-cache.git'
    origin = str(cache) if cache.is_dir() else '/gitmeta'
    call(['git', 'clone', '--shared', '--no-checkout', origin, str(source)])
    call(['git', 'config', 'core.autocrlf', 'false'], source)
else:
    assert not call(['git', 'status', '--porcelain'], source), 'dirty-validation-checkout'
call(['git', 'checkout', '--detach', head], source)
def git(*args, custody=False):
    return call(['git', *args], source, custody)
assert git('rev-parse', 'HEAD') == head and not git('status', '--porcelain')
tree = git('rev-parse', 'HEAD^{tree}')
rust = call(['rustc', '+1.97.1', '--version'])
assert rust == 'rustc 1.97.1 (8bab26f4f 2026-07-14)'
assert call(['python3', '--version']) == 'Python 3.13.5'
def size():
    measured = subprocess.run(['du', '-sk', str(target)], env=env,
                              capture_output=True, text=True, timeout=120)
    rows = measured.stdout.strip().splitlines()
    assert len(rows) == 1 and rows[0].split()[0].isdigit(), measured.stderr
    return int(rows[0].split()[0]) * 1024
initial = size() if cfg['mode'] == 'native' else 0
records = []; infrastructure_error = None
emit(dict(job=cfg['job'], head=head, tree=tree, sourceClean=True, status='starting', checkout=str(source)))
for index, argv in enumerate(cfg['steps']):
    stop = None; before = time.monotonic(); log_path = out / ('step-' + str(index + 1) + '.log')
    if before - start >= cfg['deadlineSeconds']:
        infrastructure_error = 'original-deadline-before-next-step'; break
    with log_path.open('xb') as log:
        process = subprocess.Popen(argv, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                if time.monotonic() - start >= cfg['deadlineSeconds']:
                    stop = 'original-bounded-build-and-test-deadline'
                elif cfg['mode'] == 'native' and size() - initial > cfg['maximumTargetGrowthBytes']:
                    stop = 'original-target-growth-ceiling'
                if stop:
                    break
                time.sleep(5)
        except BaseException as error:
            stop = 'validation-controller-error-' + type(error).__name__
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
            code = process.wait(timeout=10)
    raw = log_path.read_bytes()
    row = dict(argv=argv, exitCode=code, elapsedSeconds=time.monotonic() - before,
               stopReason=stop, originalProcessReaped=process.poll() is not None,
               log=log_path.name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    records.append(row)
    (out / 'progress.json').write_text(json.dumps(dict(head=head, tree=tree, steps=records), indent=2) + '\n')
    emit(row)
    if stop:
        break
receipt = dict(at=datetime.now(timezone.utc).isoformat(), head=head, tree=tree,
               steps=records, passed=len(records) == len(cfg['steps']) and all(r['exitCode'] == 0 and r['stopReason'] is None for r in records),
               elapsedSeconds=time.monotonic() - start, sourceClean=not git('status', '--porcelain', custody=True),
               sourceHeadUnchanged=git('rev-parse', 'HEAD', custody=True) == head, rustVersion=rust,
               deadlineSeconds=cfg['deadlineSeconds'], maximumTargetGrowthBytes=cfg['maximumTargetGrowthBytes'],
               targetGrowthBytes=size() - initial if cfg['mode'] == 'native' else 0,
               originalProcessReaped=all(r['originalProcessReaped'] for r in records),
               infrastructureError=infrastructure_error, completeCI=False,
               environment='Root-owned Debian12 Linux x86_64/ext4, UID10001, pinned Rust1.97.1/Python3.13.5.',
               cargoBuildJobs=2, checkout=str(source))
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
emit(receipt)
raise SystemExit(not receipt['passed'] or not receipt['sourceClean'] or not receipt['sourceHeadUnchanged'])
'''.replace("CONFIGURATION_PLACEHOLDER", repr(cfg))
compile(body, "<root-candidate-run-v2>", "exec")
(out / "runner.py").write_text(body, encoding="utf8", newline="\n")
container = json.loads(subprocess.check_output(["docker", "inspect", OWNER], timeout=30))[0]
assert container["State"]["Running"] and container["Config"]["Labels"]["latent.owner"] == "/root"
print(json.dumps(dict(job=job, head=head, mode=mode, status="running")), flush=True)
try:
    result = subprocess.run(["docker", "exec", "-i", "--user", "10001:10001", OWNER, "python3"],
                            input=body.encode(), capture_output=True, timeout=2070)
except subprocess.TimeoutExpired as error:
    (out / "observer-timeout.json").write_text(json.dumps(dict(observerDeadlineSeconds=2070,
        originalCampaignDeadlineSeconds=1800, completeCI=False)) + "\n")
    (out / "docker-output.log").write_bytes((error.stdout or b"") + (error.stderr or b""))
    raise
(out / "docker-output.log").write_bytes(result.stdout + result.stderr)
subprocess.run(["docker", "cp", OWNER + ":" + BASE + "/jobs/" + job + "/.", str(out)],
               capture_output=True, timeout=90, check=True)
receipt = json.loads((out / "receipt.json").read_bytes())
logs = []
for row in receipt["steps"]:
    data = (out / row["log"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == row["sha256"] and len(data) == row["bytes"]
    logs.append(dict(path=row["log"], sha256=row["sha256"], bytes=len(data), matchesNativeReceipt=True))
(out / "host-custody.json").write_text(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),
    receiptSha256=hashlib.sha256((out / "receipt.json").read_bytes()).hexdigest(), logs=logs,
    dockerExitCode=result.returncode, completeCI=False), indent=2) + "\n", encoding="utf8")
print(json.dumps(dict(head=head, passed=receipt["passed"], steps=receipt["steps"], receipt=str(out / "receipt.json"))), flush=True)
raise SystemExit(result.returncode)
