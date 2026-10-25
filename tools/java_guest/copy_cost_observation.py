"""Private fixed-public-fixture copy-cost observation; never a compiler policy.

Explicitly compose PublicCopyCostObservationMixin before the already-admitted
DerivedPublicCompiler in the reviewed 1462 owner. This module selects no SDK,
compiler variant, toolchain or application itself. Only an authenticated,
strictly improved candidate reaches the same normal parent Clang command.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import time

from tools.dev_workflow import paths
from tools.java_guest.fiber_component_inputs import JAVA, WIT, GENERATED_C, GENERATED_C_LIMIT
from tools.java_guest.public_wineh import expected_command, public_sources, input_identity
from tools.rust_capsule_project import canonical, digest

SCHEMA = 'latent.java.public-copy-cost-candidate.v1'
TRACE_SCHEMA = 'latent.java.coroutine-copy-observation.v1'
MARKER = TRACE_SCHEMA + ' '
MAX_TRACE = 128 * 1024
BASELINE = {
    'sourceBytes': 733980,
    'sourceDigest': 'sha256:e8ac2e599bf4777f0abefbaeeebd3f8b34dc00e45b4d45a5327ba4affc7a8e22',
    'poolsBytes': 561514,
    'poolsDigest': 'sha256:facba19bfed7230d4300b97ad2beeab5227c5983857e53ce3e6c2a5e9933d316',
    'tryRegions': 159,
}
SCALARS = ('hookCount', 'blocks', 'instructions', 'phis', 'incomings', 'handlers',
           'exceptionBindings', 'structuralWeight', 'oldSplitCalls', 'newSplitCalls',
           'oldCopiedNodes', 'newCopiedNodes', 'oldFinalBlocks', 'newFinalBlocks',
           'oldFinalWeight', 'newFinalWeight')
HASHES = ('oldDecisionSha256', 'newDecisionSha256')
FUNCTION = b'void* meth_dla_Capsule_pools() {\n'
# Tokens protect braces in string/character literals and comments. Input is
# bounded first; unknown unterminated literals/comments fail closed below.
TOKENS = re.compile(rb'//[^\n]*(?:\n|$)|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}"\']|/\*', re.S)


class ObservationStopped(ValueError):
    """Intentional failed spending gate, never compiler/component PASS."""


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('copy-cost-trace-duplicate-key')
        result[key] = value
    return result


def trace(log: str) -> dict:
    rows = []
    for line in log.splitlines():
        if MARKER not in line:
            continue
        # No success substring hidden in another diagnostic or repeated marker.
        if not line.startswith(MARKER) or line.count(MARKER) != 1:
            raise ValueError('copy-cost-trace-framing')
        raw = line[len(MARKER):].encode('utf-8')
        if len(raw) > MAX_TRACE:
            raise ValueError('copy-cost-trace-bound')
        rows.append(json.loads(raw, object_pairs_hook=_pairs))
        if len(rows) > 1:
            raise ValueError('copy-cost-trace-ambiguous')
    if len(rows) != 1:
        raise ValueError('copy-cost-trace-missing')
    value = rows[0]
    if (type(value) is not dict or set(value) != {'schemaVersion', 'irreducible', *SCALARS, *HASHES}
            or value['schemaVersion'] != TRACE_SCHEMA or type(value['irreducible']) is not bool
            or any(type(value[key]) is not int or not 0 <= value[key] <= 2147483647 for key in SCALARS)
            or any(type(value[key]) is not str or not re.fullmatch('[0-9a-f]{64}', value[key]) for key in HASHES)
            or value['hookCount'] != 1 or not 0 < value['blocks'] <= 65536
            or value['structuralWeight'] != sum(value[key] for key in
                ('blocks', 'instructions', 'phis', 'incomings', 'handlers', 'exceptionBindings'))
            or value['structuralWeight'] > 1048576):
        raise ValueError('copy-cost-trace-schema')
    for mode in ('old', 'new'):
        if (value[mode + 'SplitCalls'] > 65536 or value[mode + 'CopiedNodes'] > 1048576
                or value[mode + 'FinalBlocks'] != value['blocks'] + value[mode + 'CopiedNodes']
                or value[mode + 'FinalWeight'] < (value['structuralWeight'] if value['irreducible'] else 0)
                or bool(value[mode + 'SplitCalls']) != bool(value[mode + 'CopiedNodes'])
                or not value['irreducible'] and value[mode + 'SplitCalls'] != 0):
            raise ValueError('copy-cost-trace-inconsistent')
    return value


def c_shape(raw: bytes) -> dict:
    if type(raw) is not bytes or not 0 < len(raw) <= GENERATED_C_LIMIT or b'\0' in raw:
        raise ValueError('copy-cost-c-source-bound')
    raw.decode('utf-8')
    starts = [match.start() for match in re.finditer(rb'^' + re.escape(FUNCTION), raw, re.M)]
    if len(starts) != 1:
        raise ValueError('copy-cost-c-function')
    start = starts[0]
    opened = start + len(FUNCTION) - 2
    depth = 0
    end = None
    for token in TOKENS.finditer(raw, opened):
        value = token.group()
        if value in (b'"', b"'", b'/*'):
            raise ValueError('copy-cost-c-token')
        if value == b'{':
            depth += 1
        elif value == b'}':
            depth -= 1
            if depth == 0:
                end = token.end()
                break
    if end is None or raw[end:end + 1] != b'\n':
        raise ValueError('copy-cost-c-function-end')
    span = raw[start:end + 1]
    tries = len(re.findall(rb'^\s*TEAVM_TRY\s*$', span, re.M))
    catches = len(re.findall(rb'^\s*TEAVM_CATCH\b[^\n]*$', span, re.M))
    ends = len(re.findall(rb'^\s*TEAVM_END_TRY\s*$', span, re.M))
    if tries != catches or tries != ends:
        raise ValueError('copy-cost-c-try-shape')
    return {'sourceBytes': len(raw), 'sourceDigest': digest(raw), 'poolsBytes': len(span),
            'poolsDigest': digest(span), 'tryRegions': tries}


def candidate(observed: dict, shape: dict) -> bool:
    # Structural reduction is only a pre-Clang spending gate, never evidence of
    # final Wasm size, EH equivalence, runtime execution or cost qualification.
    return (observed['irreducible'] and observed['oldSplitCalls'] > 0 and observed['newSplitCalls'] > 0
            and observed['oldDecisionSha256'] != observed['newDecisionSha256']
            and shape['poolsDigest'] != BASELINE['poolsDigest']
            and shape['poolsBytes'] < BASELINE['poolsBytes']
            and shape['tryRegions'] < BASELINE['tryRegions'])


class PublicCopyCostObservationMixin:
    """Fixed, explicit composition with the admitted normal derived compiler.

    No automatic private variant. Constructor-time commands use the same normal
    process owner. Its possible five-second cleanup stays INSIDE600/1200 caps.
    """
    def __init__(self, *arguments, **options):
        timeout = options.get('timeout', 1200)
        if type(timeout) not in (int, float) or isinstance(timeout, bool) or not 5 < timeout <= 1200:
            raise ValueError('copy-cost-compiler-timeout')
        self._copy_owner_deadline = time.monotonic() + timeout - 5
        self._observe_public_copy_cost = False
        self._copy_trace = None
        self._copy_trace_log_digest = None
        self._copy_gate_reached = False
        options['timeout'] = timeout - 5
        super().__init__(*arguments, **options)
        self.deadline = min(self.deadline, self._copy_owner_deadline)

    def compile(self, sources: Path, wit: Path, world: str, destination: Path, **options):
        output = self.directory.parent
        if (sources != output / 'src' or wit != output / 'wit' or destination != output / 'build'
                or self.directory != output / 'compiler' or world != 'tests:caller/service@1.0.0'
                or options != {'activation_profile': True}
                or sorted(path.name for path in sources.iterdir()) != ['Capsule.java']
                or digest(paths.read(output, 'src/Capsule.java', 1024 * 1024)) != JAVA
                or digest(paths.read(output, 'wit/service.wit', 64 * 1024)) != WIT):
            raise ValueError('copy-cost-public-source-selection')
        self._observe_public_copy_cost = True
        return super().compile(sources, wit, world, destination, **options)

    def _copy_record(self, **fields):
        value = {'schemaVersion': SCHEMA, 'status': 'pre-clang-decision', 'qualification': False,
                 'publicSourceDigest': JAVA, 'publicWitDigest': WIT, 'baseline': BASELINE,
                 'clangDecision': 'refused-not-invoked',
                 'componentAcceptance': 'not-established-by-this-record',
                 'originalCommandResultAuthority': 'normal-compiler-command-record',
                 'runtimeQualified': False,
                 'trace': self._copy_trace, 'traceLogDigest': self._copy_trace_log_digest,
                 'generatedCPath': 'compiler/public-copy-cost-Capsule.c' if 'shape' in fields else None, **fields}
        raw = canonical(value)
        if len(raw) > MAX_TRACE:
            raise ValueError('copy-cost-observation-record-bound')
        paths.write_new(self.directory / 'public-copy-cost-candidate.json', raw)

    def run(self, stage: str, tool: str, *arguments, cwd: Path | None = None) -> str:
        if stage == 'c-to-wasm':
            if self._copy_gate_reached:
                raise ValueError('copy-cost-preclang-duplicate')
            self._copy_gate_reached = True
            output = self.directory.parent
            actual = [str(self.paths.get(tool, Path(tool))), *map(str, arguments)]
            if (not self._observe_public_copy_cost or tool != 'clang' or cwd is not None
                    or actual != expected_command(self, output)):
                raise ValueError('copy-cost-original-command')
            public_sources(output)
            inputs = input_identity(self, output)
            generated_c = paths.read(output, GENERATED_C, GENERATED_C_LIMIT)
            shape = c_shape(generated_c)
            selected_c = inputs['trees']['generated'].get('c/d/l/a/Capsule.c')
            if selected_c != {'digest': shape['sourceDigest'], 'size': shape['sourceBytes']}:
                raise ValueError('copy-cost-c-identity')
            if input_identity(self, output) != inputs:
                raise ValueError('copy-cost-inputs-changed')
            # Fixed public source only; retain it even when the spending gate
            # stops before Clang (the old component-new failure hook cannot).
            paths.write_new(self.directory / 'public-copy-cost-Capsule.c', generated_c)
            if self._copy_trace is None:
                self._copy_record(reason='missing-actual-hook', inputIdentity=inputs, shape=shape)
                raise ObservationStopped('copy-cost-missing-actual-hook')
            improved = candidate(self._copy_trace, shape)
            if not improved:
                self._copy_record(reason='candidate-not-improved', inputIdentity=inputs, shape=shape, improved=False)
                if getattr(self, '_public_wineh_preclang', False) is True:
                    from tools.java_guest.wineh_preclang import observe
                    observe(self, output, actual, inputs)
                raise ObservationStopped('copy-cost-not-improved')
            if getattr(self, '_public_wineh_preclang', False) is True:
                self._copy_record(reason='diagnostic-baseline-mismatch', inputIdentity=inputs, shape=shape, improved=True)
                raise ObservationStopped('copy-cost-diagnostic-baseline-mismatch')
            self._copy_record(reason='strictly-improved', inputIdentity=inputs, shape=shape, improved=True,
                              clangDecision='admitted-pending-original-command', originalCommand=actual)
            # Continue through the SAME bounded super().run below. This record
            # is the pre-Clang decision; only normal command/component records
            # can establish subsequent compilation or component acceptance.
        deadline = min(self.deadline, self._copy_owner_deadline)
        self.deadline = min(deadline, time.monotonic() + 595)
        try:
            result = super().run(stage, tool, *arguments, cwd=cwd)
        finally:
            self.deadline = deadline
        if stage == 'java-to-c':
            try:
                self._copy_trace_log_digest = digest(result.encode('utf-8'))
                self._copy_trace = trace(result)
            except (ValueError, UnicodeError):
                self._copy_record(reason='missing-or-invalid-actual-hook')
                raise
        return result
