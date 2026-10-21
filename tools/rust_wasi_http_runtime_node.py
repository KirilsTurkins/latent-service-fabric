"""Signed ordinary Rust clients on one cell with independent tenant installations."""
from __future__ import annotations

import copy
import base64
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import go_standard_http_node as shared
from tools import dotnet_resource_timer_observer as timer_observer
from tools.go_node_stop_timer_observer import ENVIRONMENT as TIMER_ENVIRONMENT, PREFIX as TIMER_PREFIX, MAXIMUM_STDERR
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_resource_tenants import client_for_foreign, credential_denial
from tools.resource_tenant_node import FOREIGN_TOKEN, SUBJECTS, TENANTS, require_denied_before_guest
from tools.rust_capsule_node import (RecordingClient, delete_all, deploy, finish_call,
    sample, selected_revision, start_call)
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json
from tools.rust_wasi_http_runtime_fixture import SERVICE
from tools.rust_wasi_http_profile import ACTIVATION, CLOCK, HTTP
from tools.standard_http.observations import delta, require_zero_contact, validate as validate_peer
from tools.standard_http.peer import Peer
from tools.standard_http.protocol import Request
from tools.standard_http.vectors import BY_ID, DOMAIN, PARTIAL, json_bytes, response as peer_response
from tools.static_api.node import policy

RUNTIME_LIMITS={'tasks':8,'executors':2,'queuedWork':8,'waits':16,'timers':8,'results':8,'nativeOwners':8}
PHYSICAL=('execution-cell-leases','guest-invocations','guest-stores','guest-host-states','guest-component-instances')
HTTP_OPS=['open','write','finish','read','chunk-bytes','trailers','abort-upload','abort-body']
DOMAIN_TEXT='200:domain:7:caf\u00e9:first|\u03bb:'
MATERIALS=('tools/rust_wasi_http_runtime_node.py','tools/rust_wasi_http_runtime_fixture.py',
    'tools/go_standard_http_node.py','tools/standard_http/peer.py','tools/standard_http/protocol.py',
    'tools/standard_http/vectors.py','tools/standard_http/observations.py',
    'tools/rust_capsule_node.py','tools/qualify_resource_tenants.py','tools/resource_tenant_node.py',
    'tools/dotnet_resource_timer_observer.py','tools/go_node_stop_timer_observer.py',
    'tools/phase2_operator_process.py','tools/phase2_operator_scenario.py',
    'tools/phase3_resource_os.py','tools/phase3_resource_profile.py','tools/static_api/node.py')


def cases():
    # name, ordinary operation, shared peer path, exact result, accepted calls,
    # peer vector, controller action. No case guesses success from elapsed time.
    return (
        ('json','json','/conformance/json',DOMAIN_TEXT,1,'domain-json',''),
        ('post','post','/conformance/echo','200:echo:POST:AAECAw==',1,'method-bytes',''),
        ('http404','status','/conformance/status/404','404:domain-error',1,'http-404',''),
        ('http500','status','/conformance/status/500','500:domain-error',1,'http-500',''),
        ('reserved-auth','reserved-auth','/conformance/json','error:reserved-header',0,None,''),
        ('reserved-cookie','reserved-cookie','/conformance/json','error:reserved-header',0,None,''),
        ('foreign-target','json','foreign','error:request-denied',0,None,''),
        ('redirect-stopped','redirect','/conformance/redirect','302:redirect-stopped',1,'redirect',''),
        ('redirect-denied-stopped','redirect','/conformance/redirect-denied','302:redirect-stopped',1,'redirect-denied',''),
        ('malformed-json','malformed-json','/conformance/body/malformed-json','error:json-decode',1,'malformed-json',''),
        ('truncated','bytes','/conformance/body/truncated','error:body-or-protocol',1,'truncated-body',''),
        ('malformed-framing','bytes','/conformance/body/malformed','error:malformed-framing',1,'malformed-framing',''),
        ('oversized','bytes','/conformance/body/oversized','error:response-size',1,'oversized-body',''),
        ('partial-complete','bytes','/conformance/body/partial',f'200:bytes:{len(PARTIAL)}',1,'partial-body','release'),
        ('early-drop','early-drop','/conformance/body/partial','200:partial:4',1,'partial-body',''),
        ('root-drop','root-drop','/conformance/body/partial','root-dropped-body',1,'partial-body',''),
        ('root-trap','trap-open','/conformance/body/partial',None,1,'partial-body','trap'),
        ('fresh-after-trap','json','/conformance/json',DOMAIN_TEXT,1,'domain-json',''),
        ('pending-cancel','bytes','/conformance/hold/headers',None,1,'pending-headers','cancel'),
        ('pending-deadline','bytes','/conformance/hold/headers',None,1,'pending-headers','deadline'),
        ('uncertain-post','uncertain-post','/conformance/mutation/close','error:uncertain-post',1,'commit-close',''),
        ('timeout-option-unsupported','timeout-option','/conformance/json','error:timeout-option',0,None,''),
        ('repeat','repeat','/conformance/json','repeat:'+DOMAIN_TEXT,2,'domain-json',''),
        ('authorized-secondary','bytes','secondary',f'200:bytes:{len(json_bytes({"redirected":True}))}',1,'redirect-target',''),
        # Eight is the unchanged per-root upper bound, not an invented observed
        # count or claim that Tasks (rather than another real owner) refused.
        ('resource-capacity','capacity','/conformance/json','error:resource-capacity',8,'domain-json','capacity'),
    )


def configuration(directory, releases, peers, credentials, *, http_present=True):
    require(set(peers)==set(credentials)==set(TENANTS),'rust-http-two-owned-installations')
    peer=peers['examples']
    startup={'destinations':peer.provider_destinations(),
        'origins':{role:peer.origin(role) for role in ('primary','secondary')}}
    path=shared.configuration(directory,releases,startup,credentials['examples'])
    value=read_json(path);providers=value['providers']
    require(value['workers']=={'runtime':1,'control':1} and len(value['cells'])==1
        and value['cells'][0]['capacity']==1 and value['cells'][0]['queueCapacity']==2
        and providers['activationRuntime']['limits']==RUNTIME_LIMITS,
        'rust-http-original-cell-and-runtime-ceilings')
    value.setdefault('engine',{})['activationStackAccounting']='activation-owned-v1'
    # The original finite configuration carries Go's additional scalar providers.
    # This selected Rust graph requires ONLY monotonic+activation+typed HTTP.
    for name in ('clockWall','random'):del providers[name]
    providers['bindings']=[row for row in providers['bindings'] if row['contract'] in {HTTP,CLOCK,ACTIVATION}]
    names={HTTP:'http-standard',CLOCK:'clockMonotonic',ACTIVATION:'activation'}
    for row in providers['bindings']:
        row['consumerService']=SERVICE
        row['providerBinding']=names[row['contract']]+'-examples-installed'
    second=copy.deepcopy(providers['httpStreaming'])
    second['identity']={'id':'http-foreign','tenant':'foreign','service':'http-foreign','epoch':1}
    second['configuration']['destinations']=peers['foreign'].provider_destinations()
    second['credentialDirectory']=str(credentials['foreign'].parent)
    second['credentials'][0]['file']=credentials['foreign'].name
    providers['additionalHttpStreaming']=[second]
    providers['scalarAliases']=[]
    for name in ('clockMonotonic','activationRuntime'):
        identity=providers[name]['identity']
        providers['scalarAliases'].append({'source':identity['id'],'identity':{
            **identity,'id':identity['id']+'-foreign','tenant':'foreign','service':identity['service']+'-foreign'}})
        source,=[row for row in providers['bindings'] if row['contract']==(CLOCK if name=='clockMonotonic' else ACTIVATION)]
        providers['bindings'].append({**source,'name':source['name']+'-foreign','tenant':'foreign',
            'providerService':identity['service']+'-foreign',
            'providerBinding':names[source['contract']]+'-foreign-installed'})
    source,=[row for row in providers['bindings'] if row['contract']==HTTP]
    providers['bindings'].append({**source,'name':'http-foreign','tenant':'foreign','providerService':'http-foreign',
        'providerBinding':'http-standard-foreign-installed'})
    value['credentials'].append({'token':FOREIGN_TOKEN,'subject':SUBJECTS['foreign'],'tenant':'foreign','role':'operator'})
    require(len(providers['bindings'])==6 and len(providers['scalarAliases'])==2,'rust-http-bounded-installed-descriptors')
    if not http_present:
        del providers['httpStreaming'];del providers['additionalHttpStreaming']
        providers['bindings']=[row for row in providers['bindings'] if row['contract']!=HTTP]
    path.write_bytes((json.dumps(value,indent=2)+'\n').encode())
    return path


