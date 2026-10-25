"""One source-matched maintained containment case; no runtime matrix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts, ci_suite_inventory as registry
from tools.build_observation import build_environment, file_identity, resolve_tools
from tools.build_snapshot import SOURCE_ALLOWLIST, SnapshotLimits
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

BRANCH='fix/containment-deadline-rendezvous-20261025'
WORKFLOW='.github/workflows/containment-deadline.yml'
CASE='healthy_activations_remain_correct_while_an_infinite_activation_times_out'


def require(value,reason):
    if not value:raise ValueError('containment-deadline-'+reason)


def identity(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def source_inputs():
    listed=subprocess.check_output(['git','ls-files','-z','--',*SOURCE_ALLOWLIST],cwd=ROOT,timeout=30)
    require(len(listed)<=2*1024**2,'source-path-bound')
    names=[name for name in listed.decode().split('\0') if name]
    limits=SnapshotLimits();require(100<=len(names)<=limits.max_entries,'source-count')
    result={};total=0
    for name in names:
        raw=read_file(ROOT/name,limits.max_file_bytes);total+=len(raw);result[name]=identity(raw)
    require(total<=limits.max_total_bytes,'source-total')
    # The one owned workflow is separately bounded, outside SOURCE_ALLOWLIST.
    result[WORKFLOW]=identity(read_file(ROOT/WORKFLOW,128*1024))
    return dict(sorted(result.items()))


def core_product(raw,target):
    require(type(raw) is bytes and 0<len(raw)<=4*1024**2,'core-inventory-bound')
    found=[];finished=False
    expected=target/'wasm32-unknown-unknown/release/examples/containment_capsule.wasm'
    for line in raw.splitlines():
        require(len(line)<=1024**2 and not finished,'core-record-order')
        row=json.loads(line)
        if row.get('reason')=='build-finished':
            require(row.get('success') is True,'core-success');finished=True
        elif row.get('reason')=='compiler-artifact' and row['target']['name']=='containment-capsule':
            require(Path(row['manifest_path']).resolve()==ROOT/'tools/toolchain-smoke/Cargo.toml'
                and row['target']['kind']==['example'] and row['target']['crate_types']==['cdylib']
                and Path(row['target']['src_path']).resolve()==ROOT/'tools/toolchain-smoke/examples/containment_capsule/component.rs'
                and row['profile']['test'] is False and row['profile']['opt_level']=='3'
                and row['profile']['debug_assertions'] is False and row['features']==[]
                and row.get('executable') is None
                and [Path(name).resolve() for name in row['filenames']]==[expected],
                'maintained-normal-core')
            found.append(expected)
    require(finished and found==[expected],'one-core-product');return expected


def qualify(output,revision):
    require(sys.platform=='linux' and os.environ.get('GITHUB_ACTIONS')=='true'
        and os.environ.get('GITHUB_REPOSITORY')=='KirilsTurkins/latent-service-fabric'
        and os.environ.get('GITHUB_REF_NAME')==BRANCH and os.environ.get('GITHUB_EVENT_NAME')=='push',
        'one-exact-hosted-push')
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents,'owned-output')
    output=fresh(output);environment=build_environment(output);target=ROOT/'target'
    environment.update(CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL='0',
        CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',
        CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
        CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
    log=output/'commands';log.mkdir()
    commands=Commands(ROOT,log,environment,deadline_seconds=1200,command_seconds=900)
    receipt={'schemaVersion':'lsf.containment-deadline.v1','status':'in-progress','sourceRevision':revision,
        'case':CASE,'requestedDeadlineMilliseconds':75,'ciSchedulingAllowanceMilliseconds':500,
        'wholeRuntimeMatrixExecuted':False,'compilerImplicitInputsAttested':False,'hermetic':False,
        'limits':{'overallSeconds':1200,'buildCommandSeconds':900,'caseProcessSeconds':60}}
    try:
        artifacts.require_source(ROOT,revision,environment)
        before=source_inputs();receipt['sourceBefore']=before;write_json(output/'source-inputs.json',before)
        toolchain=tomllib.loads(read_file(ROOT/'tools/toolchain.toml',128*1024).decode('utf-8'))
        tools,pins=resolve_tools(toolchain,ROOT,environment);receipt['observedTools']=pins
        require(toolchain['rust']['toolchain']=='1.97.1'
            and toolchain['contracts']['wasm-tools']=='1.254.0','normal-tool-pins')
        environment.update(RUSTC=str(tools['rustc']),RUSTUP_TOOLCHAIN=toolchain['rust']['toolchain'])
        receipt['stage']='maintained-containment-core'
        inventory=commands.run('build-containment-core',tools['cargo'],'build','--locked',
            '-p','latent-toolchain-smoke','--example','containment-capsule',
            '--target','wasm32-unknown-unknown','--release','--message-format=json')
        core=read_file(core_product(inventory,target),16*1024**2);receipt['core']=identity(core)
        core_path=output/'containment-core.wasm';core_path.write_bytes(core)
        component=output/'containment-component.wasm';commands.command_seconds=30
        commands.run('compose-maintained-component',tools['wasm-tools'],'component','new',core_path,'-o',component)
        commands.run('validate-maintained-component',tools['wasm-tools'],'validate',component)
        component_raw=read_file(component,16*1024**2);receipt['component']=identity(component_raw)
        receipt['stage']='one-source-matched-host-test';commands.command_seconds=900
        commands.run('build-containment-host-test',tools['cargo'],'test','--locked','-p','latent-wasmtime',
            '--test','containment_backend','--no-run','--message-format=json')
        contract,=[row for row in registry.load()['suites'] if row['id']=='latent-wasmtime.test.containment-backend']
        require(CASE in contract['expectedCases'] and CASE in contract['expectedIgnored']
            and contract['minimumCases']==7,'unchanged-seven-case-contract')
        suite=artifacts.Suite('crates/latent-wasmtime/Cargo.toml','containment_backend',
            'tests/containment_backend.rs',CASE,frozenset({CASE}),True,kind='test')
        executable=artifacts.read_inventory(output/'commands/logs/03-build-containment-host-test.stdout.txt',
            ROOT,suite,target=target)
        receipt['hostTest']=file_identity(executable.executable,'containment_backend',512*1024**2)
        commands.environment=artifacts.cargo_environment(ROOT,executable,environment,target=target)
        commands.environment['LSF_CONTAINMENT_COMPONENT']=str(component)
        commands.command_seconds=30
        listed=commands.run('list-one-deadline-case',executable.executable,CASE,'--exact','--ignored','--list')
        artifacts.validate_listing(listed,suite)
        commands.command_seconds=60
        raw=commands.run('execute-one-deadline-case',executable.executable,CASE,'--exact',
            '--ignored','--show-output','--test-threads=1')
        require(re.findall(rb'^test ([a-zA-Z0-9_:]+) \.\.\. ok$',raw,re.M)==[CASE.encode()]
            and re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; '
                rb'(\d+) measured; (\d+) filtered out;',raw,re.M)==[(b'1',b'0',b'0',b'0',b'6')],
            'one-executed-no-ignored-skip')
        receipt['stdout']=identity(raw)
        require(time.monotonic()<commands.deadline and source_inputs()==before,'final-source-deadline')
        require(read_file(core_path,16*1024**2)==core and read_file(component,16*1024**2)==component_raw,
            'final-component')
        require(file_identity(executable.executable,'containment_backend',512*1024**2)==receipt['hostTest']
            and [file_identity(tools[name],name) for name in sorted(tools)]==pins,'final-products-tools')
        artifacts.require_source(ROOT,revision,environment)
        receipt.update(status='passed',sourceAfter=before,sourceUnchanged=True,executed=[CASE],ignored=[])
        write_json(output/'receipt.json',receipt)
    except BaseException:
        receipt['status']='failed';write_json(output/'FAILED.json',receipt);raise
    finally:write_json(output/'commands.json',commands.records)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--source-commit',required=True)
    args=parser.parse_args();qualify(args.output.resolve(),args.source_commit)
