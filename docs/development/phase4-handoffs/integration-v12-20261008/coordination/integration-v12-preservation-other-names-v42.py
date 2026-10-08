from pathlib import Path
import json
import subprocess

repo=Path(r'C:\Users\turkins\Desktop\latent-fabric')
coord=Path(__file__).resolve().parent
known={r['worktree'] for r in json.loads((coord/'integration-v12-preservation-owned-inventory-v42.json').read_bytes())}
raw=subprocess.check_output(['git','worktree','list','--porcelain'],cwd=repo,text=True)
for section in raw.strip().split('\n\n'):
    row=dict(line.partition(' ')[::2] for line in section.splitlines())
    p=Path(row['worktree']); name=p.name
    if name.startswith('lf-p4-') and row['worktree'] not in known and '-root-' not in name:
        print(name+' '+row.get('HEAD','')+' '+row.get('branch',''))