def grant(client,node,publication,tenant,peer):
    require(tenant in TENANTS,'rust-http-grant-tenant')
    result=[]
    for original,capability,operations,profile,kind in (
        ('clockMonotonic',CLOCK,['now-nanos'],'activation-monotonic-v1','clock'),
        ('activation',ACTIVATION,list(shared.OPS),'activation-owned-v1','clock'),
        ('http-standard',HTTP,HTTP_OPS,'bounded-streaming-http-identity-v1','http')):
        identity=original if tenant=='examples' else ('http-foreign' if capability==HTTP else original+'-foreign')
        descriptor,=[row for row in node.startup_record['providers'] if row['id']==identity]
        require(descriptor['tenant']==tenant and descriptor['capability']==capability
            and descriptor['profile']==profile and descriptor['configurationEpoch']=='1',
            'rust-http-exact-installed-profile')
        name=original+'-'+tenant
        policy(client,'provider-binding',name+'-installed',{'formatVersion':1,'tenant':tenant,
            'capability':capability,'providerProfile':profile,'configurationDigest':descriptor['configurationDigest'],
            'configurationEpoch':1,'restriction':{'operations':[] if kind=='http' else operations}})
        origins=[(peer.origin('primary'),[],['/conformance/'])] if kind=='http' else [(None,None,None)]
        if kind=='http':origins.append((peer.origin('secondary'),['/conformance/redirect-target'],[]))
        rules=[]
        for index,(origin,paths,prefixes) in enumerate(origins):
            resource={'kind':kind} if kind!='http' else {'kind':'http','origins':[origin],
                'methods':['GET','POST'],'paths':paths,'pathPrefixes':prefixes}
            ceiling=({'operations':4096,'inputBytes':0,'outputBytes':32768,'wallTimeMillis':5000}
                if kind!='http' else {'operations':64,'inputBytes':65536,'outputBytes':262144,'wallTimeMillis':5000})
            rules.append({'id':'ordinary-'+str(index),'effect':'allow',
                'principals':[{'kind':'administrator','subject':SUBJECTS[tenant]}],
                'services':[SERVICE],'publications':[publication],'capability':capability,
                'operations':operations,'resources':resource,'ceiling':ceiling})
        policy(client,'policy',name+'-allow',{'formatVersion':1,'tenant':tenant,'rules':rules})
        result.append({'capability':capability,'policy':name+'-allow'})
    return result


def unsigned(value):
    require(type(value) is int and value>=0 or type(value) is str and value.isascii()
        and value.isdecimal() and len(value)<=20,'rust-http-exact-unsigned-counter')
    result=int(value)
    require(0<=result<=2**64-1,'rust-http-original-u64-counter-range')
    return result


def usage(client,target):
    value=client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']
    observed=value['nodeUsage']
    require(type(observed) is dict and observed['scope']=='node'
        and type(observed['unavailable']) is list and observed['unavailable']==[]
        and type(observed['counters']) is dict
        and all(key in observed['counters'] and unsigned(observed['counters'][key])>=0
            for key in ACTIVE_COUNTERS),'rust-http-required-provider-counters')
    return value


def retire(client,probe,target,output,name,*,population=2):
    physical=sample(client,probe,'after-'+name,population)
    counts=usage(client,target)
    require(all(unsigned(counts['nodeUsage']['counters'][key])==0 for key in ACTIVE_COUNTERS),
        'rust-http-original-all-provider-owners-idle')
    record={'physical':physical,'providerUsage':counts}
    write_json(output/('retirement-'+name+'.json'),record)
    return record


def positive_pending(client,probe,target):
    physical=sample(client,probe,'pending-rust-http',2,active=True)
    topology=physical['inventory']['topology']
    rows={row['name']:row for row in topology['entries']}
    require(topology['available'] is True and topology['complete'] is True and len(rows)==len(topology['entries'])
        and all(name in rows and unsigned(rows[name]['activeCount'])==1 for name in PHYSICAL),
        'rust-http-five-real-physical-owners')
    counts=usage(client,target)
    tenant=counts['tenantUsage']
    require(type(tenant) is dict and tenant['scope']=='tenant'
        and type(tenant['unavailable']) is list and tenant['unavailable']==[]
        and type(tenant['counters']) is dict
        and all(key in tenant['counters'] and unsigned(tenant['counters'][key])>=1
            for key in ('calls','sessions')),
        'rust-http-current-tenant-provider-call-and-session')
    require(all(unsigned(counts['nodeUsage']['counters'][name])>=1
        for name in ('broker_calls','pool_active_connections','pool_running_requests')),
        'rust-http-real-accepted-provider-work')
    return {'physical':physical,'providerUsage':counts,'proof':'real-peer-gate-plus-five-physical-and-provider-owners'}


def library_error(payload,client_name,expected):
    """Preserve public library diagnostics; never manufacture an underlying enum."""
    require(type(payload) is str and payload.startswith('library-error:') and len(payload.encode())<=8192,
        'rust-http-required-real-bounded-library-error')
    value=json.loads(payload.removeprefix('library-error:'))
    require(type(value) is dict and set(value)=={'phase','display','debug','displayBytes','debugBytes','truncated','public'}
        and value['phase'] in {'send','body','json'} and value['truncated'] is False,
        'rust-http-complete-real-library-error-shape')
    for name,bound in (('display',2048),('debug',4096)):
        require(type(value[name]) is str and 0<len(value[name].encode())<=bound
            and type(value[name+'Bytes']) is int and value[name+'Bytes']==len(value[name].encode()),
            'rust-http-no-truncated-or-invented-library-error-detail')
    public=value['public']
    require(type(public) is dict,'rust-http-public-library-error-kind')
    if client_name=='waki':
        require(set(public)=={'typedWasiErrorCode','serdeJsonError'}
            and type(public['serdeJsonError']) is bool
            and (public['typedWasiErrorCode'] is None or type(public['typedWasiErrorCode']) is str),
            'rust-http-real-waki-downcast-proof')
        code=public['typedWasiErrorCode']
    else:
        flags={'isBuilder','isRequest','isBody','isDecode','isTimeout','isStatus','serdeJsonError'}
        require(client_name=='golem' and set(public)==flags|{'sourceDisplay'}
            and all(type(public[k]) is bool for k in flags)
            and (public['sourceDisplay'] is None or type(public['sourceDisplay']) is str
                and len(public['sourceDisplay'].encode())<=4096),'rust-http-real-golem-public-kind-and-source')
        # Upstream converts the WASI enum into io::Error: retain its real public
        # source Display; do not describe it as a surviving typed WASI variant.
        code=public['sourceDisplay']
    phase=value['phase'];exact=False
    if expected=='error:timeout-option':
        require(phase=='send' and not public['serdeJsonError'] and (
            client_name=='waki' and code is None and value['display']==value['debug']=='failed to set connect_timeout'
            or client_name=='golem' and public['isRequest'] and not public['isTimeout']
                and code=='set_first_byte_timeout'),'rust-http-exact-unsupported-option-setter-not-other-error')
        exact=True
    elif expected=='error:request-denied':
        require(phase=='send' and not public['serdeJsonError'] and code=='ErrorCode::HttpRequestDenied',
            'rust-http-real-request-denied-not-unavailable')
        exact=True
    elif expected=='error:reserved-header':
        require(phase=='send' and not public['serdeJsonError']
            and (value['display']==value['debug']=='HeaderError::Forbidden' and code is None
                if client_name=='waki' else code=='HeaderError::Forbidden'),
            'rust-http-real-forbidden-header-not-transport-or-permission')
        exact=True
    elif expected=='error:json-decode':
        require(phase=='json' and public['serdeJsonError'] is True
            and (code is None if client_name=='waki' else public['isDecode'] is True and public['isRequest'] is False),
            'rust-http-real-serde-json-error-not-failed-transport')
        exact=True
    elif expected=='error:resource-capacity':
        require(phase=='send' and not public['serdeJsonError']
            and code=='ErrorCode::InternalError(Some("latent-runtime-resource-exhausted"))',
            'rust-http-real-original-runtime-resource-capacity-not-permission-or-unsupported')
        exact=True
    elif expected=='error:malformed-framing':
        require(phase=='send' and not public['serdeJsonError']
            and code=='ErrorCode::InternalError(Some("latent-http-connection-failed"))',
            'rust-http-exact-ambiguous-framing-send-error')
        exact=True
    else:
        require(expected in {'error:body-or-protocol','error:response-size','error:uncertain-post'}
            and not public['serdeJsonError'],'rust-http-closed-library-error-oracle')
        selected=({'ErrorCode::HttpProtocolError','ErrorCode::HttpResponseIncomplete'} if expected=='error:body-or-protocol'
            else {'ErrorCode::InternalError(Some("latent-http-response-too-large"))'} if expected=='error:response-size'
            else {'ErrorCode::InternalError(Some("latent-http-uncertain"))','ErrorCode::HttpResponseIncomplete'})
        exact=phase=='send' and code in selected
        if client_name=='golem' and phase=='body' and public['isBody'] is True:
            # Unlike Waki's opaque resource-handle Debug, Golem Body::buffer
            # invokes error.to_debug_string() and preserves that public source.
            # These exact strings are emitted by the selected backend's real
            # HttpError resource; no category is inferred from a handle number.
            body_codes=({'latent-http-unexpected-eof','latent-http-invalid-request','latent-http-uncertain'}
                if expected=='error:body-or-protocol' else {'latent-http-response-too-large'}
                if expected=='error:response-size' else {'latent-http-uncertain','latent-http-unexpected-eof'})
            exact=code in body_codes
        # A library may erase a response-stream error to the public resource
        # handle. Its body-phase LastOperationFailed is observable, but the
        # underlying native HttpError is explicitly NOT proved by that handle.
        opaque=phase=='body' and 'LastOperationFailed' in value['debug'] and (
            client_name=='waki' and value['debug'].startswith('input_stream read failed: '))
        require(exact or opaque,'rust-http-specific-protocol-or-real-opaque-stream-error-required')
    return {'publicError':value,'exactUnderlyingCategoryProven':exact,
        'upstreamWasiErrorTypePreserved':client_name=='waki' and code is not None,
        'nativeErrorInferredFromResourceHandle':False}


