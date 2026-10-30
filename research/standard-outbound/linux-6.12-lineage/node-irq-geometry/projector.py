"""Actual allocating-TU geometry only; original Node/IRQ gates stay closed."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
INPUT_SHA = "d7847246937f8b0385d19ab1de9b74550791f3551b2cc1b6b1c792b45c0fbcb6"
PRIMARY = {'kernel/irq/matrix.c': (13742, '8e3a5f1c2dbfc39cc258f3f9fee9b65c13b494c0a26c7f056c726d338f8a549b'), 'lib/maple_tree.c': (196713, 'd11eba94051ba43ebcf908e10165ba1724681a6e2803db9dc9d931f342feaa3c'), 'mm/percpu.c': (103541, 'b74279d0cd0d8a3b31f26f0892a1bbb718f32812ee8ffb44f3f71199584964e0'), 'mm/percpu-vm.c': (11969, '220a0772b528a11a42de9a1417f43eeb91293435156f69ee7664153949a3645d'), 'mm/percpu-internal.h': (7895, '8c0b90d893cc890832f1846a449121450ec5ba0ccd907905a0161b9cd672a02d'), 'kernel/irq/irqdesc.c': (25422, '3ebc03602452076511e54fd3e0e84a692bcc479fd0c426186ff1900659f89079')}
MATERIAL_PINS = {'geometry.c': (5046, '9f620fcd26c7ab155ab18feb01bd7e179d7e370b6453ade354cd63d5667c3115'), 'geometry.h': (666, '15c93f612b8b12ff43fd063e490b2225577c79bd1fb7cc80285120229a4a2abf')}
ROLES = {'kernel/irq/matrix.c': 1, 'lib/maple_tree.c': 2, 'mm/percpu.c': 3,
    'arch/x86/kernel/apic/vector.c': 4, 'kernel/irq/irqdesc.c': 5, 'kernel/irq/irqdomain.c': 6}
OUTPUTS = {'geometry.c': 'include/linux/lsf-node-irq-geometry.c',
    'geometry.h': 'include/linux/lsf-node-irq-geometry.h'}


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def require(value, reason):
    if not value:
        raise ValueError('node-geometry-' + reason)


def tail(role):
    require(type(role) is int and role in ROLES.values(), 'role')
    return ('\n/* Source-only native geometry; no admission authority. */\n'
        '#define LSF_NODE_GEOMETRY_ROLE ' + str(role) + '\n'
        '#include <linux/lsf-node-irq-geometry.c>\n'
        '#undef LSF_NODE_GEOMETRY_ROLE\n').encode()


def inverse(raw, role):
    suffix = tail(role)
    require(type(raw) is bytes and raw.endswith(suffix), 'inverse-suffix')
    return raw[:-len(suffix)]


def transform(values, primary, materials):
    require(type(values) is dict and len(values) == 457 and
        all(type(n) is str and type(b) is bytes for n, b in values.items()), 'intermediate-set')
    before = {n: identity(b) for n, b in values.items()}
    canonical = (json.dumps(before, sort_keys=True, separators=(',', ':')) + '\n').encode()
    require(hashlib.sha256(canonical).hexdigest() == INPUT_SHA, 'complete457')
    require(type(primary) is dict and set(primary) == set(PRIMARY), 'primary-set')
    require(type(materials) is dict and set(materials) == set(MATERIAL_PINS), 'material-set')
    for source, pins in [(primary, PRIMARY), (materials, MATERIAL_PINS)]:
        for name, pin in pins.items():
            raw = source[name]
            require(type(raw) is bytes and len(raw) == pin[0] and
                hashlib.sha256(raw).hexdigest() == pin[1], 'input-identity')
    require(not (set(OUTPUTS.values()) & set(values)), 'output-collision')
    result = dict(values)
    for name, role in ROLES.items():
        raw = values[name] if name in values else primary[name]
        result[name] = raw + tail(role)
        require(inverse(result[name], role) == raw, 'native-whole-body-inverse')
    for name, output in OUTPUTS.items():
        result[output] = materials[name]
    require(len(result) == 463 and all(result[n] == raw for n, raw in values.items()
        if n not in ROLES), 'only-six-native-appends')
    return result, {'stage': 'node-irq-geometry', 'beforeCount': 457, 'afterCount': 463,
        'prior457': before, 'nativePrimaryBefore': {n: identity(b) for n, b in primary.items()},
        'ordinaryAllocationBodiesExact': True, 'objectExecution': False,
        'nodeFundingQualified': False, 'irqEnabled': False, 'compiledUsefulFit': False,
        'dynamicTopologyObserved': False, 'sharedBootstrapOwnershipQualified': False}
