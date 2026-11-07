from pathlib import Path
import os, json
root = Path.cwd()
out = root / 'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1'
r = Path(os.environ['RUNNER_TEMP']) / 'pr1657-compiler'
j = json.loads((r / 'observation.json').read_bytes())
keys = ('schemaVersion', 'status', 'stage', 'actualApplicationCoreCompiled', 'normalBuildComplete', 'normalComponentGateRefused', 'actualGuestExecuted', 'httpCompositionIncluded', 'originalCore', 'combinedComponent', 'retainedOriginalSource', 'httpPreparedReceiptDigest', 'httpComposition', 'diagnosticComposer')
proof = {'observation': {k: j[k] for k in keys}, 'composition': json.loads((r / 'rust-http-composition.json').read_bytes()),
    'recipe': json.loads((r / 'recipe-origin.json').read_bytes()), 'recipeInputs': json.loads((r / 'recipe-inputs.json').read_bytes()),
    'sourceInventoryUtf8': (r / 'source-inputs.json').read_text(), 'runtimeUtf8': (r / 'rust-http-runtime.json').read_text(),
    'scope': 'Semantic regression projection of pinned original compiler inputs; not execution evidence',
    'fullInputDigests': json.loads((out / 'origin.json').read_bytes())['compilerMembers']}
