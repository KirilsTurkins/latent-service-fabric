"""Exact declared RANDOM selects standard noncrypto draws; it grants nothing."""
from tools.typescript_guest import runtime_profile as runtime

PROFILE = 'lsf-math-random-approved-v1'
CLOSED = 'lsf-math-random-unsupported-v1'
INTERFACE = 'latent:random/random@0.1.0'
WORLD = 'lsf:typescript-random-abi/abi@1.0.0'


def selected(imports):
    return INTERFACE in imports


def configuration(base: dict, graph: dict, world: str, standard: dict | None) -> dict:
    if {'standardEntropyProfile', 'standardEntropyBackendDigest'} & base.keys():
        raise ValueError('application-cannot-override-standard-entropy-backend')
    actual = runtime.public_graph(graph, world)['imports']
    if any(name.startswith('latent:random/random@') and name != INTERFACE for name in actual):
        raise ValueError('standard-entropy-exact-random-version-required')
    if INTERFACE in actual:
        if standard is None or actual[INTERFACE] != runtime.public_graph(standard, WORLD)['imports'].get(INTERFACE):
            raise ValueError('standard-entropy-exact-random-interface-required')
        profile = PROFILE
    else:
        if standard is not None:
            raise ValueError('standard-entropy-unselected-contract')
        profile = CLOSED
    return {**base, 'standardEntropyProfile': profile}
