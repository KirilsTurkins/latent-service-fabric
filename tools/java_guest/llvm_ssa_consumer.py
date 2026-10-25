"""Qualification-only identity adapter for one authenticated derived compiler."""
from __future__ import annotations

import os
from pathlib import Path
import re
import time

from tools.java_guest.compiler import Compiler
from tools.java_guest import llvm_ssa_consumer_inputs as inputs
from tools.java_guest import llvm_ssa_producer as producer
from tools.java_guest import public_wineh
from tools.java_guest.fiber_component_inputs import JAVA, WIT
from tools.java_guest import llvm_ssa_io as io
from tools import guest_emitted_code as framing


def body_inventory(raw: bytes) -> dict:
    """Bounded section/name framing only; the original assembler validates code.

    Skip body bytes without decoding instructions or printing arbitrary names.
    This cannot turn a failed component assembly into a qualified product.
    """
    inputs.need(len(raw) <= 64 * 1024 ** 2, 'core-byte-limit')
    reader = framing.Reader(raw, framing.Budget())
    inputs.need(bytes(reader.take(8)) == framing.CORE, 'core-header')
    imported, declared, bodies, labels, seen = 0, None, [], {}, set()
    sections = 0
    while reader.at < len(reader.data):
        sections += 1
        inputs.need(sections <= 128, 'core-section-limit')
        kind = reader.byte()
        inputs.need(kind == 0 or kind not in seen, 'core-duplicate-section')
        seen.add(kind)
        size = reader.leb()
        offset = reader.at
        section = framing.Reader(reader.take(size), reader.budget)
        if kind == 0:
            if section.name() == 'name':
                while section.at < len(section.data):
                    sub, names = section.byte(), section.child()
                    if sub == 1:
                        for _ in range(names.count(framing.MAX_FUNCTIONS)):
                            index, name = names.leb(), names.name()
                            inputs.need(index not in labels, 'core-duplicate-name')
                            labels[index] = name
                        names.done()
            section.at = len(section.data)
        elif kind == 2:
            for _ in range(section.count(framing.MAX_FUNCTIONS)):
                section.name(); section.name()
                sort = section.byte()
                if sort == 0:
                    section.leb(); imported += 1
                elif sort == 1:
                    framing.value_type(section); framing.limits(section)
                elif sort == 2:
                    framing.limits(section)
                elif sort == 3:
                    framing.value_type(section); section.byte()
                elif sort == 4:
                    section.byte(); section.leb()
                else:
                    inputs.need(False, 'core-import-kind')
        elif kind == 3:
            declared = section.count(framing.MAX_FUNCTIONS)
            for _ in range(declared):
                section.leb()
        elif kind == 10:
            for _ in range(section.count(framing.MAX_FUNCTIONS)):
                length = section.leb()
                start = offset + section.at
                section.take(length)
                bodies.append({'functionIndex': imported + len(bodies), 'bytes': length,
                               'start': start, 'end': start + length})
        else:
            section.at = len(section.data)
        section.done()
    inputs.need(declared is not None and len(bodies) == declared and bodies, 'core-function-count')
    inputs.need(imported + declared <= framing.MAX_FUNCTIONS
                and all(index < imported + declared for index in labels), 'core-function-index')
    largest = max(bodies, key=lambda value: value['bytes'])
    pools = [body for body in bodies if labels.get(body['functionIndex']) == 'meth_dla_Capsule_pools']
    inputs.need(len(pools) <= 1, 'core-pools-name-ambiguous')
    inputs.need(largest['bytes'] <= 7654321, 'core-original-parser-limit')
    return {'schemaVersion': 'latent.java.derived-core-body-inventory.v1',
            'framingOnly': True, 'instructionsDecoded': False, 'source': inputs.identity(raw),
            'parserFunctionByteLimit': 7654321, 'importedFunctions': imported,
            'definedFunctions': declared, 'largest': largest,
            'pools': {'status': 'named', **pools[0]} if pools else {'status': 'name-unavailable'}}


def deadline() -> float:
    """One existing 35-minute job budget, including setup and input acquisition."""
    raw = os.environ.get('LSF_JAVA_LLVM_PUBLIC_STARTED', '')
    inputs.need(re.fullmatch(r'[0-9]{10}', raw), 'job-start-clock')
    elapsed = time.time() - int(raw)
    inputs.need(0 <= elapsed < 35 * 60, 'job-deadline')
    return time.monotonic() + 35 * 60 - elapsed