def outcome(row,spec,client_name,revision,budget):
    _name,_mode,_path,expected,outbound,_vector,action=spec
    if expected=='error:malformed-framing':
        require(tuple(spec)==('malformed-framing','bytes','/conformance/body/malformed',
            'error:malformed-framing',1,'malformed-framing',''),
            'rust-http-ambiguous-framing-oracle-only-for-its-exact-vector')
    response=row['response'];data=response['data']
    require(type(row['exitCode']) is int and row['processReaped'] is True and response['outcomeKnown'] is True
        and response['requestDispatched'] is True and data.get('resolvedRevision')==revision,
        'rust-http-known-current-revision-and-reaped-call')
    consumption=data['consumption'];capacity=None
    if action=='capacity' and client_name=='golem':
        require(tuple(spec)==('resource-capacity','capacity','/conformance/json',
            'error:resource-capacity',8,'domain-json','capacity'),
            'rust-http-golem-pressure-only-its-exact-original-case')
        require(row['exitCode']==4 and row['decoded'] is None
            and response['category']=='platform-failure' and data.get('terminalState')=='guest_trap'
            and response.get('error',{}).get('code')=='guest-trap'
            and response['error'].get('details')==[
                {'fields':{'code':'guest-trap'},'kind':'activation.guest-trap'},
                {'fields':{'kind':'unreachable-code'},'kind':'activation.guest-trap-kind'}],
            'rust-http-golem-held-pressure-exact-unreachable-trap')
        capacity={'observedOutboundRequests':8,'heldResponseCountProved':False,'publicTerminal':'guest-trap',
            'trapKind':'unreachable-code','timerTrapSiteProved':False,
            'catchableLibraryErrorObserved':False,'limitingOwnerKindProven':False,
            'taskExhaustionClaimed':False,'originalEnvelopeChanged':False}
    elif action=='capacity':
        decoded=row['decoded'];prefix='fresh:'+client_name+':capacity:'
        require(row['exitCode']==0 and type(decoded) is list and len(decoded)==1
            and type(decoded[0]) is dict and set(decoded[0])=={'ok'} and type(decoded[0]['ok']) is str
            and decoded[0]['ok'].startswith(prefix),'rust-http-real-held-response-capacity-result')
        accepted,separator,error=decoded[0]['ok'].removeprefix(prefix).partition(':')
        require(separator and accepted in {str(i) for i in range(1,9)},'rust-http-original-held-response-count-bound')
        outbound=int(accepted)
        capacity={'observedAcceptedResponses':outbound,'publicError':library_error(error,client_name,expected),
            'limitingOwnerKindProven':False,'taskExhaustionClaimed':False,'originalEnvelopeChanged':False}
    require(type(consumption['outboundRequests']) is int and consumption['outboundRequests']==outbound
        and unsigned(consumption['effectCount'])==0 and 0<unsigned(consumption['cpuFuel'])<=budget['cpuFuel']
        and 0<unsigned(consumption['peakMemoryBytes'])<=budget['memoryBytes'],'rust-http-original-budget-and-effects')
    if action in {'trap','cancel','deadline'}:
        code={'trap':'guest-trap','cancel':'cancelled','deadline':'deadline-exceeded'}[action]
        require(row['exitCode']==4 and row['decoded'] is None and response['category']=='platform-failure'
            and response['error']['code']==code and data['terminalState']==code.replace('-','_'),
            'rust-http-exact-root-terminal-kind')
    else:
        if capacity is not None:return capacity
        require(row['exitCode']==0 and type(row['decoded']) is list and len(row['decoded'])==1
            and type(row['decoded'][0]) is dict and set(row['decoded'][0])=={'ok'}
            and type(row['decoded'][0]['ok']) is str,'rust-http-real-ordinary-result-type')
        result=row['decoded'][0]['ok'];prefix='fresh:'+client_name+':'
        require(result.startswith(prefix),'rust-http-fresh-ordinary-client-result')
        if expected.startswith('error:'):
            return library_error(result.removeprefix(prefix),client_name,expected)
        require(result==prefix+expected,'rust-http-exact-ordinary-library-result')


def golem_timer_pending(stderr,mode):
    require(mode in {'pending','drain'} and type(stderr) is bytes and len(stderr)<=MAXIMUM_STDERR,
        'rust-http-original-native-timer-reader-input')
    require(timer_observer.LIMITS=={k:RUNTIME_LIMITS[k] for k in ('tasks','waits','timers')},
        'rust-http-original-native-timer-bounds-equal-rust-profile')
    partial=False
    if stderr and not stderr.endswith(b'\n'):
        tail=stderr.rsplit(b'\n',1)[-1]
        if tail.startswith(TIMER_PREFIX) or TIMER_PREFIX.startswith(tail):
            require(len(tail)<=128,'rust-http-original-native-timer-partial-bound')
            stderr=stderr[:-len(tail)];partial=True
    observed=timer_observer.observe(stderr)
    require(observed['status'] in {'not-observed','observed'} and not observed['overflow']
        and observed['invalidMarkerCount']==0,'rust-http-invalid-original-native-timer-record')
    rows=observed['records']
    require([r['sequence'] for r in rows]==list(range(1,len(rows)+1)),
        'rust-http-complete-original-native-timer-sequence')
    selected=[r for r in rows if r['mode']==mode]
    require(not any(r['event']=='root-close' for r in selected),'rust-http-native-timer-root-already-closed')
    pending=[r for r in selected if r['event']=='wait-pending'
        and 1<=r['tasks']<=RUNTIME_LIMITS['tasks'] and 1<=r['waits']<=RUNTIME_LIMITS['waits']
        and 1<=r['timers']<=RUNTIME_LIMITS['timers']]
    if partial or not pending:return None
    return {'originalReader':'tools/dotnet_resource_timer_observer.py',
        'nativeHookChanged':False,'otherLanguageExecutionClaimed':False,'nativeRecords':observed,
        'waitPending':pending[-1],'proof':'actual original wait_for Poll::Pending with task/wait/timer charged'}


