"""R8-only normal public backend admission; unchanged C is expected, not improved."""
from __future__ import annotations

from pathlib import Path
import time

from tools.java_guest.compiler import Compiler
from tools.java_guest import llvm_private_store_inputs as inputs
from tools.java_guest import llvm_private_store_producer as producer
from tools.java_guest import public_wineh, wineh_preclang
from tools.java_guest.fiber_component_inputs import JAVA, WIT
from tools.java_guest.copy_cost_observation import c_shape
from tools.java_guest.llvm_ssa_consumer import body_inventory, deadline, retain_products
from tools.rust_capsule_project import canonical, digest

GENERATED_C = 'build/project/build/teavm-c/c/c/d/l/a/Capsule.c'


def backend_baseline(identity: dict, raw_c: bytes) -> dict:
    baseline = wineh_preclang.baseline()  # Exact authenticated e782 data only.
    generated = identity['trees']['generated']
    actual = {'files': len(generated), 'bytes': sum(row['size'] for row in generated.values()),
              'digest': digest(canonical(generated))}
    shape = c_shape(raw_c)
    inputs.need(actual == baseline['generatedInventory'] and shape == baseline['shape'],
                'private-backend-public-baseline')
    inputs.need(generated.get('c/d/l/a/Capsule.c') == {
        'size': shape['sourceBytes'], 'digest': shape['sourceDigest']}, 'private-backend-c-binding')
    return {'sourceBaseline': baseline['source'], 'generatedInventory': actual,
            'shape': shape, 'unchangedPublicCExpected': True,
            'componentAcceptance': 'pending-normal-command', 'runtimeQualified': False}


class PrivateScalarPublicCompiler(Compiler):
    def __init__(self, directory: Path, wasi_sdk: Path, *, admitted, **options):
        inputs.need(type(admitted) is inputs._Admitted, 'admitted-sdk-required')
        self._derived = admitted
        admitted.recheck(wasi_sdk.resolve(strict=True))
        allowance = min(options.get('timeout', 1200), admitted.deadline - time.monotonic())
        inputs.need(allowance > 5, 'job-deadline')
        # Same five-second cleanup reserve, inside the existing1200 aggregate.
        self._owner_deadline = time.monotonic() + allowance - 5
        self._public_inputs = self._backend_gate = None
        self._compile_selected = self._clang_requested = False
        options['timeout'] = allowance - 5
        super().__init__(directory, wasi_sdk, **options)
        self.deadline = self._derived.deadline = min(self.deadline, self._owner_deadline)

    def _wasi_compiler_version(self) -> str:
        self._derived.recheck(self.wasi_sdk)
        expected = [producer.OFFICIAL_VERSION[0] + '-' + producer.PROFILE,
                    *producer.OFFICIAL_VERSION[1:],
                    'lsf-llvm-patch-sha256: ' + inputs.patch.PATCH_SHA256]
        inputs.need((self.wasi_sdk / 'VERSION').read_text().splitlines() == expected
                    and self._derived.own['products']['originalVersion'] == producer.OFFICIAL_VERSION
                    and self._derived.own['products']['derivedVersion'] == expected, 'derived-version')
        return '21.1.4' + producer.SUFFIX

    def compile(self, sources: Path, wit: Path, world: str, destination: Path, **options):
        output = self.directory.parent
        inputs.need(sources == output / 'src' and wit == output / 'wit'
                    and destination == output / 'build' and world == 'tests:caller/service@1.0.0'
                    and options == {'activation_profile': True}
                    and sorted(path.name for path in sources.iterdir()) == ['Capsule.java'],
                    'private-backend-public-selection')
        inputs.need(digest(public_wineh.paths.read(output, 'src/Capsule.java', 1024 * 1024)) == JAVA
                    and digest(public_wineh.paths.read(output, 'wit/service.wit', 64 * 1024)) == WIT,
                    'private-backend-original-inputs')
        self._compile_selected = True
        return super().compile(sources, wit, world, destination, **options)

    def run(self, stage: str, tool: str, *arguments, cwd=None) -> str:
        if stage == 'c-to-wasm':
            inputs.need(self._compile_selected and not self._clang_requested,
                        'private-backend-one-clang')
            self._clang_requested = True
            output = self.directory.parent
            actual = [str(self.paths.get(tool, Path(tool))), *map(str, arguments)]
            inputs.need(tool == 'clang' and cwd is None
                        and self.directory == output / 'compiler'
                        and actual == public_wineh.expected_command(self, output), 'public-command')
            self._derived.recheck(self.wasi_sdk)
            public_wineh.public_sources(output)
            self._public_inputs = public_wineh.input_identity(self, output)
            self._backend_gate = backend_baseline(self._public_inputs,
                public_wineh.paths.read(output, GENERATED_C, 4 * 1024 ** 2))
            inputs.need(public_wineh.input_identity(self, output) == self._public_inputs,
                        'public-inputs-changed')
        absolute = min(self.deadline, self._owner_deadline)
        self.deadline = min(absolute, time.monotonic() + 595)
        try:
            result = super().run(stage, tool, *arguments, cwd=cwd)
        finally:
            self.deadline = absolute
        if stage == 'c-to-wasm':
            inputs.need(public_wineh.input_identity(self, self.directory.parent) == self._public_inputs,
                        'public-inputs-changed')
            self._derived.recheck(self.wasi_sdk)
        return result

    def check_unchanged(self):
        super().check_unchanged()
        self._derived.recheck(self.wasi_sdk)

    def qualification_record(self) -> dict:
        self.check_unchanged()
        inputs.need(self._backend_gate is not None, 'actual-public-compile-required')
        for stage in ('c-to-wasm', 'component-new'):
            rows = [row for row in self.records if row['stage'] == stage]
            inputs.need(len(rows) == 1 and type(rows[0].get('exitCode')) is int
                        and rows[0]['exitCode'] == 0 and 'processFailure' not in rows[0],
                        'private-backend-actual-component-required')
        return {'schemaVersion': 'latent.java.private-scalar-public-consumption.v1',
                'producerSource': inputs.HEAD, 'producerTree': inputs.TREE,
                'producerRun': inputs.RUN, 'producerJob': inputs.JOB,
                'qualifiedArtifact': inputs.pinned(), 'sourceDigest': JAVA, 'witDigest': WIT,
                'profile': producer.PROFILE, 'derivedVersion': self._derived.own['products']['derivedVersion'],
                'publicInputs': self._public_inputs, 'backendGate': self._backend_gate,
                'normalCompilerChecksUnchanged': True, 'componentRuntimeQualification': False,
                'nodeExecution': 'not-run'}
