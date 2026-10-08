from pathlib import Path
import json

coord=Path(__file__).resolve().parent
issues=json.loads((coord/'integration-v12-all-open-acceptance-audit-v13/milestone-issues-current.json').read_bytes())
selected={i['number']:i for i in issues if i['number'] in {387,388,400,407,408,409}}
rows=[]
for number,issue in sorted(selected.items()):
    body=issue['body']
    criteria=[line for line in body.splitlines() if line.startswith('- [ ]')]
    rows.append(dict(number=number,title=issue['title'],criteria=criteria,
        currentEvidenceCannotCloseAllCriteria=True))
out=coord/'integration-v12-union-review/current-finite-acceptance-gaps-v29.json'
out.write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(dict(custody=str(out),criteriaCounts={str(r['number']):len(r['criteria']) for r in rows})))
