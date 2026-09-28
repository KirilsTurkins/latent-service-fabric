"""Non-root, foreground container startup with the native host/profile checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_runtime import files, host, verify
from native_runtime.common import InstallError, document, execute, require
from ownership import acquire

RELEASE = Path('/opt/lsf/release')
CONFIG = Path('/etc/lsf/node.json')
DATA = Path('/var/lib/lsf')
CACHE = Path('/var/cache/lsf')
ENVIRONMENT = {'PATH': '/opt/lsf/release/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'HOME': '/var/cache/lsf', 'TMPDIR': '/var/cache/lsf'}


def preflight() -> dict:
    require(os.geteuid() == 10001 and os.getegid() == 10001, 'run-as-uid-and-gid-10001')
    os.umask(0o077)
    observation = host.platform_check()
    metadata = document(files.read(RELEASE / 'release.json', owners={0}))
    verify.manifest(metadata, metadata.get('version'))
    require('developmentTest' not in metadata, 'development-test-binary-is-not-a-runtime-release')
    expected = {item['path']: item for item in metadata['files']}
    for name in ('latent', 'latentd', 'latent-aot-compiler'):
        path = RELEASE / 'bin' / name
        with files.regular(path, owners={0}) as descriptor:
            info = os.fstat(descriptor)
            identity, size = files.digest_fd(descriptor)
            entry = expected['bin/' + name]
            require(info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o755
                    and identity == entry['sha256'] and size == entry['size'],
                    'root-owned-release-executable-identity-mismatch')
        host.dynamic_probe(path)
    node = document(files.read(CONFIG, 65536, owners={0, 10001}, private=True, trusted_gid=10001), 65536)
    require(node.get('dataDirectory') == str(DATA), 'data-directory-must-be-var-lib-lsf')
    require(node.get('supplyChain', {}).get('mode') == 'enforced', 'container-requires-enforced-package-admission')
    grace = node.get('shutdownGraceMillis', 5000)
    require(type(grace) is int and 1 <= grace <= 5000, 'shutdown-grace-must-be-1-to-5000ms')
    profile = node.get('securityProfile')
    require(profile in {'local-experimental-v1', 'external-capsule-v1'}, 'select-explicit-security-profile')
    if profile == 'external-capsule-v1':
        isolated = node.get('isolatedAot', {})
        require(isolated.get('compilerExecutable') == str(RELEASE / 'bin/latent-aot-compiler')
                and isolated.get('compilerDigest') == 'sha256:' + metadata['engine']['compilerSha256']
                and isolated.get('keyFile') == '/etc/lsf/private/native-aot.key'
                and isolated.get('blobRoot') == str(CACHE / 'native-blobs')
                and isolated.get('receiptRoot') == str(CACHE / 'native-receipts'),
                'external-compiler-and-cache-paths-must-match-image-profile')
    for directory in (DATA, CACHE):
        host.filesystem_probe(directory)
    status, output = execute([str(RELEASE / 'bin/latentd'), 'check-config', '--config', str(CONFIG)],
                             timeout=40, maximum=65536, environment=ENVIRONMENT, cwd=str(DATA))
    require(status == 0, 'native-check-config-failed-check-profile-sandbox-and-protected-configuration')
    report = document(output, 65536)
    require(report.get('schemaVersion') == 'latent.standalone.config-check.v1'
            and report.get('profile') == profile and report.get('protectedCredentialFile') is True,
            'native-profile-check-incomplete')
    require(report.get('wasmtimeVersion') == metadata['engine']['wasmtimeVersion']
            and report.get('hostAbiProfile') == metadata['engine']['hostAbiProfile'],
            'native-engine-identity-mismatch')
    if profile == 'external-capsule-v1':
        require(report.get('admission') == 'enforced' and report.get('authenticatedNativeLoading') is True
                and report.get('compilerSandbox') == 'lsf-linux-x86_64-landlock3-seccomp-v1',
                'isolated-compiler-sandbox-not-established')
    return {'schemaVersion': 'latent.container-preflight.v1', 'passed': True,
            'host': observation, 'profile': report, 'version': metadata['version'],
            'sourceCommit': metadata['sourceCommit'], 'managedPlatformQualified': False}


def main() -> int:
    owner = None
    try:
        require(sys.argv[1:] in (['check'], ['serve']), 'expected-check-or-serve')
        if sys.argv[1] == 'serve':
            owner = acquire(DATA, inherit=True)
        result = preflight()
        if sys.argv[1] == 'check':
            print(json.dumps(result, separators=(',', ':')))
            return 0
        # Replace PID 1. Native signal handling owns bounded drain and shutdown;
        # there is no shell supervisor, polling owner or background activation.
        os.chdir(DATA)
        os.execve(RELEASE / 'bin/latentd', [str(RELEASE / 'bin/latentd'), 'serve', '--config', str(CONFIG)], ENVIRONMENT)
    except InstallError as error:
        print(json.dumps({'schemaVersion': 'latent.container-failure.v1', 'stage': 'preflight',
                          'reason': str(error), 'ready': False}), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError):
        print('{"schemaVersion":"latent.container-failure.v1","stage":"preflight","reason":"inspect-release-and-private-mounts","ready":false}', file=sys.stderr)
        return 1
    finally:
        if owner is not None:
            os.close(owner)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
