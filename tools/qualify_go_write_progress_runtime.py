#!/usr/bin/env python3
"""SOURCE-ONLY four actual signed Write/io.Copy/original transfer-quota cases.

No run is implied by this source. The provider remains the explicit logical
reference; neither peer EOF nor zero userspace owners certifies kernel free.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_discovery as discovery
from tools import ci_suite_inventory as registry
from tools.go_guest.activation import MANAGED_PROFILE
from tools.go_guest.compiler import Compiler
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot
from tools.stage_runtime_wit import stage
from tools.test_run import redact
from tools.qualify_go_network_runtime import encoded, source_inputs as original_source_inputs

CASE = 'signed_go_large_writes_copy_and_transfer_quota_preserve_exact_peer_prefix_and_fresh_state'
SUITE = 'latent-wasmtime.test.go_write_progress_runtime'
EXPECTED = (('large-write',0,49189),('ordinary-copy',1,40973),('transfer-quota',2,None),('fresh-after-quota',0,49189))
INPUT_CAP = 1024*1024


def source_inputs(root):
    values = original_source_inputs(root)
    for name in ('tools/ci/suites.d/go-write-progress-runtime.json', '.github/workflows/go-write-progress-runtime.yml'):
        raw = read_file(root/name,128*1024)
        values[name] = {'digest':digest(raw),'size':len(raw)}
    return dict(sorted(values.items()))


def pattern_digest(size):
    # Deterministic fixture-owned bytes, independently checked by the real peer.
    # This reference executes no Go/library/transport or acceptance programme.
    if type(size) is not int or not 0 < size <= INPUT_CAP: raise ValueError('Go-write-progress-peer-size')
    return digest(bytes((((index*2654435761)&0xffffffff)>>24 for index in range(size))))


def outcomes(raw):
    if type(raw) is not bytes or len(raw)>1024*1024: raise ValueError('Go-write-progress-output-bound')
    passed=re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$',raw,re.M)
    totals=re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;',raw,re.M)
    if passed != [CASE.encode()] or totals != [(b'1',b'0',b'0',b'0',b'0')]:
        raise ValueError('Go-write-progress-one-actual-native-case')
    def pairs(items):
        out={}
        for key,value in items:
            if key in out: raise ValueError('Go-write-progress-duplicate-field')
            out[key]=value
        return out
    def rows(kind):
        return [json.loads(line,object_pairs_hook=pairs) for line in re.findall(b'^GO_WRITE_PROGRESS_'+kind.encode()+rb' (.+)$',raw,re.M)]
    def exact(actual,expected):
        return json.dumps(actual,sort_keys=True,separators=(',',':'))==json.dumps(expected,sort_keys=True,separators=(',',':'))
    kinds = re.findall(rb'^GO_WRITE_PROGRESS_([A-Z_]+) ',raw,re.M)
    if kinds != [b'CASE',b'PEER',b'OWNER',b'CASE',b'PEER',b'OWNER',b'QUOTA',
                 b'CASE',b'PEER',b'OWNER',b'CASE',b'PEER',b'OWNER',b'COMPLETE']:
        raise ValueError('Go-write-progress-event-order-or-unknown-marker')
    cases,peers,owners,quotas,complete=[rows(k) for k in ('CASE','PEER','OWNER','QUOTA','COMPLETE')]
    if len(cases)!=4 or len(peers)!=4 or len(owners)!=4 or len(quotas)!=1: raise ValueError('Go-write-progress-observation-count')
    for actual,peer,owner,(label,mode,wanted) in zip(cases,peers,owners,EXPECTED):
        keys={'case','mode','result','n','acceptedPrefix','mayHaveApplied','close','fresh','outboundRequests',
            'reportedEffectCount','cpuFuel','peakMemoryBytes','kernelRetirementQualified','normalProviderInstalled'}
        if set(actual)!=keys or not exact({k:actual[k] for k in ('case','mode','fresh','outboundRequests','kernelRetirementQualified','normalProviderInstalled')},
            {'case':label,'mode':mode,'fresh':1,'outboundRequests':1,'kernelRetirementQualified':False,'normalProviderInstalled':False}):
            raise ValueError('Go-write-progress-case-scope')
        for key,maximum in [('n',INPUT_CAP),('cpuFuel',1_000_000_000),('peakMemoryBytes',64*1024*1024)]:
            if type(actual[key]) is not int or not 0<actual[key]<=maximum: raise ValueError('Go-write-progress-numeric-bound')
        if type(actual['reportedEffectCount']) is not int or not 0<=actual['reportedEffectCount']<=0xffffffff:
            raise ValueError('Go-write-progress-effect-counter')
        if mode==2:
            if actual['n']<64 or type(actual['acceptedPrefix']) is not int or actual['acceptedPrefix']!=actual['n'] or type(actual['mayHaveApplied']) is not bool or actual['close'] not in ('closed','exhausted'):
                raise ValueError('Go-write-progress-typed-quota-prefix')
            result='quota|accepted='+str(actual['n'])+'|may-have-applied='+str(actual['mayHaveApplied']).lower()+'|n='+str(actual['n'])+'|close='+actual['close']+'|fresh=1'
        else:
            if actual['n']!=wanted or actual['acceptedPrefix'] is not None or actual['mayHaveApplied'] is not None or actual['close']!='closed':
                raise ValueError('Go-write-progress-success-count')
            result=('write' if mode==0 else 'copy')+'|n='+str(wanted)+'|close=closed|fresh=1'
        if actual['result']!=result: raise ValueError('Go-write-progress-actual-typed-result')
        if not exact(peer,{'case':label,'peer':{'bytes':actual['n'],'sha256':pattern_digest(actual['n']),'eof':True,'exactOriginalPattern':True}}):
            raise ValueError('Go-write-progress-peer-exact-prefix')
        if not exact(owner,{'case':label,'stores':0,'instances':0,'streamOwners':0,'ioOwners':0,'kernelRetirementQualified':False}):
            raise ValueError('Go-write-progress-physical-userspace-retirement')
    quota=cases[2]
    if not exact(quotas[0],{'inputBudgetBytes':INPUT_CAP,'acceptedWriteBytes':quota['n'],'liveConnection':True,
        'pendingPermitRead':True,'stores':1,'activeActivations':1,'ioStagedBytes':2,'ioBuffers':2,
        'perConnectionInputCap':INPUT_CAP,'perStoreTransferCap':2*INPUT_CAP,'kernelRetirementQualified':False}):
        raise ValueError('Go-write-progress-original-input-credit')
    expected_complete={'cases':4,'contacts':4,'cleanLogicalProviderStop':True,'kernelRetirementQualified':False,
        'normalProviderInstalled':False,'wholeGoNetworkingQualified':False}
    if not exact(complete,[expected_complete]): raise ValueError('Go-write-progress-scope-or-completion')
    return {'cases':cases,'peers':peers,'userSpaceOwners':owners,'originalQuota':quotas[0],'completion':complete[0]}


def qualify(root: Path, output: Path, revision: str) -> dict:
    environment = dict(os.environ, CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
                       CARGO_TARGET_DIR=str(root / 'target'), LSF_GUEST_SDK_LANGUAGE='go')
    artifacts.require_source(root, revision, environment)
    if sys.platform != 'linux':
        raise ValueError('Go-write-progress-runtime-linux-required')
    output = fresh(output)
    before = source_inputs(root)
    inputs = encoded(before)
    (output / 'native-inputs.json').write_bytes(inputs)
    record = {'schemaVersion': 'latent.go.write-progress.runtime.v1', 'sourceRevision': revision,
              'status': 'in-progress', 'sourceDigest': digest(inputs), 'normalProviderInstalled': False,
              'testHostFeature': 'development-test-host',
              'kernelAccountingQualified': False, 'fullGoNetworkingQualified': False}
    deadline = time.monotonic() + 1800

    def command(args: list[str], name: str, timeout: int, maximum: int):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Go-write-progress-runtime-overall-deadline')
        try:
            result = run_owned(args, cwd=root, env=environment, timeout=min(timeout, remaining),
                               maximum=maximum, separate_stderr=True)
        except ProcessFailure as error:
            result = error.result
            if result is not None:
                (output / (name + '.stdout.log')).write_bytes(result.output)
                (output / (name + '.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
            raise
        (output / (name + '.stdout.log')).write_bytes(result.output)
        (output / (name + '.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
        if result.returncode:
            raise ValueError('Go-write-progress-runtime-command-failed:' + name)
        return result.output

    try:
        # Compile this separate ordinary fixture once. The original twelve-case
        # network fixture/oracle remains unchanged and is not replayed here.
        prepared = output / 'fixture'
        prepared.mkdir()
        fixture = root / 'sdk/go-guest/runtime/network-progress-conformance'
        source = snapshot(fixture)
        (prepared / 'src').mkdir()
        (prepared / 'src/main.go').write_bytes(source['main.go'])
        for name in ('go.mod', 'go.sum'):
            (prepared / name).write_bytes(read_file(root / 'sdk/go-guest/runtime-deps' / name))
        stage(prepared / 'wit', fixture)
        commands = Commands(prepared, prepared, environment, deadline_seconds=900, command_seconds=600)
        compiler = Compiler(prepared / 'compiler', root / 'sdk/go-guest', commands, runtime_profile=MANAGED_PROFILE)
        component, _ = compiler.compile(prepared / 'src', prepared / 'wit',
            'examples:go-standard-network/service@1.0.0', prepared / 'build', runtime_profile=MANAGED_PROFILE)
        compiler.check_unchanged()
        if source != snapshot(fixture):
            raise ValueError('Go-write-progress-runtime-source-changed')
        compiled = {'profile': MANAGED_PROFILE, 'sourceUnchanged': True,
                    'sourceDigest': digest(source['main.go']), 'componentDigest': digest(read_file(component, 64 * 1024 * 1024)),
                    'tools': compiler.materials, 'compilerInputsDigest': digest(inventory(source))}
        (prepared / 'GO-WRITE-PROGRESS-COMPILE.json').write_bytes(encoded(compiled))
        record['component'] = compiled
        compiler_version = command(['rustc', '--version'], 'rustc', 30, 4096).decode().strip()
        if not compiler_version.startswith('rustc 1.97.1 '):
            raise ValueError('Go-write-progress-runtime-rust-compiler')
        command(['cargo', 'test', '--locked', '-p', 'latent-wasmtime', '--features', 'development-test-host', '--test', 'go_write_progress_runtime',
                 '--no-run', '--message-format=json'], 'cargo', 1200, 16 * 1024 * 1024)
        suite, = [row for row in registry.load(root / 'tools/ci/suites.json')['suites'] if row['id'] == SUITE]
        if suite['expectedCases'] != [CASE] or suite['expectedIgnored'] != [CASE] or suite['minimumCases'] != 1:
            raise ValueError('Go-write-progress-runtime-suite-contract')
        descriptor = artifacts.Suite(suite['manifest'], suite['target'], suite['source'], CASE, frozenset({CASE}), True, kind='test')
        native = artifacts.read_inventory(output / 'cargo.stdout.log', root, descriptor, target=root / 'target')
        environment = artifacts.cargo_environment(root, native, environment, target=root / 'target')
        environment['LSF_GO_WRITE_PROGRESS_FIXTURE'] = str(prepared)
        listed = command([str(native.executable), '--list'], 'list', 30, 65536)
        ignored = command([str(native.executable), '--ignored', '--list'], 'ignored', 30, 65536)
        discovery.validate_cases(suite, discovery.listing(listed), discovery.listing(ignored), {})
        raw = command([str(native.executable), '--ignored', '--exact', CASE, '--show-output', '--test-threads=1'],
                      'native', 300, 1024 * 1024)
        record['observations'] = outcomes(raw)
        if before != source_inputs(root):
            raise ValueError('Go-write-progress-runtime-native-inputs-changed')
        compiler.check_unchanged()
        if time.monotonic() >= deadline:
            raise ValueError('Go-write-progress-final-deadline')
        record.update(status='passed', sourceUnchanged=True, nativeCompiler=compiler_version,
                      nativeExecutableDigest=digest(read_file(native.executable, 1024 * 1024 * 1024)))
        (output / 'receipt.json').write_bytes(encoded(record))
        if time.monotonic() >= deadline:
            (output / 'receipt.json').unlink()
            raise ValueError('Go-write-progress-receipt-deadline')
        return record
    except BaseException:
        record['status'] = 'failed'
        (output / 'FAILED.json').write_bytes(encoded(record))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    arguments = parser.parse_args()
    print(json.dumps(qualify(ROOT, arguments.output.resolve(), arguments.source_commit)))
