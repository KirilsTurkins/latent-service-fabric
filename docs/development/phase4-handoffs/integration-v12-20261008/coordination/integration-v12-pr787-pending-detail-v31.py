from pathlib import Path
import json

coord=Path(__file__).resolve().parent
directory=coord/'integration-v12-delivery-refresh-20261008T061825Z'
rows=json.loads((directory/'raw.json').read_bytes())
row=next(r for r in rows if r['number']==787)
checks=[dict(name=c.get('name'),status=c.get('status'),conclusion=c.get('conclusion'),
    url=c.get('detailsUrl')) for c in row['statusCheckRollup'] if c.get('status')!='COMPLETED']
result=dict(pr=787,head=row['headRefOid'],mergeable=row['mergeable'],pending=checks,
    adminMergeEligibleAtSnapshot=False)
(coord/'integration-v12-union-review/pr787-pending-detail-v31.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
