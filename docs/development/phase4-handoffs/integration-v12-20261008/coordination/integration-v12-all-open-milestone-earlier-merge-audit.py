from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import subprocess

coord=Path(__file__).resolve().parent;out=coord/'integration-v12-all-open-acceptance-audit-v13';out.mkdir(exist_ok=True)
repo='KirilsTurkins/latent-service-fabric';env=dict(os.environ,GODEBUG='http2client=0')
raw=subprocess.check_output(['gh','api',f'repos/{repo}/issues?milestone=7&state=all&per_page=100'],env=env,timeout=90)
(out/'milestone-issues-current.json').write_bytes(raw)
prs_raw=subprocess.check_output(['gh','pr','list','--repo',repo,'--base','development','--state','merged','--limit','100',
    '--json','number,title,body,mergedAt,url,closingIssuesReferences'],env=env,timeout=90)
(out/'recent-merged-prs-current.json').write_bytes(prs_raw)
merged=json.loads(prs_raw);issues=json.loads(raw)
rows=[]
for issue in issues:
    if 'pull_request' in issue or issue['state']!='open':continue
    number=issue['number'];body=issue.get('body') or ''
    refs=[]
    for pr in merged:
        direct=any(row['number']==number for row in pr.get('closingIssuesReferences',[]))
        textual=bool(re.search(r'(?<!\d)#'+str(number)+r'(?!\d)',pr['title']+'\n'+(pr.get('body') or '')))
        if direct or textual:refs.append(dict(pr=pr['number'],title=pr['title'],mergedAt=pr['mergedAt'],url=pr['url'],explicitClosingReference=direct))
    criteria=[line.strip() for line in body.splitlines() if re.match(r'\s*- \[[ xX]\]',line)]
    qualification=[line for line in criteria if re.search(r'real |separate|six |all six|crash|restore|retention|Gate|gate|qualif|adversarial|physical|browser|packaged',line,re.I)]
    rows.append(dict(issue=number,title=issue['title'],url=issue['html_url'],acceptanceCheckboxCount=len(criteria),
        acceptanceCriteria=criteria,requiredQualificationStatements=qualification,recentMergedReferences=refs,
        solelyMergedReferenceEstablishesFullAcceptance=False,unambiguousEarlierCompletedTicketConfirmed=False))
record=dict(at=datetime.now(timezone.utc).isoformat(),milestone=7,openCount=len(rows),
    closedIssues=[issue['number'] for issue in issues if 'pull_request' not in issue and issue['state']=='closed'],
    earlierMergedReferenceAuditIncludesAllOpenIssues=True,sourceQualificationStillRequiredForClosure=True,
    auditRows=rows,newIssueClosures=[])
(out/'acceptance-reference-review.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(dict(openIssuesAudited=len(rows),closedIssues=record['closedIssues'],
    mergedReferenceCandidates=[dict(issue=row['issue'],prs=[pr['pr'] for pr in row['recentMergedReferences']]) for row in rows if row['recentMergedReferences']],
    newIssueClosures=[])))