def retain_products(output: Path) -> dict:
    """Fixed successful compiler products only, never execute the component."""
    public_wineh.public_sources(output)
    selections = {
        'core.wasm': ('build/core.wasm', 64 * 1024 ** 2),
        'closed-runtime.wasm': ('build/closed-runtime.wasm', 4 * 1024 ** 2),
        'component.wasm': ('build/component.wasm', 64 * 1024 ** 2),
        'Capsule.c': ('build/project/build/teavm-c/c/c/d/l/a/Capsule.c', 4 * 1024 ** 2),
    }
    values = {name: public_wineh.paths.read(output, path, maximum)
              for name, (path, maximum) in selections.items()}
    inventory = body_inventory(values['core.wasm'])
    target = io.fresh(output / 'build/derived-public-products')
    result = {}
    for name, raw in values.items():
        path = selections[name][0]
        if name != 'component.wasm':
            (target / name).write_bytes(raw)
            path = 'build/derived-public-products/' + name
        result[name] = {'path': path, **inputs.identity(raw)}
    (target / 'record.json').write_bytes(inputs.carrier.encode({
        'schemaVersion': 'latent.java.derived-public-compiler-products.v1',
        'products': result, 'bodyInventory': inventory, 'sourceDigest': JAVA, 'witDigest': WIT,
        'compilerOnly': True, 'nodeExecution': 'not-run', 'runtimeQualified': False}))
    return result


class DerivedPublicCompiler(Compiler):
    def __init__(self, directory: Path, wasi_sdk: Path, *, admitted, **options):
        inputs.need(type(admitted) is inputs._Admitted, 'admitted-sdk-required')
        self._derived = admitted
        admitted.recheck(wasi_sdk.resolve(strict=True))
        options['timeout'] = min(options.get('timeout', 1200), admitted.deadline - time.monotonic())
        inputs.need(options['timeout'] > 0, 'job-deadline')
        self._public_inputs = None
        super().__init__(directory, wasi_sdk, **options)
        self.deadline = self._derived.deadline = min(self._derived.deadline, self.deadline)

    def _wasi_compiler_version(self) -> str:
        self._derived.recheck(self.wasi_sdk)
        expected = [producer.OFFICIAL_VERSION[0] + '-' + producer.PROFILE,
                    *producer.OFFICIAL_VERSION[1:],
                    'lsf-llvm-patch-sha256: ' + inputs.patch.PATCH_SHA256]
        inputs.need((self.wasi_sdk / 'VERSION').read_text().splitlines() == expected
                    and self._derived.own['products']['originalVersion'] == producer.OFFICIAL_VERSION
                    and self._derived.own['products']['derivedVersion'] == expected, 'derived-version')
        return '21.1.4' + producer.SUFFIX

    def run(self, stage: str, tool: str, *arguments, cwd=None) -> str:
        # Base initialization can spend time copying/inventorying dependencies
        # before creating its relative deadline. Never renew the absolute job
        # budget, including for the first version command during that init.
        self.deadline = min(self.deadline, self._derived.deadline)
        if stage == 'c-to-wasm':
            output = self.directory.parent
            actual = [str(self.paths.get(tool, Path(tool))), *map(str, arguments)]
            inputs.need(tool == 'clang' and cwd is None
                        and self.directory == output / 'compiler'
                        and actual == public_wineh.expected_command(self, output), 'public-command')
            public_wineh.public_sources(output)
            self._public_inputs = public_wineh.input_identity(self, output)
        result = super().run(stage, tool, *arguments, cwd=cwd)
        if stage == 'c-to-wasm':
            inputs.need(public_wineh.input_identity(self, self.directory.parent) == self._public_inputs,
                        'public-inputs-changed')
        return result

    def check_unchanged(self):
        super().check_unchanged()
        self._derived.recheck(self.wasi_sdk)

    def qualification_record(self) -> dict:
        self.check_unchanged()
        inputs.need(self._public_inputs is not None, 'actual-public-compile-required')
        return {'schemaVersion': 'latent.java.llvm-public-compiler-consumption.v1',
                'producerSource': inputs.HEAD, 'producerTree': inputs.TREE,
                'producerRun': inputs.RUN, 'producerJob': inputs.JOB,
                'qualifiedArtifact': inputs.pinned(), 'sourceDigest': JAVA, 'witDigest': WIT,
                'derivedVersion': self._derived.own['products']['derivedVersion'],
                'normalCompilerChecksUnchanged': True, 'publicInputs': self._public_inputs,
                'componentRuntimeQualification': False, 'nodeExecution': 'not-run'}


# Explicit closed composition under the existing derived-public flag. The same
# frozen input reader admits the SDK; there is no alternate private variant.
from tools.java_guest.copy_cost_observation import PublicCopyCostObservationMixin


class CopyCostPublicCompiler(PublicCopyCostObservationMixin, DerivedPublicCompiler):
    pass
