"""Pure fixed-reader refusals; no compiler, guest or artifact acquisition."""
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import compatibility_preserved_cells as cells
from tools.compatibility_closure_matrix import read_retained


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


class PreservedCellsTests(unittest.TestCase):
    def test_original_archive_and_admission_refuse_tamper_and_nonregular_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = encoded({'sourceCommit': 'original', 'status': 'passed'})
            payload = b'original public evidence'
            files = {'qualified.json': cells.identity(qualified), 'baseline/evidence.txt': cells.identity(payload)}
            admission = encoded({'schemaVersion': 'latent.compatibility.public-union.v1', 'files': files,
                'payloadBytes': sum(row['bytes'] for row in files.values()), 'maximumUnionBytes': 256*1024**2,
                'privateSignerAndCompilerCacheIncluded': False, 'qualificationInferred': False})
            entries = {'qualified.json': qualified, 'baseline/evidence.txt': payload, 'ADMISSION.json': admission}
            def archive(name, members):
                target = root / name
                with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as output:
                    for member, raw in members.items(): output.writestr(member, raw)
                return target
            path = archive('fixed.zip', entries)
            pin = {'archive': cells.identity(path.read_bytes()), 'members': 3,
                'expanded': sum(map(len, entries.values())), 'admission': cells.identity(admission),
                'qualified': cells.identity(qualified)}
            with patch.dict(cells.PINS, {'java': pin}, clear=True):
                cells._archive(path, 'java', root / 'extracted')
                self.assertEqual(read_retained(root / 'extracted')['sourceCommit'], 'original')
                (root / 'extracted/baseline/evidence.txt').write_bytes(b'changed')
                with self.assertRaises(ValueError): read_retained(root / 'extracted')
                changed = archive('changed.zip', {**entries, 'baseline/evidence.txt': b'forged'})
                with self.assertRaises(ValueError): cells._archive(changed, 'java')
            # Even an otherwise pinned hostile archive must refuse a symbolic
            # link before creating its extraction directory.
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as output:
                for member, raw in entries.items():
                    row = zipfile.ZipInfo(member)
                    row.external_attr = ((stat.S_IFLNK | 0o777) << 16) if member == 'baseline/evidence.txt' else ((stat.S_IFREG | 0o600) << 16)
                    output.writestr(row, raw)
            hostile = root / 'hostile.zip'; hostile.write_bytes(buffer.getvalue())
            pin['archive'] = cells.identity(buffer.getvalue())
            with patch.dict(cells.PINS, {'java': pin}, clear=True):
                with self.assertRaises(ValueError): cells._archive(hostile, 'java', root / 'never-created')
            self.assertFalse((root / 'never-created').exists())

    def test_fixed_two_source_epochs_cannot_be_swapped_or_promoted_to_current_execution(self):
        for cell in ('java', 'rust', 'c'):
            pin = cells.PINS[cell]
            run = {'id': pin['run'], 'head_sha': pin['source'], 'head_branch': cells.BRANCH,
                'path': cells.WORKFLOW, 'event': 'push', 'run_attempt': 1,
                'status': 'completed', 'conclusion': 'failure'}
            job = {'id': pin['job'], 'run_id': pin['run'], 'head_sha': pin['source'],
                'name': 'Required finite ' + cell + ' compatibility completion',
                'status': 'completed', 'conclusion': 'success'}
            artifact = {'id': pin['artifact'], 'size_in_bytes': pin['archive']['bytes'],
                'digest': pin['archive']['sha256'], 'expired': False,
                'name': 'compatibility-closure-' + pin['source'] + '-' + cell,
                'workflow_run': {'id': pin['run'], 'head_sha': pin['source'], 'head_branch': cells.BRANCH}}
            cells._origin(cell, run, job, artifact)
            other = cells.SECOND_SOURCE if cell == 'java' else cells.SOURCE
            for changed in ({**run, 'head_sha': other}, {**run, 'id': cells.RUN if cell == 'rust' else cells.SECOND_RUN}):
                with self.assertRaises(ValueError): cells._origin(cell, changed, job, artifact)
            with self.assertRaises(ValueError): cells._origin(cell, run, {**job, 'conclusion': 'failure'}, artifact)

    def test_only_reviewed_passive_changes_are_excluded_from_current_runtime_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root / 'repo'; build = root / 'build'
            repo.mkdir(); build.mkdir()
            def put(name, raw):
                path = repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                return {'size': len(raw), 'digest': cells.identity(raw)['sha256']}
            passive = {}
            for name in ('tools/guest_compiler_edges.py', 'tools/guest_emitted_code.py'):
                old = b'original passive observer'
                passive[name] = {'original': {'size': len(old), 'digest': cells.identity(old)['sha256']},
                    'current': put(name, b'reviewed current passive observer')}
            runtime = put('tools/java_guest/compiler.py', b'unchanged actual compiler')
            sdk = put('sdk/java-guest/runtime.java', b'unchanged captured SDK')
            recipes = {name: row['original'] for name, row in passive.items()}
            recipes['tools/java_guest/compiler.py'] = runtime
            (build / 'recipe-inputs.json').write_bytes(encoded(recipes))
            source = {'vendor/lsf/sdk/java-guest/runtime.java': sdk,
                'wit/world.wit': {'digest': 'sha256:' + 'a'*64, 'size': 17}}
            (build / 'source-inputs.json').write_bytes(encoded(source))
            pin = {'source': cells.SOURCE, 'recipes': {'recipe-inputs.json': 3}, 'sources': {'source-inputs.json': 2}}
            with patch.object(cells, 'ROOT', repo), patch.dict(cells.PASSIVE, passive, clear=True), patch.dict(cells.PASSIVE_ORIGINALS, {cells.SOURCE: {name: row['original'] for name, row in passive.items()}}, clear=True), patch.dict(cells.PINS, {'java': pin}, clear=True):
                proof = cells._equivalence(build, 'java')
                self.assertEqual(set(proof['passiveDiagnosticChanges']), set(passive))
                self.assertFalse(proof['runtimeSourceRelabeled'])
                self.assertFalse(proof['currentDiagnosticResultInferred'])
                self.assertEqual(proof['capturedSources']['source-inputs.json']['originalGeneratedApplicationWit'], {'wit/world.wit': source['wit/world.wit']})
                (repo / 'sdk/java-guest/runtime.java').write_bytes(b'changed SDK')
                with self.assertRaises(ValueError): cells._equivalence(build, 'java')
                put('sdk/java-guest/runtime.java', b'unchanged captured SDK')
                (repo / 'tools/java_guest/compiler.py').write_bytes(b'changed compiler')
                with self.assertRaises(ValueError): cells._equivalence(build, 'java')
                put('tools/java_guest/compiler.py', b'unchanged actual compiler')
                (repo / 'tools/guest_emitted_code.py').write_bytes(b'unreviewed passive change')
                with self.assertRaises(ValueError): cells._equivalence(build, 'java')
            # The compiled auxiliary census rejects both added paths and changed
            # bytes; only the exact independently reviewed golden normalizes.
            aux = {}
            golden = 'api/proto/phase1-descriptor-contract.json'
            for name in (golden, 'schemas/one.json', 'wit/one.wit', 'examples/echo-contract/wit/one.wit', '.cargo/managed-guest.toml'):
                put(name, b'original')
                aux[name] = cells.identity(b'original')
            expected = cells.identity(encoded(aux))['sha256']
            put(golden, b'reviewed golden')
            pair = {'before': cells.identity(b'original'), 'after': cells.identity(b'reviewed golden')}
            with patch.object(cells, 'ROOT', repo), patch.object(cells, 'AUXILIARY_COUNT', 5), patch.object(cells, 'AUXILIARY_BYTES', 5*len(b'original')), patch.object(cells, 'AUXILIARY_SHA', expected), patch.dict(cells.native.NON_COMPILED_DATA, {golden: pair}, clear=True):
                self.assertEqual(cells._auxiliary('after')['normalizedOnly'], [golden])
                put('api/proto/unpaid.proto', b'new input')
                with self.assertRaises(ValueError): cells._auxiliary('after')
                (repo / 'api/proto/unpaid.proto').unlink()
                put('schemas/one.json', b'changed compiled input')
                with self.assertRaises(ValueError): cells._auxiliary('after')

    def test_default_none_Go_observer_postimage_is_exact_and_only_for_original_Go_queue_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); repo = root / 'repo'; build = root / 'build'; build.mkdir()
            api = 'tools/guest_api_analysis.py'; observer = 'tools/go_capsule_build.py'
            sdk = 'sdk/go-guest/runtime.go'
            old = {'size': 3, 'digest': cells.identity(b'old')['sha256']}
            current = {'size': 3, 'digest': cells.identity(b'new')['sha256']}
            for name in (api, observer, sdk):
                path = repo / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'new')
            (build / 'recipe.json').write_bytes(encoded({api: old, observer: old}))
            (build / 'source.json').write_bytes(encoded({'vendor/lsf/' + sdk: current, 'wit/world.wit': old}))
            pin = {'source': cells.SOURCE, 'recipes': {'recipe.json': 2}, 'sources': {'source.json': 2}}
            with patch.object(cells, 'ROOT', repo), patch.dict(cells.PINS, {'java': pin, 'go-queues': pin}, clear=True), \
                    patch.dict(cells.PASSIVE, {api: {'original': old, 'current': current}}, clear=True), \
                    patch.dict(cells.PASSIVE_ORIGINALS, {cells.SOURCE: {api: old}}, clear=True), \
                    patch.object(cells, 'GO_OBSERVER_POSTIMAGE', {'original': old, 'current': current}):
                self.assertIn(observer, cells._equivalence(build, 'go-queues')['passiveDiagnosticChanges'])
                with self.assertRaises(ValueError): cells._equivalence(build, 'java')
                (repo / observer).write_bytes(b'unreviewed builder')
                with self.assertRaises(ValueError): cells._equivalence(build, 'go-queues')


if __name__ == '__main__':
    unittest.main()
