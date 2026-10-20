"""Closed retained-component bisection; observations never qualify original13."""
import json
from tools import java_resource_runtime_node as runtime
from tools.phase2_operator_process import require
from tools.rust_capsule_node import selected_revision

CASES=(('foreign','fresh','resource-java-foreign-fresh'),
       ('examples','clear','resource-java-clear'),
       ('examples','parallel','resource-java-parallel'))


def checked(row,component,revision,mode):
    response=row['response'];used=response['data']['consumption']
    require(row['processReaped'] and response['outcomeKnown'] and revision['releaseDigest']==component
        and response['data']['resolvedRevision']==revision,'resource-java-diagnostic-known-reaped-revision')
    require(0<int(used['cpuFuel'])<=1000000000 and 0<int(used['peakMemoryBytes'])<=67108864
        and 0<=int(used['logBytes'])<=256 and all(int(used[key])==0 for key in
            ('outboundRequests','childCalls','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
        'resource-java-diagnostic-original-budgets')
    if row['exitCode']==0:
        runtime.checked_invocation(row,component,revision,mode)
        return 'exact-success-value'
    require(row['exitCode']==4 and response['category']=='platform-failure'
        and response['error']['code']=='guest-trap','resource-java-diagnostic-closed-failure')
    return 'guest-trap'


def programme(clients,targets,probe,output,component):
    result={'schemaVersion':'latent.java.resource-runtime-diagnostic.v1','status':'incomplete',
        'diagnosticOnly':True,'originalProgrammePassed':False,'fullTicketQualification':False,'cases':[]}
    for tenant,mode,label in CASES:
        client,target=clients[tenant],targets[tenant];revision=selected_revision(client,target)
        row=runtime.call_mode(client,target,mode,label)
        result['cases'].append({'tenant':tenant,'mode':mode,'invocation':row})
        (output/'diagnostic-progress.json').write_bytes((json.dumps(result,separators=(',',':'))+'\n').encode())
        result['cases'][-1]['observation']=checked(row,component,revision,mode)
        result['cases'][-1]['retirement']=runtime.retire(client,probe,target,output,label)
    result['status']='observed';return result
