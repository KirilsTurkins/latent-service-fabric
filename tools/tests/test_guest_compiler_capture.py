"""Automatic-selection/owned-I/O controls; no compiler execution claim."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import guest_compiler_capture as capture
from tools.c_guest.compiler import Compiler
from tools.captured_compiler_isolation import Isolation
from tools.dev_workflow.common import decode, digest, encode


SOURCE = b'''bool exports_example_api_run(int seed) {
    /* fake_private_call(); */
    const char *message = "private_source_only()";
    if (0) { /* lsf-api-root-edge */ outside_denied(); }
    return seed;
}
'''
IR = b'''define i32 @exports_example_api_run(i32 %seed) {
entry:
  ret i32 %seed
}
'''
FILES = {'src/main.c': SOURCE, 'sdk-lock.json': b'{}'}
BINDINGS = {key: digest(key.encode()) for key in ('recipeDigest', 'compilerDigest', 'graphDigest')}


class AutomaticCompilerCapture(unittest.TestCase):
    def test_pinned_Go_root_name_uses_actual_compiled_package_then_unique_final_byte_match(self):
        from tools import guest_api_analysis
        from tools.tests.test_guest_emitted_code import core, section
        package = 'wit_component/export_examples_greeting_api'
        symbol = capture.go_emitted_symbol(package, 'Run')
        self.assertEqual(symbol, 'wit_component_export_examples_greeting_api.Run')
        self.assertEqual(capture.go_emitted_symbol('outside.example.test/pkg.name', 'Run'),
                         'outside.example.test_pkg_2ename.Run')
        # The upstream sanitizer is lossy. A candidate is not an observed
        # compiler binding and may not be accepted across duplicate labels.
        self.assertEqual(capture.go_emitted_symbol('a-b/p', 'Run'), capture.go_emitted_symbol('a_b/p', 'Run'))
        files = {'src/main.go': b'package entry\nimport p "outside.example.test/lib"\nfunc Run() { p.Probe() }\n'}
        raw = core([b'\x01\x0b'], names={1: symbol})
        with tempfile.TemporaryDirectory() as directory:
            owner = capture.Capture(files, 'go'); identity = owner.queries[0]['id']
            owner.bind_go_root(identity, package)
            owner.retain(identity, b'Run func()\n b1:\n Ret\n')
            record = owner.finish(Path(directory), files, raw, **{
                key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            capture.validate(record, files=files)
            result = guest_api_analysis.compiler_findings({'compiler-call-edges': record}, raw)
            self.assertEqual(result['rows'][0]['rootMapping']['state'], 'potential-root-path')
            duplicate = b'\0asm\x0d\0\x01\0' + section(1, raw) + section(1, raw)
            result = guest_api_analysis.compiler_findings({'compiler-call-edges': record}, duplicate)
            self.assertEqual(result['rows'][0]['rootMapping']['state'], 'unmapped-or-ambiguous')

    def test_Rust_conditional_binding_does_not_poison_an_unrelated_original_root(self):
        raw = (b'fn compatibility_root() -> i32 { outside::probe(); 0 }\n'
               b'#[cfg(target_arch = "wasm32")]\nmod component {\n'
               b' fn callback() { outside::different(); }\n}\n')
        rows = capture.automatic({'src/lib.rs': raw}, 'rust')['queries']
        self.assertEqual(next(row for row in rows if row['root'] == 'compatibility_root')['declarationState'],
                         'unique-captured-candidate')
        self.assertEqual(next(row for row in rows if row['root'] == 'callback')['declarationState'],
                         'conditionally-compiled-declaration')
        # A conditional semicolon-bodied/unknown item is not silently skipped.
        broken = b'#[cfg(unavailable)]\nmod missing;\nfn root() { outside::probe(); }\n'
        self.assertEqual(capture.automatic({'src/lib.rs': broken}, 'rust')['queries'], [])

    def test_Go_shadowed_or_unaliased_imports_cannot_claim_selected_package_identity(self):
        header = b'package entry\nimport primary "outside.example.test/api-primary"\n'
        for function in (b'func Run(primary Local) { primary.Probe() }\n',
                         b'func Run() { primary := local; primary.Probe() }\n',
                         b'func Run() { nested := func(primary Local) { primary.Probe() }; nested(local) }\n'):
            selected = capture.automatic({'src/main.go': header + function}, 'go')
            row = next(row for row in selected['queries'] if row['callee'] == 'primary.Probe')
            self.assertEqual(row['declarationState'], 'unresolved-receiver-binding')
            self.assertEqual(row['calleeResolution'], 'unresolved-source-spelling')
            with tempfile.TemporaryDirectory() as directory:
                owner = capture.Capture({'src/main.go': header + function}, 'go')
                owner.retain(row['id'], b'Run func()\n b1:\n Ret\n')
                value = owner.finish(Path(directory), {'src/main.go': header + function}, b'component', **{
                    key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
                actual = next(row for row in value['queries'] if row['callee'] == 'primary.Probe')
                self.assertEqual(actual['state'], 'unavailable')
        unaliased = b'package entry\nimport "outside.example.test/api-primary"\nfunc Run() { primary.Probe() }\n'
        self.assertEqual(capture.automatic({'src/main.go': unaliased}, 'go')['queries'][0]['calleeResolution'],
                         'unresolved-source-spelling')
        linked = header + b'//go:linkname Run alternate.symbol\nfunc Run() { primary.Probe() }\n'
        self.assertEqual(capture.automatic({'src/main.go': linked}, 'go')['queries'][0]['declarationState'],
                         'conditionally-compiled-declaration')
        overlong = b'package entry\nimport p "' + b'a' * 190 + b'"\nfunc Run() { p.Probe() }\n'
        with tempfile.TemporaryDirectory() as directory:
            files = {'src/main.go': overlong}; owner = capture.Capture(files, 'go')
            self.assertEqual(owner.queries[0]['declarationState'], 'unresolved-receiver-binding')
            value = owner.finish(Path(directory), files, b'component', **{
                key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            self.assertEqual(value['queries'][0]['state'], 'unavailable')

    def test_original_Go_import_alias_resolves_actual_SSA_callee_without_fixture_query(self):
        raw = (b'package entry\nimport primary "outside.example.test/api-primary"\n'
               b'func Run() { primary.Probe() }\n')
        files = {'src/main.go': raw}
        selected = capture.automatic(files, 'go')
        self.assertEqual(len(selected['queries']), 1)
        query = selected['queries'][0]
        self.assertEqual((query['callee'], query['compilerTarget'], query['calleeResolution']),
            ('primary.Probe', 'outside.example.test/api-primary.Probe', 'captured-import-identity'))
        ssa = (b'Run func()\n b1:\n (?) v1 = InitMem <mem>\n'
               b' (?) v2 = WasmLoweredStaticCall <mem> {outside.example.test/api-primary.Probe} v1\n Ret v2\n')
        with tempfile.TemporaryDirectory() as directory:
            owner = capture.Capture(files, 'go'); owner.retain(query['id'], ssa)
            value = owner.finish(Path(directory), files, b'component', **{
                key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            self.assertEqual(value['queries'][0]['observation']['state'], 'observed-direct-edge')
            capture.validate(value, files=files)
            renamed = dict(files); renamed['src/main.go'] = raw.replace(b'primary', b'renamed')
            self.assertNotEqual(capture.automatic(renamed, 'go')['queries'][0]['id'], query['id'])
        # A comment cannot bind an import, and a dot import cannot identify an
        # unqualified operand. Conflicts refuse passive observation finitely.
        for body in (b'package entry\n/*\nimport p "os"\n*/\nfunc Run() { p.Open() }\n',
                     b'package entry\nimport . "os"\nfunc Run() { Open() }\n'):
            row = capture.automatic({'src/main.go': body}, 'go')['queries'][0]
            self.assertEqual(row['calleeResolution'], 'unresolved-source-spelling')
        conflict = raw.replace(b'func Run', b'import primary "another.example.test/api"\nfunc Run')
        self.assertEqual(capture.automatic({'src/main.go': conflict}, 'go')['queries'], [])

    def test_inactive_no_call_declaration_prevents_wrong_source_body_binding(self):
        for language, files, raw in (
            ('go', {'src/inactive.go': b'//go:build unavailable\npackage entry\nfunc Run() { outside_denied() }\n',
                    'src/active.go': b'package entry\nfunc Run() { return }\n'},
             b'Run func()\n  b1:\n    Ret\n'),
            ('rust', {'src/inactive.rs': b'#[cfg(unavailable)]\npub fn run() { outside_denied(); }\n',
                      'src/active.rs': b'pub fn run() { return; }\n'},
             b'fn run() -> () {\n    bb0: {\n        return;\n    }\n}\n')):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                owner = capture.Capture(files, language)
                self.assertEqual(len(owner.queries), 1)  # active declaration has NO call/query
                query = owner.queries[0]
                self.assertEqual(query['declarationState'], 'ambiguous-captured-declaration')
                owner.retain(query['id'], raw)
                value = owner.finish(Path(directory), files, b'component', **{
                    key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
                self.assertEqual(value['queries'][0]['state'], 'unavailable')

    def test_real_namespace_command_forwards_only_existing_owned_writable_SSA_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workspace = root / 'workspace'; workspace.mkdir()
            output = workspace / 'SSA'; output.mkdir()
            protected = workspace / 'captured'; protected.mkdir()
            outside = root / 'outside'; outside.mkdir()
            tool = root / 'go'; tool.write_bytes(b'compiler identity only')
            owner = Isolation.__new__(Isolation)
            owner.workspace, owner.tools = workspace, {'go': tool}
            owner.sandbox, owner.child_path = root / 'bwrap', None
            owner.distributions, owner.shared, owner.loader_directories = {}, {}, []
            owner.read_only_inputs = [protected]
            command = owner.wrap(tool, ['version'], workspace, {'GOSSADIR': str(output)})
            at = command.index('GOSSADIR')
            self.assertEqual(command[at - 1:at + 2], ['--setenv', 'GOSSADIR', str(output)])
            for forbidden in (str(outside), str(protected), str(workspace), 'relative'):
                with self.subTest(forbidden=forbidden), self.assertRaises(ValueError):
                    owner.wrap(tool, ['version'], workspace, {'GOSSADIR': forbidden})

    def test_normal_source_generates_queries_without_application_manifest_and_masks_literals(self):
        selected = capture.automatic(FILES, 'c')
        self.assertEqual([(row['root'], row['callee'], row['declarationRole']) for row in selected['queries']],
                         [('exports_example_api_run', 'outside_denied', 'export-declaration')])
        injected = dict(FILES, **{'compiler-queries.json': encode({'queries': [{'root': 'forged'}]})})
        actual = capture.automatic(injected, 'c')
        self.assertEqual(actual['queries'], selected['queries'])
        self.assertNotEqual(actual['sourceDigest'], selected['sourceDigest'])
        self.assertEqual(selected['apiResolution'], 'unknown')

    def test_initialization_and_export_candidates_precede_finite_omissions(self):
        functions = b'\n'.join(('int local_%d(void) { ordinary_%d(); return 0; }' % (n, n)).encode()
                              for n in range(40))
        files = {'src/a.c': functions, 'src/z.c': b'int initialize_root(void) { initialize_api(); return 0; }\n' + SOURCE}
        selected = capture.automatic(files, 'c')
        self.assertEqual(len(selected['queries']), capture.MAX_QUERIES)
        self.assertEqual([row['declarationRole'] for row in selected['queries'][:2]],
                         ['initializer-declaration', 'export-declaration'])
        self.assertEqual(selected['omittedQueries'], 10)
        self.assertEqual(selected['rootReachability'], 'unknown')

    def test_unknown_source_syntax_and_unavailable_witness_never_become_eliminated(self):
        files = {'src/main.rs': b"pub fn run<'a>(x: &'a str) { outside::denied(); }"}
        selected = capture.automatic(files, 'rust')
        self.assertEqual(selected['queries'], [])
        self.assertEqual(selected['unmappedSourceUnits'], 1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            raw = capture.Capture(FILES, 'c')
            value = raw.finish(output, FILES, b'component', **{key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            self.assertEqual(value['queries'][0]['state'], 'unavailable')
            self.assertEqual((value['wholeProgramElimination'], value['apiSupport']), ('unknown', 'unknown'))

    def test_real_output_bytes_bind_original_source_component_compiler_and_query(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            raw = capture.Capture(FILES, 'c')
            raw.retain_unit('src/main.c', IR)
            value = raw.finish(output, FILES, b'component', **{key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            self.assertEqual(value['queries'][0]['observation']['state'], 'edge-not-observed')
            before = (output / capture.OUTPUT).read_bytes()
            self.assertEqual(decode(before), value)
            altered = copy.deepcopy(value)
            altered['queries'][0]['callee'] = 'different_api'
            altered['identity'] = digest(encode({key: val for key, val in altered.items() if key != 'identity'}))
            with self.assertRaises(ValueError): capture.validate(altered, files=FILES)
            changed_files = dict(FILES, **{'src/main.c': SOURCE.replace(b'outside_denied', b'different_api')})
            with self.assertRaises(ValueError): capture.validate(value, files=changed_files)
            with self.assertRaises(ValueError): raw.finish(output, changed_files, b'component', **{
                key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            self.assertEqual((output / capture.OUTPUT).read_bytes(), before)
            normal = output / 'normal'; normal.mkdir()
            owner = capture.Capture(FILES, 'c'); owner.retain_unit('src/main.c', IR)
            material = capture.finish(owner, normal, FILES, b'component', b'actual recipe inventory',
                                      BINDINGS['compilerDigest'])
            retained = (normal / capture.OUTPUT).read_bytes()
            self.assertEqual(material, {'name': 'compiler-call-edges', 'digest': digest(retained), 'size': len(retained)})

    def test_actual_c_observer_retains_compile_flags_without_mutating_original_component_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / 'main.c'; source.write_bytes(SOURCE)
            helper, archive, core = output / 'probe.c', output / 'dependency.a', output / 'core.wasm'
            owner = Compiler.__new__(Compiler)
            owner.compiler_edges = capture.Capture(FILES, 'c')
            owner.compiler_edge_sources = {'src/main.c': source}
            owner.check_unchanged = lambda: None
            calls = []
            def compiler(tool, *argv):
                calls.append((tool, argv))
                Path(argv[argv.index('-o') + 1]).write_bytes(IR)
            owner.run = compiler
            original = ['cc', '-std=c23', '-target', 'wasm32-wasi', '-O2', '-Werror',
                        '-DRESOURCE=source.c', '-I', 'captured/include', '-Wl,--max-memory=67108864',
                        str(source), str(helper), str(archive), '-o', str(core)]
            before = original.copy()
            owner.observe_compiler_edges(original, output, [source, helper, archive])
            self.assertEqual(original, before)
            self.assertEqual(calls, [('zig', ('cc', '-std=c23', '-target', 'wasm32-wasi', '-O2', '-Werror',
                '-DRESOURCE=source.c', '-I', 'captured/include', '-S', '-emit-llvm', str(source),
                '-o', str(output / 'compiler-edge-0000.ll')))])
            self.assertEqual(next(iter(owner.compiler_edges.raw.values())), IR)

    def test_failed_real_observer_attempt_cannot_supply_a_negative_witness(self):
        with tempfile.TemporaryDirectory() as directory:
            owner = Compiler.__new__(Compiler)
            owner.compiler_edges = capture.Capture(FILES, 'c')
            owner.compiler_edge_sources = {'src/main.c': Path(directory) / 'source.c'}
            owner.check_unchanged = lambda: None
            def failed(*args): raise ValueError('private-compiler-error')
            owner.run = failed
            owner.observe_compiler_edges(['cc', '-O2'], Path(directory), [])
            value = owner.compiler_edges.finish(Path(directory), FILES, b'component', **{
                key.removesuffix('Digest'): val for key, val in BINDINGS.items()})
            self.assertEqual(value['queries'][0]['state'], 'unavailable')
            self.assertNotIn('private-compiler-error', encode(value).decode())


if __name__ == '__main__': unittest.main()
