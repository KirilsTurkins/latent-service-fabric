from pathlib import Path
import json

coord=Path(__file__).resolve().parent
raw=json.loads((coord/'integration-v12-delivery-refresh-20261008T061825Z/raw.json').read_bytes())
row=next(r for r in raw if r['number']==787)
result=dict(number=787,head=row['headRefOid'],mergeable=row['mergeable'],
    checks=[dict(name=c.get('name'),status=c.get('status'),conclusion=c.get('conclusion'),url=c.get('detailsUrl'))
    for c in row['statusCheckRollup']],
    allCompletedGreen=False, pendingPortableAndOCIRequiredBeforeFullCIMergeClaim=True)
(coord/'integration-v12-union-review/pr787-current-green-completion-review-v32.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps([c for c in result['checks'] if any(x in (c['name'] or '') for x in ['Rust','Fast','Repository','CI result','SDK','Documentation'])]))
