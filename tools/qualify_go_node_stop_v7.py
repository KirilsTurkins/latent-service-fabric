#!/usr/bin/env python3
"""One ordinary Go node-stop programme using authenticated V7 native products.

No historical normal27 receipt is recreated or relabelled. The default-off
closed native observer supplies positive readiness; actual shutdown still has
to retire every original owner under the unchanged node grace.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import java_phase_native_products as products
from tools import qualify_go_node_stop as stop
from tools import ci_rust_artifacts as artifacts
from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory as directory_identity
from tools.phase3_resource_profile import digest
from tools.qualify_sdk_scratch import build_component, current_inputs, package_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

HELPERS = (*stop.HELPERS, 'tools/qualify_go_node_stop_v7.py', 'tools/go_node_stop_positive.py',
           'tools/go_node_stop_timer_observer.py', 'tools/java_phase_native_products.py',
           'tools/java_replay_materials.py', 'tools/node_startup_observation.py')
COMPILE_TREES = {'wit': (2048, 8 * 1024 * 1024), 'schemas': (256, 4 * 1024 * 1024),
                 'examples/echo-contract/wit': (128, 1024 * 1024)}


def compile_trees():
    result = {}
    for name, (files, maximum) in COMPILE_TREES.items():
        captured = directory_identity(ROOT / name, maximum_files=files, maximum_bytes=maximum)
        for row in captured['files']:
            result[name + '/' + row['path']] = {key: row[key] for key in ('sha256', 'bytes')}
    return result


def selected(prepared):
    origin = products.verify_prepared(prepared)
    source = read_json(prepared / 'source-inputs.json')
    current = current_inputs('go')
    require(current['runtime'] == source['native'], 'Go-node-stop-v7-current-native-source-mismatch')
    # Producer recipes (including its diagnostic workflow) are authenticated by
    # verify_prepared against77bf Git bytes. They are not consumer compile trees.
    # Bind the current consumer recipe separately and compare every actual tree
    # entry, including rejection of extra current WIT/schema/echo files.
    expected = {name: value for name, value in source['materials'].items()
                if any(name.startswith(tree + '/') for tree in COMPILE_TREES)}
    actual = compile_trees()
    require(actual == expected, 'Go-node-stop-v7-current-native-compile-trees-mismatch')
    current = {**current, 'nativeCompileTrees': {'sha256': digest(actual), 'files': len(actual),
        'bytes': sum(value['bytes'] for value in actual.values())}}
    native = products.native_products(prepared)
    require(set(native) == {'latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring'},
            'Go-node-stop-v7-exact-five-products')
    return ({name if name in ('latent', 'latentd') else 'examples/' + name: path
             for name, path in native.items()}, origin, current)


def qualify(output, prepared, revision):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'Go-node-stop-unprivileged-linux-python313')
    artifacts.require_source(ROOT, revision, dict(os.environ))
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'Go-node-stop-output-outside-checkout')
    output = fresh(output)
    helpers = {name: file_identity(ROOT / name) for name in HELPERS}
    record = {'schemaVersion': 'latent.go.node-stop.v2', 'sourceRevision': revision, 'status': 'in-progress',
        'fullTicketQualification': False, 'newNativeBuild': False,
        'historicalNormalProgrammeRecreated': False, 'readinessSource': 'closed-positive-native-timer-observer',
        'helpers': helpers}
    stage = 'authenticated-v7-native-products'
    try:
        binaries, origin, before_inputs = selected(prepared)
        record['nativeProducer'] = origin
        record['currentSourceInputs'] = before_inputs
        for path in binaries.values():
            path.chmod(0o700)
        stage = 'ordinary-v5-source'
        app, record['fixture'] = stop.fixture.project(output / 'application')
        before = inventory(snapshot(app))
        stage = 'fresh-component-build'
        artifact = build_component('go', app, output / 'build', binaries)
        require(read_file(artifact / 'source-inputs.json') == before, 'Go-node-stop-built-source-mismatch')
        record['build'] = read_json(artifact / 'BUILD-COMPLETE.json')
        record['package'] = package_identity(artifact, record['build'])
        stage = 'normal-demo-sign'
        commands = Commands(ROOT, output, build_environment(output), deadline_seconds=600, command_seconds=120)
        signed = output / 'signed'
        commands.run('actual-node-stop-v7-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', signed, artifact)
        stage = 'actual-signed-positive-node-stop'
        record['programme'] = stop.programme({'latent': binaries['latent'], 'latentd': binaries['latentd']},
                                            signed, output, positive_timers=True)
        stage = 'final-integrity'
        after_binaries, after_origin, after_inputs = selected(prepared)
        require(after_binaries == binaries and after_origin == origin and after_inputs == before_inputs
                and inventory(snapshot(app)) == before
                and helpers == {name: file_identity(ROOT / name) for name in HELPERS},
                'Go-node-stop-observed-inputs-changed')
        record.update(status='passed', component=file_identity(artifact / 'component.wasm', 64 * 1024 * 1024),
                      commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native-products', type=Path, required=True)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    args = parser.parse_args()
    qualify(args.output, args.native_products, args.source_commit)
