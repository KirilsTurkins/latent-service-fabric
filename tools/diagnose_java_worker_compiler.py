"""Trace the fixed public worker fixture's compiler refusal; never qualify a guest.

This diagnostic changes only the generated finder's stderr observations. It does
not remove, catch or approve any compiler refusal. The ordinary qualifier remains
the authority for the component and signed execution.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_java_fibers, qualify_java_published_workers
from tools.java_guest import coroutine_patch
from tools.rust_capsule_project import ROOT, read_file, write_json

FIXTURE_SHA256 = '7b1716af2f7b4075068c476c9d84730b4733e1275903ea8acd50e62af5e6ecf2'


def diagnostic_source(raw: bytes) -> bytes:
    """Add observations, with exact preimages, without changing the verdict."""
    text = raw.decode('utf-8')
    changes = (
        ('    private IllegalStateException checkpointRefusal(String reason) {',
         '    private IllegalStateException checkpointRefusal(String reason) {\n'
         '        new Exception("fixed-public-worker-compiler-site").printStackTrace();'),
        ('            if (method == null || node == null) {',
         '            if (method == null || node == null) {\n'
         '                System.err.println("fixed-public-worker-missing " + reference\n'
         '                        + " declaration=" + (method != null) + " node=" + (node != null));'),
        ('                    throw checkpointRefusal("java-checkpoint-unresolved-741");\n'
         '                }\n                continue;\n            }\n'
         '            if (progressRuntimeClassIdentity(cls.getName()) != null',
         '                    System.err.println("fixed-public-worker-missing-root " + reference);\n'
         '                    throw checkpointRefusal("java-checkpoint-unresolved-741");\n'
         '                }\n                continue;\n            }\n'
         '            if (progressRuntimeClassIdentity(cls.getName()) != null'),
        ('    private IllegalStateException progressNativeRefusal(ClassReader owner, MethodReader method) {',
         '    private IllegalStateException progressNativeRefusal(ClassReader owner, MethodReader method) {\n'
         '        System.err.println("fixed-public-worker-native " + method.getReference());'),
    )
    for before, after in changes:
        if text.count(before) != 1:
            raise ValueError('public-worker-diagnostic-preimage')
        text = text.replace(before, after)
    return text.encode('utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--wasi-sdk', required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or output == ROOT or ROOT in output.parents:
        raise ValueError('public-worker-diagnostic-fresh-external-output')
    fixture = ROOT / 'sdk/java-guest/fibers/conformance/worker-libraries/Capsule.java'
    if hashlib.sha256(read_file(fixture)).hexdigest() != FIXTURE_SHA256:
        raise ValueError('public-worker-diagnostic-fixed-fixture')
    output.mkdir()
    prepared = output / 'build'
    retained = output / 'retained'
    retained.mkdir()
    original = coroutine_patch.corrected_async_source
    report = {'schemaVersion': 'latent.java.worker-compiler-diagnostic.v1',
        'status': 'started', 'productionQualification': False,
        'componentExecutionPerformed': False, 'guestExecutionPerformed': False,
        'fixtureSha256': FIXTURE_SHA256,
        'diagnosticSourceSha256': hashlib.sha256(read_file(Path(__file__))).hexdigest()}

    def observed(raw):
        production = original(raw)
        selected = diagnostic_source(production)
        (retained / 'AsyncMethodFinder.java').write_bytes(selected)
        report['productionFinderSha256'] = hashlib.sha256(production).hexdigest()
        report['diagnosticFinderSha256'] = hashlib.sha256(selected).hexdigest()
        return selected

    coroutine_patch.corrected_async_source = observed
    try:
        qualify_java_fibers.prepare(prepared, args.wasi_sdk, fixture='worker-libraries')
        report['status'] = 'diagnostic-component-built-not-qualified'
    except Exception:
        report['status'] = 'compiler-refused'
        raise
    finally:
        coroutine_patch.corrected_async_source = original
        try:
            report['retained'] = qualify_java_published_workers.retain(prepared, retained)
        finally:
            write_json(retained / 'diagnostic.json', report)


if __name__ == '__main__':
    main()
