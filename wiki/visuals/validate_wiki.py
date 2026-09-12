#!/usr/bin/env python3
"""Validate the full Wiki and stage its finite managed inventory for publication."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'pages'
PAGES=set('Activation-Lifecycle Architecture Capsule-Development Contracts-and-APIs Core-Concepts Deployment-and-Routing Design-Governance Development-Workflow Execution-Cells FAQ Getting-Started Glossary Home Operator-CLI Performance-and-Infrastructure Phase-0-Runbook Phase-0-Status Phase-1-Status Repository-Map Roadmap SDKs Security-and-Isolation State-and-Effects Testing-and-Benchmarks _Footer _Sidebar'.split())
ASSETS={f'assets/{name}.{suffix}' for name in ('architecture-at-a-glance','system-decomposition') for suffix in ('svg','gif')}
LEGACY={f'assets/{name}.svg' for name in ('activation-lifecycle','contract-boundaries','phase0-activation-flow','phase0-evidence-gate','phase0-scope-boundary','resource-ownership','roadmap-phases')}
BASE='https://github.com/KirilsTurkins/latent-service-fabric/'

def git(*args,cwd=None):
    return subprocess.check_output(['git',*args],cwd=cwd,text=True).strip()

def validate(authority_ref):
    expected={name+'.md' for name in PAGES}|ASSETS
    actual={p.relative_to(SOURCE).as_posix() for p in SOURCE.rglob('*') if p.is_file()}
    assert actual==expected, f'Unexpected/missing managed files: {actual^expected}'
    authorities=set(git('ls-tree','-r','--name-only',authority_ref).splitlines())
    assert 'docs/phase-1-extension-completion.md' in authorities,'Authority lacks completed Phase 1'
    assert 'docs/phase-2-operator-workflows.md' in authorities,'Authority lacks Phase 2 operator workflows'
    links=0
    for rel in sorted(expected):
        file=SOURCE/rel
        assert not file.is_symlink(),f'Symlink source: {rel}'
        if file.suffix!='.md': continue
        source=file.read_text(encoding='utf-8')
        assert source.startswith('<!-- LSF-WIKI-MANAGED -->\n'),f'Missing managed marker: {rel}'
        if file.stem not in {'_Sidebar','_Footer'}: assert source.splitlines()[1].startswith('# '),rel
        assert not re.search(r'<\s*(?:script|iframe|object|embed|img)\b',source,re.I),rel
        assert '```mermaid' not in source,rel
        assert not any(re.search(r'\[\[[^]]+\|',line) for line in source.splitlines() if line.startswith('|')),rel
        for match in re.finditer(r'!?\[([^\]]*)\]\(([^)]+)\)',source):
            label,target=match.groups()
            links+=1
            assert label.strip(),f'Empty link label: {rel}'
            if target.startswith(BASE+'blob/'):
                branch, separator, target_path=target.removeprefix(BASE+'blob/').partition('/')
                assert separator and branch in {'development','release'},f'Unexpected authority branch: {target}'
                target_path=target_path.split('#')[0]
                assert target_path in authorities,f'Missing/case-wrong authority {target_path}'
            elif target.startswith(BASE+'tree/'):
                branch, _, target_path=target.removeprefix(BASE+'tree/').partition('/')
                assert branch in {'development','release'},f'Unexpected authority branch: {target}'
                target_path=target_path.split('#')[0].rstrip('/')
                assert not target_path or any(path.startswith(target_path+'/') for path in authorities),f'Missing/case-wrong authority directory {target_path}'
            elif target.startswith(('https://','http://','#')): continue
            else:
                target=target.split('#')[0]
                path=PurePosixPath(target)
                assert not path.is_absolute() and '..' not in path.parts,rel
                candidate=target if path.suffix else target+'.md'
                assert candidate in expected,f'Broken local link {rel}: {target}'
        for target in re.findall(r'\[\[([^]|]+)(?:\|[^]]+)?\]\]',source): assert target in PAGES,rel
    sidebar=(SOURCE/'_Sidebar.md').read_text()
    assert set(re.findall(r'\[\[([^]|]+)',sidebar))==PAGES-{'_Sidebar','_Footer'},'Sidebar inventory mismatch'
    for rel in sorted(ASSETS):
        file=SOURCE/rel
        if file.suffix=='.gif':
            data=file.read_bytes()
            assert data[:6] in {b'GIF87a',b'GIF89a'} and struct.unpack('<HH',data[6:10])==(1440,760),rel
            assert len(data)<300000,rel
            continue
        source=file.read_text(encoding='utf-8')
        root=ET.fromstring(source)
        assert root.attrib.get('viewBox')=='0 0 1440 760' and root.attrib.get('role')=='img',rel
        assert 'width' not in root.attrib and 'height' not in root.attrib,rel
        ids={e.attrib['id']:e for e in root.iter() if 'id' in e.attrib}
        assert len(ids)==sum('id' in e.attrib for e in root.iter()),rel
        assert all(i.startswith(file.stem+'-') for i in ids),rel
        for value in root.attrib.get('aria-labelledby','').split(): assert value in ids and ''.join(ids[value].itertext()).strip(),rel
        assert len(root.attrib.get('aria-labelledby','').split())==2,rel
        for e in root.iter():
            assert e.tag.rsplit('}',1)[-1].lower() not in {'script','foreignobject','image','iframe','object','animate','animatemotion'},rel
            for key,value in e.attrib.items():
                assert not key.lower().startswith('on'),rel
                if key.rsplit('}',1)[-1] in {'href','src'}: assert value.startswith('#') and value[1:] in ids,rel
                for ref in re.findall(r'url\(([^)]+)\)',value): assert ref.startswith('#') and ref[1:] in ids,rel
        assert not re.search(r'https?://|@import',source.replace('http://www.w3.org/2000/svg','')),rel
    print(f'PASS: {len(PAGES)} pages, {len(ASSETS)} assets, {links} links; exact authority paths checked against {authority_ref}')
    return expected

def stage(destination,files):
    destination=destination.resolve(strict=True)
    assert (destination/'.git').is_dir(),'Stage destination must be a separate Wiki checkout'
    assert git('remote','get-url','origin',cwd=destination)==BASE.rstrip('/')+'.wiki.git','Unexpected Wiki remote'
    assert not git('status','--porcelain',cwd=destination),'Wiki checkout must be clean'
    for path in destination.rglob('*'):
        if '.git' not in path.relative_to(destination).parts: assert not path.is_symlink(),f'Symlink in Wiki checkout: {path}'
    manifest_path=destination/'.latent-service-fabric-wiki.json'
    assert manifest_path.is_file(),'Existing managed manifest is required before replacement'
    previous=json.loads(manifest_path.read_text(encoding='utf-8'))
    assert previous.get('schema_version')=='latent-service-fabric.wiki-manifest.v1','Unknown prior managed schema'
    owned=previous.get('managed_files')
    assert isinstance(owned,list) and all(isinstance(p,str) for p in owned),'Invalid prior ownership inventory'
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    def unknown_hashes():
        return {path.relative_to(destination).as_posix():digest(path)
                for path in destination.rglob('*') if path.is_file()
                and '.git' not in path.relative_to(destination).parts
                and path.relative_to(destination).as_posix() not in files|LEGACY|{'.latent-service-fabric-wiki.json'}}
    unknown_before=unknown_hashes()
    expected_hashes={rel:digest(SOURCE/rel) for rel in sorted(files)}
    for rel in sorted(LEGACY):
        path=destination/rel
        if path.exists():
            assert rel in owned,f'Refusing to remove unowned legacy asset: {rel}'
            assert path.is_file() and not path.is_symlink(),rel
            path.unlink()
    for rel in sorted(files):
        target=destination/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(SOURCE/rel,target)
    assert all((destination/rel).is_file() and digest(destination/rel)==expected_hashes[rel] for rel in files),'Staged source bytes differ'
    assert all(not (destination/rel).exists() for rel in LEGACY),'Retired assets remain'
    assert unknown_hashes()==unknown_before,'Unmanaged Wiki files changed'
    manifest={'schema_version':'latent-service-fabric.wiki-manifest.v1','publisher':'wiki/visuals/validate_wiki.py','source_revision':git('rev-parse','HEAD'),'managed_files':sorted(files),'managed_sha256':expected_hashes}
    (destination/'.latent-service-fabric-wiki.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(f'Staged and SHA256-verified {len(files)} managed files; only seven prior-owned Phase0 SVG paths may be removed. {len(unknown_before)} unmanaged files are unchanged.')

def verify_published(destination,files):
    destination=destination.resolve(strict=True)
    manifest=json.loads(git('show','HEAD:.latent-service-fabric-wiki.json',cwd=destination))
    assert set(manifest['managed_files'])==files,'Published managed inventory differs'
    assert set(manifest['managed_sha256'])==files,'Published hash inventory differs'
    for rel in sorted(files):
        blob=subprocess.check_output(['git','show',f'HEAD:{rel}'],cwd=destination)
        assert hashlib.sha256(blob).hexdigest()==manifest['managed_sha256'][rel],f'Published bytes differ: {rel}'
        assert hashlib.sha256((SOURCE/rel).read_bytes()).hexdigest()==manifest['managed_sha256'][rel],f'Published source differs: {rel}'
    tracked=set(git('ls-tree','-r','--name-only','HEAD',cwd=destination).splitlines())
    assert not tracked&LEGACY,'Published retired assets remain'
    print(f'PASS: exact Git blob SHA256 verified for all {len(files)} published files')

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--authority-ref',default='origin/development')
    parser.add_argument('--stage',type=Path)
    parser.add_argument('--verify-published',type=Path)
    args=parser.parse_args()
    files=validate(args.authority_ref)
    if args.stage: stage(args.stage,files)
    if args.verify_published: verify_published(args.verify_published,files)
