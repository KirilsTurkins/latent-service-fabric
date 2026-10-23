"""Manifest-bound native FD source composition for the isolated VM owner.

This module runs no compiler/kernel/VM. Production consumer remains NULL.
"""
from pathlib import Path
import hashlib
from tools import host_stream_kernel_cleanup_constructor_programme as prior
from tools import host_stream_kernel_cleanup_native as change

ROOT = prior.ROOT
baseline = prior.baseline
require = prior.require
baseline_source = prior.baseline_source
source_names = prior.source_names
source_fixture_configuration = prior.source_fixture_configuration


def repair_sidcache(outputs):
    """Remove only the byte-identical application block cloned with Root drain.

    The historical cleanup transform copied from the first cache-size #if,
    including the original callbacks before the device-specific detach block.
    Keep frozen historical derivations intact; repair their exact final output
    here without changing the ordinary, PCI or Root retirement bodies.
    """
    name = 'security/selinux/ss/lsf_sidcache_private.c'
    raw = outputs[name]
    require(len(raw) == 7701 and hashlib.sha256(raw).hexdigest() ==
        'cf50d5c92b204410d2239b220873cf7df81f438f3953f4bf7f03cdce993d695f',
        'cleanup-native-sidcache-duplicate-preimage')
    text = raw.decode()
    ordinary = (change.OWNED/'sidcache-private.c').read_text()
    ordinary = ordinary[ordinary.index('#if CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE > 0\n'):]
    require(text.count(ordinary) == 2, 'cleanup-native-two-identical-sidcache-blocks')
    duplicate = text.rindex(ordinary)
    repaired = text[:duplicate] + text[duplicate+len(ordinary):]
    for symbol in ('lsf_prepaid_sidcache_callback', 'lsf_prepaid_sidcache_retire',
            'lsf_prepaid_sidcache_destroy'):
        require(repaired.count('static ' + ('bool ' if symbol.endswith('destroy') else 'void ') +
            symbol + '(') == 1, 'cleanup-native-single-sidcache-callback')
    for symbol in ('lsf_prepaid_sidcache_detach', 'lsf_prepaid_device_sidcache_detach',
            'lsf_prepaid_cleanup_sidcache_detach'):
        require(repaired.count('void ' + symbol + '(') == 2,
            'cleanup-native-both-sidcache-profile-branches')
    result = dict(outputs)
    result[name] = repaired.encode()
    return result


def compose(base, originals, config):
    parent = prior.compose(base, originals, config)
    result = change.transform(parent, {})
    require(len(parent) == 322 and len(result) == 323 and
        sum(parent.get(name) != raw for name, raw in result.items()) == 6,
        'cleanup-native-exact-six-source-delta')
    return repair_sidcache(result)


def qualification_projection(outputs, config):
    # Preserve the complete selected config byte-for-byte here. A VM owner may
    # need additional boot options only as a separately reviewed explicit diff.
    require(type(config) is bytes and b'CONFIG_HZ=1000\n' in config and
        b'CONFIG_X86_64=y\n' in config and b'CONFIG_NR_CPUS=64\n' in config,
        'cleanup-native-selected-configuration')
    projected = change.qualification_projection(outputs)
    def identity(raw):
        return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    name = 'net/factory-private.h'
    proof = dict(schemaVersion='lsf.kernel-cleanup-native-candidate-projection.v1',
        sourceDifference={name:dict(preimage=identity(outputs[name]), postimage=identity(projected[name]))},
        configuration=identity(config), configurationDifference={},
        normalConstructorPredicate=0, candidateConstructorPredicate=1,
        productionSocketConsumerSelected=False, finalFreeCertificate=False,
        completeAllocationClosure=False, productionInstallation=False)
    return projected, proof


def local_freeze():
    result = prior.local_freeze()
    for path in (Path(__file__), Path(change.__file__), change.FIXTURE,
            change.OWNED/'factory-cleanup-native-bootstrap.c'):
        result[path.relative_to(ROOT).as_posix()] = baseline.objects.identity(path)
    return result
