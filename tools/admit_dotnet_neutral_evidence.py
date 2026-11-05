"""Admit only bounded public observations from the frozen neutral diagnostic."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

NAMES = frozenset({
    'checkout.txt','rustc-version.txt','wasm-tools-version.txt','source-sha256.txt',
    'python-tests.log','acquisition.log','acquisition.json','original-qualified.json',
    'derivation.log','derivation.json','cargo.log','checker-compile.log','compiler.json',
    'checker-tests.log','independent.log','independent.json','original.wit','derived.wit',
    'component-sha256.txt','original.wasm','derived.wasm',
})
BINARIES = {'original.wasm':(7542795,'3ab0ae8b54c5ed0469b3f9ea105fd566f308e314bdf3aeeb4529b9ed4085f20a'),
            'derived.wasm':(7542817,'f48d42c7c966aa6e87bd2e01f5a90379d2c7b5e6e2e84de26e4581b4391d3f80')}


def admit(root):
    root=Path(root).absolute()
    marker=root/'evidence-admission.json'
    result={'schemaVersion':'latent.dotnet.neutral.evidence-admission.v1','status':'failed'}
    try:
        source=root/'observed'
        if not root.is_dir() or root.is_symlink() or not source.is_dir() or source.is_symlink():
            raise ValueError('invalid-root')
        rows=[]
        for path in sorted(source.iterdir()):
            if path.name not in NAMES:
                continue
            if not path.is_file() or path.is_symlink():
                raise ValueError('invalid-file')
            maximum=8*1024*1024 if path.name in BINARIES else 1024*1024
            if path.stat().st_size>maximum:
                raise ValueError('file-bound')
            with path.open('rb') as source_file:
                raw=source_file.read(maximum+1)
            if len(raw)>maximum:
                raise ValueError('file-bound')
            digest=hashlib.sha256(raw).hexdigest()
            if path.name in BINARIES and (len(raw),digest)!=BINARIES[path.name]:
                raise ValueError('binary-identity')
            rows.append((path,raw,digest))
        if not rows or len(rows)>len(NAMES) or sum(len(raw) for _,raw,_ in rows)>20*1024*1024:
            raise ValueError('total-bound')
        public=root/'public'
        public.mkdir(exist_ok=False)
        for path,raw,digest in rows:
            destination=public/path.name
            with destination.open('xb') as output:
                output.write(raw)
            with path.open('rb') as source_file:
                current=source_file.read(len(raw)+1)
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=digest or current!=raw:
                raise ValueError('copy-drift')
        result.update(status='passed',files={p.name:{'bytes':len(raw),'sha256':'sha256:'+digest}
                                            for p,raw,digest in rows},maximumBytes=20*1024*1024)
    finally:
        marker.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(admit(args.output)['status'])