proof['observation']['capture'] = {'sourceDigest': j['capture']['sourceDigest']}
proof['observation']['commands'] = [{k: x[k] for k in ('stage', 'exitCode')} for x in j['commands']]
(out / 'compiler-control.json').write_text(json.dumps(proof, indent=2) + '\n')
p = root / 'tools/tests/test_rust_thread_http_combined_node.py'
s = p.read_text(); pos = s.index("if __name__ == '__main__':")
s = s[:pos] + '''class CorrectedCompilerControls(unittest.TestCase):
    def retained(self):
        from tools import rust_thread_http_combined_package as package
        return json.loads((package.CATALOGUE / 'compiler-control.json').read_bytes())

    def validate(self, record):
        from tools import rust_thread_http_combined_package as package
        package.validate_producer(record['observation'], record['composition'], record['recipe'],
            record['recipeInputs'], record['sourceInventoryUtf8'].encode(), record['runtimeUtf8'].encode())

    def test_corrected_event_retains_real_source_lineage_without_reclassifying_old_failure(self):
        from tools import rust_thread_http_combined_package as package
        from tools import rust_combined_diagnostic_envelope as envelope, rust_original_delta as delta
        record = self.retained()
        self.validate(record)
        self.assertEqual(record['recipe']['head'], package.SOURCE)
        self.assertEqual(package.ORIGIN['producerJobConclusion'], 'success')
        self.assertEqual(package.ORIGIN['workflowConclusion'], 'failure')
        self.assertEqual(package.ORIGIN['historicalCompiler']['outcome'], 'failure')
        self.assertFalse(package.ORIGIN['historicalCompiler']['reclassified'])
        original = (package.CATALOGUE / 'combined-original-core.wasm').read_bytes()
        component = (package.CATALOGUE / 'combined-final-component.wasm').read_bytes()
        material = delta.encode(original, component)
        self.assertEqual(material, (package.CATALOGUE / 'combined-original-delta.bin').read_bytes())
        wrapped = envelope.frame(component, material)
        self.assertEqual({'bytes': len(wrapped), 'sha256': package.digest(wrapped)}, package.WRAPPED)
        self.assertNotEqual(component, (package.CATALOGUE.parent / 'combined-final-component.wasm').read_bytes())

    def test_incomplete_relabelled_crossed_or_mutated_compiler_evidence_refuses(self):
        original = self.retained()
        changes = [
            ('observation', 'status', 'passed'), ('observation', 'stage', 'compile'),
            ('observation', 'actualApplicationCoreCompiled', False),
            ('observation', 'normalBuildComplete', True),
            ('observation', 'normalComponentGateRefused', False),
            ('observation', 'actualGuestExecuted', True),
            ('observation', 'httpCompositionIncluded', False),
            ('composition', 'librarySourceRewritten', True),
            ('composition', 'publicGraphUnchanged', False),
            ('composition', 'signedExecutionQualification', True),
            ('recipe', 'head', '0' * 40), ('recipe', 'tree', '0' * 40),
        ]
        for section, key, value in changes:
            with self.subTest(section=section, key=key):
                changed = deepcopy(original)
                changed[section][key] = value
                with self.assertRaises(WorkflowError):
                    self.validate(changed)
        for field in ('sourceInventoryUtf8', 'runtimeUtf8'):
            changed = deepcopy(original)
            changed[field] += ' '
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                self.validate(changed)
        changed = deepcopy(original)
        changed['observation']['commands'][5]['exitCode'] = 1
        with self.assertRaises(WorkflowError):
            self.validate(changed)
        changed = deepcopy(original)
        changed['recipe']['files'].append(changed['recipe']['files'][0])
        with self.assertRaises(WorkflowError):
            self.validate(changed)

    def test_signed_node_requires_current_event_and_separate_compiler_job_result(self):
        from tools import rust_thread_http_combined_package as package
        record = {'componentDigest': package.WRAPPED['sha256'],
            'selectedHostProfile': package.PROFILE, 'compilerSource': package.SOURCE,
            'compilerRun': package.RUN, 'compilerJob': package.JOB, 'compilerArtifact': package.ARTIFACT,
            'compilerRunConclusion': package.ORIGIN['workflowConclusion'],
            'compilerJobConclusion': package.ORIGIN['producerJobConclusion'],
            'compilerWorkflowSource': package.ORIGIN['workflowSource'],
            'compilerObservationStatus': package.ORIGIN['compilerObservationStatus'],
            'applicationRecompiled': True, 'applicationRecompiledDuringAssembly': False,
            'originalCompilerObservationRewritten': False, 'normalRustBuilderRouteOpened': False}
        node.require_current_projection(record, package.WRAPPED)
        for key, value in (('compilerSource', '0' * 40), ('compilerWorkflowSource', package.SOURCE),
                           ('compilerJob', 0), ('compilerArtifact', 0), ('compilerRunConclusion', 'success'),
                           ('compilerJobConclusion', 'failure'), ('applicationRecompiled', False),
                           ('applicationRecompiledDuringAssembly', True),
                           ('originalCompilerObservationRewritten', True),
                           ('normalRustBuilderRouteOpened', True)):
            changed = {**record, key: value}
            with self.subTest(key=key), self.assertRaises(WorkflowError):
                node.require_current_projection(changed, package.WRAPPED)

    def test_framing_rejects_crossed_original_and_final_images(self):
        from tools import rust_thread_http_combined_package as package
        original = (package.CATALOGUE / 'combined-original-core.wasm').read_bytes()
        final = (package.CATALOGUE / 'combined-final-component.wasm').read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'raw-core.wasm').write_bytes(original)
            (root / 'combined-component.wasm').write_bytes(final)
            self.assertEqual(len(package.framed(root, package.CATALOGUE)), package.WRAPPED['bytes'])
            for filename, content in (('raw-core.wasm', original), ('combined-component.wasm', final)):
                altered = bytearray(content)
                altered[-1] ^= 1
                (root / filename).write_bytes(altered)
                with self.subTest(filename=filename), self.assertRaises(WorkflowError):
                    package.framed(root, package.CATALOGUE)
                (root / filename).write_bytes(content)


''' + s[pos:]
p.write_text(s)
p = root / 'crates/latent-component-threading/src/rust_component.rs'
s = p.read_text()
needle = '        assert!(verify_embedded_combined_diagnostic(&wrapped).is_ok());'
assert s.count(needle) == 1
s = s.replace(needle, needle + '''

        // Keep the historical failed bytes as evidence, not an alternative
        // runtime selector after the corrected graph has been selected.
        let historical = crate::rust_original_delta::attach_unverified(
            include_bytes!("rust_catalogue/combined-final-component.wasm"),
            include_bytes!("rust_catalogue/combined-original-delta.bin"),
        )
        .unwrap();
        assert!(!matches_fixed_combined_diagnostic(&historical));
        assert_eq!(
            verify_embedded_combined_diagnostic(&historical).unwrap_err(),
            "rust-combined-fixed-material-required"
        );''')
p.write_text(s)
