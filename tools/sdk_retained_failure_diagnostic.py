#!/usr/bin/env python3
'''Capture exact failed-owner artifacts once and report bounded public diagnostics.'''
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import re,subprocess,zipfile

REPO = 'KirilsTurkins/latent-service-fabric'
OWNERS = (
 ('rust',41959459784,127022081605,13386221747,1857881,
  '23681a99be7d82bcba44acfbe09736b511fea04353932ad27951325a054c0aac','80243cfa55377d15c03f433602bb9f00fa85fb05'),
 ('q35',41960168003,127024405192,13386252486,791131,
  'bec9926aff592f5517a555ed0009297d399861855ae450a0fee979d3cc1e29cc','15e8e4b31493a2bd5df7a936578c00fe513cdcdc'),
 ('dotnet',41956909273,127013898742,13386035903,6691708,
  'fe24765685faa0b42fe918b004cb78eaf6ef4a90f19cc02bb9628bbabd547e31','589a81643094e2c3a3f9bec6b8293acb92e3203b'),
 ('java',41959719013,127022935214,13385972468,31022,
  '2978750678e1ab7c21ba2fa6a330e7a944ffabce3be0927ffd3b2b88f160ce13','9538b0c991e58fe2677c1ab187fdd2a5310afddc'),
)
IDENT=re.compile(r'^[a-z][a-z0-9_.-]{1,119}$')
TOKEN=re.compile(r'(?<![A-Za-z0-9-])[a-z][a-z0-9]+(?:-[a-z0-9]+){2,}(?![A-Za-z0-9-])')
PROGRESS=re.compile(r'\bprogress-[a-z0-9.-]{1,60}[ =:]+[0-9:.-]{1,30}\b',re.I)
COMPILER=re.compile(r'\berror:\s*(?:no previous prototype for|implicit declaration of function|unknown type name|conflicting types for|undefined reference to)\s*[\x27\x60\u2018]?([A-Za-z_][A-Za-z0-9_]{0,100})')

def api(endpoint):
    p=subprocess.run(['gh','api',f'repos/{REPO}/{endpoint}'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if p.returncode != 0 or len(p.stdout)>8*1024*1024: raise ValueError('sdk-evidence-metadata-unavailable')
    return json.loads(p.stdout)

def fetch(endpoint,path,maximum):
    with path.open('xb') as out:
        p=subprocess.run(['gh','api',f'repos/{REPO}/{endpoint}'],stdout=out,stderr=subprocess.PIPE,timeout=180)
    if p.returncode != 0 or path.stat().st_size>maximum: raise ValueError('sdk-evidence-download-failed')
    return hashlib.sha256(path.read_bytes()).hexdigest()

def committed_codes():
    pattern=re.compile(r'''[\x27\x22]([a-z][a-z0-9]+(?:-[a-z0-9]+){2,})[\x27\x22]''')
    result=set()
    for base in (Path('tools'),Path('crates/latent-packaging/src')):
        for p in base.rglob('*'):
            if p.suffix not in ('.py','.rs') or not p.is_file() or p.stat().st_size>4*1024*1024: continue
            result.update(pattern.findall(p.read_text(encoding='utf-8',errors='ignore')))
    return result

def identity(value):
    return value if isinstance(value,str) and IDENT.fullmatch(value) else None

def inspect_archive(path,codes):
    with zipfile.ZipFile(path) as z:
        files=z.infolist()
        if len(files)>1000 or sum(f.file_size for f in files)>160*1024*1024: raise ValueError('sdk-evidence-archive-bound')
        if z.testzip() is not None: raise ValueError('sdk-evidence-archive-crc')
        stages,failures,matches,progress,symbols=set(),set(),set(),set(),set()
        for info in files:
            n=info.filename
            if info.file_size>4*1024*1024: continue
            if n.endswith(('FAILED.json','commands.json')):
                try: value=json.loads(z.read(info))
                except (ValueError,UnicodeError): continue
                if isinstance(value,dict):
                    stage=identity(value.get('stage'))
                    if stage: stages.add(stage)
                    seq=value.get('commands',[])
                else: seq=value
                if isinstance(seq,list):
                    for item in seq:
                        if not isinstance(item,dict): continue
                        stage=identity(item.get('stage')); status=item.get('exitCode')
                        if stage and isinstance(status,int) and status!=0: failures.add((stage,status))
            if n.endswith(('.stderr.txt','.stdout.txt','.log')):
                text=z.read(info).decode('utf-8',errors='replace')
                for line in text.splitlines():
                    if any(w in line.lower() for w in ('error','fail','panic','refus','exception')):
                        matches.update(t for t in TOKEN.findall(line) if t in codes)
                    progress.update(PROGRESS.findall(line));symbols.update(COMPILER.findall(line))
        return {'zipMembers':len(files),'crcVerified':True,'stages':sorted(stages)[:20],
                'failedCommands':[{'stage':x,'exitCode':y} for x,y in sorted(failures)[:20]],
                'committedDiagnosticCodes':sorted(matches)[:30],
                'progressMarkers':sorted(progress)[:15],'compilerErrorSymbols':sorted(symbols)[:15]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);codes=committed_codes();results=[]
    for label,run,job,artifact,size,digest,head in OWNERS:
        m=api(f'actions/runs/{run}');item=api(f'actions/artifacts/{artifact}')
        if (m.get('head_sha')!=head or m.get('status')!='completed' or m.get('conclusion')!='failure'
            or item.get('expired') or item.get('size_in_bytes')!=size or item.get('digest')!='sha256:'+digest):
            raise ValueError('sdk-evidence-owner-identity-mismatch')
        archive=args.output/(label+'.zip');actual=fetch(f'actions/artifacts/{artifact}/zip',archive,16*1024*1024)
        if actual!=digest or archive.stat().st_size!=size: raise ValueError('sdk-evidence-artifact-digest-mismatch')
        log=args.output/(label+'.log');log_digest=fetch(f'actions/jobs/{job}/logs',log,16*1024*1024)
        found=inspect_archive(archive,codes);found.update(label=label,run=run,job=job,artifact=artifact,head=head,
            artifactSha256=actual,jobLogSha256=log_digest);results.append(found)
        print('::notice title=SDK '+label+' retained failure::'+json.dumps(found,separators=(',',':'),ensure_ascii=True),flush=True)
    (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__': main()
