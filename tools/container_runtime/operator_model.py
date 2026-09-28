"""Closed headless operator requests and exact operation receipt association."""
import re

from native_runtime.common import require


def members(value, names):
    require(isinstance(value, dict) and set(value) == set(names), 'operator-closed-document-required')


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', value),
            'operator-identifier-required')
    return value


def counter(value):
    require(isinstance(value, str) and re.fullmatch(r'0|[1-9][0-9]{0,19}', value)
            and int(value) < 2 ** 64, 'operator-generation-required')
    return value


def publication(value):
    require(isinstance(value, str) and re.fullmatch(r'publication:sha256:[0-9a-f]{64}', value),
            'operator-publication-required')
    return value


def validate(request, tenant):
    require(isinstance(request, dict), 'operator-request-object-required')
    kind = request.get('kind')
    if kind == 'publish':
        members(request, ('kind', 'id', 'generation', 'package', 'evidence'))
        identifier(request['id']); counter(request['generation'])
        for name in ('package', 'evidence'):
            value = request[name]
            require(isinstance(value, str) and len(value) <= 512
                    and re.fullmatch(r'/work/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+', value)
                    and not any(part in {'.', '..'} for part in value.split('/')), 'operator-input-mount-path')
    elif kind == 'route':
        members(request, ('kind', 'id', 'generation', 'stateVersion', 'manifest'))
        identifier(request['id']); counter(request['generation']); counter(request['stateVersion'])
        manifest = request['manifest']
        members(manifest, ('apiVersion', 'kind', 'metadata', 'spec'))
        members(manifest['metadata'], ('name', 'tenant'))
        require(manifest['apiVersion'] == 'latent.dev/v1alpha1' and manifest['kind'] == 'HttpTrigger'
                and manifest['metadata']['tenant'] == tenant, 'operator-route-tenant')
        identifier(manifest['metadata']['name'])
        members(manifest['spec'], ('target', 'configuration'))
        members(manifest['spec']['target'], ('kind', 'publication'))
        require(manifest['spec']['target']['kind'] == 'static-web', 'operator-static-route-required')
        publication(manifest['spec']['target']['publication'])
        configuration = manifest['spec']['configuration']
        members(configuration, ('profile', 'scheme', 'host', 'path', 'pathMatch', 'method'))
        require(configuration['profile'] == 'static-site-v1' and configuration['method'] in {'GET', 'HEAD'}
                and configuration['scheme'] in {'http', 'https'} and configuration['pathMatch'] in {'exact', 'prefix'},
                'operator-static-route-profile')
        require(all(isinstance(configuration[name], str) and 0 < len(configuration[name]) <= 255
                    for name in ('host', 'path')), 'operator-route-address-bound')
    elif kind in {'web-get', 'trigger-get', 'package-inspect'}:
        members(request, ('kind', 'value'))
        if kind == 'web-get':
            publication(request['value'])
        elif kind == 'trigger-get':
            identifier(request['value'])
        else:
            validate({'kind': 'publish', 'id': 'inspect', 'generation': '0',
                      'package': request['value'], 'evidence': request['value']}, tenant)
    else:
        require(False, 'operator-command-not-supported')
    return request


def receipt_matches(result, request, tenant):
    if not (result.get('category') == 'success' and result.get('outcomeKnown') is True):
        return False
    data = result.get('data', {})
    if request['kind'] == 'publish':
        value = data.get('operation', {})
        return (value.get('operationId') == request['id'] and value.get('expectedGeneration') == request['generation']
                and value.get('publication', {}).get('tenant') == tenant)
    value = data.get('receipt', {})
    manifest = request['manifest']
    return (value.get('operationId') == request['id'] and value.get('tenant') == tenant
            and value.get('triggerId') == manifest['metadata']['name']
            and value.get('action') == 'TRIGGER_OPERATION_ACTION_APPLY'
            and value.get('expectedGeneration') == request['generation']
            and value.get('expectedStateVersion') == request['stateVersion']
            and value.get('target', {}).get('publication') == {
                'id': manifest['spec']['target']['publication'], 'tenant': tenant})
