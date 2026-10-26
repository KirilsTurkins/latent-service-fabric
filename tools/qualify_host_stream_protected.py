"""Current-source host typecheck + six focused controls; no kernel/provider qualification."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import fresh

ROOT = Path(__file__).resolve().parents[1]
MAXIMUM_SECONDS = 1320
MAXIMUM_PUBLIC = 48 * 1024**2
CASES = {
    'latent-capabilities': (
        'broker::pools::client::stream_quarantine_controls::stream_quarantine_false_and_unwind_keep_original_lease_until_completed_step',
        'broker::pools::client::stream_quarantine_controls::temporarily_dequeued_quarantine_still_funds_its_original_reinsertion_place',
    ),
    'latent-streams': (
        'transport::tests::private_wire_fault_keeps_uncertainty_without_ciphertext_as_plaintext_prefix',
        'transport::tests::repeated_handshake_reads_share_one_original_encrypted_input_ceiling',
    ),
    'latent-network': (
        'dns::tests::truncated_udp_uses_only_the_same_explicit_tcp_resolver_and_fixed_cache',
        'dns::tests::tcp_length_is_rejected_before_unbounded_read_or_allocation',
    ),
}


def require(value, why):
    if not value:
        raise ValueError('protected-stream-host-' + why)


def outcome(raw, name):
    require(type(raw) is bytes and len(raw) <= 65536, 'result-bound')
    names = re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
        rb'(\d+) measured; (\d+) filtered out;', raw, re.M)
    require(names == [name.encode()] and len(totals) == 1 and totals[0][:4] ==
        (b'1', b'0', b'0', b'0'), 'missing-failed-extra-ignored-case')
    return name


class Commands:
    def __init__(self, output, environment):
        self.output, self.environment = output, environment
        self.deadline = time.monotonic() + MAXIMUM_SECONDS
        self.rows = []

    def run(self, arguments, name, maximum_seconds, maximum_bytes, *, environment=None):
        remaining = self.deadline - time.monotonic() - 5
        require(math.isfinite(remaining) and remaining > 0, 'aggregate-deadline')
        limit = min(maximum_seconds, remaining)
        started = time.monotonic()
        failure = None
        try:
            result = run_owned(arguments, cwd=ROOT,
                env=environment or self.environment, timeout=limit,
                maximum=maximum_bytes, separate_stderr=True)
        except ProcessFailure as fault:
            failure, result = fault, fault.result
        if result is not None:
            stdout = self.output/(name+'.stdout.log')
            stderr = self.output/(name+'.stderr.log')
            stdout.write_bytes(result.output)
            stderr.write_bytes(result.stderr)
            self.rows.append(dict(name=name, argv=arguments, timeoutSeconds=limit,
                maximumCombinedBytes=maximum_bytes, elapsedSeconds=time.monotonic()-started,
                returncode=result.returncode, cleaned=result.cleaned, reaped=result.reaped,
                stdout=dict(bytes=len(result.output),sha256=hashlib.sha256(result.output).hexdigest()),
                stderr=dict(bytes=len(result.stderr),sha256=hashlib.sha256(result.stderr).hexdigest())))
        require(failure is None and result is not None, 'process-owner-failed:'+name)
        require(result.returncode == 0 and result.cleaned, 'command-failed-or-unreaped:'+name)
        require(time.monotonic() < self.deadline, 'aggregate-expired:'+name)
        return result.output


def file_identity(path, deadline):
    digest, count = hashlib.sha256(), 0
    with path.open('rb') as source:
        while chunk := source.read(65536):
            count += len(chunk)
            require(count <= 1024**3 and time.monotonic() < deadline, 'executable-bound')
            digest.update(chunk)
    return dict(bytes=count,sha256=digest.hexdigest())


def qualify(output, revision):
    require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'real-linux-x86-required')
    require(re.fullmatch(r'[0-9a-f]{40}', revision) is not None, 'source-revision')
    output = fresh(output)
    environment = {**os.environ, 'CARGO_BUILD_JOBS':'2', 'CARGO_INCREMENTAL':'0',
        'CARGO_TARGET_DIR':str(ROOT/'target')}
    for key in ('GH_TOKEN', 'GITHUB_TOKEN'):
        environment.pop(key, None)
    commands = Commands(output, environment)
    receipt = dict(schemaVersion='lsf.protected-stream-host-source.v1', sourceCommit=revision,
        status='FAILED', phase='source', commands=commands.rows, cases=[],executables={},
        customKernelExecuted=False, protectedProviderInstalled=False,
        physicalRetirementQualified=False, completeAllocationClosure=False,
        productionInstallation=False, whole738Complete=False)
    problem = None
    try:
        head = commands.run(['git','-c','gc.auto=0','rev-parse','HEAD'], 'head',30,256).strip().decode()
        require(head == revision, 'head-mismatch')
        clean = commands.run(['git','-c','gc.auto=0','status','--porcelain','--untracked-files=no'], 'status-before',30,65536)
        require(not clean.strip(), 'tracked-source-dirty-before')
        before = commands.run(['git','-c','gc.auto=0','ls-tree','-rz','HEAD'], 'source-before',30,4*1024**2)
        receipt['sourceTreeInventorySha256'] = hashlib.sha256(before).hexdigest()
        compiler = commands.run(['rustc','--version'], 'compiler',30,4096).decode().strip()
        require(compiler.startswith('rustc 1.97.1 '), 'pinned-rustc')
        receipt['compiler'] = compiler
        receipt['phase'] = 'compile-current-three-libraries'
        arguments = ['cargo','test','--locked','--all-features']
        for package in CASES:
            arguments += ['-p',package]
        commands.run(arguments+['--lib','--no-run','--message-format=json'],
            'cargo',1200,16*1024**2)
        for package,names in CASES.items():
            target = package.replace('-','_')
            suite = artifacts.Suite('crates/'+package+'/Cargo.toml',target,'src/lib.rs','',frozenset(names),True)
            executable = artifacts.read_inventory(output/'cargo.stdout.log',ROOT,suite,target=ROOT/'target')
            identity = file_identity(executable.executable, commands.deadline)
            receipt['executables'][package] = dict(path=executable.executable.relative_to(ROOT).as_posix(),**identity)
            def execute(arguments, **options):
                raw = commands.run(arguments, package+'-libdir', options['timeout'],options['maximum'])
                return 0,raw
            env = artifacts.cargo_environment(ROOT,executable,environment,execute=execute,target=ROOT/'target')
            listed = commands.run([str(executable.executable),'--list'],package+'-list',30,256*1024,environment=env)
            registered = re.findall(rb'^([a-zA-Z0-9_:]+): test$',listed,re.M)
            require(all(registered.count(name.encode()) == 1 for name in names), 'exact-registration')
            ignored = commands.run([str(executable.executable),'--ignored','--list'],package+'-ignored',30,256*1024,environment=env)
            require(not any(name.encode()+b': test' in ignored for name in names), 'selected-case-ignored')
            for index,name in enumerate(names):
                receipt['phase'] = name
                raw = commands.run([str(executable.executable),name,'--exact','--show-output','--test-threads=1'],
                    package+'-case'+str(index+1),120,65536,environment=env)
                receipt['cases'].append(outcome(raw,name))
            require(file_identity(executable.executable, commands.deadline) == identity, 'executable-changed')
        receipt['phase'] = 'final-source-and-owner-fences'
        after = commands.run(['git','-c','gc.auto=0','ls-tree','-rz','HEAD'],'source-after',30,4*1024**2)
        require(before == after, 'source-tree-changed')
        dirty = commands.run(['git','-c','gc.auto=0','status','--porcelain','--untracked-files=no'],'status',30,65536)
        require(not dirty.strip(), 'tracked-source-modified')
        require(len(receipt['cases']) == 6 and len(set(receipt['cases'])) == 6,'all-six-required')
        receipt['status'] = 'host-type-and-six-controls-passed'
        receipt['phase'] = 'complete-host-only'
    except BaseException as fault:
        problem = fault
        receipt['failureType'] = type(fault).__name__
    finally:
        try:
            raw = (json.dumps(receipt,indent=2)+'\n').encode()
            require(len(raw) <= 1024**2, 'receipt-bound')
            # Fresh output contains only fixed public command channels, never
            # CARGO_TARGET_DIR/source trees/SDK/cache/private runtime scratch.
            require(sum(path.stat().st_size for path in output.iterdir() if path.is_file())+len(raw)
                <= MAXIMUM_PUBLIC, 'public-evidence-bound')
            (output/'receipt.json').write_bytes(raw)
        except BaseException:
            if problem is None:
                raise # Never replace original compile/test/cleanup failure.
    if problem is not None:
        raise problem
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    args = parser.parse_args()
    qualify(args.output,args.source_commit)
