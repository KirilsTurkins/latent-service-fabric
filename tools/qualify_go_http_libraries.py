"""Capture/build/sign two ordinary Go clients with frozen normal native tools."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None,''}: sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.go_http_library_fixture import capture_source
from tools.go_http_library_reference import observe as native_reference
from tools.go_standard_http_node import run
from tools.phase2_operator_process import read_json, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.rust_capsule_project import ROOT, fresh


def qualify(output: Path, native_qualification: Path):
    output = fresh(output)
    deadline = time.monotonic()+1200
    record = {'schemaVersion':'latent.go.http-libraries.qualification.v1','status':'in-progress',
        'scope':'two-default-clients-captured-private-worker-and-signed-provider-subset',
        'commandLimits':{'overallSeconds':1200,'captureEachSeconds':300,'buildEachSeconds':300,'nodeEachSeconds':300,'nativeReferenceEachSeconds':120},
        'transportInjection':False,'catalogueDispatch':False,'fullTicketQualification':False,'variants':[]}
    source_paths = ('tools/qualify_go_http_libraries.py','tools/go_http_library_fixture.py',
        'tools/go_standard_http_node.py','sdk/go-guest/runtime/http-library-conformance/main.go',
        'tools/go_http_library_reference.py')
    record['sources'] = {name:file_identity(ROOT/name) for name in source_paths}
    stage = 'normal-native-products'
    try:
        receipt_path = native_qualification/'qualification.json'
        receipt = read_json(receipt_path)
        require(receipt.get('schemaVersion') == 'latent.go-capsule.qualification.v1'
            and receipt.get('status') == 'passed','go-http-libraries-normal-native-qualification-required')
        original_receipt = file_identity(receipt_path)
        binaries = {name:native_qualification/'native-binaries'/key.replace('/','-') for name,key in NATIVE_NAMES.items()}
        original_binaries = {name:file_identity(path,512*1024**2) for name,path in binaries.items()}
        require(all(original_binaries[name] == receipt['binaries'][key] for name,key in NATIVE_NAMES.items()),
            'go-http-libraries-frozen-native-product-drift')
        record.update(nativeQualification=original_receipt,binaries=original_binaries)
        go = Path(shutil.which('go') or 'missing-go').resolve(strict=True)
        original_go = file_identity(go)
        for variant in ('original-coordinate','renamed-coordinate'):
            require(time.monotonic() < deadline,'go-http-libraries-original-deadline')
            stage = variant+'-source'
            owned = output/variant; owned.mkdir()
            identity = 'outside.example.test/http-library/'+variant
            app, library = capture_source(owned/'application',owned/'private-original',identity)
            stage = variant+'-capture-and-review'
            command = [sys.executable,str(ROOT/'tools/go_http_library_fixture.py'),'--project',str(app),
                '--private-source',str(library),'--identity',identity,'--go',str(go),'--output',str(owned/'capture.json')]
            maximum = min(300,deadline-time.monotonic())
            require(maximum > 0,'go-http-libraries-original-deadline')
            write_json(owned/'capture-command.json',{'command':command,'maximumSeconds':maximum})
            result = run_bounded_result(command,ROOT,build_environment(owned),maximum,2*1024**2)
            for name in ('stdout','stderr'): (owned/('capture.'+name+'.txt')).write_bytes(getattr(result,name))
            require(result.returncode == 0,'go-http-libraries-native-capture-failed')
            captured = read_json(owned/'capture.json')
            stage = variant+'-native-truncated-reference'
            reference = native_reference(app,go,owned/'native-reference.json',deadline=deadline,include_malformed=True)
            require(reference['sourceDigest'] == captured['sourceDigest'],'go-http-libraries-native-reference-source')
            stage = variant+'-normal-component-build'
            command = [sys.executable,str(ROOT/'tools/go_capsule.py'),'build',str(app),
                '--output',str(owned/'build'),'--repository','https://github.com/KirilsTurkins/latent-service-fabric',
                '--contracts-tool',str(binaries['capsule_contracts']),'--packager',str(binaries['package'])]
            maximum = min(300,deadline-time.monotonic())
            require(maximum > 0,'go-http-libraries-original-deadline')
            write_json(owned/'compiler-command.json',{'command':command,'maximumSeconds':maximum})
            result = run_bounded_result(command,ROOT,build_environment(owned),maximum,2*1024**2)
            for name in ('stdout','stderr'): (owned/('compiler.'+name+'.txt')).write_bytes(getattr(result,name))
            require(result.returncode == 0,'go-http-libraries-component-build-failed')
            stage = variant+'-signed-node'
            node = run(owned/'build',{name:binaries[name] for name in ('latent','latentd','capsule_authoring')},
                       owned/'node',deadline=deadline,suite='libraries',native_reference=reference)
            record['variants'].append({'identity':identity,'capture':captured,'nativeReference':reference,'node':node,
                'component':file_identity(owned/'build/component.wasm',64*1024**2)})
            require(original_go == file_identity(go),'go-http-libraries-native-resolver-changed')
        require(original_receipt == file_identity(receipt_path)
            and original_binaries == {name:file_identity(path,512*1024**2) for name,path in binaries.items()},
            'go-http-libraries-native-products-changed')
        require(record['sources'] == {name:file_identity(ROOT/name) for name in source_paths},
            'go-http-libraries-qualification-source-changed')
        require(time.monotonic() < deadline,'go-http-libraries-original-deadline')
        record['status'] = 'passed'
        write_json(output/'qualification.json',record)
        return record
    except BaseException:
        record.update(status='failed',stage=stage)
        write_json(output/'FAILED.json',record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--native-qualification',type=Path,required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output.resolve(),args.native_qualification.resolve())))
