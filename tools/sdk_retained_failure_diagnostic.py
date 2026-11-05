#!/usr/bin/env python3
"""Classify the failed hosted evidence reader without publishing its raw log."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess
R='KirilsTurkins/latent-service-fabric'
HEAD='00d37b67df066df22b4ac4340672f732a96413c8'
MARKERS=('sdk-evidence-metadata-unavailable','sdk-evidence-owner-identity-mismatch',
 'sdk-evidence-download-failed','sdk-evidence-artifact-digest-mismatch',
 'sdk-evidence-archive-bound','sdk-evidence-archive-crc','no space left on device',
 'api rate limit exceeded','HTTP 403','HTTP 404','HTTP 410','HTTP 429')
EXCEPTIONS=('BadZipFile','KeyError','TypeError','ValueError','TimeoutExpired','MemoryError','OSError','CalledProcessError')
def api(endpoint):
 p=subprocess.run(['gh','api',f'repos/{R}/{endpoint}'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,check=True)
 return json.loads(p.stdout)
def classify(raw):
 t=raw.decode('utf-8',errors='replace')
 return {'markers':[x for x in MARKERS if x.lower() in t.lower()],
  'exceptions':[x for x in EXCEPTIONS if re.search(r'\b'+re.escape(x)+r'\b',t)],
  'readerTraceLines':sorted(set(int(x) for x in re.findall(r'sdk_retained_failure_diagnostic\.py", line ([0-9]+)',t)))}
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 m=api('actions/runs/41968097876');j=api('actions/jobs/127049781326')
 if m.get('head_sha')!=HEAD or m.get('conclusion')!='failure' or j.get('run_id')!=41968097876 or j.get('conclusion')!='failure': raise ValueError('reader identity mismatch')
 path=a.output/'reader.log'
 with path.open('xb') as out:
  p=subprocess.run(['gh','api',f'repos/{R}/actions/jobs/127049781326/logs'],stdout=out,stderr=subprocess.PIPE,timeout=180)
 if p.returncode or path.stat().st_size>16*1024*1024: raise ValueError('reader log unavailable')
 raw=path.read_bytes();x=classify(raw);x.update(run=41968097876,job=127049781326,head=HEAD,logSha256=hashlib.sha256(raw).hexdigest())
 (a.output/'summary.json').write_text(json.dumps(x,indent=2)+'\n',encoding='utf-8')
 print('::notice title=SDK evidence reader failure::'+json.dumps(x,separators=(',',':')),flush=True)
if __name__=='__main__': main()
