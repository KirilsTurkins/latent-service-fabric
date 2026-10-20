"""Synthetic port seam for tests which already mock the entire NativeAOT compiler."""
from types import SimpleNamespace

from tools.build_observation import file_identity
from tools.dotnet_guest import closed_filesystem
from tools.rust_capsule_project import digest, write_json


def prepare(sdk, tools, packages, dotnet, project, output, evidence, run, *, task_wait_port=None, protect_inputs=None):
    # These existing compiler fixtures model synchronous roots. Real derivation,
    # intermediate ownership and ILC binding have separate port controls.
    if task_wait_port is not None:
        raise AssertionError('synthetic-filesystem-fixture-requires-synchronous-root')
    directory = output / 'synthetic-filesystem-port'
    directory.mkdir()
    assembly = directory / 'System.Private.CoreLib.dll'
    assembly.write_bytes(b'synthetic closed filesystem compiler seam')
    identity = file_identity(assembly, 'closed-filesystem-derived-corelib')
    record = {'profile': closed_filesystem.PROFILE, 'frameworkInput': {'digest': digest(b'synthetic original')},
        'base': {'digest': digest(b'synthetic original')}, 'derived': identity, 'sourceCaptureDigest': digest(b'synthetic source'),
        'targetsDigest': digest(b'synthetic targets'), 'taskWaitIntermediate': None,
        'originalMethodBodies': closed_filesystem.METHODS, 'modifiedOriginalMethods': 2, 'unchangedBaseMethods': 44744,
        'otherBaseBodiesUnchanged': True, 'publicWrappersUnchanged': True, 'newHostImports': 0,
        'filesystemAuthority': False, 'nativeAotReferenceBinding': {'fixture': 'synthetic-no-native-execution'}}
    def recheck():
        if file_identity(assembly, 'closed-filesystem-derived-corelib') != identity:
            raise ValueError('synthetic-filesystem-derived-drift')
    def finish(actual_project, actual_evidence):
        if actual_project != project or actual_evidence != evidence:
            raise AssertionError('synthetic-filesystem-fixture-owned-output')
        recheck()
        write_json(evidence / 'closed-filesystem-port.json', record)
        return record
    if protect_inputs is not None:
        protect_inputs(assembly)
    return SimpleNamespace(identity=identity, recheck=recheck, finish=finish)
