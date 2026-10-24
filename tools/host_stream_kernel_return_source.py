"""Bind ordinary VFS/LSM allocation paths before a NEW observation image.

Explicit prepaid constructors never replace these ordinary bodies. The original
factory mutex excludes Root removal during mint's transient permission checks.
This establishes source lifetime premises, not VFS cost or actual execution.
"""
import hashlib
import json
from pathlib import Path

from tools import host_stream_kernel_retirement_observation as observation
from tools.host_stream_kernel_device_security import function

FIXTURE = Path(__file__).parent/'tests/fixtures/host_stream_kernel_return_vfs.json'
FIXTURE_SHA = 'a24ab04858ab5bdc0c280c9192579b13e7340ad9fb13a6092da1e62c73f4a6cf'


def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def fixture():
    raw = FIXTURE.read_bytes()
    observation.require(0 < len(raw) <= 32*1024 and identity(raw)['sha256'] == FIXTURE_SHA,
        'return-vfs-fixed-fixture')
    value = json.loads(raw)
    observation.require(value['schemaVersion'] == 'lsf.kernel-return-vfs-lifetime-source.v1'
        and value['upstreamCommit'] == '7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e',
        'return-vfs-original-origin')
    return value


def body_identities(compiled):
    """Check ACTUAL derived functions, including unmodified ordinary allocators."""
    value, result = fixture(), {}
    for name,items in value['bodies'].items():
        text = compiled[name].decode()
        result[name] = {}
        for prefix,bound in items.items():
            actual = function(text,prefix).encode()
            observation.require(identity(actual)['sha256'] == bound['sha256']
                and actual == bound['text'].encode(), 'return-vfs-ordinary-body-mutated')
            result[name][prefix] = identity(actual)
    return result


def ordinary_bodies(compiled):
    result, value = body_identities(compiled), fixture()
    # No added hook is permitted on the always-enabled capability component.
    raw = compiled['security/commoncap.c']
    observation.require(identity(raw) == value['originals']['security/commoncap.c'],
        'return-vfs-capability-hooks-mutated')
    # Function bodies alone would not bind registration of the active hooks.
    # Preserve the actual SELinux table too, including its config predicates.
    raw = compiled['security/selinux/hooks.c']
    table = value['selinuxHookRegistration']
    prefix = table['prefix'].encode()
    observation.require(raw.count(prefix) == 1, 'return-vfs-hook-table-occurrence')
    start = raw.index(prefix)
    end = raw.find(b'\n};',start)
    observation.require(end >= start and identity(raw[start:end+3]) ==
        {name:table[name] for name in ('bytes','sha256')}, 'return-vfs-hook-table-mutated')
    return result


def authenticate(originals, compiled, config):
    value = fixture()
    observation.require(all(identity(originals[name]) == expected
        for name,expected in value['originals'].items()), 'return-vfs-whole-originals')
    observation.require(identity(config) == value['configuration'], 'return-vfs-active-hook-config')
    bodies = ordinary_bodies(compiled)
    return {'originals':value['originals'],'compiledOrdinaryBodies':bodies,
        'compiledSelinuxHookRegistration':value['selinuxHookRegistration'],
        'configuration':identity(config),'explicitPrepaidContextRequired':True,
        'ordinaryObjectsOutsideBankSourceClosure':True,'contextInodeReferenceRetained':False,
        'fullVfsLsmCostsQualified':False,'actualMintExecuted':False}


def compose(normal, projected):
    """The historical whole preimages MUST match; no old image is relabelled."""
    result = observation.transform(projected)
    delta = {name for name in result if result[name] != projected.get(name)}
    observation.require(delta == {'net/factory.c','net/factory-cleanup-root-final-free.c',
        observation.FRAGMENT}, 'return-vfs-exact-three-new-files')
    return result, {'parentDerived':{name:identity(raw) for name,raw in projected.items()},
        'normalDerived':{name:identity(raw) for name,raw in normal.items()},
        'derived':{name:identity(raw) for name,raw in result.items()},'newDerivedDelta':sorted(delta),
        'freshKernelRequired':True,'historicalImageReused':False}
