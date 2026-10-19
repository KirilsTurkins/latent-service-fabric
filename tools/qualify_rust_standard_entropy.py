"""Explicit captured ordinary Rust entropy on an enforced signed node."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_standard_sysroot_build as std, rust_standard_entropy_fixture as fixture
from tools import rust_standard_logging_inputs as standard
from tools.build_observation import build_environment, resolve_tools
from tools.dev_workflow.common import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_git_components import prepared_inputs, PRODUCTS, COMPANIONS
from tools.qualify_rust_standard_clocks import source_archive
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands, build
from tools.rust_capsule_project import ROOT, create, digest, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = ('tools/qualify_rust_standard_entropy.py', 'tools/rust_standard_entropy_fixture.py',
             'tools/rust_standard_entropy_probe.py', 'tools/rust_standard_entropy_profile.py',
             'tools/qualify_rust_git_components.py', 'tools/qualify_rust_standard_clocks.py',
             'tools/qualify_rust_standard_clock.py', 'tools/qualify_rust_capsules.py',
             'tools/run_rust_capsule_workflow.py', *standard.RECIPE)


def companions(prepared, qualified):
    result = {}
    for name in COMPANIONS:
        directory = prepared / 'builds' / name
        marker = read_json(directory / 'BUILD-COMPLETE.json')
        require(marker == qualified['builds'][name], 'rust-stdio-original-companion-marker')
        for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
                                 ('build-observation.json', 'observationDigest')):
            raw = read_file(directory / filename, 64 * 1024 * 1024)
            require(digest(raw) == marker[field], 'rust-stdio-original-companion-bytes')
            result[name + '/' + filename] = digest(raw)
    return result


def qualify(prepared: Path, output: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'rust-entropy-linux-python313')
    output = fresh(output)
    require(ROOT not in output.parents and output != ROOT, 'rust-entropy-output-outside-checkout')
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in dict.fromkeys(MATERIALS)}
    stage = 'prepared-inputs'
    try:
        before, qualified, products = prepared_inputs(prepared)
        original_companions = companions(prepared, qualified)
        require(set(products) == set(PRODUCTS), 'rust-entropy-original-native-five')
        for binary in products.values(): binary.chmod(0o700)
        paths, tools = resolve_tools(tomllib.loads((ROOT / 'tools/toolchain.toml').read_text()), ROOT, commands.environment)
        require(next(row for row in tools if row['name'] == 'cargo')
                == next(row for row in qualified['tools'] if row['name'] == 'cargo'), 'rust-entropy-prepared-compiler')
        archive = output / 'rust-src-1.97.1.tar.xz'
        stage = 'authenticated-stdlib-source'
        source_archive(archive)
        stage = 'entropy-owned-std'
        sysroot = output / 'entropy-std'
        built = std.build(archive, sysroot, paths['rustc'].parent, entropy=True)
        stage = 'ordinary-source-capture'
        application = create(output / 'application', 'greeting', runtime_profile=standard.ENTROPY)
        captured = fixture.install(application, output / 'outside', paths['cargo'])
        write_json(output / 'capture.json', captured)
        original = inventory(snapshot(application))
        common = dict(offline=True, standard_runtime=sysroot)
        arguments = (products['examples/capsule_contracts'], products['examples/package'],
                     'https://github.com/KirilsTurkins/latent-service-fabric')
        stage = 'unapproved-executable-refusal'
        denied = output / 'approval-required'
        try:
            build(application, denied, *arguments, **common)
        except ValueError:
            failed = read_json(denied / 'BUILD-FAILED.json')
            require(failed['stage'] == 'executable-input-approval'
                    and not (denied / 'BUILD-COMPLETE.json').exists(), 'rust-entropy-exact-approval-boundary')
            approval = read_json(denied / 'executable-input-approval-request.json')
            executable = approval['specification']['executableInputs']
            require(len(executable) == 1 and executable[0]['metadata']['package'] == 'getrandom'
                    and executable[0]['metadata']['version'] == '0.3.4', 'rust-entropy-audited-script-only')
        else:
            raise ValueError('rust-entropy-unapproved-script-executed')
        stage = 'isolated-offline-component'
        artifact = build(application, output / 'build', *arguments, **common, executable_approval=approval['identity'])
        require(inventory(snapshot(application)) == original, 'rust-entropy-build-mutated-original-source')
        require(read_json(artifact / 'cargo-inputs.json')['networkResolution'] is False,
                'rust-entropy-offline-compiler-resolved-network')
        require(read_json(artifact / 'standard-runtime-selection.json')['profile'] == standard.ENTROPY,
                'rust-entropy-emitted-profile')
        require(read_json(artifact / 'executable-input-approval-request.json') == approval,
                'rust-entropy-exact-retained-execution-approval')
        stage = 'same-products-signing'
        require(prepared_inputs(prepared)[:2] == (before, qualified)
                and companions(prepared, qualified) == original_companions, 'rust-entropy-prepared-source-mutated')
        signed = output / 'signed'
        commands.run('entropy-demo-sign', products['examples/capsule_authoring'], 'demo-sign', signed,
                     artifact, *(prepared / 'builds' / name for name in COMPANIONS))
        stage = 'signed-node'
        node = node_workflow(products['latent'], products['latentd'], signed, output / 'node',
                             language='rust', rust_standard_entropy=True)
        receipt = node.get('rustStandardEntropy', {})
        require(node['status'] == 'passed' and receipt.get('status') == 'passed'
                and len(node['invocations']) == 45 and len(receipt['cases']) == 9
                and len(receipt['recovery']) == 3
                and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
                'rust-entropy-actual-signed-acceptance')
        require(time.monotonic() < commands.deadline, 'rust-entropy-existing-overall-deadline')
        require(prepared_inputs(prepared)[:2] == (before, qualified)
                and companions(prepared, qualified) == original_companions
                and materials == {name: file_identity(ROOT / name) for name in materials}, 'rust-entropy-final-input-mutated')
        value = {'schemaVersion': 'latent.rust.standard-entropy-qualified.v1', 'status': 'passed',
            'runtimeProfile': standard.ENTROPY, 'sysrootIdentity': built['identity'], 'capture': captured,
            'build': read_json(artifact / 'BUILD-COMPLETE.json'), 'executableApproval': approval,
            'signedInvocations': 45, 'entropy': receipt, 'nodeReceipt': file_identity(output / 'node/workflow.json'),
            'nativeBinaries': qualified['binaries'], 'preparedSourceIdentityDigest': qualified['sourceIdentityDigest'],
            'originalCompanionInputs': original_companions,
            'materials': materials, 'commands': commands.records, 'publisherAuthenticated': False,
            'releasePublished': False, 'fullTicketQualification': False, 'concurrencyQualified': False,
            'aggregateExhaustionClaimed': False, 'fipsCertification': False}
        write_json(output / 'qualification.json', value)
        return value
    except BaseException as error:
        write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage,
                   'errorCategory': type(error).__name__, 'commands': commands.records})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps({'status': qualify(args.prepared_qualification, args.output)['status']}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
