#!/usr/bin/env python3
'''Capture exact failed-owner artifacts once and report bounded public diagnostics.'''
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
import re,subprocess,zipfile

REPO = 'KirilsTurkins/latent-service-fabric'
OWNERS = (
 ('java-guard',41966722819,127045319343,13389050424,23429411,
  '4a4da4c4930570768260b3010601f5882097a042491a67bbb98946dc86719464','b2de1326f0c9411e24746a936759e66f19c92e09'),
)
GUARD_MARKERS = (
 'CHECKPOINT_CLASSINFO_DIRECT_CONTROL PASS original',
 'CHECKPOINT_CLASSINFO_DIRECT_CONTROL PASS corrected',
 'CHECKPOINT_COMPATIBILITY finite PASS', 'CHECKPOINT_COMPATIBILITY finite FAIL',
 'CHECKPOINT_COMPATIBILITY class-reflection PASS', 'CHECKPOINT_COMPATIBILITY class-reflection FAIL',
 'latent.java.classinfo-operands.v1 refused', 'checkpoint-control-progress-verdict',
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
        stages,failures,matches,progress,symbols,guard_markers=set(),set(),set(),set(),set(),set()
        guard_summary=None
        for info in files:
            if info.file_size>4*1024*1024 or not info.filename.endswith(('FAILED.json','commands.json','result.json')): continue
            try: value=json.loads(z.read(info))
            except (ValueError,UnicodeError): continue
            if isinstance(value,dict):
                if value.get('scope') == 'jvm-only-compiler-control':
                    status=value.get('status')
                    guard_summary={'status':status if status in ('started','failed','passed') else None}
                    for key in ('controls','compilerControls','monitorControls','classloaderControls'):
                        v=value.get(key)
                        guard_summary[key]=min(len(v),16) if isinstance(v,list) else None
                    for key in ('componentExecutionPerformed','nativeExecutionPerformed'):
                        v=value.get(key)
                        guard_summary[key]=v if type(v) is bool else None
                stage=identity(value.get('stage'))
                if stage: stages.add(stage)
                seq=value.get('commands',[])
            else: seq=value
            if isinstance(seq,list):
                for item in seq:
                    if not isinstance(item,dict): continue
                    stage=identity(item.get('stage')); status=item.get('exitCode')
                    if stage and isinstance(status,int) and status!=0: failures.add((stage,status))
        failing={stage for stage,_ in failures}
        for info in files:
            n=info.filename
            if info.file_size>4*1024*1024 or not n.endswith(('.stderr.txt','.stdout.txt','.log')): continue
            text=z.read(info).decode('utf-8',errors='replace')
            selected=any('-'+stage+'.' in n for stage in failing)
            for line in text.splitlines():
                guard_markers.update(marker for marker in GUARD_MARKERS if marker in line)
                if selected:
                    matches.update(t for t in TOKEN.findall(line) if t in codes)
                progress.update(PROGRESS.findall(line));symbols.update(COMPILER.findall(line))
        return {'zipMembers':len(files),'crcVerified':True,'stages':sorted(stages)[:20],
                'failedCommands':[{'stage':x,'exitCode':y} for x,y in sorted(failures)[:20]],
                'committedDiagnosticCodes':sorted(matches)[:30],
                'progressMarkers':sorted(progress)[:15],'compilerErrorSymbols':sorted(symbols)[:15],
                'guardMarkers':sorted(guard_markers),'guardControlSummary':guard_summary}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);codes=committed_codes();results=[]
    for label,run,job,artifact,size,digest,head in OWNERS:
        m=api(f'actions/runs/{run}');item=api(f'actions/artifacts/{artifact}')
        if (m.get('head_sha')!=head or m.get('status')!='completed' or m.get('conclusion')!='failure'
            or item.get('expired') or item.get('size_in_bytes')!=size or item.get('digest')!='sha256:'+digest):
            raise ValueError('sdk-evidence-owner-identity-mismatch')
        archive=args.output/(label+'.zip');actual=fetch(f'actions/artifacts/{artifact}/zip',archive,32*1024*1024)
        if actual!=digest or archive.stat().st_size!=size: raise ValueError('sdk-evidence-artifact-digest-mismatch')
        log=args.output/(label+'.log');log_digest=fetch(f'actions/jobs/{job}/logs',log,16*1024*1024)
        found=inspect_archive(archive,codes);found.update(label=label,run=run,job=job,artifact=artifact,head=head,
            artifactSha256=actual,jobLogSha256=log_digest);results.append(found)
        print('::notice title=SDK '+label+' retained failure::'+json.dumps(found,separators=(',',':'),ensure_ascii=True),flush=True)
    (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__': main()
