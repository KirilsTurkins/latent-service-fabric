from pathlib import Path
import json

root=Path(__file__).resolve().parent/'integration-v12-all-open-acceptance-audit-v13'
issues=json.loads((root/'milestone-issues-current.json').read_bytes())
prs=json.loads((root/'recent-merged-prs-current.json').read_bytes())
for number in (390,392,394):
    issue=next(row for row in issues if row['number']==number)
    print(json.dumps(dict(issue=number,title=issue['title'],criteria=[line for line in issue['body'].splitlines() if line.strip().startswith('- [')]),ensure_ascii=False))
for number in (757,794,764):
    pr=next(row for row in prs if row['number']==number)
    print(json.dumps(dict(pr=number,title=pr['title'],body=pr['body'],closingReferences=pr['closingIssuesReferences']),ensure_ascii=False))
