"""Strict host-codec producer schema over the unchanged fixed-member reader.

This module has no producer pins and cannot select a branch tip. A separately
reviewed immutable tuple is required before it can acquire any products.
"""
from __future__ import annotations

import ast
import math
from pathlib import PurePosixPath
import re
import subprocess

from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT
from tools.sdk_native_products_reader import FrozenNativeProducts, PRODUCTS, _identity

WORKFLOW = '.github/workflows/host-codec-memory.yml'
COHORT = 'wasmtime-48.0.7-latent-dynamic-value-memory-v1'
SCOPE = ('ordinary-host-codec-original-memory-and-selected-c-public-async-type-sync-core-admission; '
    'legacy framing and serialized transport controller frames excluded')


def _producer_contract(raw, groups, count, *, extra_control=None, recipe_count=22):
    """Read literal data from the frozen Git producer, without importing it."""
    require(type(raw) is bytes and 0 < len(raw) <= 128 * 1024, 'codec-reader-producer-source-bound')
    wanted = {}
    for statement in ast.parse(raw).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name) and target.id in ('CONTROLS', 'RECIPE', 'PRODUCTS'):
                require(target.id not in wanted, 'codec-reader-single-producer-declaration')
                wanted[target.id] = ast.literal_eval(statement.value)
    require(set(wanted) == {'CONTROLS', 'RECIPE', 'PRODUCTS'} and wanted['PRODUCTS'] == PRODUCTS,
        'codec-reader-original-five-products')
    controls, recipe = wanted['CONTROLS'], wanted['RECIPE']
    require(type(controls) is tuple and len(controls) == groups
        and type(recipe) is tuple and len(recipe) == len(set(recipe)) == recipe_count
        and WORKFLOW in recipe and 'tools/qualify_host_codec_native.py' in recipe
        and all(type(name) is str and re.fullmatch(r'[A-Za-z0-9_./-]{1,256}', name)
            and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
            for name in recipe), 'codec-reader-original-producer-recipe')
    names, stages = [], []
    for row in controls:
        require(type(row) is tuple and len(row) == 4, 'codec-reader-control-row')
        stage, package, needle, cases = row
        require(type(stage) is str and re.fullmatch(r'[a-z0-9-]{1,60}', stage)
            and type(package) is str
            and (re.fullmatch(r'latent-[a-z-]{1,48}', package) or row == extra_control)
            and type(needle) is str and 0 < len(needle) <= 160
            and type(cases) is tuple and 0 < len(cases) <= 32
            and all(type(case) is str and re.fullmatch(r'[A-Za-z0-9_:]{1,256}', case) for case in cases),
            'codec-reader-control-identities')
        names.extend(cases); stages.append(stage)
    require(len(stages) == len(set(stages)) == groups and len(names) == len(set(names)) == count,
        'codec-reader-exact-sixty-one-controls' if count == 61
        else 'codec-reader-exact-ninety-two-controls' if count == 92
        else 'codec-reader-exact-one-hundred-fourteen-controls' if count == 114
        else 'codec-reader-exact-one-hundred-twenty-eight-controls' if count == 128
        else 'codec-reader-exact-eighty-one-controls')
    return controls, recipe


def producer_contract(raw):
    return _producer_contract(raw, 14, 61)


