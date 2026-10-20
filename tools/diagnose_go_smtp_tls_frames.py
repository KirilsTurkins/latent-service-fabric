#!/usr/bin/env python3
"""Private numeric-frame replay of one exact failed component; never qualification."""
from __future__ import annotations
import argparse
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import diagnose_go_entry_frames as frames
from tools import qualify_go_smtp_tls_runtime as smtp
from tools.java_replay_materials import NoRedirect, Ranges, api
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_project import ROOT, digest, fresh, read_file
from tools.test_run import redact

SOURCE='ca723d3c693eb1a8d62972ac96ae017b4d38e277'
RUN=39437307701
JOB=118677626944
ARTIFACT=12272663708
SIZE=2890188
SHA='sha256:a9cf862dec8839c5180366132fc8844a56a55377ff540b5a673a5c6dd76b5bce'
COMPONENT='sha256:0e7a4d083d551f230907b7a1438f34a75481fdfe24e83c64f55cbc7c19eb5d9e'
SELECTED=('native-inputs.json','FAILED.json','fixture/GO-SMTP-TLS-COMPILE.json','fixture/build/component.wasm')


def selected(raw):
    if len(raw)!=SIZE or digest(raw)!=SHA:
        raise ValueError('smtp-frame-exact-archive')
    result={}
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        rows=z.infolist();names=[r.filename for r in rows]
        if len(rows)!=50 or len(set(names))!=50 or sum(r.file_size for r in rows)>64*1024**2:
            raise ValueError('smtp-frame-archive-shape')
        for r in rows:
            p=PurePosixPath(r.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in r.filename or r.file_size>16*1024**2 or stat.S_IFMT(r.external_attr>>16) not in (0,stat.S_IFREG,stat.S_IFDIR):
                raise ValueError('smtp-frame-member-shape')
            data=z.read(r) # Validate every CRC, including members not extracted.
            if r.filename in SELECTED:result[r.filename]=data
    if set(result)!=set(SELECTED) or digest(result['fixture/build/component.wasm'])!=COMPONENT:
        raise ValueError('smtp-frame-exact-component')
    return result


def acquire():
    meta=api(f'actions/artifacts/{ARTIFACT}')
    job=api(f'actions/jobs/{JOB}')
    if meta['id']!=ARTIFACT or meta['size_in_bytes']!=SIZE or meta['digest']!=SHA or meta['expired'] or meta['workflow_run']['id']!=RUN or meta['workflow_run']['head_sha']!=SOURCE:
        raise ValueError('smtp-frame-artifact-origin')
    if job['run_id']!=RUN or job['head_sha']!=SOURCE or job['status']!='completed' or job['conclusion']!='failure':
        raise ValueError('smtp-frame-failed-job-origin')
    token=os.environ.get('GH_TOKEN')
    if not token:raise ValueError('smtp-frame-explicit-actions-token')
    request=urllib.request.Request(f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{ARTIFACT}/zip',headers={'Authorization':'Bearer '+token})
    try:urllib.request.build_opener(NoRedirect).open(request,timeout=30)
    except urllib.error.HTTPError as error:
        if error.code!=302:raise ValueError('smtp-frame-artifact-redirect') from None
        url=error.headers['Location']
    else:raise ValueError('smtp-frame-artifact-redirect-required')
    if not url.startswith('https://'):raise ValueError('smtp-frame-artifact-https')
    return selected(Ranges(url,SIZE).read(SIZE))


def verify_original(inputs):
    if not isinstance(inputs,dict) or not 100<=len(inputs)<=32768:raise ValueError('smtp-frame-source-shape')
    total=0
    for name,row in inputs.items():
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or set(row)!={'digest','size'}:raise ValueError('smtp-frame-source-row')
        raw=read_file(ROOT/name,16*1024**2);total+=len(raw)
        if total>128*1024**2 or row!={'digest':digest(raw),'size':len(raw)}:raise ValueError('smtp-frame-original-source-changed')


def diagnose(output):
    output=fresh(output)
    record={'schemaVersion':'latent.go.smtp.private-frames.v1','qualification':False,'status':'in-progress',
        'originalSource':SOURCE,'originalRun':RUN,'originalJob':JOB,'originalArtifact':ARTIFACT,
        'archiveDigest':SHA,'componentDigest':COMPONENT,'guestRecompiled':False,'nativeFiveRebuilt':False,
        'productionSignedGatePassed':False,'limitsChanged':False,'dwarfEnabled':False,'maximumNumericFrames':32}
    def save(name): (output/name).write_bytes((json.dumps(record,indent=2)+'\n').encode())
    originals={name:read_file(ROOT/name) for name in frames.PATHS}
    installed=False;inputs=None
    try:
        members=acquire();inputs=json.loads(members['native-inputs.json']);failed=json.loads(members['FAILED.json'])
        if failed['sourceRevision']!=SOURCE or failed['sourceDigest']!=digest(members['native-inputs.json']):raise ValueError('smtp-frame-receipt-source')
        verify_original(inputs)
        prepared=output/'fixture';(prepared/'build').mkdir(parents=True);(prepared/'src').mkdir();(prepared/'wit').mkdir()
        compile_record=json.loads(members['fixture/GO-SMTP-TLS-COMPILE.json'])
        source=read_file(ROOT/'sdk/go-guest/runtime/smtp-tls-conformance/main.go')
        if compile_record['profile']!='go-component-activation-v5' or compile_record['sourceUnchanged'] is not True or compile_record['sourceDigest']!=digest(source) or compile_record['componentDigest']!=COMPONENT:
            raise ValueError('smtp-frame-compile-preimage')
        (prepared/'src/main.go').write_bytes(source)
        (prepared/'wit/world.wit').write_bytes(read_file(ROOT/'sdk/go-guest/runtime/smtp-tls-conformance/world.wit'))
        (prepared/'GO-SMTP-TLS-COMPILE.json').write_bytes(members['fixture/GO-SMTP-TLS-COMPILE.json'])
        (prepared/'build/component.wasm').write_bytes(members['fixture/build/component.wasm'])
        record['compileObservationDigest']=digest(members['fixture/GO-SMTP-TLS-COMPILE.json'])
        private=output/'overlays';private.mkdir()
        identities,overlays=frames.overlay_sources(ROOT,private)
        installed=True
        for replacement,original in overlays:
            raw=read_file(replacement)
            # Conservatively indicate possible truncation at the engine ceiling.
            raw=raw.replace(b'trace.frames().len() > 32',b'trace.frames().len() >= 32')
            original.write_bytes(raw)
            identities[original.relative_to(ROOT).as_posix()]['private']=digest(raw)
        record['privateOverlays']=identities
        environment=dict(os.environ,CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',CARGO_TARGET_DIR=str(ROOT/'target'),LSF_GUEST_SDK_LANGUAGE='go',LSF_GO_SMTP_TLS_FIXTURE=str(prepared))
        for key in ('GH_TOKEN','GITHUB_TOKEN'):environment.pop(key,None)
        def command(args,name,timeout,maximum):
            def retain(result):
                if result is not None:
                    (output/(name+'.stdout.log')).write_bytes(result.output)
                    (output/(name+'.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8','replace')).encode())
            try:result=run_owned(args,cwd=ROOT,env=environment,timeout=timeout,maximum=maximum,separate_stderr=True)
            except ProcessFailure as error:retain(error.result);raise
            retain(result);return result
        built=command(['cargo','test','--locked','-p','latent-wasmtime','--test','go_smtp_tls','--no-run','--message-format=json'],'cargo',1200,16*1024**2)
        if built.returncode:raise ValueError('smtp-frame-private-target-build')
        descriptor=artifacts.Suite('crates/latent-wasmtime/Cargo.toml','go_smtp_tls','tests/go_smtp_tls.rs',smtp.CASE,frozenset({smtp.CASE}),True,kind='test')
        native=artifacts.read_inventory(output/'cargo.stdout.log',ROOT,descriptor,target=ROOT/'target')
        environment=artifacts.cargo_environment(ROOT,native,environment,target=ROOT/'target')
        invoked=command([str(native.executable),'--ignored','--exact',smtp.CASE,'--show-output','--test-threads=1'],'native',300,1024**2)
        if digest(read_file(prepared/'build/component.wasm',16*1024**2))!=COMPONENT:
            raise ValueError('smtp-frame-retained-component-changed')
        record['retainedComponentUnchanged']=True
        record['privateTestExit']=invoked.returncode
        record['frames']=frames.numeric_frames(invoked.output+invoked.stderr)
        if invoked.returncode!=101 or not record['frames']['available'] or not record['frames']['frames']:
            raise ValueError('smtp-frame-original-failure-and-numeric-frames-required')
        for name,identity in identities.items():
            if digest(read_file(ROOT/name))!=identity['private']:raise ValueError('smtp-frame-overlay-changed')
        record['status']='diagnostic-captured'
    except BaseException:
        record['status']='failed';raise
    finally:
        if installed:
            for name,raw in originals.items():(ROOT/name).write_bytes(raw)
        record['originalSourceRestored']=all(read_file(ROOT/name)==raw for name,raw in originals.items())
        try:
            if inputs is not None:verify_original(inputs)
        except BaseException:
            record['status']='failed';record['originalInputsRechecked']=False
            save('FAILED.json');raise
        record['originalInputsRechecked']=inputs is not None
        save('receipt.json' if record['status']=='diagnostic-captured' else 'FAILED.json')
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(diagnose(parser.parse_args().output.resolve())))
