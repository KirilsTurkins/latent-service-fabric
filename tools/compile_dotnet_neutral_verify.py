"""Compile the standalone frozen-sample checker using the existing locked crate dependencies."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def select_artifacts(messages: Path, deps: Path):
    deps=deps.resolve(strict=True)
    if messages.stat().st_size > 64*1024*1024:
        raise ValueError('cargo-message-bound')
    selected={'wasmparser@0.259.0':set(),'sha2@0.11.0':set()}
    for line in messages.read_text(encoding='utf-8').splitlines():
        row=json.loads(line)
        if row.get('reason') != 'compiler-artifact': continue
        package=row.get('package_id','')
        for identity in selected:
            if package.endswith('#'+identity):
                for filename in row.get('filenames',[]):
                    path=Path(filename)
                    if path.suffix=='.rlib':
                        real=path.resolve(strict=True)
                        if real.parent!=deps or re.fullmatch(r'lib[a-z0-9_]+-[0-9a-f]+\.rlib',real.name) is None:
                            raise ValueError('compiler-artifact-path')
                        selected[identity].add(real)
    if not all(len(paths)==1 for paths in selected.values()):
        raise ValueError('compiler-artifact-ambiguity')
    return {identity:next(iter(paths)) for identity,paths in selected.items()}


def compile_checker(messages: Path, output: Path):
    root=Path(__file__).resolve().parents[1]
    deps=(root/'target/debug/deps').resolve(strict=True)
    require=lambda ok, reason: None if ok else (_ for _ in ()).throw(ValueError(reason))
    selected=select_artifacts(messages,deps)
    output.mkdir(parents=True,exist_ok=False)
    source=root/'tools/dotnet_neutral_verify.rs'
    arguments=['--edition=2024','-L','dependency='+str(deps)]
    for identity,path in selected.items():
        arguments.extend(['--extern',identity.split('@')[0]+'='+str(path)])
    records=[]
    for name,extra in (('tests',['--test']),('checker',[])):
        target=output/name
        command=['rustc',*arguments,*extra,str(source),'-o',str(target)]
        result=subprocess.run(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
        require(len(result.stdout)<=1024*1024,'compiler-output-bound')
        (output/(name+'-compile.log')).write_bytes(result.stdout)
        if result.returncode: print(result.stdout.decode('utf-8',errors='replace'))
        require(result.returncode==0,'compiler-failed-'+name)
        records.append({'name':name,'exit':result.returncode})
    result=subprocess.run([str(output/'tests')],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    require(len(result.stdout)<=1024*1024,'test-output-bound')
    (output/'tests.log').write_bytes(result.stdout)
    if result.returncode: print(result.stdout.decode('utf-8',errors='replace'))
    require(result.returncode==0,'checker-tests-failed')
    artifacts={}
    for identity,path in selected.items():
        artifacts[identity]={'name':path.name,'sha256':'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()}
    receipt={'schemaVersion':'latent.dotnet.neutral-compiler.v1',
             'sourceSha256':'sha256:'+hashlib.sha256(source.read_bytes()).hexdigest(),
             'dependencies':artifacts,'commands':records,'testExit':result.returncode,
             'guestExecution':False,'productionProfile':False}
    (output/'compiler.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cargo-messages',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    compile_checker(args.cargo_messages,args.output)