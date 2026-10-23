"""One finite real-descriptor/node-quarantine programme; no custom kernel boot."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import qualify_host_stream_tls_provider as provider
from tools.owned_test_process import run_owned
from tools.rust_capsule_project import fresh

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'kernel::native::tests::'
CASES = frozenset(PREFIX+name for name in (
    'fixed_wire_rejects_wrong_expiry_error_and_unknown_phase',
    'exhausted_node_allowance_refuses_before_any_open',
    'possible_failed_open_retains_original_node_charge',
    'postopen_failure_closes_real_fd_without_refunding_backing',
    'ready_owner_drop_closes_on_original_worker_and_retains_capacity',
    'abandoned_waiter_cannot_drop_running_job_or_late_returned_owner',
    'unavailable_cleanup_slot_keeps_fd_and_backing_without_inline_close',
    'cleanup_panic_keeps_original_connection_after_lost_unit_result',
    'original_deadline_does_not_refund_a_blocked_native_constructor',
    'constructor_panic_retains_prepaid_backing_and_closes_real_fd',
))
INPUTS = (
    'Cargo.toml','Cargo.lock','rust-toolchain.toml',
    'crates/latent-capabilities/src/broker/pools.rs',
    'crates/latent-capabilities/src/broker/pools/control.rs',
    'crates/latent-capabilities/src/broker/pools/client.rs',
    'crates/latent-capabilities/src/broker/pools/protocol.rs',
    'crates/latent-capabilities/src/broker/pools/maintenance.rs',
    'crates/latent-capabilities/src/broker/pools/limits.rs',
    'tools/qualify_host_stream_native.py',
    'tools/ci/suites.d/outbound-streams.json',
    '.github/workflows/stream-native-factory-owner.yml',
)


def snapshot(root):
    names = set(INPUTS) | {path.relative_to(root).as_posix() for path in
        (root/'crates/latent-streams').rglob('*') if path.is_file()}
    return {name:provider.digest_file(root/name, 4*1024*1024) for name in sorted(names)}


def outcomes(raw):
    if len(raw) > 65536:
        raise ValueError('native-factory-result-bound')
    actual = [name.decode() for name in re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$',raw,re.M)]
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
        rb'(\d+) measured; (\d+) filtered out;', raw, re.M)
    if len(actual) != 10 or set(actual) != CASES or totals != [(b'10',b'0',b'0',b'0',b'30')]:
        raise ValueError('native-factory-missing-failed-or-extra-case')
    return sorted(actual)


def qualify(root, output, revision):
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise ValueError('native-factory-real-linux-required')
    environment = {**os.environ, 'CARGO_BUILD_JOBS':'2', 'CARGO_INCREMENTAL':'0',
        'CARGO_TARGET_DIR':str(root/'target')}
    artifacts.require_source(root, revision, environment)
    output = fresh(output)
    before = snapshot(root)
    def command(arguments, name, seconds, maximum):
        result = run_owned(arguments, cwd=root, env=environment, timeout=seconds,
            maximum=maximum, separate_stderr=True)
        (output/(name+'.stdout.log')).write_bytes(result.output)
        (output/(name+'.stderr.log')).write_bytes(result.stderr)
        if result.returncode:
            raise ValueError('native-factory-command-failed:'+name)
        return result.output
    compiler = command(['rustc','--version'],'compiler',30,4096).decode().strip()
    if not compiler.startswith('rustc 1.97.1 '):
        raise ValueError('native-factory-pinned-compiler')
    command(['cargo','test','--locked','--all-features','-p','latent-streams','--lib',
        '--no-run','--message-format=json'],'cargo',1200,16*1024*1024)
    suite = artifacts.Suite('crates/latent-streams/Cargo.toml','latent_streams','src/lib.rs',
        PREFIX,CASES,False)
    executable = artifacts.read_inventory(output/'cargo.stdout.log',root,suite,target=root/'target')
    environment = artifacts.cargo_environment(root,executable,environment,target=root/'target')
    listed = command([str(executable.executable),PREFIX,'--list'],'list',30,65536)
    registered = {name.decode() for name in re.findall(rb'^([a-zA-Z0-9_:]+): test$',listed,re.M)}
    ignored = command([str(executable.executable),PREFIX,'--ignored','--list'],'ignored',30,65536)
    if registered != CASES or re.search(rb': test$',ignored,re.M):
        raise ValueError('native-factory-registration-or-ignore-drift')
    raw = command([str(executable.executable),PREFIX,'--show-output','--test-threads=1'],
        'tests',120,65536)
    executed = outcomes(raw)
    artifacts.require_source(root,revision,environment)
    if snapshot(root) != before:
        raise ValueError('native-factory-source-changed')
    receipt = dict(schemaVersion='lsf.stream-native-factory-owner.v1',sourceRevision=revision,
        compiler=compiler,sourceBefore=before,sourceAfter=before,registeredCases=sorted(registered),
        executedCases=executed,ignored=[],
        executableSha256=provider.digest_file(executable.executable,1024*1024*1024),
        realLinuxDescriptors=True,originalNodeQuotaRetained=True,
        customKernelExecuted=False,constructorQualified=False,finalFreeCertificate=False,
        completeAllocationClosure=False,productionInstallation=False)
    (output/'receipt.json').write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--source-commit',required=True)
    arguments=parser.parse_args()
    qualify(ROOT,arguments.output,arguments.source_commit)