def golem_terminal_timer(stderr,mode,positive,action=''):
    require(type(stderr) is bytes and len(stderr)<=MAXIMUM_STDERR and mode in {'pending','drain'}
        and action in {'','release','trap','cancel','deadline'},'rust-http-bounded-terminal-timer-input')
    observed=timer_observer.observe(stderr)
    require(observed['status']=='observed' and not observed['overflow']
        and observed['invalidMarkerCount']==0,'rust-http-valid-original-terminal-timer-records')
    rows=observed['records']
    sequences=[int(line.split(b'|')[3]) for line in stderr.splitlines() if line.startswith(TIMER_PREFIX)]
    require(type(positive) is dict and type(positive.get('waitPending')) is dict
        and set(positive['waitPending'])=={'mode','event','sequence','tasks','waits','timers'}
        and all(type(positive['waitPending'][key]) is int for key in ('sequence','tasks','waits','timers')),
        'rust-http-typed-original-positive-pending-record')
    require(sequences==list(range(1,len(rows)+1)) and positive['waitPending'] in rows
        and positive['waitPending']['mode']==mode and positive['waitPending']['event']=='wait-pending'
        and all(1<=positive['waitPending'][key]<=RUNTIME_LIMITS[key] for key in ('tasks','waits','timers')),
        'rust-http-current-positive-pending-and-ordered-terminal-records')
    closes=[row for row in rows if row['mode']==mode and row['event']=='root-close']
    require(len(closes)<=1 and all(row['sequence']>positive['waitPending']['sequence'] for row in closes),
        'rust-http-no-stale-or-duplicate-guest-close')
    forced=action in {'cancel','deadline'}
    require(not forced or {'cancel':'pending','deadline':'drain'}[action]==mode,
        'rust-http-exact-forced-terminal-observer-mode')
    # RootClose is emitted only by the guest activation.close import. Forced
    # host termination can stop the app before its compiler-owned root drain;
    # it must still pass the exact public terminal and full retirement gates.
    require(forced or bool(closes),'rust-http-original-native-root-close-after-real-pending')
    return {'nativeRecords':observed,'guestCloseStatus':'observed' if closes else 'not-observed',
        'forcedHostTermination':forced,'guestCloseSynthesized':False,
        'physicalRetirementProvenByMarker':False}


def retain_terminal_timer(node,output,label):
    node.drain();stderr=bytes(node.buffers[1])
    markers=[line for line in stderr.splitlines() if line.startswith(TIMER_PREFIX)]
    write_json(output/('terminal-native-timer-'+label+'.json'),{
        'qualification':False,'scope':'actual-bounded-native-observer-before-terminal-assertion',
        'stderrBytes':len(stderr),'stderrDigest':digest(stderr),
        'markersTruncated':len(markers)>16 or any(len(line)>128 for line in markers),
        'markerLines':[base64.b64encode(line[:128]).decode('ascii') for line in markers[:16]],
        'parsed':timer_observer.observe(stderr)})
    return stderr


def retain_partial(process,node,output,label):
    """Diagnostic bytes from this owned public-fixture CLI, never an outcome.

    Process.close reaps but does not drain. Save already collected bytes after
    one bounded drain, then close the process. Do not fabricate finish_call or
    infer known dispatch/completion from a partial JSON document.
    """
    drained=False
    try:
        process.drain();drained=True
    except Exception:pass
    buffers=[bytes(raw) for raw in process.buffers]
    require(len(buffers)==2 and sum(map(len,buffers))<=32768,'rust-http-original-partial-output-bound')
    record={'schemaVersion':'latent.rust.http.partial-invocation.v1','qualification':False,
        'activation':process.authoring_activation,'normalResultCompleted':False,
        'oneBoundedDrainSucceeded':drained,'collectionEndedBeforeCleanup':True,
        'streams':{name:{'bytes':len(raw),'sha256':digest(raw),'base64':base64.b64encode(raw).decode('ascii')}
            for name,raw in zip(('stdout','stderr'),buffers)},'nativeTimerRecords':[]}
    # Keep only the exact existing static native marker family, rather than any
    # unrelated node log or error message. The marker reader itself remains the
    # qualification gate; these raw diagnostic lines supply no passing credit.
    if node is not None:
        try:node.drain()
        except Exception:pass
        records=[raw for raw in bytes(node.buffers[1]).splitlines(keepends=True) if raw.startswith(TIMER_PREFIX)]
        record['nativeTimerRecordsTruncated']=len(records)>32 or any(len(raw)>128 for raw in records)
        record['nativeTimerRecords']=[base64.b64encode(raw[:128]).decode('ascii') for raw in records[:32]]
    try:process.close()
    finally:
        record['cliProcessReapedAfterCleanup']=process.owner.finished is True
        write_json(output/('partial-invocation-'+label+'.json'),record)
    return record


def retain_after_failure(process,node,output,label):
    # Diagnostics must never replace the primary controller/library failure.
    # If collection, writing or process cleanup refuses, retain only closed
    # certainty fields where possible. A failed diagnostic earns no credit.
    try:return retain_partial(process,node,output,label)
    except BaseException:
        refused={'schemaVersion':'latent.rust.http.partial-retention-refusal.v1',
            'qualification':False,'collectionStatus':'refused','primaryFailurePreserved':True,
            'cliProcessReapedObserved':getattr(getattr(process,'owner',None),'finished',False) is True}
        try:write_json(output/('partial-retention-refused-'+label+'.json'),refused)
        except BaseException:pass
        return refused


def close_call(process,*,primary_failure):
    if not primary_failure:
        process.close()  # Successful calls still require successful cleanup.
        return
    try:process.close()
    except BaseException:pass


def malformed_framing_peer(before,after):
    """Bind the public send error to this peer's complete ambiguous CL+TE head.

    The category alone does not prove the parser's failing branch. The fixed
    source-bound vector, complete write and one current request prove the
    supplied response and exclude an invisible retry or a different vector.
    """
    change=delta(before,after)
    wire,suffix=peer_response(BY_ID['malformed-framing'],None,0)
    require(wire==b'HTTP/1.1 200 Fixture\r\nContent-Length: 1\r\n'
        b'Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n0\r\n\r\n'
        and suffix==b'','rust-http-original-ambiguous-cl-te-vector')
    require(after['openConnections']==0 and change['acceptedConnections']==change['startedRequests']
        ==change['completedResponseWrites']==1 and len(change['requests'])==1
        and change['rejectedRequests']==change['committedMutations']==change['connectionBoundRejections']==0,
        'rust-http-ambiguous-framing-one-complete-contact-no-retry')
    row,=change['requests']
    require(row['request']==before['acceptedConnections']+1 and row.get('vector')=='malformed-framing'
        and row['method']=='GET' and row['role']=='primary' and row['state']=='closed'
        and row['closeReason']=='response-write-complete'
        and row['responseBytesWritten']==len(wire),
        'rust-http-exact-ambiguous-response-vector-and-complete-bytes')
    return {'request':row['request'],'vector':row['vector'],'responseBytesWritten':len(wire),
        'responseDigest':digest(wire),'contacts':1,'parserBranchInferred':False}


def retain_peer_observations(output,label,before,after):
    # Actual controlled-public-peer state is diagnostic evidence even when the
    # next strict outcome/contact assertion refuses. Never turn charged starts
    # into an invented remote request, response object or physical close.
    value={'qualification':False,'scope':'controlled-peer-observation-before-contact-assertion',
        'before':before,'after':after}
    write_json(output/('peer-before-contact-'+label+'.json'),value)
    return value


def programme_selection(pressure_observation_only):
    require(type(pressure_observation_only) is bool,'rust-http-exact-pressure-diagnostic-selection')
    original=tuple(enumerate(cases()))
    if pressure_observation_only:
        return original[-1:], (('foreign','golem'),)
    return original, (('examples','waki'),('foreign','golem'))


def closed_before_request(row):
    # This proves no parsed request or written response, not zero received
    # request bytes: the public peer does not expose a per-connection RX count.
    require(type(row) is dict and set(row)=={'request','role','state','responseBytesWritten',
        'receiveBufferBytes','sendBufferBytes','closeReason'}
        and type(row['request']) is int and 1<=row['request']<=32
        and row['role']=='primary' and row['state']=='closed'
        and type(row['responseBytesWritten']) is int and row['responseBytesWritten']==0
        and row['closeReason']=='remote-write-half-ended'
        and all(type(row[k]) is int and 0<row[k]<=128*1024
            for k in ('receiveBufferBytes','sendBufferBytes')),
        'rust-http-exact-closed-before-request-parsed')
    return row


