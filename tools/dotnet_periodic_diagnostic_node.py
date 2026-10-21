"""One failed periodic invocation, with a closed LOG-length diagnostic only."""
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import dotnet_managed_capacity_node as capacity
from tools import dotnet_standard_http_node as base
from tools.dotnet_periodic_diagnostic import codes, LOG
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_http_mixed_node import retain_partial
from tools.java_http_release_preparation import prepare
from tools.java_http_tenant_node import cleanup_owner
from tools.phase2_operator_process import require,stopped_record
from tools.phase2_operator_scenario import connect,stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import RecordingClient,deploy,delete_all,sample,start_call,finish_call,selected_revision
from tools.rust_capsule_project import fresh,read_json,write_json
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy

ACTIVATION='periodic-diagnostic'


def frame_size(message_length):
    require(type(message_length) is int and 1<=message_length<=94,'periodic-fixed-frame-length')
    # Exact frozen6fd logging.rs BorrowedLog and normalized BTreeMap order.
    # The original host trace/span formats are fixed32/16 lowercase hex.
    value={'activation_id':ACTIVATION,'level':'error','message':'p'*message_length,
        'fields':{'latent.activation_id':ACTIVATION,'latent.span_id':'0'*16,'latent.trace_id':'0'*32}}
    return len(json.dumps(value,separators=(',',':'),ensure_ascii=True).encode())


def decode(log_bytes):
    require(type(log_bytes) is int and 0<=log_bytes<=1024,'periodic-public-log-byte-bound')
    if log_bytes==0:return {'status':'not-observed','code':None,'reason':'unknown','qualification':False}
    values=[index for index in range(94) if frame_size(index+1)==log_bytes]
    require(len(values)==1,'periodic-not-exactly-one-fixed-diagnostic-frame')
    code=values[0]
    if code>=38:
        kind,error=divmod(code-38,7)
        return {'status':'original-reserve-refusal-observed','code':code,'reason':'managed-work-admission-refused',
            'ownerKind':kind,'ownerName':('task','managed-idle-worker','executor','queued-work','wait','timer','result','native')[kind],
            'originalHostU32':error,'hostError':('unavailable','permission-denied','resource-exhausted','cancelled',
                'deadline','invalid-state','invalid-token')[error],
            'qualification':False,'originalExceptionTextExported':False,'originalFailureUnchanged':True}
    return {'status':'original-handler-observed','code':code,
        'reason':'unknown' if code==0 else codes()[code-1],'qualification':False,
        'originalExceptionTextExported':False,'originalFailureUnchanged':True}


