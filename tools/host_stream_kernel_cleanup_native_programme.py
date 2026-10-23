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


def compose(base, originals, config):
    parent = prior.compose(base, originals, config)
    result = change.transform(parent, {})
    require(len(parent) == 322 and len(result) == 323 and
        sum(parent.get(name) != raw for name, raw in result.items()) == 6,
        'cleanup-native-exact-six-source-delta')
    return result


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
