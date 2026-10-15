"""One separately captured strict command; signed custody never grants HTTP."""
from __future__ import annotations

import copy
import re
import socket

from tools.phase2_operator_process import read_json, write_json
from tools.phase2_operator_scenario import receipt
from tools.rust_capsule_project import read_file

from . import configuration as cfg, http, lifecycle, policies
from .campaign import Campaign, command_input, precondition, rpc_result
from .inputs import decode, digest, require

SERVICE = cfg.EARLY_HTTP_SERVICE
DEPLOYMENT = 'transaction-java-forbidden-http-before-stage'


def operations(item, publication):
    companion = decode(read_file(item.directory / 'project/transaction-binding.json', 131072))
    require(item.name == 'forbidden-http-before-stage' and item.requirements_digest is None
            and digest(read_file(item.directory / 'project/transaction-binding.json', 131072)) == item.companion_digest
            and companion['capsule'] == SERVICE and companion['deployment'] == DEPLOYMENT
            and companion['binding'] == DEPLOYMENT and companion['namespace'] == cfg.NAMESPACE
            and re.fullmatch(r'publication:sha256:[0-9a-f]{64}', publication or ''),
            'exact-early-signed-operation-identities')
    require(companion['operations'] == [
        {'operation': name, 'mode': 'strict-command' if name == 'update' else 'fresh-query',
         'inputFormat': 'lsf-wit-values-v1', 'resultFormat': 'lsf-wit-values-v1'}
        for name in ('update', 'query', 'scan')], 'exact-early-three-operation-companion')
    return [{'tenant': cfg.TENANT, 'componentDigest': item.component_digest,
             'publication': publication, 'contract': cfg.CONTRACT, 'function': name,
             'deployment': DEPLOYMENT, 'route': DEPLOYMENT, 'binding': DEPLOYMENT,
             'companionDigest': item.companion_digest, 'incarnation': 1,
             'resultPolicy': cfg.RESULT_POLICY, 'statePolicies': [cfg.STATE_POLICY]}
            for name in ('update', 'query', 'scan')]


def proposals(value, publication):
    require(isinstance(value, dict) and set(value) == policies.INSPECTION_FIELDS
            and value['schemaVersion'] == 'latent.transaction-host-inspection.v1'
            and value['deferredHttp'] == [], 'early-inspection-has-no-effect-installation')
    policies.identifier(value['stateProviderProfile'])
    policies.sha(value['stateConfigurationDigest'])
    policies.epoch(value['stateConfigurationEpoch'])
    for name in ('configuredHttpCallers', 'configuredTransportCallers'):
        callers = value[name]
        require(isinstance(callers, list) and 0 < len(callers) <= 64
                and all(isinstance(row, dict) and set(row) == policies.CALLER_FIELDS
                        and row['ownerKind'] in {'user', 'administrator'} and row['service'] is None
                        and row['recoveryKind'] == 'original-caller' for row in callers)
                and len({(row['subject'], row['ownerKind'], row['tenant']) for row in callers}) == len(callers),
                'exact-early-original-callers')
        for row in callers:
            for field in ('subject', 'tenant', 'recoveryScope'):
                policies.identifier(row[field])
    alice = policies._caller(value['configuredHttpCallers'], cfg.ALICE, 'user')
    require(alice == policies._caller(value['configuredTransportCallers'], cfg.ALICE, 'user'),
            'same-early-http-rpc-caller')
    operator = policies._caller(value['configuredTransportCallers'], cfg.OPERATOR, 'administrator')
    rows = value['configuredProviders']
    require(isinstance(rows, list) and len(rows) == 3, 'exact-early-native-provider-set')
    providers = {}
    for row in rows:
        require(isinstance(row, dict) and set(row) == policies.PROVIDER_FIELDS
                and row['id'] in {*cfg.CLOCKS, 'http'} and row['id'] not in providers
                and row['tenant'] == cfg.TENANT and row['service'] == 'runtime-host'
                and row['capability'] == (cfg.CLOCKS[row['id']][0] if row['id'] in cfg.CLOCKS
                                          else policies.HTTP_CONTRACT), 'exact-early-provider-identity')
        policies.identifier(row['profile'])
        policies.sha(row['configurationDigest'])
        policies.epoch(row['configurationEpoch'], decimal=True)
        providers[row['id']] = row
    require(re.fullmatch(r'publication:sha256:[0-9a-f]{64}', publication or ''), 'early-admitted-publication')
    result = {'bindings': {DEPLOYMENT: policies.binding(policies.STATE_CONTRACT,
        value['stateProviderProfile'], value['stateConfigurationDigest'], value['stateConfigurationEpoch'], [])},
        'policies': {}, 'deploymentGrants': [
            {'capability': policies.STATE_CONTRACT, 'policy': cfg.STATE_POLICY,
             'operations': list(policies.DATA_OPERATIONS)}]}
    rules = []
    for caller, names in ((alice, policies.DATA_OPERATIONS),
                          (operator, ['namespace-create', 'namespace-inspect', 'read-result'])):
        rule = policies.rule(caller['ownerKind'], caller['ownerKind'], caller['subject'], [publication],
                             policies.STATE_CONTRACT, names,
                             {'kind': 'state', 'scopes': [policies.scope(caller)]})
        rule['services'] = [SERVICE]
        rules.append(rule)
    result['policies'][cfg.STATE_POLICY] = {'formatVersion': 1, 'tenant': cfg.TENANT, 'rules': rules}
    for provider, (capability, operation) in cfg.CLOCKS.items():
        row = providers[provider]
        name = {'clockMonotonic': 'clock-monotonic', 'clockWall': 'clock-wall'}[provider]
        result['bindings'][name + '-installed'] = policies.binding(capability, row['profile'],
            row['configurationDigest'], policies.epoch(row['configurationEpoch'], decimal=True), [operation])
        rule = policies.rule('clock', 'user', cfg.ALICE, [publication], capability, [operation],
                             {'kind': 'clock'}, input_bytes=0, output_bytes=32768, calls=4096, wall=120000)
        rule['services'] = [SERVICE]
        result['policies'][name + '-allow'] = {'formatVersion': 1, 'tenant': cfg.TENANT, 'rules': [rule]}
        result['deploymentGrants'].append({'capability': capability, 'policy': name + '-allow'})
    return result