def run(artifact,native,output,*,deadline):
    output=fresh(output);original=capacity.shared.identities(artifact)
    products={name:file_identity(path,512*1024**2) for name,path in native.items()}
    record={'qualification':False,'originalPeriodicOraclePassed':False,'status':'incomplete',
        'originalBuild':original,'nativeProducts':products,'selectedOwnerLimits':dict(capacity.LIMITS),
        'selectedDiagnosticLogBytes':1024,'newGuestInvocations':0}
    stage='normal-signing'
    try:
        signed=output/'releases'
        signed_result=run_bounded_result([str(native['capsule_authoring']),'demo-sign',str(signed),str(artifact)],
            output,build_environment(output),timeout_seconds=30,max_output_bytes=65536)
        require(signed_result.returncode==0,'periodic-normal-demo-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-periodic-diagnostic-') as temporary,owned_cancellation() as cancellation,ExitStack() as cleanup:
            work=Path(temporary)
            for name in ('node','client','credentials'):(work/name).mkdir(mode=0o700)
            secret=('Bearer '+secrets.token_hex(32)).encode('ascii');credential=work/'credentials/main'
            credential.write_bytes(secret);credential.chmod(0o600)
            peer=Peer(secret,maximum_seconds=300);cleanup_owner(cleanup,peer,record,'peer')
            client=RecordingClient(native['latent'],work/'client',cancellation,min(deadline,time.monotonic()+300),
                evidence=output/'controls',invocation_timeout_millis=120000,control_timeout_millis=15000)
            config=capacity.configuration(work/'node',signed,peer,credential,2);settings=read_json(config)
            settings['providers']['log']={'identity':{'id':'periodic-log','tenant':'examples','service':'runtime-host','epoch':1}}
            settings['providers']['bindings'].append({'name':'periodic-log','tenant':'examples','consumerService':base.SERVICE,
                'providerService':'runtime-host','contract':LOG,'providerBinding':'periodic-log-installed'})
            config.write_text(json.dumps(settings,indent=2)+'\n',encoding='utf8')
            node=connect(client,native['latentd'],work/'node',config,'examples',1)
            cleanup_owner(cleanup,node,record,'node');probe=Probe(node,products['latentd'])
            source=signed/'dotnet-standard-http';stage='publication-preparation'
            published=client.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                '--operation-id','periodic-publish','--expected-generation','0')
            publication=published['data']['operation']['publication']['id']
            record['preparation']=prepare(client,publication,'examples',original['component.wasm']['sha256'],output)
            target=deploy(client,source/'deployment.json',publication)
            _,grants=base.grants(client,node,publication,peer.origin())
            descriptor,=[row for row in node.startup_record['providers'] if row['id']=='periodic-log']
            require(descriptor['capability']==LOG and descriptor['profile']=='activation-log-v1','periodic-original-log-provider')
            policy(client,'provider-binding','periodic-log-installed',{'formatVersion':1,'tenant':'examples','capability':LOG,
                'providerProfile':'activation-log-v1','configurationDigest':descriptor['configurationDigest'],
                'configurationEpoch':1,'restriction':{'operations':['write']}})
            policy(client,'policy','periodic-log-allow',{'formatVersion':1,'tenant':'examples','rules':[{
                'id':'fixed-diagnostic','effect':'allow','principals':[{'kind':'administrator','subject':'workflow-operator'}],
                'services':[base.SERVICE],'publications':[publication],'capability':LOG,'operations':['write'],
                'resources':{'kind':'log','levels':['error']},
                'ceiling':{'operations':1,'inputBytes':1024,'outputBytes':0,'wallTimeMillis':5000}}]})
            target=deploy(client,source/'deployment.json',publication,generation=str(target['generation']),
                grants=[*grants,{'capability':LOG,'policy':'periodic-log-allow'}])
            revision=selected_revision(client,target);stage='original-periodic-mode3'
            process=start_call(client,target,'dotnet-standard-http','run',[3,capacity.shared.endpoint(peer)],ACTIVATION)
            failed=False
            try:
                while not process.owner.exited():
                    require(time.monotonic()<min(deadline,client.deadline),'periodic-original-invocation-timeout')
                    process.drain();node.drain();peer.poll(.005)
                row=finish_call(client,process);write_json(output/'result.json',row);record['newGuestInvocations']=1
            except BaseException:
                failed=True
                retain_partial(client,process,peer,ACTIVATION,'periodic-only-diagnostic',None,None,None,False);raise
            finally:
                try:process.close()
                except BaseException:
                    try:write_json(output/'process-cleanup-refusal.json',{'qualification':False,'processCleanupConfirmed':False})
                    except BaseException:pass
                    if not failed:raise
            response=row['response']
            require(row['exitCode']==4 and row['processReaped'] is True and response['outcomeKnown'] is True
                and response['requestDispatched'] is True and response['error']['code']=='guest-trap'
                and response['data']['terminalState']=='guest_trap' and response['data']['resolvedRevision']==revision,
                'periodic-original-failure-must-remain-failure')
            used=response['data']['consumption'];require(capacity.shared.natural(used['outboundRequests'])==0
                and 0<capacity.shared.natural(used['cpuFuel'])<=1000000000
                and 0<capacity.shared.natural(used['peakMemoryBytes'])<=134217728,'periodic-original-execution-ceilings')
            record['diagnostic']=decode(capacity.shared.natural(used['logBytes']))
            record['result']=file_identity(output/'result.json');record['physical']=sample(client,probe,'after-periodic-diagnostic',1)
            record['providerUsage']=capacity.shared.usage(client,target)
            require(all(capacity.shared.natural(record['providerUsage']['counters'][key])==0 for key in ACTIVE_COUNTERS),
                'periodic-all-eighteen-active-counters-zero')
            delete_all(client,[target['name']]);stop(client,node);shutdown=stopped_record(node)
            require(shutdown['reaped'] is True and shutdown['record']['clean'] is True,'periodic-clean-reaped-node')
            record['shutdown']=shutdown;record['peer']=peer.close();validate_peer(record['peer'])
            require(record['peer']['startedRequests']==record['peer']['openConnections']==record['peer']['committedMutations']==0,
                'periodic-no-http-contact')
        require(original==capacity.shared.identities(artifact) and products=={
            name:file_identity(path,512*1024**2) for name,path in native.items()},'periodic-final-products-unchanged')
        record['status']='diagnostic-complete';write_json(output/'diagnostic.json',record);return record
    except BaseException:
        record.update(status='failed',stage=stage);write_json(output/'FAILED.json',record);raise
