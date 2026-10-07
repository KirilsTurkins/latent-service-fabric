"""Source-owned scoped clock globals, distinct from frozen-clock upstream stubs."""
from __future__ import annotations
import hashlib
from tools.typescript_guest.activation_engine import identity, replace_once

CLOCK_WIT_SHA256 = 'a009ecd4ad23d581523fe97b66327ebe352ac27c9c72d4e09ecc9bb003c466ea'
INSTALL_PREIMAGE = '5505f41a11079e4668ffb0aeb1718a0fb840674f585a4ba1ff39d4d27ae60bf0'
GENERATED = {
    'clocks.c': '973e0fcc381ae69f8ea41f9c57505fd977d87635b4dd4107453c5f7cb61821b7',
    'clocks.h': '52d7686d2fa5d770fd55a691081f4d758adaf62a6270a1f6439daeda1225b4ae',
    'clocks_component_type.o': '0f6d19fba71434d0e72b7a55deb9e94308e951c187a2742ced57199fd4145865',
}
CLOCK_PROFILE = 'spidermonkey-activation-promises-clocks-v1'
CLOCK_INTERFACES = ('latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0')
CLOCK_NATIVE_SOURCES = ('native_clock_engine.cpp', 'native_clocks.h', 'clock_values.h', 'clock_globals.js')


def derive_clock_source(install_source: bytes, globals_source: bytes,
                        clock_wit: bytes, generated: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    if hashlib.sha256(install_source).hexdigest() != INSTALL_PREIMAGE:
        raise ValueError('unreviewed-original-builtin-install-source')
    if hashlib.sha256(clock_wit).hexdigest() != CLOCK_WIT_SHA256:
        raise ValueError('unreviewed-maintained-clock-interface')
    if set(generated) != set(GENERATED):
        raise ValueError('exact-generated-clock-ABI-required')
    for name, expected in GENERATED.items():
        if hashlib.sha256(generated[name]).hexdigest() != expected:
            raise ValueError('unreviewed-generated-clock-ABI:'+name)
    if b')LSF_CLOCK_SOURCE"' in globals_source or b'\0' in globals_source:
        raise ValueError('invalid-clock-source-literal')
    source = replace_once(install_source, b'#include "extension-api.h"\n',
        b'#include "extension-api.h"\n#include "native_clocks.h"\n', 'owned-clock-install-header')
    source = replace_once(source, b'  return true;\n',
        b'  return lsf::typescript::activation::install_clock_globals(engine->cx(), engine->global());\n',
        'source-clock-module-before-application-evaluation')
    result = {'StarlingMonkey/builtins/install_builtins.cpp':source,
              'lsf/clock_globals.inc':b'R"LSF_CLOCK_SOURCE(\n'+globals_source+b')LSF_CLOCK_SOURCE"\n'}
    result.update({'lsf/'+name:raw for name,raw in generated.items()})
    receipt = {'format':'latent.typescript.native-clock-source-derivation.v1',
        'originalInstallSha256':INSTALL_PREIMAGE,'maintainedClockWitSha256':CLOCK_WIT_SHA256,
        'globalsSourceSha256':hashlib.sha256(globals_source).hexdigest(),
        'generatedActualWitBindgen062':identity(generated),'derivedSource':identity(result),
        'supportedOperations':['Date.now','Date()','new Date()','performance.now','performance.timeOrigin'],
        'explicitDateArgumentsPreserveOriginalConstructor':True,
        'clockSource':'separately-installed-granted-latent-clock-0.1.0',
        'ambientClockPermissionAdded':False,'snapshotClockObservation':'denied',
        'performanceOrigin':'lazy-first-read-per-fresh-Store; no compiler-time origin',
        'supportedAsyncProfile':False,'signedLSFComponentQualified':False}
    return result,receipt


def extend_selected_engine_source(base_source: dict[str, bytes], native_clock: dict[str, bytes],
                                  clock_wit: bytes, generated: dict[str, bytes]) -> tuple[dict[str, bytes], dict]:
    """Make a distinct unqualified named source selection; mutate no carrier.

    The existing activation interface and original app contract stay unchanged.
    Clock interfaces must be declared, installed and granted independently.
    This source helper does not execute a compiler, install providers or certify
    the resulting module/profile as available.
    """
    if set(native_clock) != set(CLOCK_NATIVE_SOURCES):
        raise ValueError('exact-private-clock-native-source-selection-required')
    before = identity(base_source)
    identity(native_clock)
    install_path = 'StarlingMonkey/builtins/install_builtins.cpp'
    if install_path not in base_source or any('lsf/'+name in base_source for name in (*CLOCK_NATIVE_SOURCES, *GENERATED)):
        raise ValueError('unreviewed-or-already-extended-clock-engine-source')
    selected, receipt = derive_clock_source(base_source[install_path], native_clock['clock_globals.js'], clock_wit, generated)
    result = dict(base_source)
    result.update(selected)
    result.update({'lsf/'+name:raw for name,raw in native_clock.items()})
    receipt.update(profile=CLOCK_PROFILE, originalSelectedEngineSource=before,
        derivedCompleteSource=identity(result), requestedClockInterfaces=list(CLOCK_INTERFACES),
        compilerSourceFilesToAdd=['lsf/native_clock_engine.cpp','lsf/clocks.c'],
        compilerMetadataObjectToAdd='lsf/clocks_component_type.o',
        existingPromiseTimerAndLifecycleSourceChanged=False,
        originalSynchronousCompilerSelectionChanged=False, clockAuthorityGranted=False,
        qualification='unknown', supportedAsyncProfile=False, signedLSFComponentQualified=False)
    return result, receipt
