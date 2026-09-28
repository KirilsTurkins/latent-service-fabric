#!/usr/bin/env python3
"""Create a container build context from an authenticated, already downloaded release."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.native_runtime import archive, files, verify
from tools.native_runtime.common import InstallError, encode, require

ROOT = Path(__file__).resolve().parents[1]


def prepare(args) -> dict:
    require(sys.platform == 'linux', 'prepare-in-a-linux-workspace')
    output = args.output.absolute()
    require(not output.exists(), 'fresh-container-output-required')
    trust = verify.PublisherTrust(args.publisher_policy.absolute(), args.trusted_root.absolute(), args.verifier.absolute())
    with verify.release(args.release_directory.absolute(), args.version, trust) as authenticated:
        identity = (os.geteuid(), os.getegid())
        files.mkdir(output, 0o700, identity, owners={0, identity[0]})
        release = output / 'release'
        files.mkdir(release, 0o755, identity, owners={0, identity[0]})
        archive.extract(authenticated.archive_fd, release, authenticated.metadata['files'])
        archive.check_tree(release, authenticated.metadata['files'])
        files.create(release / 'release.json', encode(authenticated.metadata), 0o644)
        runtime = output / 'runtime'
        files.mkdir(runtime, 0o755, identity, owners={0, identity[0]})
        modules = runtime / 'native_runtime'
        files.mkdir(modules, 0o755, identity, owners={0, identity[0]})
        # Fixed reviewed helper set; no dependency installation or app sources.
        recipe = []
        paths = [ROOT / 'tools/native_runtime' / (name + '.py')
                 for name in ('__init__', 'common', 'files', 'host', 'verify')]
        paths += [ROOT / 'tools/container_runtime' / name for name in ('entrypoint.py', 'ownership.py', 'probe.py', 'Dockerfile')]
        for source in paths:
            data = files.read(source.absolute(), 262144, owners={0, identity[0]})
            destination = (output if source.name == 'Dockerfile' else
                           runtime if source.name in {'entrypoint.py', 'ownership.py', 'probe.py'} else modules) / source.name
            files.create(destination, data, 0o644)
            recipe.append({'path': source.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(data).hexdigest()})
        files.create(output / '.dockerignore', b'*\n!Dockerfile\n!release/**\n!runtime/**\n', 0o644)
        receipt = {'schemaVersion': 'latent.container-build-inputs.v1', 'version': args.version,
                   'sourceCommit': authenticated.metadata['sourceCommit'],
                   'archive': authenticated.metadata['archive'], 'publisher': authenticated.authentication,
                   'recipe': recipe, 'imageBuilt': False, 'runtimeQualified': False, 'managedPlatformQualified': False}
        files.create(output / 'build-inputs.json', encode(receipt), 0o644)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-directory', required=True, type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--publisher-policy', required=True, type=Path)
    parser.add_argument('--trusted-root', required=True, type=Path)
    parser.add_argument('--verifier', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    try:
        receipt = prepare(parser.parse_args())
        print(encode(receipt).decode(), end='')
        return 0
    except InstallError as error:
        print(str(error), file=sys.stderr)
    except OSError:
        print('inspect-protected-release-and-output-paths', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
