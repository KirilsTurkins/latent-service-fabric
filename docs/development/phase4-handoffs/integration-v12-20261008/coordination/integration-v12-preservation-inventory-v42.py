from pathlib import Path
import json
import subprocess

repo=Path(r'C:\Users\turkins\Desktop\latent-fabric')
coord=Path(__file__).resolve().parent
raw=subprocess.check_output(['git','worktree','list','--porcelain'],cwd=repo,text=True)
rows=[]
for section in raw.strip().split('\n\n'):
    row={}
    for line in section.splitlines():
        key,_,value=line.partition(' ')
        row[key]=value
    name=Path(row['worktree']).name
    if name.startswith('lf-p4-') and (name.endswith('-v12') or name.startswith('lf-p4-current-')
            or name in {'lf-p4-pr823-java-current-bridge-v21','lf-p4-pr823-witness-vector-v35',
                'lf-p4-pr828-current-renderer-contracts-v23','lf-p4-qualified-http-origin-v19',
                'lf-p4-query-refusal-observation-v17','lf-p4-query-unavailable-observation-v20',
                'lf-p4-current823-qualified-collector-v19',
                'lf-p4-ci823-staging-model-20261007-v35','lf-p4-ci828-owner-fixtures-20261007-v36'}):
        p=Path(row['worktree'])
        row['exists']=p.exists()
        if p.exists():
            row['status']=subprocess.check_output(['git','status','--porcelain=v1'],cwd=p,text=True)
            row['unmerged']=subprocess.check_output(['git','ls-files','--unmerged'],cwd=p,text=True)
        rows.append(row)
out=coord/'integration-v12-preservation-owned-inventory-v42.json'
out.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(dict(path=str(out),count=len(rows),rows=[dict(path=r['worktree'],head=r.get('HEAD'),
    branch=r.get('branch'),dirty=bool(r.get('status')),unmerged=bool(r.get('unmerged')),status=r.get('status')) for r in rows]),indent=2))