def metadata(client, signed, item, publication, grants):
    manifest = read_json(signed / ('java718-' + item.name) / 'deployment.json')
    require(manifest['metadata'] == {'tenant': cfg.TENANT, 'name': DEPLOYMENT}
            and manifest['spec']['service'] == SERVICE and manifest['spec']['release'] == item.component_digest
            and manifest['spec']['resources']['outboundRequests'] == 0
            and {row['capability'] for row in grants} == {policies.STATE_CONTRACT, *[v[0] for v in cfg.CLOCKS.values()]},
            'early-deployment-has-no-http-or-intent-grant')
    manifest['spec'].update(publication=publication, grants=copy.deepcopy(grants))
    prior = client.call('deployment', 'get', DEPLOYMENT, '--operation-snapshot', codes=(0, 6))['data']
    path = client.directory / 'early-deployment.json'
    write_json(path, manifest)
    operation = 'early-http-deploy'
    receipt(client.call('--rpc-timeout-ms', '300000', 'deployment', 'apply', path,
        '--operation-id', operation, '--expected-generation',
        prior['deployment']['generation'] if prior.get('deployment') else '0',
        '--expected-state-version', prior['stateVersion'], timeout=310), operation)
    deployed = client.call('deployment', 'get', DEPLOYMENT)['data']['deployment']
    snapshot = client.call('route', 'get')['data']['snapshot']
    selected = [row for row in snapshot['services'] if row['routeId'] == DEPLOYMENT]
    require(len(selected) == 1 and len(selected[0]['revisions']) == 1, 'one-early-route-revision')
    return {'service': SERVICE, 'contract': cfg.CONTRACT, 'route': DEPLOYMENT, 'publication': publication,
            'revision': selected[0]['revisions'][0]['revisionId'], 'deploymentGeneration': int(deployed['generation'])}


def bind_routes(client, authority, item, target):
    for mode in ('command', 'query', 'result'):
        name = 'java-early-http-' + mode
        prior = client.call('trigger', 'get', name, codes=(0, 6))['data']
        configuration = {'profile': 'transaction-http-v1', 'scheme': 'http', 'host': authority,
            'path': lifecycle.PATHS[mode], 'pathMatch': 'exact', 'method': 'POST' if mode == 'command' else 'GET',
            'transactionMode': mode, 'namespace': cfg.NAMESPACE, 'incarnation': '1',
            'stateSchema': lifecycle.schema(item), 'companionDigest': item.companion_digest,
            'stateBinding': DEPLOYMENT, 'resultPolicy': cfg.RESULT_POLICY}
        if mode == 'command':
            import base64
            configuration['preconditionKey'] = base64.b64encode(lifecycle.KEY).decode()
        path = client.directory / (name + '.json')
        write_json(path, {'apiVersion': 'latent.dev/v1alpha1', 'kind': 'HttpTrigger',
            'metadata': {'name': name, 'tenant': cfg.TENANT}, 'spec': {'target': dict(target,
                function='query' if mode == 'query' else 'update'), 'configuration': configuration}})
        operation = 'early-trigger-' + mode
        receipt(client.call('trigger', 'apply', path, '--operation-id', operation,
            '--expected-generation', prior['trigger']['generation'] if prior['trigger'] else '0',
            '--expected-state-version', prior['stateVersion']), operation)


def typed_denial(result):
    require(result['disposition'] == 'rejected' and result['effect-ids'] == []
            and decode(http.canonical_base64(result['result']['body-base64'], 131072)) == [{'err': 'rejected'}],
            'actual-early-declared-typed-http-denial')


def execute(client, configuration, path, signed, item, publication, documents, receipts, node):
    campaign = Campaign(client, configuration, path, signed, (item,), {item.name: publication},
                        documents, receipts, None, node, service=SERVICE)
    # The captured URL is fixed at loopback port 1. Reserve its actual TCP
    # listener before execution so any contact remains observable through close.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 1))
        listener.listen(1)
        listener.setblocking(False)
        before, original = campaign.query(0)
        key, body = 'java-early-http-denial', command_input(1)
        result = campaign.result(campaign.socket('command', original_key=key, body=body,
                                                condition=precondition(original)))
        typed_denial(result)
        durable = lifecycle.lookup(client, publication, key)
        rpc_result(durable, result, publication, key)
        replay = campaign.result(campaign.socket('command', original_key=key, body=body,
                                                condition=precondition(original)))
        http.replay(result, replay)
        retained = campaign.original(key)
        http.replay(result, retained)
        after, aggregate = campaign.query(0)
        require(aggregate['key-version'] == original['key-version'] == {'none': None},
                'early-http-denial-cannot-write-business-state')
        node.stop()
        try:
            connection, _address = listener.accept()
        except BlockingIOError:
            contacts = 0
        else:
            connection.close()
            contacts = 1
        require(contacts == 0, 'early-http-denial-has-no-actual-tcp-contact')
    observed = {'original': result, 'durable': durable, 'replayed': replay, 'retained': retained,
                'before': before, 'after': after, 'actualTcpContacts': contacts,
                'postStageRollbackQualified': False}
    client.evidence.passed('signed-early-http-typed-denial', observed)
    return observed
