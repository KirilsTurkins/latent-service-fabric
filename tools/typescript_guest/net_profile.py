"""Finite ordinary TCP Socket selection; declarations and imports grant nothing."""
from tools.typescript_guest import runtime_profile as runtime

PROFILE = 'lsf-node-net-tcp-v1'
INTERFACE = 'latent:network/streams@0.1.0'
DECLARATION = 'sdk/typescript-guest/runtime/net.d.ts'
BACKEND = 'tools/typescript_guest/node_net.mjs'
TRANSPORT = 'tools/typescript_guest/node_net_transport.mjs'
BINDINGS = 'tools/typescript_guest/node_net_bindings.mjs'
RESOLVER = 'tools/typescript_guest/net_builtin.mjs'
WIT = 'wit/platform/network/package.wit'
RECIPE = (BACKEND, TRANSPORT, BINDINGS, RESOLVER, DECLARATION,
          'tools/typescript_guest/net_profile.py', WIT)


def configuration(base, graph, world, standard, *, runtime_profile):
    if any(name.startswith('standardNet') for name in base):
        raise ValueError('application-cannot-override-standard-net-backend')
    if runtime_profile != runtime.IMPORT_PROFILE:
        return dict(base)
    imports = runtime.public_graph(graph, world)['imports']
    if INTERFACE not in imports:
        return dict(base)
    expected = runtime.public_graph(standard, 'latent:network/contract-probe@0.1.0')['imports'][INTERFACE]
    if imports[INTERFACE] != expected:
        raise ValueError('standard-net-exact-stream-interface-required')
    return {**base, 'standardNetProfile': PROFILE}


def selected(observation, identities):
    modules = observation.get('standardNetModules', [])
    fields = {'standardNetProfile', 'standardNetIdentities'}
    if type(modules) is not list or modules not in ([], ['node:net']):
        raise ValueError('typescript-standard-net-module-set')
    if not modules:
        if fields & observation.keys():
            raise ValueError('typescript-unused-standard-net-profile')
        return None
    if (modules != ['node:net'] or observation.get('standardNetProfile') != PROFILE
            or observation.get('standardNetIdentities') != identities):
        raise ValueError('typescript-standard-net-selection-drift')
    return {'schemaVersion': 'latent.typescript.standard-net-selection.v1',
            'profile': PROFILE, 'modules': modules, 'identities': identities,
            'maximumSocketStates': 2, 'maximumPendingOperationsPerSocket': 3,
            'maximumQueuedWriteBytes': 65536, 'maximumQueuedWriteRecords': 16,
            'maximumTransferWindowBytes': 16384,
            'transport': 'tcp', 'tlsApi': False, 'dnsApi': False,
            'listeners': False, 'descriptorNamespace': False,
            'rootRequiresCompletedClose': True, 'automaticCloseDrain': True,
            'closeDrain': 'accepted-terminal-intent-only-v1', 'maximumRootCloseWaiters': 1,
            'pausedEndRead': 'eof-only-unread-data-refuses',
            'physicalRetirement': 'not-inferred', 'authority': 'none', 'qualification': 'unknown'}


def identities(root):
    from tools.rust_capsule_project import digest, read_file
    return {name: digest(read_file(root / path)) for name, path in (
        ('backend', BACKEND), ('transport', TRANSPORT), ('bindings', BINDINGS),
        ('resolver', RESOLVER), ('declaration', DECLARATION), ('interface', WIT))}


def retain_selection(compiled, output, expected):
    import json
    from tools.rust_capsule_project import digest, read_file
    name = 'typescript-net-selection.json'
    path = compiled / name
    if not path.exists():
        return (), []
    raw = read_file(path, 65536)
    value = json.loads(raw)
    normal = selected({'standardNetModules': ['node:net'], 'standardNetProfile': PROFILE,
                       'standardNetIdentities': expected}, expected)
    canonical = lambda item: json.dumps(item, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if canonical(value) != canonical(normal):
        raise ValueError('typescript-standard-net-retained-selection-drift')
    (output / name).write_bytes(raw)
    return ((name, 'asset', 'application/vnd.latent.typescript.net-selection.v1+json'),), [
        {'name': 'typescript-standard-net', 'digest': digest(raw), 'size': len(raw)}]
