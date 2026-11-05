#!/usr/bin/env python3
"""Retain exact failed SDK check logs once; publish only bounded identifiers."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
R='KirilsTurkins/latent-service-fabric'
OWNERS=(
 ('stream-dotnet-tools',41961125029,127027831899,'4570c2279212ccd2359bf5e7d2916f8a80a66b67'),
 ('rust-dotnet-tools',41959639613,127022679368,'33b4e1cb4a3cd31ff9b67579828cc4c67f041f6f'),
 ('rust-typescript-tools',41959639613,127022679464,'33b4e1cb4a3cd31ff9b67579828cc4c67f041f6f'),
 ('rust-sdk-advisories',41959639781,127032604722,'33b4e1cb4a3cd31ff9b67579828cc4c67f041f6f'),
 ('rust-tests',41959639617,127032871752,'33b4e1cb4a3cd31ff9b67579828cc4c67f041f6f'),
 ('q35-sdk-advisories',41960172326,127045012755,'15e8e4b31493a2bd5df7a936578c00fe513cdcdc'),
 ('java-wsl-build',41966728063,127045341259,'b2de1326f0c9411e24746a936759e66f19c92e09'),
)
MARKERS=('no space left on device','disk quota exceeded','temporary failure in name resolution',
 'connection timed out','connection reset by peer','certificate verify failed','out of memory',
 'cannot allocate memory','permission denied','failed to download','deadline exceeded',
 'command-exit','failed to fetch','too many requests','test result: failed',
 'package vulnerability','github actions runner lost communication')
EXCEPTIONS=('TimeoutError','FileNotFoundError','BuildProcessError','AssertionError','HTTPError',
 'ConnectionError','ValueError','CalledProcessError','OSError','URLError','RuntimeError')
TOKEN=re.compile(r'(?<![A-Za-z0-9-])[a-z][a-z0-9]+(?:-[a-z0-9]+){2,}(?![A-Za-z0-9-])')
def metadata(endpoint):
 p=subprocess.run(['gh','api',f'repos/{R}/{endpoint}'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=True)
 if len(p.stdout)>8*1024*1024: raise ValueError('oversize metadata')
 return json.loads(p.stdout)
def known_codes():
 p=re.compile(r"[\x27\x22]([a-z][a-z0-9]+(?:-[a-z0-9]+){2,})[\x27\x22]")
 out=set()
 for root in (Path('tools'),Path('crates/latent-packaging/src')):
  for f in root.rglob('*'):
   if f.is_file() and f.suffix in ('.py','.rs') and f.stat().st_size<=4*1024*1024:
    out.update(p.findall(f.read_text(encoding='utf-8',errors='ignore')))
 return out
def classify(data,codes):
 text=data.decode('utf-8',errors='replace'); lower=text.lower()
 ids=sorted(set(re.findall(r'\b(?:CVE-[0-9]{4}-[0-9]{4,8}|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|RUSTSEC-[0-9]{4}-[0-9]{4,})\b',text,re.I)))
 tests=sorted(set(re.findall(r'\btest ([A-Za-z_][A-Za-z0-9_:]{0,159}) \.\.\. FAILED\b',text)))
 return {'fixedMarkers':[x for x in MARKERS if x in lower],
  'exceptions':[x for x in EXCEPTIONS if re.search(r'\b'+re.escape(x)+r'\b',text)],
  'rustCompilerCodes':sorted(set(re.findall(r'\berror\[(E[0-9]{4})\]',text)))[:30],
  'failedTestNames':tests[:30], 'advisoryIds':ids[:30],
  'sourceDiagnosticCodes':sorted(set(TOKEN.findall(text)) & codes)[:50]}
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
 args.output.mkdir(parents=True,exist_ok=False);codes=known_codes();results=[];failed=False
 for label,run,job,head in OWNERS:
  try:
   m=metadata(f'actions/runs/{run}');j=metadata(f'actions/jobs/{job}')
   if m.get('head_sha')!=head or j.get('head_sha')!=head or j.get('run_id')!=run or j.get('status')!='completed' or j.get('conclusion')!='failure': raise ValueError('identity mismatch')
   path=args.output/(label+'.log')
   with path.open('xb') as out:
    p=subprocess.run(['gh','api',f'repos/{R}/actions/jobs/{job}/logs'],stdout=out,stderr=subprocess.PIPE,timeout=180)
   if p.returncode or path.stat().st_size>32*1024*1024: raise ValueError('log unavailable or oversized')
   raw=path.read_bytes();item=classify(raw,codes);item.update(label=label,run=run,job=job,head=head,logSha256=hashlib.sha256(raw).hexdigest())
  except Exception as exc:
   item={'label':label,'run':run,'job':job,'head':head,'captureFailure':type(exc).__name__};failed=True
  results.append(item)
  (args.output/'summary.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
  print('::notice title=SDK CI failure '+label+'::'+json.dumps(item,separators=(',',':'),ensure_ascii=True),flush=True)
 if failed: raise ValueError('one or more exact logs were not captured')
if __name__=='__main__': main()
