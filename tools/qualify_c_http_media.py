"""Re-sign one retained libfetch guest and check its exact POST media type.

The original C compiler and guest remain attributed to their earlier owner.
This bounded follow-up builds neither a host nor a guest and does not grant
new network authority or claim the wider C HTTP/runtime qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_http_media_node as node
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
ORIGINAL_HEAD = '38c4d59a2669a4d193f9cb8e321f6beae8552648'
ORIGINAL_RUN, ORIGINAL_JOB, ORIGINAL_ARTIFACT = 41815463734, 126524955334, 13315485021
ARCHIVE_BYTES = 2042308
ARCHIVE_SHA = '111163fca632f9f073ab5d5edcc3581e8635d68ac329d3071a61809d4b7fd890'
COMPONENT_SHA = '5b6cde622f43d7e71472a7841aef7cf4afc2fc459575bf3be6276bfb06d3f6c1'
QUALIFIED_SHA = 'c66835ee481d053bba05468ff2e804cc0fb6a877f6418b74a7e413e0275294ff'
MARKER_SHA = 'b66866268420e008c35a878beb66b2b79aaa6e064778bbeb189e76e55beec117'
CAPSULE_SHA = '704d64282f015ab61202ec9475218642e6c08b96a7013b61e0433024c6e092ab'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def official_metadata(api):
    run = api('actions/runs/' + str(ORIGINAL_RUN))
    require(run['id'] == ORIGINAL_RUN and run['head_sha'] == ORIGINAL_HEAD
            and run['head_branch'] == 'feat/sdk-690-c-http-post-20261031'
            and run['event'] == 'push' and run['run_attempt'] == 1
            and run['path'] == '.github/workflows/c-http-post-companion.yml'
            and run['status'] == 'completed' and run['conclusion'] == 'success',
            'c-media-original-run-identity')
    jobs = api('actions/runs/' + str(ORIGINAL_RUN) + '/jobs?per_page=100')['jobs']
    require(len(jobs) == 1 and jobs[0]['id'] == ORIGINAL_JOB
            and jobs[0]['name'] == 'Four signed ordinary C POST and cancellation cells'
            and jobs[0]['status'] == 'completed' and jobs[0]['conclusion'] == 'success',
            'c-media-original-job-identity')
    artifact = api('actions/artifacts/' + str(ORIGINAL_ARTIFACT))
    require(artifact['id'] == ORIGINAL_ARTIFACT and artifact['name'] == 'c-http-post-' + str(ORIGINAL_RUN)
            and artifact['size_in_bytes'] == ARCHIVE_BYTES and artifact['digest'] == 'sha256:' + ARCHIVE_SHA
            and artifact['expired'] is False and artifact['workflow_run']['id'] == ORIGINAL_RUN
            and artifact['workflow_run']['head_sha'] == ORIGINAL_HEAD, 'c-media-original-artifact-identity')
    return {'run': ORIGINAL_RUN, 'job': ORIGINAL_JOB, 'head': ORIGINAL_HEAD,
            'artifact': ORIGINAL_ARTIFACT, 'archiveSha256': 'sha256:' + ARCHIVE_SHA}


def restore_build(archive: bytes, destination: Path):
    require(type(archive) is bytes and len(archive) == ARCHIVE_BYTES and sha(archive) == ARCHIVE_SHA,
            'c-media-original-archive-identity')
    destination = fresh(destination)
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        entries = source.infolist()
        names = [entry.filename for entry in entries]
        require(len(entries) == 474 and len(set(names)) == len(names)
                and sum(entry.file_size for entry in entries) <= 8 * 1024**2,
                'c-media-original-archive-entries')
        require(source.testzip() is None, 'c-media-original-archive-crc')
        qualified = source.read('qualified.json')
        require(sha(qualified) == QUALIFIED_SHA, 'c-media-original-result-identity')
        original = json.loads(qualified)
        require(original['status'] == 'passed' and original['source']['head'] == ORIGINAL_HEAD
                and original['node']['status'] == 'passed'
                and [row['case'] for row in original['node']['cases']]
                    == ['post-echo', 'post-uncertain', 'post-cancel', 'fresh-get'],
                'c-media-original-four-outcomes')
        selected = [entry for entry in entries if entry.filename.startswith('build/') and not entry.is_dir()]
        require(len(selected) == 110 and sum(entry.file_size for entry in selected) == 4472333,
                'c-media-original-build-inventory')
        rows = {}
        for entry in selected:
            relative = entry.filename.removeprefix('build/')
            path = PurePosixPath(relative)
            require(relative and '\\' not in relative and not path.is_absolute()
                    and all(part not in ('', '.', '..') for part in relative.split('/'))
                    and path.as_posix() == relative and len(relative) <= 256
                    and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                    and not entry.flag_bits & 1 and 0 <= entry.file_size <= 4 * 1024**2,
                    'c-media-original-build-path')
            data = source.read(entry)
            require(len(data) == entry.file_size, 'c-media-original-build-size')
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            rows[relative] = {'bytes': len(data), 'sha256': 'sha256:' + sha(data)}
    require(rows['component.wasm'] == {'bytes': 116877, 'sha256': 'sha256:' + COMPONENT_SHA}
            and rows['BUILD-COMPLETE.json']['sha256'] == 'sha256:' + MARKER_SHA
            and rows['capsule.json']['sha256'] == 'sha256:' + CAPSULE_SHA,
            'c-media-original-component-and-build-markers')
    return rows


def unchanged_build(directory: Path, expected: dict):
    actual = {}
    for path in sorted(directory.rglob('*')):
        require(not path.is_symlink(), 'c-media-retained-build-symlink')
        if path.is_file():
            actual[path.relative_to(directory).as_posix()] = file_identity(path, 4 * 1024**2)
    require(actual == expected, 'c-media-retained-build-mutated')


def current_materials(native_directory: Path):
    rows = read_json(native_directory / 'native-products.json')['materials']
    require(type(rows) is dict and len(rows) == 135, 'c-media-native-material-count')
    for name, expected in rows.items():
        require(type(name) is str and '\\' not in name, 'c-media-native-material-path')
        path = PurePosixPath(name)
        require(not path.is_absolute() and path.as_posix() == name
                and all(part not in ('', '.', '..') for part in name.split('/')),
                'c-media-native-material-path')
        value = ROOT.joinpath(*path.parts)
        require(not value.is_symlink() and all(not ROOT.joinpath(*path.parts[:i]).is_symlink()
                for i in range(1, len(path.parts))) and file_identity(value) == expected,
                'c-media-native-material-drift')
    return rows


def qualify(native_directory: Path, output: Path, *, expected_head: str):
    from tools import wasmtime_48_0_8_678b_native_products as products
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-media-unprivileged-linux-python313')
    require(type(expected_head) is str and len(expected_head) == 40
            and all(char in '0123456789abcdef' for char in expected_head), 'c-media-exact-source')
    native_directory = Path(native_directory).resolve(strict=True)
    output = Path(output).absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
            and output != native_directory and output not in native_directory.parents
            and native_directory not in output.parents, 'c-media-separated-inputs')
    output = fresh(output)
    record = {'schemaVersion': 'latent.c.http-media.qualification.v1', 'status': 'incomplete',
              'sourceCommit': expected_head, 'guestRecompiled': False, 'hostRecompiled': False,
              'originalComponentSource': ORIGINAL_HEAD, 'full690Qualified': False}
    stage = 'authenticate-current-source-and-native'
    try:
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=ROOT, timeout=20).decode().strip()
        require(git('rev-parse', 'HEAD') == expected_head and not git('status', '--porcelain'),
                'c-media-clean-exact-source')
        receipt = products.verify_prepared(native_directory)
        native = products.native_products(native_directory)
        require(set(native) == {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'},
                'c-media-exact-five-native-products')
        for path in native.values():
            path.chmod(0o700)
        current_native = source_identity(ROOT)
        require(current_native == git_source_identity(products.SOURCE), 'c-media-current-native-source')
        materials = current_materials(native_directory)
        selected = ('tools/qualify_c_http_media.py', 'tools/c_http_media_node.py',
                    'tools/c_http_media_peer.py', 'tools/c_http_post_companion.py',
                    'tools/c_thread_runtime_node.py', 'tools/standard_http/peer.py',
                    'tools/standard_http/protocol.py', 'tools/standard_http/vectors.py',
                    'tools/standard_http/observations.py', 'tools/phase3_resource_identity.py',
                    'tools/wasmtime_48_0_8_678b_native_products.py',
                    'tools/sdk_native_products_reader.py', 'tools/java_replay_materials.py',
                    '.github/workflows/c-http-media.yml')
        recipe = {name: file_identity(ROOT / name) for name in selected}
        record.update(nativeSource=current_native, nativeProducts=receipt, recipe=recipe)
        token = os.environ.get('GH_TOKEN')
        require(bool(token), 'c-media-artifact-token-required')
        environment = build_environment(output)
        environment.update(GH_TOKEN=token, GH_PROMPT_DISABLED='1')
        def api(path):
            result = run_bounded_result(['gh', 'api', 'repos/' + REPOSITORY + '/' + path],
                cwd=output, env=environment, timeout_seconds=30, max_output_bytes=1024*1024)
            require(result.returncode == 0, 'c-media-official-metadata-read')
            return json.loads(result.stdout)
        stage = 'authenticate-retained-original-build'
        record['original'] = official_metadata(api)
        fetched = run_bounded_result(['gh', 'api', 'repos/' + REPOSITORY + '/actions/artifacts/'
                                      + str(ORIGINAL_ARTIFACT) + '/zip'], cwd=output, env=environment,
                                     timeout_seconds=120, max_output_bytes=ARCHIVE_BYTES + 1)
        require(fetched.returncode == 0, 'c-media-original-artifact-read')
        retained = output / 'retained-build'
        build_rows = restore_build(fetched.stdout, retained)
        record['originalBuild'] = {'files': len(build_rows), 'component': build_rows['component.wasm']}
        stage = 'one-signed-original-post'
        observed = node.run(retained, native, output / 'node')
        require(observed['status'] == 'passed' and observed['media']['exactMatch'] is True,
                'c-media-signed-observation')
        unchanged_build(retained, build_rows)
        require(products.verify_prepared(native_directory) == receipt
                and current_materials(native_directory) == materials
                and source_identity(ROOT) == current_native
                and recipe == {name: file_identity(ROOT / name) for name in selected}
                and git('rev-parse', 'HEAD') == expected_head and not git('status', '--porcelain'),
                'c-media-final-source-and-native-identities')
        record.update(status='passed', nodeReceipt=file_identity(output / 'node/qualified.json'))
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    print(qualify(args.native, args.output, expected_head=args.expected_head)['status'])
