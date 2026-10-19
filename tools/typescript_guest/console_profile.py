"""Declared typed LOG selects a bounded strict console, never an operator grant."""
from tools.typescript_guest import runtime_profile as runtime

PROFILE = 'lsf-console-strict-v1'
INTERFACE = 'latent:log/log@0.1.0'


def selected(imports: list[str]) -> bool:
    return INTERFACE in imports


def configuration(base: dict, graph: dict, world: str, standard: dict) -> dict:
    if {'standardConsoleProfile', 'activationExports'} & base.keys():
        raise ValueError('application-cannot-override-standard-console-backend')
    expected = dict(standard)
    expected['worlds'] = [{'name': 'console', 'package': 0,
                           'imports': {'interface-0': {'interface': {'id': 0}}}, 'exports': {}}]
    if runtime.public_graph(graph, world)['imports'].get(INTERFACE) != runtime.public_graph(
            expected, 'latent:log/console@0.1.0')['imports'][INTERFACE]:
        raise ValueError('standard-console-exact-log-interface-required')
    exports = []

    def camel(name):
        import re
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', name):
            raise ValueError('standard-console-named-export-required')
        return re.sub(r'-([a-z0-9])', lambda match: match[1].upper(), name)

    def function(name, value):
        if value['kind'] not in ('freestanding', 'async-freestanding') or len(value['params']) > 32:
            raise ValueError('standard-console-resource-export-unsupported')
        return {'name': camel(name), 'parameters': len(value['params'])}

    for name, item in runtime.find_world(graph, world)['exports'].items():
        if set(item) == {'function'}:
            exports.append({**function(name, item['function']), 'functions': None})
        elif set(item) == {'interface'}:
            interface = graph['interfaces'][item['interface']['id']]
            exports.append({'name': camel(interface['name']), 'functions': [function(key, value)
                for key, value in interface['functions'].items()]})
        else:
            raise ValueError('standard-console-export-unsupported')
    if not exports or len(exports) > 64:
        raise ValueError('standard-console-export-limit')
    return {**base, 'standardConsoleProfile': PROFILE, 'activationExports': exports}
