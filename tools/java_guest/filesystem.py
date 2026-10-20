"""Authenticate the maintained C filesystem owner before its closed Java port."""
from pathlib import Path

from tools.rust_capsule_project import digest, read_file, read_json

PROFILE = 'java-closed-filesystem-v1'
PREIMAGES = (
    {'path': 'org/teavm/teavm-core/0.15.0/teavm-core-0.15.0.jar',
     'sha256': '501ca5eae7a835cd6278c822685f32800fa0818e3f42204afc9b558408c943df',
     'size': 2956367, 'platform': 'any'},
    {'path': 'org/teavm/teavm-classlib/0.15.0/teavm-classlib-0.15.0.jar',
     'sha256': '7d805be4670a892a34c89d9d750a8afd65e2f8201b7b3a10343634ea19d1c410',
     'size': 17718996, 'platform': 'any'},
)
SOURCE = 'facilities/compiler/dev/latent/guest/facilities/compiler/ClosedFilesystemPlugin.java'


def stage(sdk: Path) -> dict:
    artifacts = read_json(sdk / 'feasibility/dependencies.lock.json')['artifacts']
    for expected in PREIMAGES:
        if [row for row in artifacts if row.get('path') == expected['path']] != [expected]:
            raise ValueError('java-closed-filesystem-preimage-drift')
    return {'profile': PROFILE, 'originalArtifacts': list(PREIMAGES),
        'sourceDigest': digest(read_file(sdk / SOURCE)),
        'owner': 'org.teavm.backend.c.runtime.fs.CFileSystem',
        'refusedMethods': ['getUserDir', 'getFile'], 'targetIsWindows': False,
        'publicIoWrappersReplaced': False, 'resourceStreamsChanged': False,
        'filesystemImportsAdded': False, 'writableScratchImplemented': False,
        'componentExecutionQualifiedByThisRecord': False}
