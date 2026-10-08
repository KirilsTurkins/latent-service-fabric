"""Review conflict records against actual merged workflows; preserve obligations."""
import json
from pathlib import Path
import subprocess
import sys

root=Path.cwd().resolve()
sys.path.insert(0,str(root))
from tools import ci_contracts as contracts, ci_lane_inventory as lanes

paths=[p for p in subprocess.check_output(['git','diff','--name-only','--diff-filter=U']).decode().splitlines()
       if p.startswith('tools/ci/contracts/workflows/')]
reports=[]
for name in paths:
    parents=[json.loads(subprocess.check_output(['git','show',f':{stage}:{name}'])) for stage in [2,3]]
    first,second=parents
    assert first['kind']==second['kind'] and first['workflow']==second['workflow']
    workflow=first['workflow']
    try:
        raw=subprocess.check_output(['git','show',':0:'+workflow]).decode()
    except subprocess.CalledProcessError:
        raw=(root/workflow).read_text(encoding='utf8')
    observed=lanes.structural_workflow(lanes.workflow_model(raw))
    result=dict(first)
    if first['kind']=='workflow':
        policy={k:v for k,v in observed.items() if k!='jobs'}
        assert all(set(p['requiredJobs'])<=set(observed['jobs']) for p in parents)
        # Trigger paths/triggers are independent of parameter ordering.
        for p in parents:
            for event,data in p['policy'].get('on',{}).items():
                assert event in policy.get('on',{})
                for key,value in data.items() if isinstance(data,dict) else []:
                    if isinstance(value,list): assert set(value)<=set(policy['on'][event][key])
                    else: assert value==policy['on'][event][key]
            assert p['policy'].get('permissions')==policy.get('permissions')
        result.update(policy=policy,requiredJobs=sorted(observed['jobs']))
        unchanged=True
    else:
        assert first['jobId']==second['jobId']
        for key in ['baselineRevision','before','coverage']:
            assert first[key]==second[key],(name,key)
        definition=observed['jobs'][first['jobId']]
        actual_commands=lanes.run_commands(workflow,{'jobs':{first['jobId']:definition}})
        for p in parents:
            old_commands=lanes.run_commands(workflow,{'jobs':{p['jobId']:p['definition']}})
            assert set(old_commands)<=set(actual_commands),(name,'removed command')
            for key in old_commands:
                assert old_commands[key]==actual_commands[key],(name,key,'command changed')
        result['definition']=definition
        unchanged=True
    result['reviewReason']=first['reviewReason']+' Retain incoming reviewed obligations: '+second['reviewReason']
    (root/name).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8',newline='\n')
    reports.append({'record':name,'actualStructuralWorkflowDerived':True,'bothParentCommandsTriggersPermissionsRetained':unchanged})
out=Path(r'C:\Users\turkins\Desktop\latent-phase4-coordination\integration-v12-union-review\pr828-workflow-record-union-review.json')
out.write_text(json.dumps(reports,indent=2)+'\n')
print(json.dumps({'resolvedWorkflowRecords':len(reports),'allParentRequirementsRetained':True}))