def golem_pressure_peer(before,after):
    change=delta(before,after)
    require(after['openConnections']==0 and change['acceptedConnections']==8
        and change['startedRequests']==change['completedResponseWrites']==7
        and change['rejectedRequests']==change['committedMutations']==change['connectionBoundRejections']==0
        and len(change['requests'])==8,'rust-http-golem-pressure-eight-connections-seven-parsed')
    completed=change['requests'][:-1];last=closed_before_request(change['requests'][-1])
    request=Request();request.method=b'GET'
    wire,suffix=peer_response(BY_ID['domain-json'],request,0)
    require(suffix==b'' and all(row.get('vector')=='domain-json' and row.get('method')=='GET'
        and row['role']=='primary' and row['state']=='closed'
        and row.get('closeReason')=='response-write-complete' and row['responseBytesWritten']==len(wire)
        and row.get('bodyBytes')==0 and row.get('authorizationPresent') is True
        and row.get('cookiePresent') is False and row.get('proxyAuthorizationPresent') is False
        for row in completed),'rust-http-golem-pressure-exact-seven-complete-authorized-json-responses')
    return {'acceptedConnections':8,'parsedRequests':7,'completedResponseWrites':7,
        'closedBeforeRequestParsed':last,'receivedRequestBytesProved':False,
        'heldResponseCountProved':False,'timerTrapSiteProved':False}


def invoke(client,node,target,peers,tenant,client_name,alias,spec,probe,output,label):
    _name,mode,path,_expected,contacts,vector,action=spec
    require(alias in {'alpha','delta'} and client_name in {'waki','golem'},'rust-http-closed-ordinary-client-selection')
    peer=peers[tenant]
    before={name:value.observation() for name,value in peers.items()}
    role='secondary' if path=='secondary' else 'primary'
    selected_peer=peers['foreign' if tenant=='examples' else 'examples'] if path=='foreign' else peer
    origin=selected_peer.origin(role)
    selected_path='/conformance/denied-target' if path=='foreign' else '/conformance/redirect-target' if path=='secondary' else path
    endpoint=f"http://{origin['host']}:{origin['port']}"+selected_path
    chosen=copy.deepcopy(target)
    if action=='deadline':chosen['budget']['wallTimeLimitMillis']=4000
    pin=selected_revision(client,target)
    native_mode=({'cancel':'pending','deadline':'drain'}.get(action) if client_name=='golem' else None)
    activation='node-stop-'+native_mode if native_mode else label
    process=start_call(client,chosen,'greeting','greet',[alias+'|'+client_name+'|'+mode+'|'+endpoint],activation)
    pending=cancelled=None;released=False;primary_failure=False
    try:
        expires=min(client.deadline,time.monotonic()+10)
        while not process.owner.exited():
            require(time.monotonic()<expires,'rust-http-original-call-deadline')
            process.drain();node.drain()
            for value in peers.values():
                value.poll(.002)
                require(value.observation()['failure'] is None,'rust-http-shared-peer-failed')
            gates=[g for g in peer.gates() if g.request>before[tenant]['acceptedConnections']]
            require(len(gates)<=1,'rust-http-no-ambiguous-current-gate')
            timer=golem_timer_pending(bytes(node.buffers[1]),native_mode) if native_mode and pending is None else None
            if gates and pending is None and action in {'release','cancel','deadline'} and (not native_mode or timer is not None):
                gate,=gates
                require(gate.phase==('body' if action=='release' else 'headers'),'rust-http-exact-pending-phase')
                pending={'request':gate.request,'phase':gate.phase,
                    'owners':positive_pending(client,probe,target),'transitiveTimer':timer,
                    'activation':activation,'tenant':tenant,'selectedRevision':pin}
                write_json(output/('pending-'+label+'.json'),pending)
                require(not process.owner.exited(),'rust-http-root-ended-before-positive-barrier')
                if action=='release':peer.release(gate);released=True
                elif action=='cancel':
                    cancelled=client.call('activation','cancel',activation,'--reason','Owned ordinary Rust HTTP cancellation')
                    require(cancelled['outcomeKnown'] is True and cancelled['data']['activationId']==activation
                        and cancelled['data']['disposition']=='accepted','rust-http-original-root-cancel-receipt')
        row=finish_call(client,process)
    except BaseException:
        primary_failure=True
        retain_after_failure(process,node,output,label)
        raise
    finally:close_call(process,primary_failure=primary_failure)
    # Original public result is retained before any posthoc assertion/cleanup.
    write_json(output/('invocation-'+label+'.json'),row)
    require(row['activation']==activation,'rust-http-exact-owned-activation-result')
    framing=None
    if spec[3]=='error:malformed-framing':
        for _ in range(64):
            for value in peers.values():value.poll(.002)
            if all(value.observation()['openConnections']==0 for value in peers.values()):break
        snapshots={name:value.observation() for name,value in peers.items()}
        # Retain controlled public peer data before the outcome can refuse;
        # no credential bytes or successful guest outcome are manufactured.
        write_json(output/('peer-before-outcome-'+label+'.json'),{
            'qualification':False,'scope':'controlled-peer-observation-before-outcome',
            'before':before,'after':snapshots})
        framing=malformed_framing_peer(before[tenant],snapshots[tenant])
    diagnostic=outcome(row,spec,client_name,pin,chosen['budget'])
    if action=='capacity':
        contacts=diagnostic['observedOutboundRequests' if client_name=='golem' else 'observedAcceptedResponses']
    require(action not in {'release','cancel','deadline'} or pending is not None,'rust-http-missing-real-pending-witness')
    require(action!='release' or released,'rust-http-real-body-release-not-observed')
    require(action!='cancel' or cancelled is not None,'rust-http-cancel-receipt-required')
    terminal_timer=None
    if native_mode:
        stderr=retain_terminal_timer(node,output,label)
        terminal_timer=golem_terminal_timer(stderr,native_mode,pending['transitiveTimer'],action)
    for _ in range(64):
        for value in peers.values():value.poll(.002)
        if all(value.observation()['openConnections']==0 for value in peers.values()):break
    observations={name:value.observation() for name,value in peers.items()}
    if action=='capacity':retain_peer_observations(output,label,before,observations)
    pressure_peer=(golem_pressure_peer(before[tenant],observations[tenant])
        if action=='capacity' and client_name=='golem' else None)
    parsed_contacts=pressure_peer['parsedRequests'] if pressure_peer else contacts
    for name,value in observations.items():
        change=delta(before[name],value)
        new=value['requests'][before[name]['acceptedConnections']:]
        require(value['openConnections']==0 and change['startedRequests']==(parsed_contacts if name==tenant else 0)
            and change['acceptedConnections']==(contacts if name==tenant else 0),'rust-http-exact-contact-and-physical-peer-close')
        if name!=tenant or contacts==0:require_zero_contact(before[name],value)
        if pressure_peer and name==tenant:new=new[:-1]
        expected_vectors=[vector]*parsed_contacts if name==tenant else []
        require([r.get('vector') for r in new]==expected_vectors
            and all(r['role']==role and r['state']=='closed'
                and r['authorizationPresent'] is (role=='primary')
                and r['cookiePresent'] is False and r['proxyAuthorizationPresent'] is False for r in new),
            'rust-http-exact-library-contacts-and-credential-isolation')
        if vector=='commit-close' and name==tenant:
            require(len(new)==1 and new[0]['mutationCommitted'] is True and new[0]['method']=='POST'
                and new[0]['bodyBytes']==4 and new[0]['responseBytesWritten']==0,
                'rust-http-single-uncertain-post-no-replay')
    retired=retire(client,probe,target,output,label)
    return {'case':label,'tenant':tenant,'client':client_name,'outsideCrate':alias,'specification':list(spec),
        'invocation':row,'libraryError':diagnostic,'pending':pending,'cancel':cancelled,'selectedRevision':pin,'budget':chosen['budget'],
        'terminalNativeTimer':terminal_timer,'actualActivation':activation,'observedContacts':contacts,
        'malformedFramingPeer':framing,'parsedPeerRequests':parsed_contacts,'pressurePeer':pressure_peer,
        'retirement':retired,'peerBefore':before,'peerAfter':observations}


