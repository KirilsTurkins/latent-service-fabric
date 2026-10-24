#!/usr/bin/env python3
"""Two normal v7 Go builds and one exact source-matched signed native programme."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

if __package__ in {None,''}: sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts, ci_suite_discovery as discovery, ci_suite_inventory as registry
from tools import go_stack_ceiling_fixture as fixture, go_stack_ceiling_outcomes as oracle
from tools.build_observation import build_environment, file_identity
from tools.owned_test_process import ProcessFailure, run_owned
from tools.qualify_go_network_runtime import source_inputs as original_source_inputs, encoded
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, inventory
from tools.test_run import redact

SUITE = 'latent-wasmtime.test.go_stack_ceiling_runtime'


def source_inputs(root):
    values = original_source_inputs(root)
    for name in ('tools/ci/suites.d/go-stack-ceiling-runtime.json','.github/workflows/go-stack-ceiling-runtime.yml'):
        raw = read_file(root/name,128*1024);values[name] = {'digest':digest(raw),'size':len(raw)}
    return dict(sorted(values.items()))


def placement(raw):
    oracle.require(type(raw) is bytes and len(raw) <= 1024*1024,'reference-output-bound')
    text = raw.decode('utf-8')
    rows = re.findall(r'^main\.stackFrame STEXT size=[0-9]+ align=0x[0-9a-f]+ args=0x[0-9a-f]+ locals=0x([0-9a-f]+)\b',text,re.M)
    oracle.require(len(rows) == 1 and 'moved to heap: frame' not in text
        and 'frame escapes to heap' not in text,'actual-reference-stack-frame')
    size = int(rows[0],16)
    oracle.require(17*size < 512*1024 and 97*size > 1024*1024,'reference-depths-bracket-cap')
    body = text[text.index('main.stackFrame STEXT'):]
    body = re.split(r'\n[^\n]+ STEXT ',body,maxsplit=1)[0]
    instructions = re.findall(r'^\t0x[0-9a-f]+ [0-9]+ \([^\n]+/main\.go:([0-9]+)\)\t([^\n]+)$',body,re.M)
    instructions = [(int(line),op) for line,op in instructions]
    source = fixture.reference_source().decode().splitlines()
    array_line = next(i+1 for i,line in enumerate(source) if 'var frame [8192]byte' in line)
    checksum_line = next(i+1 for i,line in enumerate(source) if 'for _, item := range frame' in line)
    def address(at,line):
        selected = instructions[at:at+5]
        if len(selected) != 5 or any(n != line for n,_ in selected): return None
        values = [op for _,op in selected]
        if values[0:2] != ['Get\tSP','I64ExtendI32U'] or values[3:] != ['I64Add','I32WrapI64']: return None
        match = re.fullmatch(r'I64Const\t\$([0-9]+)',values[2])
        return int(match[1]) if match else None
    arrays,copies = [],[]
    for i in range(len(instructions)):
        a = address(i,array_line)
        if a is not None and instructions[i+5:i+8] == [(array_line,'I32Const\t$0'),(array_line,'I32Const\t$8192'),(array_line,'MemoryFill')]: arrays.append(a)
        dst,src = address(i,checksum_line),address(i+5,checksum_line)
        if dst is not None and src is not None and instructions[i+10:i+12] == [(checksum_line,'I32Const\t$8192'),(checksum_line,'MemoryCopy')]: copies.append((dst,src))
    oracle.require(len(arrays) == 1 and len(copies) == 1 and copies[0][1] == arrays[0]
        and copies[0][0] >= arrays[0]+8192 and copies[0][0]+8192 <= size
        and '\tCall\tmain.stackFrame(SB)' in body,'actual-SP-relative-array-and-postrecursive-copy')
    return {'compilerFrameBytes':size,'arrayStackOffset':arrays[0],'checksumCopyStackOffset':copies[0][0],
        'arrayBytes':8192,'referenceExecuted':False,'finalComponentProofFromReferenceAlone':False}


def contracts_product(raw,root):
    oracle.require(len(raw) <= 16*1024*1024,'contracts-inventory-bound')
    selected = []; finished = False; links = set()
    for line in raw.splitlines():
        oracle.require(len(line) <= 1024*1024 and not finished,'contracts-inventory-tail')
        value = json.loads(line,object_pairs_hook=artifacts.unique_object)
        if value.get('reason') == 'build-finished':
            oracle.require(value.get('success') is True,'contracts-build-failed');finished = True
        elif value.get('reason') == 'build-script-executed':
            for link in value.get('linked_paths',[]):
                oracle.require(type(link) is str and len(link) <= 4096,'contracts-link-bound')
                path = Path(link.split('=',1)[-1])
                if path.is_absolute() and path.resolve().is_relative_to(root/'target'): links.add(path.resolve())
                oracle.require(len(links) <= 256,'contracts-link-count')
        elif value.get('reason') == 'compiler-artifact':
            target = value.get('target',{})
            if target.get('kind') != ['example'] or target.get('name') != 'capsule_contracts': continue
            oracle.require(Path(value['manifest_path']).resolve() == root/'crates/latent-packaging/Cargo.toml'
                and Path(target['src_path']).resolve() == root/'crates/latent-packaging/examples/capsule_contracts.rs'
                and value['profile']['test'] is False,'contracts-owner')
            path = Path(value['executable'])
            oracle.require(path.is_absolute() and not path.is_symlink() and path.is_file()
                and path.resolve() == root/'target/debug/examples/capsule_contracts','contracts-executable')
            selected.append(path.resolve())
    oracle.require(finished and len(selected) == 1,'one-current-contracts-product')
    return artifacts.Artifact(selected[0],root/'crates/latent-packaging',tuple(sorted(links)))


def compile_variant(app,variant,output,contracts):
    from tools.go_capsule_build import build
    before = fixture.verify(app,variant)
    build(app,output,contracts,None,'https://github.com/KirilsTurkins/latent-service-fabric')
    oracle.require(before == fixture.verify(app,variant),'application-changed-during-build')


def qualify(root,output,revision):
    environment = dict(os.environ,CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',
        CARGO_TARGET_DIR=str(root/'target'),LSF_GUEST_SDK_LANGUAGE='go')
    artifacts.require_source(root,revision,environment)
    oracle.require(sys.platform == 'linux','hosted-linux-required')
    output = fresh(output);before = source_inputs(root)
    (output/'native-inputs.json').write_bytes(encoded(before))
    deadline = time.monotonic()+1800
    record = {'schemaVersion':'latent.go.stack-ceiling.runtime.v1','sourceRevision':revision,
        'sourceDigest':digest(encoded(before)),'status':'in-progress','profile':fixture.PROFILE,
        'effectiveBudget':fixture.LIMITS,'runtimeLimits':oracle.RUNTIME,'wholeGoCostQualification':False,
        'kernelRetirementQualified':False,'testHostFeature':'development-test-host'}
    commands = []
    def command(args,label,timeout,maximum):
        remaining = deadline-time.monotonic();oracle.require(remaining > 0,'overall-deadline')
        started = time.monotonic()
        try:
            value = run_owned(list(map(str,args)),cwd=root,env=environment,timeout=min(timeout,remaining),
                maximum=maximum,separate_stderr=True)
        except ProcessFailure as error:
            if error.result is not None:
                (output/(label+'.stdout.log')).write_bytes(error.result.output)
                (output/(label+'.stderr.log')).write_bytes(redact(error.result.stderr.decode('utf-8','replace')).encode())
            raise
        (output/(label+'.stdout.log')).write_bytes(value.output)
        (output/(label+'.stderr.log')).write_bytes(redact(value.stderr.decode('utf-8','replace')).encode())
        commands.append({'label':label,'seconds':round(time.monotonic()-started,6),'exitCode':value.returncode,
            'stdoutDigest':digest(value.output),'stderrDigest':digest((output/(label+'.stderr.log')).read_bytes())})
        oracle.require(value.returncode == 0,'command-failed:'+label);return value.output
    try:
        version = command(['rustc','--version'],'rustc',30,4096).decode().strip()
        oracle.require(version.startswith('rustc 1.97.1 '),'source-matched-native-Rust-toolchain')
        record['nativeCompiler'] = version
        raw = command(['cargo','build','--locked','-p','latent-packaging','--example','capsule_contracts',
            '--message-format=json'],'contracts',1200,16*1024*1024)
        product = contracts_product(raw,root)
        environment = artifacts.cargo_environment(root,product,environment,target=root/'target')
        contracts_identity = file_identity(product.executable,'contracts-tool')
        reference = output/'reference';reference.mkdir()
        project = reference/'project';project.mkdir()
        (project/'main.go').write_bytes(fixture.reference_source())
        (project/'go.mod').write_bytes(b'module lsf-stack-v7-proof\n\ngo 1.27.3\n')
        reference_env = build_environment(reference)
        reference_env.update(GOOS='wasip1',GOARCH='wasm',GOTOOLCHAIN='local',GOWORK='off',
            GOFLAGS='-mod=readonly',GOPROXY='off',GOSUMDB='off',CGO_ENABLED='0',
            GOCACHE=str(reference/'cache'),GOMODCACHE=str(reference/'modules'))
        remaining = deadline-time.monotonic();oracle.require(remaining > 0,'reference-deadline')
        c = Commands(project,reference,reference_env,deadline_seconds=min(240,remaining),command_seconds=180)
        go = shutil.which('go',path=environment['PATH']);oracle.require(go is not None,'pinned-Go-required')
        oracle.require(c.run('compiler-version',go,'version').strip() == b'go version go1.27.3 linux/amd64','reference-Go-version')
        c.run('compile-only',go,'build','-gcflags=lsf-stack-v7-proof=-m=2 -S','-o',reference/'not-executed.wasm','.')
        diagnostics = read_file(reference/'logs/01-compile-only.stderr.txt',1024*1024)
        record['placementReference'] = {**placement(diagnostics),'sourceDigest':digest(fixture.reference_source()),
            'diagnosticsDigest':digest(diagnostics),'compiler':file_identity(Path(go),'go'),'commands':c.records}
        applications = output/'applications';applications.mkdir(); variants = []
        for variant in fixture.VARIANTS:
            name = 'go-stack-'+variant;app = fixture.create(applications/name,variant)
            captured = fixture.verify(app,variant)
            command([sys.executable,'-B',root/'tools/qualify_go_stack_ceiling_runtime.py',
                '--compile-variant',variant,'--project',app,'--output',output/name,
                '--contracts-tool',product.executable],'build-'+variant,900,1024*1024)
            oracle.require(captured == fixture.verify(app,variant),'captured-variant-changed')
            complete = read_json(output/name/'BUILD-COMPLETE.json')
            oracle.require(complete['packageAssembled'] is False,'normal-package-source-required')
            oracle.require(complete['sourceDigest'] == captured['sourceInputsDigest']
                and complete['componentDigest'] == digest(read_file(output/name/'component.wasm',16*1024*1024)),
                'normal-build-source-and-component-binding')
            observation = read_json(output/name/'build-observation.json')
            oracle.require(complete['observationDigest'] == digest(read_file(output/name/'build-observation.json'))
                and observation['parameters']['runtime'] == fixture.PROFILE,'normal-v7-observation-binding')
            oracle.require([m for m in observation['materials'] if m['name'] == 'go']
                == [record['placementReference']['compiler']],'same-pinned-Go-reference-and-component-compiler')
            variants.append({'name':name,**captured,'buildComplete':complete})
        record['normalBuilds'] = variants
        oracle.require(file_identity(product.executable,'contracts-tool') == contracts_identity,'contracts-product-changed')
        command(['cargo','test','--locked','-p','latent-wasmtime','--features','development-test-host',
            '--test','go_stack_ceiling_runtime','--no-run','--message-format=json'],'cargo',1200,16*1024*1024)
        suite, = [s for s in registry.load(root/'tools/ci/suites.json')['suites'] if s['id'] == SUITE]
        oracle.require(suite['expectedCases'] == [oracle.CASE] and suite['expectedIgnored'] == [oracle.CASE]
            and suite['minimumCases'] == 1,'suite-contract')
        descriptor = artifacts.Suite(suite['manifest'],suite['target'],suite['source'],oracle.CASE,
            frozenset({oracle.CASE}),True,kind='test')
        native = artifacts.read_inventory(output/'cargo.stdout.log',root,descriptor,target=root/'target')
        environment = artifacts.cargo_environment(root,native,environment,target=root/'target')
        environment['LSF_GUEST_CAPSULES'] = str(output)
        listed = command([native.executable,'--list'],'list',30,65536)
        ignored = command([native.executable,'--ignored','--list'],'ignored',30,65536)
        discovery.validate_cases(suite,discovery.listing(listed),discovery.listing(ignored),{})
        raw = command([native.executable,'--ignored','--exact',oracle.CASE,'--show-output','--test-threads=1'],
            'native',300,1024*1024)
        record['observations'] = oracle.read(raw)
        oracle.require(before == source_inputs(root),'native-source-changed')
        oracle.require(time.monotonic() < deadline,'final-deadline')
        record.update(status='passed',sourceUnchanged=True,commands=commands,
            nativeExecutableDigest=digest(read_file(native.executable,1024*1024*1024)))
        (output/'receipt.json').write_bytes(encoded(record))
        if time.monotonic() >= deadline:
            (output/'receipt.json').unlink();raise ValueError('Go-stack-receipt-deadline')
        return record
    except BaseException:
        record.update(status='failed',commands=commands);(output/'FAILED.json').write_bytes(encoded(record));raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-commit',default=os.environ.get('GITHUB_SHA'))
    p.add_argument('--compile-variant',choices=fixture.VARIANTS)
    p.add_argument('--project',type=Path)
    p.add_argument('--contracts-tool',type=Path)
    a = p.parse_args()
    if a.compile_variant:
        if a.project is None or a.contracts_tool is None: p.error('compile variant needs owned project/contracts tool')
        compile_variant(a.project,a.compile_variant,a.output,a.contracts_tool)
    else:
        if a.project is not None or a.contracts_tool is not None: p.error('programme creates its own normal projects/products')
        print(json.dumps(qualify(ROOT,a.output.resolve(),a.source_commit)))