class FrozenHostCodecProducts(FrozenNativeProducts):
    cohort, scope = COHORT, SCOPE
    control_count, command_count = 61, 31
    job_name = 'Original ledger, actual codec and backend result ownership'

    def _producer_contract(self, raw):
        return producer_contract(raw)

    def __init__(self, *, source, run, job, artifact, receipts, branch, event='push'):
        require(type(source) is str and re.fullmatch(r'[0-9a-f]{40}', source),
            'codec-reader-explicit-frozen-source')
        raw = subprocess.check_output(['git', 'show', source + ':tools/qualify_host_codec_native.py'],
            cwd=ROOT, timeout=30)
        self.controls, self.recipe = self._producer_contract(raw)
        stages = ('source-revision', 'rust-version', 'normal-host-build',
            *(stage + suffix for stage, _, _, _ in self.controls for suffix in ('-list', '-run')))
        super().__init__(source=source, run=run, job=job, artifact=artifact, receipts=receipts,
            branch=branch, stages=stages, event=event, include_protocol=True)

    def _material_recipe(self):
        return self.recipe

    def _producer_origin(self):
        return WORKFLOW, self.job_name, 'host-codec-memory-'

    def validate_record(self, record, snapshot, native, materials):
        fields = {'schemaVersion', 'status', 'sourceRevision', 'source', 'materials', 'compiler',
            'products', 'commands', 'controlCount', 'nativeCohort', 'controls', 'profile',
            'signedQualification', 'guestJavaScriptEngineCompiled', 'guestSourceCompiled',
            'historicalReceiptRewritten', 'scope'}
        require(type(record) is dict and set(record) == fields
            and record['schemaVersion'] == 'latent.host-codec.native-products.v1'
            and record['status'] == 'passed' and record['sourceRevision'] == self.source
            and record['source'] == native and record['materials'] == materials
            and snapshot == {'native': native, 'materials': materials}, 'codec-reader-exact-producer-source')
        require(record['profile'] == 'normal-managed-guest-default-features'
            and record['nativeCohort'] == self.cohort and record['scope'] == self.scope
            and record['signedQualification'] is False and record['guestSourceCompiled'] is False
            and record['guestJavaScriptEngineCompiled'] is False and record['historicalReceiptRewritten'] is False
            and type(record['compiler']) is str and len(record['compiler']) <= 128
            and record['compiler'].startswith('rustc 1.97.1 ('), 'codec-reader-profile-not-guest-qualification')
        require(type(record['controlCount']) is int and record['controlCount'] == self.control_count
            and record['controls'] == {stage: list(cases) for stage, _, _, cases in self.controls}
            and type(record['products']) is dict and set(record['products']) == set(PRODUCTS)
            and all(_identity(row) for row in record['products'].values()), 'codec-reader-controls-and-five-products')
        commands = record['commands']
        require(type(commands) is list and len(commands) == len(self.stages) == self.command_count,
            'codec-reader-all-thirty-one-commands' if self.command_count == 31
            else 'codec-reader-all-forty-three-commands' if self.command_count == 43
            else 'codec-reader-all-fifty-one-commands' if self.command_count == 51
            else 'codec-reader-all-fifty-nine-commands' if self.command_count == 59
            else 'codec-reader-all-thirty-seven-commands')
        require(type(commands[2]) is dict and type(commands[2].get('argv')) is list
            and len(commands[2]['argv']) > 2, 'codec-reader-original-host-build-command')
        config = commands[2]['argv'][2]
        require(type(config) is str and len(config) <= 512 and config.startswith('/')
            and config.endswith('/.cargo/managed-guest.toml') and '..' not in PurePosixPath(config).parts,
            'codec-reader-original-managed-cargo-configuration')
        cargo = ['cargo', '--config', config]
        expected = [['git', 'rev-parse', 'HEAD'], ['rustc', '--version'],
            [*cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd', '--bins',
                '-p', 'latent-packaging', '--example', 'package', '--example', 'capsule_contracts',
                '-p', 'latent-policy', '--example', 'capsule_authoring']]
        for _, package, needle, _ in self.controls:
            command = [*cargo, 'test', '--locked', '-p', package, '--lib', needle, '--']
            expected.extend([command + ['--list'], command + ['--test-threads=1']])
        retained = 0
        for ordinal, (row, stage, argv) in enumerate(zip(commands, self.stages, expected)):
            require(type(row) is dict and set(row) == {'stage', 'exitCode', 'seconds', 'argv', 'logs'}
                and row['stage'] == stage and row['argv'] == argv
                and type(row['exitCode']) is int and row['exitCode'] == 0
                and type(row['seconds']) in (int, float) and math.isfinite(row['seconds'])
                and 0 <= row['seconds'] <= 1320, 'codec-reader-exact-successful-command')
            require(type(row['logs']) is dict and set(row['logs']) == {'stdout', 'stderr'},
                'codec-reader-both-original-log-streams')
            for stream, log in row['logs'].items():
                require(type(log) is dict and set(log) == {'path', 'bytes', 'sha256'}
                    and log['path'] == f'logs/{ordinal:02d}-{stage}.{stream}.txt'
                    and type(log['bytes']) is int and 0 <= log['bytes'] <= 4 * 1024**2
                    and type(log['sha256']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', log['sha256']),
                    'codec-reader-bounded-original-log-identity')
                retained += log['bytes']
        require(sum(row['seconds'] for row in commands) <= 1320.001 and retained <= 16 * 1024**2,
            'codec-reader-original-total-time-and-diagnostic-bounds')
