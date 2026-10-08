from pathlib import Path
import json
import re

root=Path(__file__).resolve().parent/'integration-v12-all-open-acceptance-audit-v13'
record=json.loads((root/'acceptance-reference-review.json').read_text())
prs={row['number']:row for row in json.loads((root/'recent-merged-prs-current.json').read_text())}
for row in record['auditRows']:
    evidence=[]
    for reference in row['recentMergedReferences']:
        pr=prs[reference['pr']]
        paragraphs=(pr.get('body') or '').split('\n\n')
        partial=[part for part in paragraphs if re.search(r'(?:does not close|can close|still needs|still need|remain required|remaining acceptance|full.*pending|acceptance.*pending|broader issue|implementation slice|substrate milestone|not.*qualification)',part,re.I)]
        if partial:evidence.append(dict(pr=pr['number'],url=pr['url'],explicitRemainingScope=partial[:2]))
    row['mergedPrBodiesExplicitlyRetainPendingAcceptance']=evidence
record['concreteReviewedEarlierPartialTickets']=[390,392,394]
record['concreteEarlierPartialProof']='MergedPR757 explicitly authority slice,794 requires actual verified guest/ordinary dispatcher/reconciliation,764 lacks integrated trusted selector/guest/cell/commit/trap qualification.'
(root/'acceptance-reference-review.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'allOpenIssuesAudited':record['openCount'],
    'earlierMergedReferenceBodiesWithExplicitPendingScope':sum(bool(row['mergedPrBodiesExplicitlyRetainPendingAcceptance']) for row in record['auditRows']),
    'unambiguousCompletedEarlierMergeTickets':[],'newIssueClosures':[]}))
