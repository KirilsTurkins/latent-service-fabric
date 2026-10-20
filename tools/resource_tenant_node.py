"""Finite same-node tenant reuse of immutable resource components.

This controller owns no guest runtime: ordinary signing, admission, provider
policies, CLI invocation and physical owner barriers remain authoritative.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import time

from tools.phase2_operator_process import read_json, require, write_json
from tools.phase2_operator_scenario import TOKEN
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import call, deploy, sample, selected_revision

TENANTS = ('examples','foreign')
FOREIGN_TOKEN = 'LSF-PUBLIC-RESOURCE-TENANT-TEST-ONLY'
SUBJECTS = {'examples':'workflow-operator','foreign':'foreign-resource-operator'}
PROFILES = {
    'latent:clock/monotonic@0.1.0':('clockMonotonic','activation-monotonic-v1','clock',['now-nanos']),
    'latent:clock/wall@0.1.0':('clockWall','activation-wall-v1','clock',['now-unix-millis']),
    'latent:random/random@0.1.0':('random','system-random-v1','random',[]),
    'latent:log/log@0.1.0':('log','activation-log-v1','log',['write']),
}


def required_imports(capsule):
    rows = capsule.get('imports')
    require(type(rows) is list and len(rows) <= len(PROFILES)
        and all(type(row) is dict and set(row) == {'contract','optional'}
            and row['optional'] is False and row['contract'] in PROFILES for row in rows),
        'resource-tenant-closed-original-import-set')
    names = [row['contract'] for row in rows]
    require(len(names) == len(set(names)),'resource-tenant-duplicate-import')
    return names


def configure(settings, capsule, language):
    imports = required_imports(capsule)
    require(language in {'c','rust','typescript','go','java','dotnet'}
        and settings['workers'] == {'runtime':1,'control':1}
        and len(settings['cells']) == 1 and settings['cells'][0]['capacity'] == 1
        and settings['cells'][0]['queueCapacity'] == 2
        and set(settings.get('providers',{})) == {'formatVersion','http','bindings'}
        and settings['providers']['formatVersion'] == 1
        and settings['providers']['http']['identity']['tenant'] == 'examples'
        and len(settings['providers']['bindings']) == 1
        and settings['providers']['bindings'][0]['contract'] == 'latent:http/client@0.2.0',
        'resource-tenant-original-single-cell-profile')
    maximum = 134217728 if language in {'dotnet','typescript'} else 67108864
    require(capsule['execution']['limits']['memoryBytes'] <= maximum,
        'resource-tenant-original-memory-profile')
    settings['cells'][0]['maximumMemoryBytes'] = maximum
    settings['execution']['maximumWallTimeMillis'] = 5000 if language in {'c','rust'} else 120000
    settings['cache'].update(entries=2,preparations=1)
    settings['budgetProfile'] = {'mode':'phase3','maximumOutboundRequests':8,
        'maximumBlobReadBytes':65536,'maximumBlobWriteBytes':65536}
    settings['capabilityPolicies'] = {'formatVersion':1,'maximumControlJobs':2,
        'store':{'maximumRecords':64,'maximumOutcomes':128,'maximumCatalogBytes':4194304,
            'maximumReadOwners':64,'maximumPageRecords':16}}
    settings['audit'].update(records=4096,diskBytes=67108864)
    settings['shutdownGraceMillis'] = 5000
    if language == 'java':settings.setdefault('engine',{})['javaGuest'] = True
    require(settings['credentials'] == [{'token':TOKEN,'subject':SUBJECTS['examples'],
        'tenant':'examples','role':'operator'}],'resource-tenant-original-credential')
    settings['credentials'].append({'token':FOREIGN_TOKEN,'subject':SUBJECTS['foreign'],
        'tenant':'foreign','role':'operator'})
    # Retain the normal owned HTTP observation infrastructure without granting
    # it to this resource service. Its original available pool/IO counters are
    # needed to distinguish zero physical owners from absent observations.
    providers = copy.deepcopy(settings['providers']);providers['scalarAliases'] = []
    for capability in imports:
        name,_profile,_kind,_operations = PROFILES[capability]
        providers[name] = {'identity':{'id':name,'tenant':'examples','service':'runtime-host','epoch':1}}
        providers['scalarAliases'].append({'source':name,'identity':{'id':name+'-foreign',
            'tenant':'foreign','service':'foreign-runtime','epoch':1}})
        for tenant in TENANTS:
            providers['bindings'].append({'name':name+'-'+tenant,'tenant':tenant,
                'consumerService':'my-greeting','providerService':'runtime-host' if tenant == 'examples' else 'foreign-runtime',
                'contract':capability,'providerBinding':name+'-'+tenant+'-installed'})
    require(len(providers['bindings']) <= 16 and 1+len(imports)*2 <= 14,
        'resource-tenant-original-provider-capacity')
    settings['providers'] = providers
    return settings


def scoped_deployment(original, tenant):
    require(tenant in TENANTS and original['metadata'].get('tenant') is None
        and original['spec']['service'] == 'my-greeting' and original['spec']['grants'] == [],
        'resource-tenant-neutral-deployment-required')
    selected = copy.deepcopy(original)
    selected['metadata'].update(tenant=tenant,name='resource-'+tenant)
    return selected


def install_grants(client, node, source, publication, target, capabilities, language, tenant):
    require(tenant in TENANTS and target['service'] == 'my-greeting'
        and target['grants'] == [] and len(capabilities) == len(set(capabilities))
        and set(capabilities) <= set(PROFILES), 'resource-tenant-independent-grant-selection')
    grants = []
    for capability in capabilities:
        name,profile,kind,operations = PROFILES[capability]
        operations = list(operations)
        if kind == 'random':operations = ['bytes'] if language in {'c','dotnet'} else ['u64-value']
        provider = name if tenant == 'examples' else name+'-foreign'
        service = 'runtime-host' if tenant == 'examples' else 'foreign-runtime'
        rows = [row for row in node.startup_record['providers'] if row['id'] == provider]
        require(len(rows) == 1 and rows[0]['tenant'] == tenant and rows[0]['service'] == service
            and rows[0]['capability'] == capability and rows[0]['profile'] == profile
            and rows[0]['configurationEpoch'] == '1','resource-tenant-installed-original-provider')
        binding_id,policy_id = name+'-'+tenant+'-installed',name+'-'+tenant+'-allow'
        binding = client.directory/(binding_id+'.json')
        write_json(binding,{'formatVersion':1,'tenant':tenant,'capability':capability,'providerProfile':profile,
            'configurationDigest':rows[0]['configurationDigest'],'configurationEpoch':1,
            'restriction':{'operations':operations}})
        client.call('policy','--kind','provider-binding','apply','--id',binding_id,'--file',binding,
            '--operation-id','install-'+name+'-'+tenant,'--expected-generation','0')
        resources = {'kind':kind}
        if kind == 'log':resources['levels'] = ['info','error']
        ceiling = {'operations':64 if kind == 'log' else 16 if kind == 'random' and language == 'dotnet' else 4096,
            'inputBytes':16384 if kind == 'log' else 8 if kind == 'random' else 0,
            'outputBytes':0 if kind == 'log' else 4096 if kind == 'random' and language == 'dotnet' else 32768,
            'wallTimeMillis':5000}
        document = {'formatVersion':1,'tenant':tenant,'rules':[{'id':'resource-runtime','effect':'allow',
            'principals':[{'kind':'administrator','subject':SUBJECTS[tenant]}],
            'services':[target['service']],'publications':[publication],'capability':capability,
            'operations':operations,'resources':resources,'ceiling':ceiling}]}
        policy = client.directory/(policy_id+'.json');write_json(policy,document)
        client.call('policy','apply','--id',policy_id,'--file',policy,
            '--operation-id','grant-'+name+'-'+tenant,'--expected-generation','0')
        grants.append({'capability':capability,'policy':policy_id})
    return deploy(client,source,publication,generation=str(target['generation']),grants=grants)


def provider_idle(client, target):
    observed = client.call('capability','list','--deployment',target['name'],'--include-node-usage')['data']
    require(observed['nextPageToken'] is None and not observed['nodeUsage']['unavailable']
        and all(int(observed['nodeUsage']['counters'][name]) == 0 for name in ACTIVE_COUNTERS),
        'resource-tenant-physical-provider-retirement')
    return observed['nodeUsage']


def require_denied_before_guest(row):
    response = row['response'];consumed = response['data']['consumption']
    require(row['exitCode'] == 4 and row['processReaped'] and response['outcomeKnown'] is True
        and response['category'] == 'platform-failure' and response['error']['code'] == 'permission-denied'
        and response['data']['terminalState'] == 'rejected'
        and all(int(consumed[key]) == 0 for key in ('cpuFuel','peakMemoryBytes','childCalls','outboundRequests',
            'logBytes','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')),
        'resource-tenant-foreign-grants-not-inherited')


def sequence(language):
    if language == 'dotnet':
        from tools.dotnet_standard_console_fixture import EXPECTED
        return 'console:initializer',EXPECTED['initializer'],'console:trap'
    if language == 'c':
        from tools.c_compiled_resource_fixture import CASES
        return 'resource:utf8',CASES[0][1],'resource:trap'
    if language == 'java':
        from tools.java_resource_fixture import EXPECTED
    else:
        from tools.embedded_resource_fixture import EXPECTED as ALL
        require(language in ALL,'resource-tenant-language')
        EXPECTED = ALL[language]
    return 'resources:text',EXPECTED['text'],'resources:trap'


def invoke(client, target, argument, label, component):
    pin = selected_revision(client,target)
    row = call(client,target,'greeting','greet',[argument],label)
    require(row['processReaped'] and row['response']['outcomeKnown'] is True
        and row['response']['data']['resolvedRevision'] == pin
        and pin['releaseDigest'] == component,'resource-tenant-exact-selected-publication-and-component')
    usage = row['response']['data']['consumption']
    require(0 < int(usage['cpuFuel']) <= target['budget']['cpuFuel']
        and 0 < int(usage['peakMemoryBytes']) <= target['budget']['memoryBytes']
        and all(int(usage[key]) == 0 for key in ('outboundRequests','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes'))
        and 0 <= int(usage['logBytes']) <= target['budget']['logBytes'],
        'resource-tenant-original-activation-budgets')
    return row


def programme(clients, targets, probe, component, language, result):
    value,expected,trap = sequence(language)
    steps = [('examples','initial',value),('examples','trap',trap),('foreign','after-other-trap',value),
        ('examples','fresh',value),('foreign','trap',trap),('examples','after-other-trap',value),('foreign','fresh',value)]
    cases = []
    for tenant,phase,argument in steps:
        row = invoke(clients[tenant],targets[tenant],argument,'resource-'+language+'-'+tenant+'-'+phase,component)
        result['invocations'].append(row)
        if phase == 'trap':
            require(row['exitCode'] == 4 and row['response']['error']['code'] == 'guest-trap'
                and row['response']['data']['terminalState'] == 'guest_trap','resource-tenant-explicit-trap')
        else:require(row['exitCode'] == 0 and row['decoded'] == [{'ok':expected}],'resource-tenant-exact-fresh-resource')
        idle = provider_idle(clients[tenant],targets[tenant])
        physical = sample(clients[tenant],probe,row['activation']+'-retired',2)
        result['providerIdle'].append(idle);result['samples'].append(physical)
        cases.append({'tenant':tenant,'phase':phase,'invocation':row,'physicalRetirement':physical,'providerRetirement':idle})
    return {'status':'passed','cases':cases,'sameComponent':component,'sameNode':True,
        'singleExecutionCell':True,'sameTenantAndForeignFreshAfterTrap':True,
        'concurrentResourceReadsQualified':False,'pendingFlushQualified':False,'lateCompletionQualified':False,
        'guestRequestIdentityApiQualified':False,
        'fullTicketQualification':False}
