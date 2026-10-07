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