def checked_signing(artifact,signed,original):
    release_set=read_json(signed/'release-set.json')
    require(release_set.get('schemaVersion')=='latent.capsule.demo.v1'
        and release_set.get('tenant') is None and release_set.get('tenants')==list(TENANTS)
        and release_set.get('packagingOnly') is True and release_set.get('componentCompilationPerformed') is False
        and release_set.get('trust')=='isolated-neutral-resource-two-tenant-test-only'
        and release_set.get('inheritedCompilerObservationAsset')=='resource-original-build-observation.json'
        and release_set.get('expiresAtUnixSeconds',0)>time.time()+180
        and type(release_set.get('releases')) is list and len(release_set['releases'])==1,
        'rust-http-explicit-two-tenant-normal-signing')
    release,=release_set['releases'];source=signed/SERVICE
    capsule=read_json(artifact/'capsule.json')
    require(capsule['metadata']=={'name':'examples/'+SERVICE,'tenant':'examples'}
        and capsule['exports']==['examples:greeting/api@1.0.0']
        and release['name']==release['service']==SERVICE and release['world']==capsule['component']['world']
        and release['componentDigest']==capsule['component']['digest']==original['component.wasm']['sha256'],
        'rust-http-same-original-public-world-and-component')
    previous=read_json(artifact/'build-observation.json');observed=read_json(source/'build-observation.json')
    require(observed['source']==previous['source'] and observed['parameters']==previous['parameters']
        and observed['componentDigest']==previous['componentDigest']==release['componentDigest']
        and observed['componentSize']==previous['componentSize']==original['component.wasm']['bytes']
        and observed['buildType']==previous['buildType']
        and observed['hermetic'] is False and observed['reproducibility']=='not-checked',
        'rust-http-packaging-is-not-another-compiler-observation')
    rows={r['name']:r for r in observed['materials']}
    require(len(rows)==len(observed['materials']) and all(rows.get(r['name'])==r
        for r in previous['materials'] if r['name']!='package-inputs')
        and rows.get('resource-original-build-observation')=={
            'name':'resource-original-build-observation','digest':original['build-observation.json']['sha256'],
            'size':original['build-observation.json']['bytes']}
        and {'resource-neutral-package-source','resource-neutral-derivation'}<=rows.keys(),
        'rust-http-all-original-materials-and-mandatory-packaging-derivation')
    require(file_identity(source/'build-observation.json')['sha256']==release['observationDigest'],
        'rust-http-signed-packaging-observation-identity')
    return {'release':release,'observation':file_identity(source/'build-observation.json'),
        'originalObservation':original['build-observation.json'],'componentCompilationPerformed':False}


def deployment(source,tenant):
    require(tenant in TENANTS and 'tenant' not in source['metadata']
        and source['spec']['service']==SERVICE and source['spec']['grants']==[],
        'rust-http-original-neutral-deployment')
    value=copy.deepcopy(source);value['metadata'].update(tenant=tenant,name='rust-http-'+tenant)
    return value


def check_peer_final(value,expected,*,closed_before_parse=()):
    validate_peer(value)
    require(type(closed_before_parse) in (tuple,list) and len(closed_before_parse)<=1,
        'rust-http-one-explicit-pressure-unparsed-connection')
    excluded={closed_before_request(row)['request']:row for row in closed_before_parse}
    require(len(excluded)==len(closed_before_parse)
        and all(key<=len(value['requests']) and value['requests'][key-1]==row for key,row in excluded.items()),
        'rust-http-final-same-authenticated-unparsed-connection')
    parsed=[row for row in value['requests'] if row['request'] not in excluded]
    require(value['state']=='stopped' and value['listeningOrigins']==value['openConnections']==0
        and value['acceptedConnections']==len(expected)+len(excluded) and value['startedRequests']==len(expected)
        and value['rejectedRequests']==value['connectionBoundRejections']==0
        and [row.get('vector') for row in parsed]==expected
        and all(row['state']=='closed' and row.get('cookiePresent') is False
            and row.get('proxyAuthorizationPresent') is False
            and row.get('authorizationPresent') is (row['role']=='primary') for row in parsed),
        'rust-http-final-exact-peer-contact-and-owner-ledger')
    require(value['committedMutations']==expected.count('commit-close'),
        'rust-http-uncertain-mutation-never-replayed')
    for row in parsed:
        if row['vector']=='commit-close':
            require(row['mutationCommitted'] is True and row['bodyBytes']==4
                and row['responseBytesWritten']==0 and row['closeReason']=='response-withheld-after-commit',
                'rust-http-final-single-uncertain-mutation')
    result={'contacts':len(expected)+len(excluded),'mutations':value['committedMutations'],
        'completedWrites':value['completedResponseWrites'],'allClosed':True,'vectors':list(expected)}
    if excluded:result.update(parsedRequests=len(expected),closedBeforeRequestParsed=list(excluded))
    return result


def provider_absence(signed,native,output,deadline):
    output=fresh(output);record={'status':'incomplete','httpProviderInstalled':False,'invocations':[]}
    try:
        with tempfile.TemporaryDirectory(prefix='lsf-rust-http-absent-') as temporary, \
            owned_cancellation() as cancellation,ExitStack() as cleanup:
            work=Path(temporary)
            for name in ('node','client','peer'):(work/name).mkdir(mode=0o700)
            peers={};credentials={}
            for tenant in TENANTS:
                directory=work/'peer'/tenant;directory.mkdir(mode=0o700)
                secret=('Bearer '+secrets.token_hex(32)).encode()
                path=directory/'authorization';path.write_bytes(secret);path.chmod(0o600)
                credentials[tenant]=path;peers[tenant]=Peer(secret,maximum_seconds=60)
                cleanup.callback(peers[tenant].close)
            client=RecordingClient(native['latent'],work/'client',cancellation,min(deadline,time.monotonic()+60),
                evidence=output/'controls')
            config=configuration(work/'node',signed,peers,credentials,http_present=False)
            node=connect(client,native['latentd'],work/'node',config,'examples',1);cleanup.callback(node.close)
            require(all(row['capability']!=HTTP for row in node.startup_record['providers']),
                'rust-http-actually-absent-provider')
            record['startup']=node.startup_record;probe=Probe(node,file_identity(native['latentd']))
            source=signed/SERVICE
            publication=client.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                '--operation-id','rust-http-absent-publish','--expected-generation','0')['data']['operation']['publication']['id']
            manifest=client.directory/'deployment.json';write_json(manifest,deployment(read_json(source/'deployment.json'),'examples'))
            target=deploy(client,manifest,publication)
            for name in ('waki','golem'):
                pending=start_call(client,target,'greeting','greet',['alpha|'+name+'|json|'+peers['examples'].url('domain-json')],
                    'rust-http-provider-absent-'+name)
                try:row=finish_call(client,pending)
                except BaseException:
                    retain_after_failure(pending,node,output,'provider-absent-'+name)
                    raise
                write_json(output/('invocation-'+name+'.json'),row)
                response=row['response']
                require(row['exitCode']==4 and row['processReaped'] is True and row['decoded'] is None
                    and response['outcomeKnown'] is True and response['error']['code']=='incompatible-contract'
                    and response['data']['terminalState']=='rejected'
                    and all(int(v)==0 for k,v in response['data']['consumption'].items() if k!='wallTimeMicros'),
                    'rust-http-missing-provider-before-guest-no-authority-or-dispatch')
                record['invocations'].append({'client':name,'invocation':row,
                    'retirement':retire(client,probe,target,output,'provider-absent-'+name,population=1)})
            delete_all(client,[target['name']]);stop(client,node)
            record['shutdown']=stopped_record(node)
            require(record['shutdown']['reaped'] is True and record['shutdown']['record']['clean'] is True,
                'rust-http-absent-provider-clean-stop')
            for tenant,peer in peers.items():
                value=peer.close();check_peer_final(value,[])
                write_json(output/(tenant+'-peer-final.json'),value)
        record['status']='passed';write_json(output/'qualification.json',record);return record
    except BaseException:
        record['status']='failed'
        try:write_json(output/'FAILED.json',record)
        except OSError:pass
        raise


