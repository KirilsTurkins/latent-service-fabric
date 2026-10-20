"""One cell, two independently installed HTTP providers, ordinary Go clients."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools import go_standard_http_node as original
from tools.go_http_adversarial import CEILING, OPERATIONS, outcome
from tools.guest_runtime_profiles import RUNTIME
from tools.phase2_operator_process import Process, read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import client_for_foreign, credential_denial
from tools.resource_tenant_node import SUBJECTS, TENANTS, FOREIGN_TOKEN, provider_idle, require_denied_before_guest
from tools.rust_capsule_node import RecordingClient, call, delete_all, deploy, sample, selected_revision
from tools.rust_capsule_project import ROOT
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.standard_http.observations import validate as validate_peer
from tools.static_api.node import policy

SERVICE = 'go-standard-http'
DOMAIN = '200:domain:7:caf\u00e9:first|\u03bb'
RUNTIME_LIMITS = {'tasks':8,'executors':2,'queuedWork':8,'waits':16,'timers':8,'results':8,'nativeOwners':8}


def settings(original_settings, startups, credentials):
    value = copy.deepcopy(original_settings)
    providers = value['providers']
    require(value['workers'] == {'runtime':1,'control':1} and len(value['cells']) == 1
        and value['cells'][0]['capacity'] == 1 and value['cells'][0]['queueCapacity'] == 2
        and providers['activationRuntime']['limits'] == RUNTIME_LIMITS
        and set(startups) == set(credentials) == set(TENANTS)
        and len(value['credentials']) == 1 and value['credentials'][0]['tenant'] == 'examples',
        'go-http-tenant-original-single-cell-and-runtime-limits')
    value['credentials'].append({'token':FOREIGN_TOKEN,'subject':SUBJECTS['foreign'],
        'tenant':'foreign','role':'operator'})
    providers['additionalHttpStreaming'] = []
    providers['scalarAliases'] = []
    for tenant in TENANTS:
        provider = copy.deepcopy(providers['httpStreaming'])
        provider['identity'] = {'id':'http-'+tenant,'tenant':tenant,'service':'http-'+tenant,'epoch':1}
        credential = credentials[tenant]
        provider['credentialDirectory'] = str(credential.parent)
        provider['credentials'][0]['file'] = credential.name
        provider['configuration']['destinations'] = startups[tenant]['destinations']
        if tenant == 'examples':providers['httpStreaming'] = provider
        else:providers['additionalHttpStreaming'].append(provider)
    # Alias only the maintained scalar/activation implementations. HTTP is a
    # second installation with its own private credential store and origin set.
    for name in (*RUNTIME,'activationRuntime'):
        source = providers[name]['identity']
        providers['scalarAliases'].append({'source':name,'identity':{
            'id':source['id']+'-foreign','tenant':'foreign','service':source['service']+'-foreign','epoch':1}})
    providers['bindings'] = []
    for tenant in TENANTS:
        providers['bindings'].append({'name':'http-'+tenant,'tenant':tenant,'consumerService':SERVICE,
            'providerService':'http-'+tenant,'contract':original.CAPABILITY,'providerBinding':'http-'+tenant+'-installed'})
        for name in (*RUNTIME,'activationRuntime'):
            identity = providers[name]['identity']
            capability = original.ACTIVATION if name == 'activationRuntime' else RUNTIME[name][0]
            providers['bindings'].append({'name':name+'-'+tenant,'tenant':tenant,'consumerService':SERVICE,
                'providerService':identity['service']+('-foreign' if tenant == 'foreign' else ''),
                'contract':capability,'providerBinding':name+'-'+tenant+'-installed'})
    require(len(providers['bindings']) == 10 and len(providers['scalarAliases']) == 4,
        'go-http-tenant-original-descriptor-and-binding-ceilings')
    return value


def deployment(source, tenant):
    require(tenant in TENANTS and source['metadata'].get('tenant') is None
        and source['spec']['service'] == SERVICE and source['spec']['grants'] == [],
        'go-http-tenant-neutral-original-deployment')
    value = copy.deepcopy(source)
    value['metadata'].update(tenant=tenant,name='go-http-'+tenant)
    return value


def grant(client, node, publication, tenant, origin):
    grants = []
    for name,(capability,profile,operation,kind) in RUNTIME.items():
        grants.append(_grant(client,node,publication,tenant,name,capability,profile,[operation],
            {'kind':kind},{'operations':4096,'inputBytes':8 if name == 'random' else 0,
                'outputBytes':32768,'wallTimeMillis':5000}))
    descriptor = next(row for row in node.startup_record['providers'] if row['id'] == 'activation')
    grants.append(_grant(client,node,publication,tenant,'activationRuntime',original.ACTIVATION,
        descriptor['profile'],original.OPS,{'kind':'clock'},
        {'operations':4096,'inputBytes':0,'outputBytes':32768,'wallTimeMillis':5000}))
    runtime = list(grants)
    grants.append(_grant(client,node,publication,tenant,'http',original.CAPABILITY,
        'bounded-streaming-http-identity-v1',OPERATIONS,
        {'kind':'http','origins':[origin],'methods':['GET','POST'],'paths':[],
            'pathPrefixes':['/conformance/']},dict(CEILING)))
    return runtime,grants


def _grant(client,node,publication,tenant,name,capability,profile,operations,resources,ceiling):
    identity = ('http-'+tenant if name == 'http' else
        ('activation' if name == 'activationRuntime' else name)+('-foreign' if tenant == 'foreign' else ''))
    rows = [row for row in node.startup_record['providers'] if row['id'] == identity]
    require(len(rows) == 1 and rows[0]['tenant'] == tenant and rows[0]['capability'] == capability
        and rows[0]['profile'] == profile and rows[0]['configurationEpoch'] == '1',
        'go-http-tenant-exact-installed-profile')
    binding,allow = name+'-'+tenant+'-installed',name+'-'+tenant+'-allow'
    policy(client,'provider-binding',binding,{'formatVersion':1,'tenant':tenant,'capability':capability,
        'providerProfile':profile,'configurationDigest':rows[0]['configurationDigest'],'configurationEpoch':1,
        'restriction':{'operations':[] if name == 'http' else operations}})
    policy(client,'policy',allow,{'formatVersion':1,'tenant':tenant,'rules':[{'id':'ordinary-http-runtime',
        'effect':'allow','principals':[{'kind':'administrator','subject':SUBJECTS[tenant]}],
        'services':[SERVICE],'publications':[publication],'capability':capability,
        'operations':operations,'resources':resources,'ceiling':ceiling}]})
    return {'capability':capability,'policy':allow}


def cases():
    return (
        ('examples','sling-json',0,'/conformance/json',DOMAIN,1),
        ('foreign','requests-json',100,'/conformance/json',DOMAIN,1),
        ('examples','sling-post',1,'/conformance/echo','200:echo:AAECAw==',1),
        ('foreign','requests-post',101,'/conformance/echo','200:echo:AAECAw==',1),
        ('examples','delegating-extension',300,'/conformance/json','delegated:200:1:caf\u00e9',1),
        ('foreign','delegating-extension',300,'/conformance/json','delegated:200:1:caf\u00e9',1),
        ('examples','delegating-origin-denied',300,'foreign','delegated-transport-error:1',0),
        ('foreign','delegating-origin-denied',300,'examples','delegated-transport-error:1',0),
        ('examples','foreign-origin-denied',0,'foreign','transport-error',0),
        ('foreign','foreign-origin-denied',100,'examples','transport-error',0),
        ('examples','return-pending',301,'/conformance/body/partial','root-returned-with-pending-body',1),
        ('foreign','sling-after-other-return',0,'/conformance/json',DOMAIN,1),
        ('foreign','trap-pending',302,'/conformance/body/partial',None,1),
        ('examples','requests-after-other-trap',100,'/conformance/json',DOMAIN,1),
        ('foreign','requests-fresh',100,'/conformance/json',DOMAIN,1),
        ('examples','trap-pending',302,'/conformance/body/partial',None,1),
        ('foreign','requests-after-other-trap',100,'/conformance/json',DOMAIN,1),
        ('foreign','return-pending',301,'/conformance/body/partial','root-returned-with-pending-body',1),
        ('examples','sling-after-other-return',0,'/conformance/json',DOMAIN,1),
    )


def invoke(client,target,which,address,label):
    return call(client,target,'go-standard-http','run',[which,address],label)


def peer_outcome(value, tenant):
    validate_peer(value)
    selected = [row for row in cases() if row[0] == tenant and row[5] == 1]
    expected = [('primary','partial-body' if path.endswith('/partial') else
        'method-bytes' if path.endswith('/echo') else 'domain-json') for _,_,_,path,_,_ in selected]
    require(value['acceptedConnections'] == value['startedRequests'] == len(expected)
        and value['rejectedRequests'] == value['connectionBoundRejections'] == value['openConnections'] == 0
        and value['committedMutations'] == 0
        and [(row['role'],row.get('vector')) for row in value['requests']] == expected,
        'go-http-tenant-exact-own-peer-contacts')
    require(all(row.get('authorizationPresent') is True and row.get('cookiePresent') is False
        and row.get('proxyAuthorizationPresent') is False for row in value['requests']),
        'go-http-tenant-private-credentials-not-crossed')
    partial = {row['request'] for row in value['requests'] if row.get('vector') == 'partial-body'}
    require(len(partial) == 2 and {row['request'] for row in value['events']
        if row['kind'] == 'gate-pending' and row.get('phase') == 'body'} == partial
        and not any(row['kind'] == 'gate-released' for row in value['events']),
        'go-http-tenant-pending-body-not-replayed-or-released')


def run(artifact, native, output, deadline):
    output.mkdir(mode=0o700)
    result = {'schemaVersion':'latent.go.http-tenant-node.v1','status':'incomplete','cases':[],
        'sameComponent':file_identity(artifact/'component.wasm',64*1024**2),'sameNode':True,
        'singleCellCapacity':1,'runtimeLimits':RUNTIME_LIMITS,'productionKernelQualification':False,
        'lateRemoteCompletionQualified':False,'httpsTransportSupported':False}
    stage = 'checked-neutral-packaging-and-ephemeral-signature'
    node = None;peers = {};clients = {}
    try:
        signed = output/'signed'
        signature = run_bounded_result([str(native['capsule_authoring']),'demo-sign-neutral-resources',
            str(signed),str(artifact)],output,build_environment(output),min(30,deadline-time.monotonic()),65536)
        (output/'sign.stdout.log').write_bytes(signature.stdout);(output/'sign.stderr.log').write_bytes(signature.stderr)
        require(signature.returncode == 0,'go-http-tenant-original-build-neutral-signing')
        manifest = read_json(signed/'release-set.json')
        require(manifest.get('tenant') is None and manifest['tenants'] == list(TENANTS)
            and manifest['trust'] == 'isolated-neutral-resource-two-tenant-test-only'
            and manifest['packagingOnly'] is True and manifest['componentCompilationPerformed'] is False,
            'go-http-tenant-explicit-neutral-packaging-not-compilation')
        result['neutralPackaging'] = manifest
        source = signed/SERVICE
        ancestry = read_json(artifact/'build-observation.json')
        current = read_json(source/'build-observation.json')
        inherited = [row for row in current['materials'] if row['name'] == 'resource-original-build-observation']
        original_observation = file_identity(artifact/'build-observation.json')
        require(all(current[key] == ancestry[key] for key in ('buildType','source','parameters','componentDigest','componentSize'))
            and inherited == [{'name':'resource-original-build-observation','digest':original_observation['sha256'],
                'size':original_observation['bytes']}],
            'go-http-tenant-neutral-packaging-original-compiler-ancestry')
        with tempfile.TemporaryDirectory(prefix='lsf-go-http-tenants-') as temporary, owned_cancellation() as cancellation:
            work = Path(temporary)
            for name in ('node','examples','peer-examples','peer-foreign'):(work/name).mkdir(mode=0o700)
            clients['examples'] = RecordingClient(native['latent'],work/'examples',cancellation,deadline,
                evidence=output/'examples-controls',invocation_timeout_millis=120000)
            client = clients['examples'];startups = {};credentials = {}
            for tenant in TENANTS:
                credentials[tenant] = work/('peer-'+tenant)/'authorization'
                credentials[tenant].write_bytes(('Bearer '+secrets.token_hex(32)).encode())
                credentials[tenant].chmod(0o600)
                peers[tenant] = Process([sys.executable,str(ROOT/original.PEER_SOURCE),'--credential',str(credentials[tenant])],
                    credentials[tenant].parent,build_environment(work),cancellation,maximum=65536)
                startups[tenant] = peers[tenant].line(min(deadline,time.monotonic()+10))
            config = original.configuration(work/'node',signed,startups['examples'],credentials['examples'])
            value = settings(read_json(config),startups,credentials)
            config.write_bytes((json.dumps(value,indent=2)+'\n').encode())
            # Credentials here are references to private files, never their bytes.
            write_json(output/'node-configuration.json',value)
            result['configurationIdentity'] = file_identity(config)
            stage = 'same-manager-single-cell-two-http-installations'
            node = connect(client,native['latentd'],work/'node',config,'examples',1)
            clients['foreign'] = client_for_foreign(client,node,work/'foreign',output/'foreign-controls')
            result['providers'] = node.startup_record['providers']
            probe = Probe(node,file_identity(native['latentd']))
            targets,publications,sources,urls = {},{},{},{}
            result['denials'] = []
            for tenant in TENANTS:
                selected = clients[tenant]
                published = selected.call('release','publish-package',source/'package','--evidence',source/'evidence/index.json',
                    '--operation-id','go-http-publish-'+tenant,'--expected-generation','0')
                require(published['outcomeKnown'] and published['data']['release']['digest'] == result['sameComponent']['sha256'],
                    'go-http-tenant-original-component-publication')
                publications[tenant] = published['data']['operation']['publication']['id']
                sources[tenant] = selected.directory/'deployment.json'
                write_json(sources[tenant],deployment(read_json(source/'deployment.json'),tenant))
                targets[tenant] = deploy(selected,sources[tenant],publications[tenant])
                origin = startups[tenant]['origins']['primary'];urls[tenant] = f"http://{origin['host']}:{origin['port']}"
                denied = invoke(selected,targets[tenant],300,urls[tenant]+'/conformance/json','tenant-runtime-denied-'+tenant)
                require_denied_before_guest(denied);result['denials'].append(denied)
                runtime,authorized = grant(selected,node,publications[tenant],tenant,origin)
                targets[tenant] = deploy(selected,sources[tenant],publications[tenant],generation=str(targets[tenant]['generation']),grants=runtime)
                denied = invoke(selected,targets[tenant],300,urls[tenant]+'/conformance/json','tenant-http-denied-'+tenant)
                require_denied_before_guest(denied);result['denials'].append(denied)
                targets[tenant] = deploy(selected,sources[tenant],publications[tenant],generation=str(targets[tenant]['generation']),grants=authorized)
            require(publications['examples'] != publications['foreign'],'go-http-tenant-distinct-publications')
            result['credentialDenial'] = credential_denial(clients['foreign'],targets['foreign'])
            stage = 'ordinary-clients-extension-and-cross-tenant-retirement'
            for index,(tenant,name,which,path,expected,contacts) in enumerate(cases()):
                selected,target = clients[tenant],targets[tenant]
                address = urls[path]+'/conformance/json' if path in TENANTS else urls[tenant]+path
                revision = selected_revision(selected,target)
                label = 'go-http-tenant-'+str(index)+'-'+tenant
                row = invoke(selected,target,which,address,label)
                outcome(row,expected,contacts,revision,target['budget'])
                idle = provider_idle(selected,target)
                physical = sample(client,probe,label+'-retired',2)
                write_json(output/(label+'-physical.json'),physical)
                result['cases'].append({'tenant':tenant,'name':name,'mode':which,'expected':expected,
                    'outboundRequests':contacts,'invocation':row,'physicalReceipt':label+'-physical.json','providerIdle':idle})
            for tenant in TENANTS:delete_all(clients[tenant],[targets[tenant]['name']])
            clients['foreign'].node = None;stop(client,node)
            result['shutdown'] = stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'],'go-http-tenant-clean-stop')
            node = None;result['peers'] = {}
            for tenant,peer in peers.items():
                peer.stop()
                lines = bytes(peer.buffers[0]).splitlines()
                require(len(lines) == 1,'go-http-tenant-one-terminal-peer-record')
                observation = json.loads(lines[0]);peer_outcome(observation,tenant)
                require(peer.owner.finished and peer.owner.process.returncode == 0,'go-http-tenant-peer-reaped')
                result['peers'][tenant] = observation
        result['status'] = 'passed'
        write_workflow_receipt(output/'qualified.json',result)
        return result
    except BaseException as error:
        result.update(status='failed',stage=stage,errorCategory=type(error).__name__)
        write_workflow_receipt(output/'FAILED.json',result)
        raise
    finally:
        for client in clients.values():client.node = None
        if node is not None:node.close()
        for peer in peers.values():peer.close()
