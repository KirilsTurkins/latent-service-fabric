"""Current compiler-material oracle tests; synthetic bytes establish no compilation."""
import copy
import json
import unittest
import io
import gzip
import tarfile
from dataclasses import replace

from tools.java_transaction_qualification import current_inputs as current
from tools.java_transaction_qualification.inputs import digest, WORLD
from tools.rust_capsule_project import inventory


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture():
    project = {"transaction-binding.json": b"exact-companion", "transaction-profile.json": encoded({"hostAbiDigest": "sha256:" + "a" * 64}),
               "vendor/lsf/sdk/java-guest/" + "captured/" * 10 + "LongSource.java": b"original-source"}
    component = b"\0asm\x0d\0\x01\0" + b"synthetic-test-input"
    files = {"project/" + name: raw for name, raw in project.items()}
    archive = io.BytesIO()
    with gzip.GzipFile(fileobj=archive, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as captured:
            for name, raw in project.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                captured.addfile(entry, io.BytesIO(raw))
    files.update({"component.wasm": component, "source-inputs.json": inventory(project), "source.tar.gz": archive.getvalue(),
                  "recipe-inputs.json": b"original-recipe", "compiler-inputs.json": b"original-tools"})
    report = {"schemaVersion": "latent.transaction-guest.compiler.v1", "language": "java", "variant": "aggregate",
              "evidenceKind": "authored-component-compiler", "world": WORLD, "sourceRevision": "1" * 40,
              "status": "compiled", "compiled": True, "workingTreeChanged": False,
              "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
              "componentBytes": len(component), "componentDigest": digest(component),
              "sourceDigest": digest(files["source-inputs.json"]), "sourceArchiveDigest": digest(files["source.tar.gz"]),
              "recipeDigest": digest(files["recipe-inputs.json"]), "companionDigest": digest(project["transaction-binding.json"]),
              "hostAbiDigest": "sha256:" + "a" * 64, "actualImports": sorted(current.REQUIRED_IMPORTS),
              "details": {"commands": [{"stage": name, "exitCode": 0} for name in sorted(current.SUCCESS_STAGES)]}}
    files["report.json"] = encoded(report)
    selection = current.CurrentSelection("1" * 40, "aggregate", digest(files["report.json"]), digest(component), digest(files["compiler-inputs.json"]))
    return files, selection


class CurrentJavaInputs(unittest.TestCase):
    def test_independent_selected_report_and_source_materials_preserve_original_bytes(self):
        files, selected = fixture()
        before = copy.deepcopy(files)
        report = current.validate_materials(files, selected)
        self.assertEqual(report["sourceRevision"], selected.source_commit)
        self.assertFalse(report["signedNodeExecutionQualified"])
        self.assertEqual(files, before)

    def test_changed_component_report_source_or_tool_closure_refuses(self):
        for name in ("component.wasm", "report.json", "source-inputs.json", "source.tar.gz", "recipe-inputs.json", "compiler-inputs.json", "project/transaction-binding.json"):
            files, selected = fixture()
            files[name] += b"changed"
            with self.subTest(material=name), self.assertRaises(ValueError):
                current.validate_materials(files, selected)
        files, selected = fixture()
        with self.assertRaises(ValueError):
            current.validate_materials(files, replace(selected, source_commit="2" * 40))

    def test_failed_missing_stages_and_claimed_signed_execution_refuse_even_with_reselected_report_digest(self):
        for change in ("failed-stage", "missing-stage", "signed-claim", "dirty-source", "foreign-language"):
            files, selected = fixture()
            report = json.loads(files["report.json"])
            if change == "failed-stage": report["details"]["commands"][0]["exitCode"] = 1
            elif change == "missing-stage": report["details"]["commands"].pop()
            elif change == "signed-claim": report["signedNodeExecutionQualified"] = True
            elif change == "dirty-source": report["workingTreeChanged"] = True
            else: report["language"] = "go"
            files["report.json"] = encoded(report)
            with self.subTest(change=change), self.assertRaises(ValueError):
                current.validate_materials(files, replace(selected, report_digest=digest(files["report.json"])))

    def test_declared_import_profile_and_selection_bounds_refuse(self):
        files, selected = fixture()
        for value in (replace(selected, source_commit="short"), replace(selected, variant="guessed"), replace(selected, component_digest="digest")):
            with self.subTest(selection=value), self.assertRaises(ValueError): current.validate_materials(files, value)
        report = json.loads(files["report.json"])
        report["actualImports"].append("latent:http/client@0.2.0")
        files["report.json"] = encoded(report)
        with self.assertRaises(ValueError): current.validate_materials(files, replace(selected, report_digest=digest(files["report.json"])))


class CurrentJavaNativeMemoryPackaging(unittest.TestCase):
    def test_terminal_and_pending_identity_bind_native_memory_custody_packet_bytes(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import patch
        from tools import run_java_transaction_http_qualification as terminal
        from tools import run_java_pending_recovery_qualification as pending
        packet = 'docs/testing/evidence/java-current-native-memory-capture-2026-10-14.json'
        self.assertIn(packet, terminal.COLLECTORS)
        source = Path(terminal.__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in dict.fromkeys(terminal.COLLECTORS + pending.EXTRA_COLLECTORS):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((source / name).read_bytes())
            with patch.object(terminal, '__file__', str(root / 'tools/run_java_transaction_http_qualification.py')), \
                    patch.object(pending, '__file__', str(root / 'tools/run_java_pending_recovery_qualification.py')):
                before, inherited = terminal.collector_identity(), pending.collector_identity()
                self.assertEqual(before[packet], inherited[packet])
                path = root / packet
                path.write_bytes(path.read_bytes() + b'\n')
                after, inherited_after = terminal.collector_identity(), pending.collector_identity()
                self.assertNotEqual(before[packet], after[packet])
                self.assertEqual(after[packet], inherited_after[packet])
                for original, changed in ((before, after), (inherited, inherited_after)):
                    self.assertEqual({name: value for name, value in original.items() if name != packet},
                                     {name: value for name, value in changed.items() if name != packet})

    def context(self):
        from pathlib import Path
        from types import SimpleNamespace
        names, packets = CurrentJavaPackaging.signing_packets()
        for packet in packets.values():
            packet['captures']['sourceCommit'] = '9bae83952d9513c965a88d375b2a533916a98473'
        source = 'eba0d96e9439028aacd6c1f9a85d4ce0118a19bc'
        filename = 'java-current-native-memory-capture-2026-10-14.json'
        packets[filename] = {'captures': {'sourceCommit': source,
            'nativeIdempotencyProfile': 'qualified-http-v1:74c19c60dccdecdca0b94eb8c88776516aa77c261b21dc978dab9793f9600cc5',
            'variants': {name: {'materials': {'report': {'sha256': digest(('native-memory:' + name).encode())}}}
                         for name in names}}}
        items = [SimpleNamespace(name=name, directory=Path('/capture') / name, compiler_source=source)
                 for name in names]
        return items, packets, filename, source

    def test_native_memory_signing_requires_complete_new_report_set_under_its_source(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        items, packets, _, _ = self.context()
        def material(path, *_args):
            return encoded(packets[path.name]) if path.name != 'report.json' else ('native-memory:' + path.parent.name).encode()
        with patch.object(packaging, 'read_file', side_effect=material):
            self.assertEqual(packaging.current_signing_mode(items), 'fixture-sign-native-memory-current-java-inputs')
            for changed in (items[:-1], items + [items[0]], items[:-1] + [items[0]]):
                with self.subTest(incomplete=[item.name for item in changed]), self.assertRaises(ValueError):
                    packaging.current_signing_mode(changed)

    def test_native_memory_signing_rejects_mixed_sources_profiles_and_old_report_substitution(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        for other in ('historical:', '', 'fresh:', 'unreviewed:'):
            items, packets, _, _ = self.context()
            def mixed(path, *_args):
                if path.name != 'report.json':
                    return encoded(packets[path.name])
                return ((other if path.parent.name == 'aggregate' else 'native-memory:') + path.parent.name).encode()
            with self.subTest(report=other), patch.object(packaging, 'read_file', side_effect=mixed), self.assertRaises(ValueError):
                packaging.current_signing_mode(items)
        items, packets, filename, source = self.context()
        def selected(path, *_args):
            return encoded(packets[path.name]) if path.name != 'report.json' else ('native-memory:' + path.parent.name).encode()
        with patch.object(packaging, 'read_file', side_effect=selected):
            for wrong_source in ('9bae83952d9513c965a88d375b2a533916a98473', 'f' * 40):
                items[0].compiler_source = wrong_source
                with self.subTest(source=wrong_source), self.assertRaises(ValueError):
                    packaging.current_signing_mode(items)
            items[0].compiler_source = source
            packets[filename]['captures']['nativeIdempotencyProfile'] = packets['pr970-current-post-evidence.json']['captures']['nativeIdempotencyProfile']
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items)
            packets[filename]['captures']['nativeIdempotencyProfile'] = 'qualified-http-v1:74c19c60dccdecdca0b94eb8c88776516aa77c261b21dc978dab9793f9600cc5'
            for item in items:
                item.compiler_source = 'f' * 40
            packets[filename]['captures']['sourceCommit'] = 'f' * 40
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items)


class CurrentJavaPackaging(unittest.TestCase):
    @staticmethod
    def signing_packets():
        names = ('aggregate', 'put-once-legacy-v1', 'put-once-compatible-v2', 'put-once-writer-v2', 'put-once-diagnostics')
        packets = {}
        for filename, prefix, profile in (
                ('pr970-current-post-evidence.json', 'historical:', '96de426fb7aebd66c97033631e9aec1f85d4eac11f581637e67b7f25239bd161'),
                ('java-current-rebuilt-capture-2026-10-13.json', '', '96de426fb7aebd66c97033631e9aec1f85d4eac11f581637e67b7f25239bd161'),
                ('java-current-fresh-http-capture-2026-10-13.json', 'fresh:', '74c19c60dccdecdca0b94eb8c88776516aa77c261b21dc978dab9793f9600cc5')):
            packets[filename] = {'captures': {'sourceCommit': 'a' * 40,
                'nativeIdempotencyProfile': 'qualified-http-v1:' + profile,
                'variants': {name: {'materials': {'report': {'sha256': digest((prefix + name).encode())}}}
                             for name in names}}}
        return names, packets

    def test_recompiled_signing_requires_complete_exact_report_set(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        names, packets = self.signing_packets()
        source = '9bae83952d9513c965a88d375b2a533916a98473'
        for packet in packets.values():
            packet['captures']['sourceCommit'] = source
        _, native_packets, native_filename, _ = CurrentJavaNativeMemoryPackaging().context()
        packets[native_filename] = native_packets[native_filename]
        items = [SimpleNamespace(name=name, directory=Path('/capture') / name,
                                 compiler_source=source) for name in names]
        def material(path, *_args):
            return encoded(packets[path.name]) if path.name != 'report.json' else path.parent.name.encode()
        with patch.object(packaging, 'read_file', side_effect=material):
            self.assertEqual(packaging.current_signing_mode(items), 'fixture-sign-rebuilt-current-java-inputs')
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items[:-1])
            items[0].compiler_source = 'b' * 40
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items)
        def mixed(path, *_args):
            if path.name != 'report.json':
                return encoded(packets[path.name])
            return b'historical' if path.parent.name == 'aggregate' else path.parent.name.encode()
        with patch.object(packaging, 'read_file', side_effect=mixed):
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items)

    def test_fresh_http_signing_requires_one_complete_closed_capture_report_set(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        names, packets = self.signing_packets()
        source = '9bae83952d9513c965a88d375b2a533916a98473'
        for packet in packets.values():
            packet['captures']['sourceCommit'] = source
        _, native_packets, native_filename, _ = CurrentJavaNativeMemoryPackaging().context()
        packets[native_filename] = native_packets[native_filename]
        items = [SimpleNamespace(name=name, directory=Path('/capture') / name,
                                 compiler_source=source) for name in names]
        for prefix, mode in (('historical:', 'fixture-sign-current-java-inputs'),
                             ('', 'fixture-sign-rebuilt-current-java-inputs'),
                             ('fresh:', 'fixture-sign-fresh-http-current-java-inputs')):
            def material(path, *_args):
                return encoded(packets[path.name]) if path.name != 'report.json' else (prefix + path.parent.name).encode()
            with self.subTest(mode=mode), patch.object(packaging, 'read_file', side_effect=material):
                self.assertEqual(packaging.current_signing_mode(items), mode)
                for changed in (items[:-1], items + [items[0]], items[:-1] + [items[0]]):
                    with self.assertRaises(ValueError):
                        packaging.current_signing_mode(changed)

    def test_fresh_http_custody_profile_mixed_reports_and_foreign_source_refuse(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        names, packets = self.signing_packets()
        source = '9bae83952d9513c965a88d375b2a533916a98473'
        for packet in packets.values():
            packet['captures']['sourceCommit'] = source
        _, native_packets, native_filename, _ = CurrentJavaNativeMemoryPackaging().context()
        packets[native_filename] = native_packets[native_filename]
        items = [SimpleNamespace(name=name, directory=Path('/capture') / name,
                                 compiler_source=source) for name in names]
        for other in ('historical:', '', 'unreviewed:'):
            def mixed(path, *_args):
                if path.name != 'report.json':
                    return encoded(packets[path.name])
                return ((other if path.parent.name == 'aggregate' else 'fresh:') + path.parent.name).encode()
            with self.subTest(mixed=other), patch.object(packaging, 'read_file', side_effect=mixed):
                with self.assertRaises(ValueError):
                    packaging.current_signing_mode(items)
        def fresh(path, *_args):
            return encoded(packets[path.name]) if path.name != 'report.json' else ('fresh:' + path.parent.name).encode()
        with patch.object(packaging, 'read_file', side_effect=fresh):
            items[0].compiler_source = 'b' * 40
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items)
            items[0].compiler_source = source
            packets['java-current-fresh-http-capture-2026-10-13.json']['captures']['nativeIdempotencyProfile'] = \
                packets['java-current-rebuilt-capture-2026-10-13.json']['captures']['nativeIdempotencyProfile']
            with self.assertRaises(ValueError):
                packaging.current_signing_mode(items)

    def test_separate_early_capture_keeps_original_six_selection_closed_and_rejects_claims_or_late_call(self):
        from pathlib import Path
        from unittest.mock import patch
        from tools.java_transaction_qualification import early_http_inputs as early
        from tools.java_transaction_qualification.current_inputs import CurrentSelection
        from tools.java_transaction_qualification.inputs import digest
        selected = CurrentSelection('a' * 40, early.VARIANT, 'sha256:' + 'b' * 64,
                                    'sha256:' + 'c' * 64, 'sha256:' + 'd' * 64)
        with self.assertRaises(ValueError):
            selected.validate()
        source = b'''try (var command = State.acquireCommand().value()) {
Bindings.LatentHttpClient.send(
Bindings.LatentHttpClientHttpError.permissionDenied().tag()
command.get(KEY)
command.put(KEY
.stage(command)
}'''
        declaration = {'schemaVersion': 'latent.java.early-http-denial-input.v1', 'variant': early.VARIANT,
            'originalPostStageSourceDigest': 'sha256:' + 'e' * 64, 'sourceDigest': digest(source),
            'worldDigest': digest(b'world'), 'companionDigest': 'sha256:' + 'f' * 64,
            'callBefore': ['state-get', 'state-put', 'intent-stage'], 'expectedTypedError': 'permission-denied',
            'expectedBusinessResult': 'rejected', 'componentCompiled': False, 'signedExecutionQualified': False,
            'immediateHttpDenialQualified': False, 'postStageRollbackQualified': False}
        files = {'project/java-early-http-denial-input.json': encoded(declaration),
                 'project/src/dev/latent/app/Capsule.java': source, 'project/wit/world.wit': b'world',
                 'project/capsule-project.json': encoded({
                     'service': 'examples/transaction-java-forbidden-http-before-stage',
                     'limits': {'cpuFuel': 1_000_000_000, 'memoryBytes': 67_108_864,
                         'wallTimeLimitMillis': 120000, 'childCalls': 0, 'outboundRequests': 0,
                         'stateReadBytes': 4194304, 'stateWriteBytes': 2097152, 'blobReadBytes': 0,
                         'blobWriteBytes': 0, 'logBytes': 0, 'effectCount': 32}})}
        report = {'earlyHttpDenialInputDigest': digest(files['project/java-early-http-denial-input.json']),
            'companionDigest': declaration['companionDigest'], 'componentDigest': selected.component_digest,
            'sourceDigest': 'sha256:' + '1' * 64, 'hostAbiDigest': 'sha256:' + '2' * 64,
            'immediateHttpDenialQualified': False, 'postStageRollbackQualified': False}
        with patch.object(early, '_validate_materials', return_value=report) as captured:
            result = early.validate_files(Path('captured'), files, selected)
        self.assertEqual(result.name, early.VARIANT)
        captured.assert_called_once_with(files, selected, (early.VARIANT,))
        for changed in ({'approved': True}, {'componentCompiled': True}, {'expectedTypedError': 'unavailable'}):
            invalid = dict(files, **{'project/java-early-http-denial-input.json': encoded(dict(declaration, **changed))})
            with patch.object(early, '_validate_materials', return_value=report), self.assertRaises(ValueError):
                early.validate_files(Path('captured'), invalid, selected)
        invalid = dict(files, **{'project/java-current-http-profile.json': b'marker'})
        with patch.object(early, '_validate_materials', return_value=report), self.assertRaises(ValueError):
            early.validate_files(Path('captured'), invalid, selected)
        late = source.replace(b'Bindings.LatentHttpClient.send(\n', b'') + b'Bindings.LatentHttpClient.send(\n'
        changed = dict(declaration, sourceDigest=digest(late))
        invalid = dict(files, **{'project/src/dev/latent/app/Capsule.java': late,
                                'project/java-early-http-denial-input.json': encoded(changed)})
        late_report = dict(report, earlyHttpDenialInputDigest=digest(invalid['project/java-early-http-denial-input.json']))
        with patch.object(early, '_validate_materials', return_value=late_report), self.assertRaises(ValueError):
            early.validate_files(Path('captured'), invalid, selected)

    def test_package_retains_exact_current_marker_and_negative_source_as_signed_assets(self):
        from types import SimpleNamespace
        from tools.java_transaction_qualification import packaging
        files = {'wit/world.wit': b'captured world', 'state-schema.json': b'captured schema',
                 'transaction-profile.json': b'captured profile',
                 'deferred-http-requirements.json': b'captured requirements',
                 'java-current-http-profile.json': b'captured current marker',
                 'src/dev/latent/app/Capsule.java': b'captured source'}
        item = SimpleNamespace(name='put-once-legacy-v1', requirements_digest='sha256:' + 'a' * 64)
        retained = packaging.captured_assets(item, files)
        self.assertIs(retained['java-current-http-profile.json'], files['java-current-http-profile.json'])
        self.assertIs(retained['deferred-http-requirements.json'], files['deferred-http-requirements.json'])
        item = SimpleNamespace(name='forbidden-http', requirements_digest=None)
        negative = {name: raw for name, raw in files.items()
                    if name not in {'deferred-http-requirements.json', 'java-current-http-profile.json'}}
        retained = packaging.captured_assets(item, negative)
        self.assertIs(retained['src/dev/latent/app/Capsule.java'], negative['src/dev/latent/app/Capsule.java'])
        self.assertNotIn('java-current-http-profile.json', retained)
        for changed, selected in ((files, item), (files, SimpleNamespace(name='aggregate', requirements_digest=None))):
            with self.assertRaises(ValueError):
                packaging.captured_assets(selected, changed)

    def test_current_forbidden_preparation_preserves_signature_without_claiming_execution_denial(self):
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        surface = {'world': packaging.WORLD, 'imports': sorted({
            'latent:state/key-value@0.2.0', 'latent:intents/staging@0.1.0',
            'latent:http/client@0.2.0', 'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'}),
            'exports': ['examples:transactional-aggregate/api@1.0.0']}
        item = SimpleNamespace(name='forbidden-http', component_digest='sha256:' + 'a' * 64)
        record = {'currentPreparationControls': [], 'profileRejections': []}
        with patch.object(packaging, 'prepare') as prepared, \
             patch.object(packaging, 'read_file', return_value=encoded(surface)), \
             patch.object(packaging, 'write_json'):
            packaging._current_forbidden_preparation(item, Path('output'), Path('contracts'),
                Path('signer'), object(), record)
        prepared.assert_called_once()
        self.assertEqual(record['profileRejections'], [])
        observed = record['currentPreparationControls'][0]
        for field in ('signed', 'executionAuthorized', 'requestDispatched',
                      'immediateHttpDenialQualified', 'signedNodeExecutionQualified'):
            self.assertIs(observed[field], False)
        for changed in (dict(surface, imports=[]), dict(surface, exports=[]),
                        dict(surface, world='another:world/service@1.0.0'), dict(surface, approved=True)):
            with self.subTest(changed=changed), patch.object(packaging, 'prepare'), \
                 patch.object(packaging, 'read_file', return_value=encoded(changed)), \
                 patch.object(packaging, 'write_json', side_effect=AssertionError('must not record malformed surface')):
                with self.assertRaises(ValueError):
                    packaging._current_forbidden_preparation(item, Path('output'), Path('contracts'),
                        Path('signer'), object(), record)

    def test_current_package_selects_explicit_compiler_source_without_historical_fallback(self):
        from pathlib import Path
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        from tools.java_transaction_qualification.inputs import ComponentInput
        _, selected = fixture()
        first = ComponentInput("aggregate", Path("one"), "sha256:" + "1" * 64, "companion", "source", "1" * 40, "abi", None)
        negative = replace(first, name="forbidden-http", directory=Path("two"), component_digest="sha256:" + "2" * 64)
        choices = ((Path("one"), selected), (Path("two"), replace(selected, variant="forbidden-http")))
        with patch.object(current, "load_current", side_effect=(first, negative)), \
                patch.object(packaging, "_package_items", return_value=Path("signed")) as signer:
            self.assertEqual(packaging.package_current(choices, Path("output"), Path("contracts"), Path("signer")), Path("signed"))
        signer.assert_called_once_with((first, negative), Path("output"), Path("contracts"), Path("signer"),
                                       timeout=600, compiler_source="1" * 40)

    def test_current_selection_requires_both_original_and_forbidden_before_any_signing(self):
        from pathlib import Path
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        files, selected = fixture()
        with patch.object(current, "load_current", side_effect=AssertionError("must not load malformed selection")), \
                patch.object(packaging, "_package_items", side_effect=AssertionError("must not sign malformed selection")):
            for value in ([], (), ("guessed",), ((Path("one"), "guessed"),)):
                with self.subTest(selection=value), self.assertRaises(ValueError):
                    packaging.package_current(value, Path("output"), Path("contracts"), Path("signer"))

    def test_duplicate_variant_or_mixed_source_refuses_without_invoking_signer(self):
        from pathlib import Path
        from unittest.mock import patch
        from tools.java_transaction_qualification import packaging
        from tools.java_transaction_qualification.inputs import ComponentInput
        _, selected = fixture()
        first = ComponentInput("aggregate", Path("one"), "sha256:" + "1" * 64, "companion", "source", "1" * 40, "abi", None)
        negative = ComponentInput("forbidden-http", Path("two"), "sha256:" + "2" * 64, "companion", "source", "2" * 40, "abi", None)
        choices = ((Path("one"), selected), (Path("two"), replace(selected, variant="forbidden-http")))
        for items in ((first, first), (first, negative), (first,)):
            with self.subTest(items=items), patch.object(current, "load_current", side_effect=items), \
                    patch.object(packaging, "_package_items", side_effect=AssertionError("must not sign mismatched originals")):
                with self.assertRaises(ValueError):
                    packaging.package_current(choices if len(items) == 2 else choices[:1], Path("output"), Path("contracts"), Path("signer"))


class CurrentJavaCampaign(unittest.TestCase):
    def document(self):
        rows = [{"sourceCommit": "1" * 40, "variant": name,
                 "reportDigest": "sha256:" + str(index) * 64,
                 "componentDigest": "sha256:" + str(index) * 64,
                 "compilerInputsDigest": "sha256:" + "a" * 64}
                for index, name in enumerate(current.NAMES, start=1)]
        return {"schemaVersion": "latent.java.current-campaign-selections.v1", "selections": rows}

    def test_current_campaign_requires_all_six_distinct_explicit_captures_with_original_digest(self):
        from pathlib import Path
        import tempfile
        from tools.java_transaction_qualification import current_campaign
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "selected.json"
            raw = encoded(self.document())
            path.write_bytes(raw)
            result = current_campaign.selections(root, path, digest(raw))
            self.assertEqual({row.variant for _directory, row in result}, set(current.NAMES))
            self.assertEqual({row.source_commit for _directory, row in result}, {"1" * 40})
            self.assertEqual(path.read_bytes(), raw)
            with self.assertRaises(ValueError):
                current_campaign.selections(root, path, "sha256:" + "f" * 64)

    def test_current_campaign_refuses_partial_duplicate_mixed_source_or_claimed_authority(self):
        from pathlib import Path
        import tempfile
        from tools.java_transaction_qualification import current_campaign
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "selected.json"
            for name in ("missing", "duplicate", "mixed", "authority"):
                value = self.document()
                if name == "missing": value["selections"].pop()
                elif name == "duplicate": value["selections"][1] = value["selections"][0]
                elif name == "mixed": value["selections"][1]["sourceCommit"] = "2" * 40
                else: value["selections"][0]["signedNodeExecutionQualified"] = True
                raw = encoded(value)
                path.write_bytes(raw)
                with self.subTest(change=name), self.assertRaises(ValueError):
                    current_campaign.selections(root, path, digest(raw))


if __name__ == "__main__":
    unittest.main()