def queued_cancel(client,node,target,peers,probe,output):
    """One root holds real HTTP; a distinct accepted queue entry is cancelled.

    No elapsed sleep proves dispatch state. The sole cell's five original owners,
    real held peer request and sole queue-depth transition identify this pair.
    """
    peer=peers['examples'];before={t:p.observation() for t,p in peers.items()}
    pin=selected_revision(client,target);held=queued=None;witness=None;primary_failure=False
    try:
        held=start_call(client,target,'greeting','greet',[
            'alpha|waki|bytes|'+peer.url('pending-headers')],'rust-http-held-for-queue')
        until=min(client.deadline,time.monotonic()+3)
        while witness is None:
            require(time.monotonic()<until and not held.owner.exited(),'rust-http-holder-ended-before-real-gate')
            held.drain();node.drain()
            for p in peers.values():p.poll(.002)
            gates=[g for g in peer.gates() if g.request>before['examples']['acceptedConnections']]
            require(len(gates)<=1,'rust-http-queued-holder-ambiguous')
            if gates:
                require(gates[0].phase=='headers','rust-http-queued-holder-wrong-gate')
                witness={'gate':{'request':gates[0].request,'phase':'headers'},
                    'owners':positive_pending(client,probe,target)}
        queued=start_call(client,target,'greeting','greet',[
            'delta|golem|json|'+peer.url('domain-json')],'rust-http-queued-before-dispatch')
        observed=None;until=min(client.deadline,time.monotonic()+2)
        for _ in range(32):
            require(time.monotonic()<until and not held.owner.exited() and not queued.owner.exited(),
                'rust-http-queue-pair-ended-before-observation')
            held.drain();queued.drain();node.drain()
            for p in peers.values():p.poll(.002)
            inventory=client.call('node','get','operator-workflow-test')['data']['inventory']
            if int(inventory['queueDepth'])==1:
                rows={r['name']:r for r in inventory['topology']['entries']}
                require(inventory['topology']['available'] is True and inventory['topology']['complete'] is True
                    and all(int(rows[n]['activeCount'])==1 for n in PHYSICAL),
                    'rust-http-queued-before-dispatch-original-holder-owned')
                observed=inventory;break
        require(observed is not None,'rust-http-accepted-queue-entry-not-observed')
        write_json(output/'queued-before-dispatch-positive.json',{'holder':witness,'queuedInventory':observed})
        cancelled=client.call('activation','cancel','rust-http-queued-before-dispatch','--reason','Owned queued Rust HTTP cancellation')
        require(cancelled['outcomeKnown'] is True and cancelled['data']['activationId']=='rust-http-queued-before-dispatch'
            and cancelled['data']['disposition']=='accepted','rust-http-queued-exact-cancel-receipt')
        row=finish_call(client,queued);write_json(output/'queued-before-dispatch-result.json',row)
        response=row['response']
        require(row['exitCode']==4 and row['decoded'] is None and row['processReaped'] is True
            and response['outcomeKnown'] is True and response['error']['code']=='cancelled'
            and all(int(v)==0 for k,v in response['data']['consumption'].items() if k!='wallTimeMicros'),
            'rust-http-queued-cancel-must-not-enter-guest-or-provider')
        require(not held.owner.exited(),'rust-http-holder-retired-before-distinct-queued-cancel')
        for p in peers.values():p.poll(0)
        for tenant,p in peers.items():
            change=delta(before[tenant],p.observation())
            require(change['acceptedConnections']==change['startedRequests']==(1 if tenant=='examples' else 0),
                'rust-http-queued-cancel-contacted-peer')
        holder_cancel=client.call('activation','cancel','rust-http-held-for-queue','--reason','Owned Rust HTTP holder retirement')
        require(holder_cancel['outcomeKnown'] is True and holder_cancel['data']['disposition']=='accepted'
            and holder_cancel['data']['activationId']=='rust-http-held-for-queue','rust-http-holder-cancel-receipt')
        holder=finish_call(client,held);write_json(output/'queued-holder-result.json',holder)
        spec=('queue-holder','bytes','/conformance/hold/headers',None,1,'pending-headers','cancel')
        outcome(holder,spec,'waki',pin,target['budget'])
        for _ in range(64):
            for p in peers.values():p.poll(.002)
            if all(p.observation()['openConnections']==0 for p in peers.values()):break
        require(all(p.observation()['openConnections']==0 for p in peers.values()),'rust-http-queue-holder-peer-close')
        retirement=retire(client,probe,target,output,'queued-before-dispatch')
        return {'queued':row,'holder':holder,'positive':witness,'queuedInventory':observed,
            'queuedCancel':cancelled,'holderCancel':holder_cancel,'retirement':retirement}
    except BaseException:
        primary_failure=True
        for name,process in (('holder',held),('queued',queued)):
            if process is not None:retain_after_failure(process,node,output,'queue-'+name)
        raise
    finally:
        for process in (queued,held):
            if process is not None:close_call(process,primary_failure=primary_failure)


def compact_record(record,output):
    """Bind original per-case evidence without copying it into the aggregate."""
    def reference(name,value):
        path=output/name
        require(read_json(path,262144)==value,'rust-http-summary-original-evidence-required')
        return {'path':name,**file_identity(path,262144)}
    result=dict(record)
    allowed={tenant+'-'+spec[0] for tenant in TENANTS for spec in cases()}
    allowed.update(tenant+'-cross-fresh' for tenant in TENANTS)
    require(len(record['cases'])<=52 and len(record['preEntryRefusals'])<=8,
        'rust-http-summary-original-case-count-bounds')
    result['cases']=[]
    for item in record['cases']:
        require(item['case'] in allowed,'rust-http-summary-owned-case-name')
        result['cases'].append({key:item[key] for key in ('case','tenant','client','observedContacts')}
            | {'evidence':reference('case-'+item['case']+'.json',item)})
    result['preEntryRefusals']=[]
    for item in record['preEntryRefusals']:
        require(item['tenant'] in TENANTS and item['case'] in
            {'ungranted','missing-http','missing-clock','missing-activation'},
            'rust-http-summary-owned-refusal-name')
        result['preEntryRefusals'].append({'tenant':item['tenant'],'case':item['case'],
            'evidence':reference('pre-entry-'+item['tenant']+'-'+item['case']+'.json',item)})
    if 'queuedCancel' in record:
        result['queuedCancel']={'evidence':reference('queued-before-dispatch.json',record['queuedCancel'])}
    if 'providerAbsence' in record:
        value=record['providerAbsence']
        result['providerAbsence']={'status':value['status'],'httpProviderInstalled':value['httpProviderInstalled'],
            'invocations':[{'client':item['client']} for item in value['invocations']],
            'evidence':reference('provider-absence/qualification.json',value)}
    result['evidenceLayout']='individual-original-records-with-sha256-and-byte-length'
    return result


def retain_failed_record(output,record):
    # Reporting must never replace the original controller failure, including
    # when collection or its bounded serialization refuses.
    try:write_json(output/'FAILED.json',compact_record(record,output))
    except BaseException:
        try:write_json(output/'FAILED.json',{'schemaVersion':record['schemaVersion'],
            'status':'failed','stage':record['stage'],'qualification':False,
            'summaryRetentionRefused':True,'originalFailurePreserved':True})
        except BaseException:pass


