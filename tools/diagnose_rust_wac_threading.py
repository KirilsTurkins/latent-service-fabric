"""Compare fixed WAC parsers on one retained uncomposed Rust component.

This source-bound diagnostic does not compile, compose the HTTP adapter, sign,
execute a guest or change the normal SDK composer selection.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded_result
from tools.dotnet_guest.internal_io import core_modules
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, decode_json, fresh, inventory, read_file, write_json
from tools.rust_wasi_http_compose import unchanged_interfaces
from tools.rust_wasi_http_profile import names

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
SOURCE = 'cc334f38cc1d01b13d2f1e680c4f446376c9805f'
RUN, JOB, ARTIFACT = 41909345923, 126852445992, 13364298225
ARCHIVE_SIZE = 67756439
ARCHIVE_SHA = '3fc103f34a0605af5368e96d82583a9cf42f6e02ed89deeb9d93edc111c8a89b'
NEW_WAC_SIZE = 22917648
NEW_WAC_SHA = '83259349b630f79a60490322b068e7ad2dba784720b0d467decccc0aecc743b5'
MEMBERS = {
    'rust-http-thread-combined/preview-component.wasm': (941142, '091847d0aa7829a08354997d9fe4bd8755593ad512817e345e1ccaa2353dd976'),
    'rust-http-thread-combined/preview-component-graph.json': (38866, '80f5b7e044ecfbbbed164a5a19b9ae19b0bed36c4c9f6cd0ec8f25fcd5b83115'),
    'rust-http-thread-combined/FAILED.json': (359700, '811cb19502c850ff94de64ba645c7c5603e56cab35cae2a969bb41c6cdf41698'),
    'rust-http-thread-combined/logs/34-rust-http-exact-composition.stderr.txt': (632, '49add1cba66d631ba7a8662e6bc58d008abcbd87114df837db7775d8748aaec3'),
    'rust-http-thread-http/component-composer/wac': (21726840, '250c11762916ba733c7d22b62487580f21270ec9dde4f13460ea69d300e25406'),
}
RECIPE = ('tools/diagnose_rust_wac_threading.py', '.github/workflows/rust-wac-threading-probe.yml',
    'tools/rust_wasi_http_profile.py', 'tools/rust_wasi_http_compose.py',
    'tools/dotnet_guest/internal_io.py', 'tools/build_process.py', 'tools/rust_capsule_project.py')
SCRIPT = b'package lsf:wac-threading-probe;\nlet application = new lsf:application { ... };\nexport application...;\n'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def official_metadata(api):
    run = api('actions/runs/' + str(RUN))
    require(run['id'] == RUN and run['head_sha'] == SOURCE and run['event'] == 'push'
        and run['head_branch'] == 'fix/rust-http-bindgen-20261104'
        and run['path'] == '.github/workflows/rust-http-thread-composition-diagnostic.yml'
        and run['status'] == 'completed' and run['conclusion'] == 'failure'
        and run['run_attempt'] == 1, 'wac-probe-original-run-identity')
    jobs = api('actions/runs/' + str(RUN) + '/jobs')['jobs']
    require(len(jobs) == 1 and jobs[0]['id'] == JOB and jobs[0]['head_sha'] == SOURCE
        and jobs[0]['name'] == 'Capture one unadmitted composed HTTP and ThreadPool graph'
        and jobs[0]['status'] == 'completed' and jobs[0]['conclusion'] == 'failure',
        'wac-probe-original-job-identity')
    artifact = api('actions/artifacts/' + str(ARTIFACT))
    require(artifact['id'] == ARTIFACT and artifact['name'] == 'rust-http-thread-composition-diagnostic-' + SOURCE
        and artifact['size_in_bytes'] == ARCHIVE_SIZE and artifact['digest'] == 'sha256:' + ARCHIVE_SHA
        and artifact['expired'] is False and artifact['workflow_run']['id'] == RUN
        and artifact['workflow_run']['head_sha'] == SOURCE, 'wac-probe-original-artifact-identity')
    return {'run': RUN, 'job': JOB, 'head': SOURCE, 'artifact': ARTIFACT,
        'archiveBytes': ARCHIVE_SIZE, 'archiveSha256': 'sha256:' + ARCHIVE_SHA}


def selected_members(archive):
    require(type(archive) is bytes and len(archive) == ARCHIVE_SIZE and sha(archive) == ARCHIVE_SHA,
        'wac-probe-original-archive-identity')
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        entries = source.infolist(); by_name = {entry.filename: entry for entry in entries}
        require(len(entries) <= 512 and len(by_name) == len(entries), 'wac-probe-original-archive-entries')
        result = {}
        for name, (size, digest) in MEMBERS.items():
            require(name in by_name and by_name[name].file_size == size and not by_name[name].is_dir()
                and not by_name[name].flag_bits & 1, 'wac-probe-original-member-shape')
            data = source.read(by_name[name])  # ZIP reader checks the original CRC.
            require(len(data) == size and sha(data) == digest, 'wac-probe-original-member-identity')
            result[name] = data
    return result


def compare(output: Path, new_wac: Path, expected_head: str):
    require(sys.platform == 'linux' and type(expected_head) is str
        and re.fullmatch(r'[0-9a-f]{40}', expected_head) is not None, 'wac-probe-linux-and-source')
    output = Path(output).absolute(); new_wac = Path(new_wac).resolve(strict=True)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'wac-probe-output-separated')
    require(len(read_file(new_wac, NEW_WAC_SIZE)) == NEW_WAC_SIZE
        and sha(read_file(new_wac, NEW_WAC_SIZE)) == NEW_WAC_SHA, 'wac-probe-new-composer-identity')
    output = fresh(output); (output / 'logs').mkdir()
    record = {'schemaVersion': 'latent.rust.wac-threading-probe.v1', 'status': 'incomplete',
        'sourceCommit': expected_head, 'retainedOriginalRun': RUN, 'fullHttpComposition': False,
        'hostAdmission': False, 'guestExecuted': False, 'runtimeQualification': False,
        'sharedSdkComposerChanged': False, 'attempts': []}
    stage = 'verify-current-source'
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, timeout=20).decode().strip()
    def log(name, argv, env, *, maximum=128*1024, timeout=120):
        result = run_bounded_result([str(x) for x in argv], cwd=output, env=env,
            timeout_seconds=timeout, max_output_bytes=maximum)
        (output / 'logs' / (name + '.stdout.txt')).write_bytes(result.stdout)
        (output / 'logs' / (name + '.stderr.txt')).write_bytes(result.stderr)
        row = {'name': name, 'exitCode': result.returncode,
            'stdout': {'bytes': len(result.stdout), 'sha256': 'sha256:' + sha(result.stdout)},
            'stderr': {'bytes': len(result.stderr), 'sha256': 'sha256:' + sha(result.stderr)}}
        record['attempts'].append(row)
        return result
    try:
        require(git('rev-parse', 'HEAD') == expected_head and not git('status', '--porcelain'),
            'wac-probe-clean-exact-source')
        recipe = {name: file_identity(ROOT / name) for name in RECIPE}
        record['recipe'] = recipe
        require(os.environ.get('GH_TOKEN'), 'wac-probe-official-artifact-token-required')
        gh_env = build_environment(output)
        gh_env.update(GH_TOKEN=os.environ['GH_TOKEN'], GH_PROMPT_DISABLED='1')
        def api(path):
            result = run_bounded_result(['gh', 'api', 'repos/' + REPOSITORY + '/' + path],
                cwd=output, env=gh_env, timeout_seconds=30, max_output_bytes=1024*1024)
            require(result.returncode == 0, 'wac-probe-official-metadata-read')
            return decode_json(result.stdout)
        stage = 'authenticate-original-failed-event'
        record['original'] = official_metadata(api)
        archive = run_bounded_result(['gh', 'api', 'repos/' + REPOSITORY + '/actions/artifacts/' + str(ARTIFACT) + '/zip'],
            cwd=output, env=gh_env, timeout_seconds=180, max_output_bytes=70*1024*1024)
        require(archive.returncode == 0, 'wac-probe-official-artifact-read')
        members = selected_members(archive.stdout)
        failed = decode_json(members['rust-http-thread-combined/FAILED.json'])
        require(failed['stage'] == 'maintained-http-composition-preview'
            and failed['reason'].startswith('rust-http-exact-composition failed')
            and failed['actualApplicationCoreCompiled'] is True
            and failed['httpCompositionIncluded'] is False and failed['actualGuestExecuted'] is False,
            'wac-probe-exact-previous-failure')
        require(b'invalid leading byte (0x2d) for canonical function' in
            members['rust-http-thread-combined/logs/34-rust-http-exact-composition.stderr.txt'],
            'wac-probe-exact-previous-opcode-refusal')
        old_wac = output / 'wac-0.10.1'; old_wac.write_bytes(members['rust-http-thread-http/component-composer/wac']); old_wac.chmod(0o700)
        preview = output / 'preview.wasm'; preview.write_bytes(members['rust-http-thread-combined/preview-component.wasm'])
        original_graph = decode_json(members['rust-http-thread-combined/preview-component-graph.json'])
        script = output / 'identity.wac'; script.write_bytes(SCRIPT)
        deps = output / 'empty-deps'; deps.mkdir()
        env = build_environment(output)
        wasm_tools = shutil.which('wasm-tools', path=env.get('PATH'))
        require(wasm_tools is not None, 'wac-probe-wasm-tools-missing')
        wasm_tools = Path(wasm_tools).resolve(strict=True)
        record['tools'] = {'old': file_identity(old_wac, 'old-wac', 32*1024*1024),
            'new': file_identity(new_wac, 'new-wac', 32*1024*1024),
            'wasm-tools': file_identity(wasm_tools, 'wasm-tools', 256*1024*1024)}
        for label, tool, expected in (('old-version', old_wac, b'wac-cli 0.10.1'),
                                      ('new-version', new_wac, b'wac-cli 0.11.0')):
            result = log(label, (tool, '--version'), env)
            require(result.returncode == 0 and result.stdout.strip() == expected, 'wac-probe-composer-version')
        wasm_version = log('wasm-tools-version', (wasm_tools, '--version'), env)
        require(wasm_version.returncode == 0 and wasm_version.stdout.strip() in
            (b'wasm-tools 1.254.0', b'wasm-tools 1.254.0 (bb58fdf91 2026-07-20)'),
            'wac-probe-wasm-tools-version')
        def verify_inputs():
            require(sha(read_file(preview, MEMBERS['rust-http-thread-combined/preview-component.wasm'][0]))
                    == MEMBERS['rust-http-thread-combined/preview-component.wasm'][1]
                and read_file(script, 65536) == SCRIPT
                and sha(read_file(old_wac, MEMBERS['rust-http-thread-http/component-composer/wac'][0]))
                    == MEMBERS['rust-http-thread-http/component-composer/wac'][1]
                and sha(read_file(new_wac, NEW_WAC_SIZE)) == NEW_WAC_SHA,
                'wac-probe-comparison-input-mutated')
        stage = 'bounded-old-and-new-retained-preview-probes'
        args = ('compose', script, '--deps-dir', deps, '--dep', 'lsf:application=' + str(preview))
        verify_inputs()
        old = log('old-preview', (old_wac, *args, '-o', output / 'old.wasm'), env)
        verify_inputs()
        new = log('new-preview', (new_wac, *args, '-o', output / 'new.wasm'), env)
        verify_inputs()
        record['oldRejectedThreadYieldOpcode'] = (old.returncode != 0 and
            b'invalid leading byte (0x2d) for canonical function' in old.stderr)
        record['newParserExitCode'] = new.returncode
        write_json(output / 'attempts.json', {'attempts': record['attempts'],
            'oldRejectedThreadYieldOpcode': record['oldRejectedThreadYieldOpcode'], 'newParserExitCode': new.returncode})
        require(record['oldRejectedThreadYieldOpcode'] and new.returncode == 0,
            'wac-probe-parser-comparison-not-established')
        composed = read_file(output / 'new.wasm', 16*1024*1024)
        validate = log('new-validate', (wasm_tools, 'validate', '--features', 'all', output / 'new.wasm'), env)
        require(validate.returncode == 0, 'wac-probe-new-component-validation')
        graph = log('new-graph', (wasm_tools, 'component', 'wit', output / 'new.wasm', '--json'), env, maximum=4*1024*1024)
        require(graph.returncode == 0, 'wac-probe-new-component-graph')
        final_graph = decode_json(graph.stdout)
        for direction in ('imports', 'exports'):
            unchanged_interfaces(original_graph, final_graph, names(original_graph, direction), names(final_graph, direction))
        original_cores, new_cores = Counter(core_modules(preview.read_bytes())), Counter(core_modules(composed))
        require(original_cores and not original_cores - new_cores, 'wac-probe-original-core-bytes-changed')
        record.update(oldWacRejectedOpcode=True, newWacIdentityCompositionSucceeded=True,
            unchangedPublicImportsAndExports=True, originalCoreModulesRetained=len(list(original_cores.elements())),
            originalWholeComponentEmbedded=preview.read_bytes() in composed,
            preview={'bytes': preview.stat().st_size, 'sha256': 'sha256:' + sha(preview.read_bytes())},
            composed={'bytes': len(composed), 'sha256': 'sha256:' + sha(composed)})
        require(recipe == {name: file_identity(ROOT / name) for name in RECIPE}
            and git('rev-parse', 'HEAD') == expected_head and not git('status', '--porcelain')
            and sha(read_file(new_wac, NEW_WAC_SIZE)) == NEW_WAC_SHA,
            'wac-probe-source-or-composer-changed')
        record['status'] = 'parser-comparison-passed'
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--new-wac', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    print(compare(args.output, args.new_wac, args.expected_head)['status'])