def run(artifact,native,output,*,deadline,pressure_observation_only=False):
    selected_cases,selected_clients=programme_selection(pressure_observation_only)
    output=fresh(output)
    original_names=('component.wasm','BUILD-COMPLETE.json','source-inputs.json','recipe-inputs.json',
        'build-observation.json','capsule.json','package-source.json','rust-http-runtime.json')
    original={name:file_identity(artifact/name) for name in original_names}
    products={name:file_identity(path,512*1024**2) for name,path in native.items()}
    materials={name:file_identity(ROOT/name) for name in MATERIALS}
    record={'schemaVersion':'latent.rust.wasi-http.node.v1','status':'incomplete','cases':[],
        'preEntryRefusals':[],'source':materials,'original':original,'nativeProducts':products,
        'fullTicketQualification':False,'libraryCodePatched':False,'applicationTransportInjected':False,
        'ordinaryFactories':['waki::Client::new()','golem_wasi_http::Client::new()']}
    if pressure_observation_only:
        record.update(qualification=False,diagnosticOnly=True,scope='single-original-golem-capacity-call')
    stage='normal-neutral-signing';node=None
    try:
        environment=build_environment(output);signed=output/'releases'
        result=run_bounded_result([str(native['capsule_authoring']),'demo-sign-neutral-resources',str(signed),str(artifact)],
            output,environment,timeout_seconds=min(30,deadline-time.monotonic()),max_output_bytes=65536)
        require(result.returncode==0,'rust-http-normal-signing')
        record['signing']=checked_signing(artifact,signed,original)
        stage='actual-provider-absence'
        if not pressure_observation_only:
            record['providerAbsence']=provider_absence(signed,native,output/'provider-absence',deadline)
        with tempfile.TemporaryDirectory(prefix='lsf-rust-http-runtime-') as temporary, \
            owned_cancellation() as cancellation,ExitStack() as cleanup:
            work=Path(temporary)
            for name in ('node','examples','peers'):(work/name).mkdir(mode=0o700)
            peers={};credentials={};secrets_to_protect=[]
            for tenant in TENANTS:
                directory=work/'peers'/tenant;directory.mkdir(mode=0o700)
                secret=('Bearer '+secrets.token_hex(32)).encode();secrets_to_protect.append(secret)
                credential=directory/'authorization';credential.write_bytes(secret);credential.chmod(0o600)
                credentials[tenant]=credential
                peer=Peer(secret,maximum_seconds=300);peers[tenant]=peer;cleanup.callback(peer.close)
            client=RecordingClient(native['latent'],work/'examples',cancellation,min(deadline,time.monotonic()+280),
                evidence=output/'examples-controls')
            config=configuration(work/'node',signed,peers,credentials)
            client.environment[TIMER_ENVIRONMENT]='1'
            record['configurationIdentity']=file_identity(config)
            stage='one-cell-current-node'
            node=connect(client,native['latentd'],work/'node',config,'examples',1);cleanup.callback(node.close)
            clients={'examples':client,'foreign':client_for_foreign(client,node,work/'foreign',output/'foreign-controls')}
            probe=Probe(node,products['latentd']);source=signed/SERVICE
            targets={};publications={};manifests={};all_grants={}
            stage='independent-publications-and-grants'
            for tenant in TENANTS:
                selected=clients[tenant]
                published=selected.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                    '--operation-id','rust-http-publish-'+tenant,'--expected-generation','0')
                require(published['outcomeKnown'] is True and published['data']['release']['digest']==original['component.wasm']['sha256'],
                    'rust-http-original-component-publication')
                publication=published['data']['operation']['publication']['id'];publications[tenant]=publication
                manifest=selected.directory/'deployment.json';write_json(manifest,deployment(read_json(source/'deployment.json'),tenant))
                manifests[tenant]=manifest;target=deploy(selected,manifest,publication)
                grants=grant(selected,node,publication,tenant,peers[tenant]);all_grants[tenant]=grants
                # Each of the exact three declarations remains independently mandatory.
                for missing in (() if pressure_observation_only else (None,HTTP,CLOCK,ACTIVATION)):
                    selected_grants=[] if missing is None else [g for g in grants if g['capability']!=missing]
                    target=deploy(selected,manifest,publication,generation=str(target['generation']),grants=selected_grants)
                    name='ungranted' if missing is None else 'missing-'+{HTTP:'http',CLOCK:'clock',ACTIVATION:'activation'}[missing]
                    snapshots={t:p.observation() for t,p in peers.items()}
                    endpoint=peers[tenant].url('domain-json')
                    pending=start_call(selected,target,'greeting','greet',['alpha|waki|json|'+endpoint],tenant+'-'+name)
                    denied=finish_call(selected,pending);require_denied_before_guest(denied)
                    require(all(int(v)==0 for k,v in denied['response']['data']['consumption'].items() if k!='wallTimeMicros'),
                        'rust-http-pre-entry-no-fuel-or-dispatch')
                    for t,p in peers.items():p.poll(0);require_zero_contact(snapshots[t],p.observation())
                    retirement=retire(selected,probe,target,output,tenant+'-'+name,population=len(targets)+1)
                    record['preEntryRefusals'].append({'tenant':tenant,'case':name,'invocation':denied,'retirement':retirement})
                    write_json(output/('pre-entry-'+tenant+'-'+name+'.json'),record['preEntryRefusals'][-1])
                targets[tenant]=deploy(selected,manifest,publication,generation=str(target['generation']),grants=grants)
            require(publications['examples']!=publications['foreign'],'rust-http-no-cross-tenant-publication-identity')
            record['publications']=publications;record['credentialDenial']=credential_denial(clients['foreign'],targets['foreign'])
            expected={tenant:[] for tenant in TENANTS}
            unparsed={tenant:[] for tenant in TENANTS}
            stage='ordinary-client-programme'
            # Alternating tenant executions exercise repeated A->B reuse; the
            # two outside coordinates alternate independently of either library.
            for index,spec in selected_cases:
                for tenant,client_name in selected_clients:
                    label=tenant+'-'+spec[0];stage=label
                    try:
                        item=invoke(clients[tenant],node,targets[tenant],peers,tenant,client_name,
                            'alpha' if index%2==0 else 'delta',spec,probe,output,label)
                    except BaseException:
                        if pressure_observation_only:
                            # Preserve the original assertion. The same normal
                            # owner check and subsequent actual peer snapshot
                            # distinguish transport state from charged starts.
                            try:
                                retire(clients[tenant],probe,targets[tenant],output,'diagnostic-pressure-after-refusal')
                                for _ in range(64):
                                    for peer in peers.values():peer.poll(.002)
                                    if all(peer.observation()['openConnections']==0 for peer in peers.values()):break
                                write_json(output/'diagnostic-pressure-after-retirement.json',{
                                    'qualification':False,'primaryFailurePreserved':True,
                                    'peers':{name:peer.observation() for name,peer in peers.items()}})
                            except BaseException:
                                try:write_json(output/'diagnostic-pressure-retention-refused.json',{
                                    'qualification':False,'primaryFailurePreserved':True,'retentionStatus':'refused'})
                                except BaseException:pass
                        raise
                    expected[tenant].extend([spec[5]]*item['parsedPeerRequests']);record['cases'].append(item)
                    if item['pressurePeer'] is not None:
                        require(tenant=='foreign' and client_name=='golem' and spec[0]=='resource-capacity',
                            'rust-http-unparsed-connection-only-original-golem-pressure')
                        unparsed[tenant].append(item['pressurePeer']['closedBeforeRequestParsed'])
                    write_json(output/('case-'+label+'.json'),item)
                if index==0 and not pressure_observation_only:
                    stage='queued-before-dispatch-cancel'
                    record['queuedCancel']=queued_cancel(clients['examples'],node,targets['examples'],peers,probe,output)
                    expected['examples'].append('pending-headers')
                    write_json(output/'queued-before-dispatch.json',record['queuedCancel'])
            # A final opposite-library call in each tenant must start at one:
            # no client/static/credential state transfers with the reused cell.
            for tenant,client_name in (() if pressure_observation_only else (('examples','golem'),('foreign','waki'))):
                spec=('cross-tenant-fresh','json','/conformance/json',DOMAIN_TEXT,1,'domain-json','')
                item=invoke(clients[tenant],node,targets[tenant],peers,tenant,client_name,'delta',spec,probe,output,tenant+'-cross-fresh')
                record['cases'].append(item);expected[tenant].append('domain-json')
                write_json(output/('case-'+tenant+'-cross-fresh.json'),item)
            stage='final-owner-and-shutdown'
            for index,tenant in enumerate(TENANTS):
                retire(clients[tenant],probe,targets[tenant],output,tenant+'-final',population=len(TENANTS)-index)
                delete_all(clients[tenant],[targets[tenant]['name']])
            stop(client,node);record['shutdown']=stopped_record(node)
            require(record['shutdown']['reaped'] is True and record['shutdown']['record']['clean'] is True,
                'rust-http-normal-clean-node-shutdown')
            record['peers']={}
            for tenant,peer in peers.items():
                observed=peer.close();public=json.dumps(observed,ensure_ascii=True).encode()
                require(all(secret not in public and secret.removeprefix(b'Bearer ') not in public
                    for secret in secrets_to_protect),'rust-http-no-controlled-credential-retained')
                record['peers'][tenant]=check_peer_final(observed,expected[tenant],closed_before_parse=unparsed[tenant])
                write_json(output/(tenant+'-peer-final.json'),observed)
            record['startup']=node.startup_record
        require(original=={name:file_identity(artifact/name) for name in original_names}
            and products=={name:file_identity(path,512*1024**2) for name,path in native.items()}
            and materials=={name:file_identity(ROOT/name) for name in MATERIALS}
            and time.monotonic()<deadline,'rust-http-final-source-products-and-original-deadline')
        if pressure_observation_only:
            record.update(status='diagnostic-completed',qualification=False,guestExecutions=1,
                invocationAttempts=1,preEntryRefusalsCount=0)
            summary=compact_record(record,output)
            write_json(output/'diagnostic.json',summary);return summary
        record.update(status='passed',guestExecutions=len(record['cases'])+1,
            invocationAttempts=len(record['cases'])+len(record['preEntryRefusals'])+4,
            preEntryRefusalsCount=len(record['preEntryRefusals'])+3,
            ordinaryLibraryCases=len(record['cases']),queuedBeforeGuestCancelled=1,providerAbsenceRefusals=2)
        summary=compact_record(record,output)
        write_json(output/'qualification.json',summary);return summary
    except BaseException:
        record.update(status='failed',stage=stage)
        retain_failed_record(output,record)
        raise
