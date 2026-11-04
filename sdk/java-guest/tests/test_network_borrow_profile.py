"""Exact generated network borrow selection and owned Java resource controls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.java_capsule_project import ROOT
from tools.java_guest import async_imports, bindings, java
from tools.java_guest.model import Graph, cident, snake


def network_graph(data=None, *, synchronous_ready=False, aggregate=False):
    if data is None:
        data = json.loads((ROOT/'tools/tests/fixtures/typescript_runtime_profile/borrow-void-function.json').read_bytes())
    selected = next(world for world in data['worlds'] if world['name'] == 'service')
    probe = object.__new__(Graph)
    probe.data = data
    header = ''
    for direction in ('imports', 'exports'):
        for entry in selected[direction].values():
            index = entry['interface']['id']
            interface = data['interfaces'][index]
            prefix = probe.c_prefix(index, direction == 'exports')
            for function in interface['functions'].values():
                asynchronous = (direction == 'imports' and function['kind'] == 'async-freestanding'
                                and not (synchronous_ready and index == 0 and function['name'] == 'ready'))
                result = 'probe_subtask_status_t' if asynchronous else 'void'
                symbol = prefix + '_' + snake(function['name'])
                if asynchronous and aggregate and len(function['params']) > 1:
                    fields = ' '.join('probe_value ' + cident(p['name']) + ';' for p in function['params'])
                    header += f'typedef struct {symbol}_args {{ {fields} }} {symbol}_args_t;\n'
                    arguments = [symbol + '_args_t *args']
                else:
                    arguments = ['probe_value arg' + str(i) for i, _ in enumerate(function['params'])]
                if function.get('result') is not None:
                    arguments.append('probe_value *result')
                header += f'extern {result} {symbol}(' + (', '.join(arguments) or 'void') + ');\n'
    return data, header


class NetworkBorrowProfile(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('LATENT_JAVA_NETWORK_BINDGEN') == '1', 'pinned native WIT tools')
    def test_real_generated_network_copies_input_before_async_dispatch(self):
        from tools import stage_runtime_wit
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root/'wit'
            stage_runtime_wit.stage(staged, ROOT/'sdk/java-guest/tests/network')
            graphs = []
            def run(stage, tool, *arguments):
                process = subprocess.run([tool, *map(str, arguments)], capture_output=True, text=True, timeout=60)
                self.assertEqual(process.returncode, 0, stage + ': ' + process.stderr)
                if stage == 'wit-graph': graphs.append(json.loads(process.stdout))
                return process.stdout
            output = root/'bindings'
            bindings.generate(run, staged, 'service', output, activation_profile=True, fiber_io_profile=True)
            self.assertEqual(len(graphs), 1)
            graph = Graph(graphs[0], 'service', (output/'probe.h').read_text(encoding='utf-8'), async_imports=True)
            interface = next(index for index, value in enumerate(graph.data['interfaces'])
                if value.get('name') == 'streams'
                and graph.data['packages'][value['package']]['name'] == 'latent:network@0.1.0')
            read, = [f for f in graph.imports if f['interface'] == interface and f['name'] == 'read']
            write, = [f for f in graph.imports if f['interface'] == interface and f['name'] == 'write']
            bridge = (output/'bridge.c').read_text(encoding='utf-8')
            begin = bridge.split('void *lsf_java_async_begin', 1)[1].split('int32_t lsf_java_async_state', 1)[0]
            cancel = bridge.split('int32_t lsf_java_async_cancel_root_wait', 1)[1].split('void *lsf_java_async_take', 1)[0]
            take = bridge.split('void *lsf_java_async_take', 1)[1]
            def operation(body, number):
                start = body.index('case ' + str(number) + ': {')
                end = body.find('\ncase ', start + 1)
                return body[start:] if end < 0 else body[start:end]
            for function in (read, write):
                body = operation(begin, function['operation'])
                self.assertIn('.__handle)', body)
                self.assertLess(body.index('.__handle)'), body.index('call->status = ' + function['symbol']))
                self.assertLess(body.index('lsf_finish(&input)'), body.index('call->status = ' + function['symbol']))
                self.assertNotIn('case ' + str(function['operation']) + ':', cancel)
            write_begin = operation(begin, write['operation'])
            self.assertIn('.ptr = lsf_allocate(', write_begin)
            self.assertIn('lsf_get(&input, 1)', write_begin)
            self.assertLess(write_begin.index('.ptr = lsf_allocate('), write_begin.index('call->status = ' + write['symbol']))
            member = 'call->data.op' + str(write['operation'])
            member += ('.args.' + write['cAggregate'][1]['name']) if 'cAggregate' in write else '.arg1'
            self.assertIn('(' + member + ').ptr = lsf_allocate(', write_begin)
            self.assertIn('lsf_release((' + member + ').ptr,', operation(take, write['operation']))
            self.assertLess(take.index('lsf_require(state == PROBE_SUBTASK_RETURNED'),
                            take.index('switch (call->operation)'))
            self.assertIn('call->next = lsf_async_calls; lsf_async_calls = call; lsf_async_count++;', begin)
            self.assertIn('state == PROBE_SUBTASK_RETURNED', take)
            generated = (output/'Bindings.java').read_text(encoding='utf-8')
            self.assertIn('Wire.NETWORK_READ', generated)
            self.assertIn('Wire.NETWORK_WRITE', generated)
            self.assertIn('arguments.call(hostCall,', generated)
            captured = Path(os.environ['LATENT_JAVA_NETWORK_CAPTURE'])
            captured.mkdir(parents=True, exist_ok=False)
            for name in ('probe.h', 'bridge.c', 'Bindings.java'):
                shutil.copyfile(output/name, captured/name)
            (captured/'wit-graph.json').write_text(json.dumps(graphs[0], sort_keys=True, separators=(',', ':'))+'\n',
                                                   encoding='utf-8')
            print('NETWORK_BORROW_ABI_CONTROL PASS real-wit-bindgen;copied-handles-and-bytes;terminal-retention;COMPONENT_QUALIFICATION=pending')

    def test_generated_async_network_inputs_are_copied_before_dispatch_and_retained_until_terminal(self):
        for aggregate in (False, True):
            with self.subTest(aggregate=aggregate):
                data, header = network_graph(aggregate=aggregate)
                graph = Graph(data, 'service', header, async_imports=True)
                generated = async_imports.generate(graph)
                begin = generated.split('void *lsf_java_async_begin', 1)[1].split('int32_t lsf_java_async_state', 1)[0]
                take = generated.split('void *lsf_java_async_take', 1)[1]
                read = next(f for f in graph.imports if f['interface'] == 0 and f['name'] == 'read')
                write = next(f for f in graph.imports if f['interface'] == 0 and f['name'] == 'write')
                def operation(body, number):
                    start = body.index('case ' + str(number) + ': {')
                    end = body.find('\ncase ', start + 1)
                    return body[start:] if end < 0 else body[start:end]
                read_begin = operation(begin, read['operation'])
                write_begin = operation(begin, write['operation'])
                write_take = operation(take, write['operation'])
                for fragment, function in ((read_begin, read), (write_begin, write)):
                    self.assertIn('.__handle)', fragment)
                    self.assertLess(fragment.index('.__handle)'), fragment.index('call->status = ' + function['symbol']))
                    self.assertLess(fragment.index('lsf_finish(&input)'), fragment.index('call->status = ' + function['symbol']))
                self.assertIn('.ptr = lsf_allocate(', write_begin)
                self.assertIn('lsf_get(&input, 1)', write_begin)
                self.assertLess(write_begin.index('.ptr = lsf_allocate('), write_begin.index('call->status = ' + write['symbol']))
                self.assertIn('lsf_release(', write_take)
                self.assertLess(take.index('lsf_require(state == PROBE_SUBTASK_RETURNED'),
                                take.index('switch (call->operation)'))
                self.assertIn('call->next = lsf_async_calls; lsf_async_calls = call; lsf_async_count++;', begin)
                bridge = (ROOT/'sdk/java-guest/runtime/bridge.h').read_text(encoding='utf-8')
                self.assertIn('static void lsf_require(bool condition) { if (!condition) __builtin_trap(); }', bridge)

    def test_permit_has_no_public_factory_or_mutable_dispatch_binding(self):
        data, header = network_graph()
        output = java.generate(Graph(data, 'service', header, async_imports=True))
        start = output.index('public static final class BorrowPermit {')
        end = output.index('\n}', start) + 2
        permit = output[start:end]
        self.assertEqual(permit.count('private BorrowPermit('), 1)
        self.assertIn('private final Wire.HostFunction function; private final int operation, direction;', permit)
        self.assertIn('return function == candidate && this.operation == operation;', permit)
        self.assertEqual(re.findall(r'(?m)^public (?:static )?BorrowPermit\s+[A-Za-z_]', output), [])
        wire = (ROOT/'sdk/java-guest/runtime/dev/latent/guest/Wire.java').read_text(encoding='utf-8')
        self.assertIn('private final Bindings.BorrowPermit permit;', wire)
        self.assertIn('else require(permit.authorizes(function, operation));', wire)
        self.assertIn('if (permit != null) require(permit.authorizes(null, operation));', wire)
        self.assertIn('if (permit == null) require(borrows.isEmpty());', wire)
        self.assertIn('require(!closed && !started && !retainedUncertain);', wire)
        self.assertEqual(re.findall(r'public\s+(?:static\s+)?Bindings\.BorrowPermit\s+[A-Za-z_]', wire), [])

    def test_uncertain_writer_roots_all_inputs_before_the_exact_call(self):
        wire = (ROOT/'sdk/java-guest/runtime/dev/latent/guest/Wire.java').read_text(encoding='utf-8')
        call = wire.split('public Reader call(HostFunction function,', 1)[1].split('private void rootInput()', 1)[0]
        self.assertLess(call.index('permit.authorizes(function, operation)'), call.index('if (rooted) rootInput();'))
        self.assertLess(call.index('if (rooted) rootInput();'), call.index('function.callOwned(operation, data, length)'))
        self.assertIn(': function.call(operation, Address.ofData(data), length);', call)
        self.assertIn('if (rooted && function.retainsBorrowedResources()) retainedUncertain = true;', call)
        self.assertIn('if (rooted && !retainedUncertain) unrootInput();', call)
        close = wire.split('@Override public void close()', 2)[2]
        self.assertIn('if (!retainedUncertain) {', close)
        self.assertLess(close.index('if (!retainedUncertain) {'), close.index('borrows.clear(); Arrays.fill(data, (byte) 0);'))
        for name in ('rootInput', 'unrootInput'):
            method = wire.split('private void ' + name + '()', 1)[1].split('\n        }', 1)[0]
            self.assertIn('synchronized (INPUT_LOCK)', method)
            self.assertNotRegex(method, r'\b(?:for|while|do|new|throw)\b')

    def test_resource_monitor_bodies_have_no_calls_loops_or_host_io(self):
        resource = (ROOT/'sdk/java-guest/runtime/dev/latent/guest/Resource.java').read_text(encoding='utf-8')
        marker = 'synchronized (this) {'
        positions = [m.start() for m in re.finditer(re.escape(marker), resource)]
        self.assertEqual(len(positions), 4)
        for start in positions:
            begin = resource.index('{', start); depth = 1; end = begin + 1
            while depth and end < len(resource):
                depth += (resource[end] == '{') - (resource[end] == '}')
                end += 1
            self.assertEqual(depth, 0)
            body = resource[begin + 1:end - 1]
            self.assertEqual(set(re.findall(r'\b([A-Za-z_$][\w$]*)\s*\(', body)) - {'if'}, set())
            self.assertNotRegex(body, r'\b(?:for|while|do|new|throw)\b')
        plugin = (ROOT/'sdk/java-guest/fibers/compiler/dev/latent/guest/runtime/compiler/RuntimePlugin.java').read_text(encoding='utf-8')
        self.assertIn('new LoopGraph(ProgramUtils.buildControlFlowGraph(program))', plugin)
        self.assertIn('for (int index : headers)', plugin)
        self.assertIn('first.insertPrevious(call("checkpoint", ValueType.VOID))', plugin)
        self.assertNotRegex(resource, r'\b(?:for|while|do)\s*\(')

    @unittest.skipUnless(os.environ.get('LATENT_JAVA_MODEL_CLASSPATH'), 'locked TeaVM model classpath')
    def test_real_teavm_plugin_cannot_checkpoint_borrow_or_input_root_updates(self):
        sdk = ROOT/'sdk/java-guest'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data, header = network_graph()
            generated = java.generate(Graph(data, 'service', header, async_imports=True))
            start = generated.index('public static final class BorrowPermit {')
            end = generated.index('\n}', start) + 2
            binding = root/'dev/latent/generated/Bindings.java'
            binding.parent.mkdir(parents=True)
            binding.write_text('package dev.latent.generated; import dev.latent.guest.Wire; public final class Bindings {\n'
                               + 'public enum LatentRuntimeActivationOwnerKind { Wait }\n'
                               + generated[start:end] + '\n}\n', encoding='utf-8')
            activation = root/'dev/latent/guest/runtime/Activation.java'
            activation.parent.mkdir(parents=True)
            activation.write_text('package dev.latent.guest.runtime; import dev.latent.generated.Bindings;'
                ' public final class Activation { public static Lease owner(Bindings.LatentRuntimeActivationOwnerKind kind)'
                ' { throw new AssertionError(); } public static final class Lease { public void close() { } } }\n',
                encoding='utf-8')
            sources = sorted((sdk/'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
            sources += [sdk/'runtime/dev/latent/guest/Wire.java', sdk/'runtime/dev/latent/guest/Resource.java',
                        sdk/'fibers/io/dev/latent/guest/runtime/HostCalls.java',
                        sdk/'tests/network/NetworkBorrowModelControl.java', binding, activation]
            tooling = os.environ['LATENT_JAVA_MODEL_CLASSPATH']
            compiled = subprocess.run(['javac', '--release', '25', '-proc:none', '-encoding', 'UTF-8',
                                       '-cp', tooling, '-d', str(root), *map(str, sources)],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            observed = subprocess.run(['java', '-Xmx256m', '-cp', str(root) + os.pathsep + tooling,
                                       'dev.latent.guest.runtime.compiler.NetworkBorrowModelControl'],
                                      capture_output=True, text=True, timeout=60)
            self.assertEqual(observed.returncode, 0, observed.stderr)
            self.assertEqual(observed.stdout.strip(), 'NETWORK_BORROW_MODEL PASS actual-resource-and-writer;'
                             'monitors;no-checkpoints;owned-array-direct-entry;selected-loop-positive;'
                             'COMPONENT_QUALIFICATION=pending')
            print(observed.stdout.rstrip())

    def test_retained_actual_network_graph_selects_only_owned_connection(self):
        # Lossless wasm-tools graph retained by the separate borrow investigation.
        # Marking its declared async imports here exercises selection only; it
        # does not claim that a real Java component was lowered or executed.
        data = json.loads((ROOT/'tools/tests/fixtures/typescript_runtime_profile/borrow-void-function.json').read_bytes())
        graph = Graph.preflight(data, 'service')
        for function in graph.imports:
            if function['kind'] == 'async-freestanding':
                function['asyncLowered'] = True
        network = next(i for i in graph.resources if graph.name(i) == 'LatentNetworkStreamsConnection')
        chunk = next(i for i in graph.resources if graph.name(i) == 'LatentNetworkStreamsChunk')
        self.assertTrue(java.network_connection(graph, network))
        self.assertFalse(java.network_connection(graph, chunk))
        functions = [f for f in graph.imports if f['interface'] == graph.types[network]['owner']['interface']]
        self.assertEqual({f['name']: java.network_lane(graph, f) for f in functions}, {
            'connect': None, 'read': 'NETWORK_READ', 'write': 'NETWORK_WRITE', 'ready': 'NETWORK_READY',
            'chunk-bytes': None, 'inspect': 'NETWORK_INSPECT', 'shutdown': None, 'close': None})

    def test_every_async_import_gets_its_own_private_call_and_operation_bound_permit(self):
        original, _ = network_graph()
        changed_package = deepcopy(original)
        changed_package['packages'][0]['name'] = 'latent:network@0.2.0'
        changed_signature = deepcopy(original)
        borrowed = changed_signature['interfaces'][0]['functions']['read']['params'][0]['type']
        changed_signature['interfaces'][0]['functions']['read']['params'].append({'name': 'other', 'type': borrowed})
        for data in (original, changed_package, changed_signature):
            graph_data, header = network_graph(deepcopy(data))
            graph = Graph(graph_data, 'service', header, async_imports=True)
            generated = java.generate(graph)
            selected = [function for function in graph.imports if function.get('asyncLowered')]
            self.assertTrue(selected)
            self.assertIn('private BorrowPermit(Wire.HostFunction function, int operation, int direction)', generated)
            for function in selected:
                lane = java.network_lane(graph, function)
                direction = 'Wire.' + lane if lane else '0'
                permit = 'new Wire.Writer(new BorrowPermit(hostCall, ' + str(function['operation']) + ', ' + direction + '))'
                call = 'arguments.call(hostCall, ' + str(function['operation']) + ', false)'
                with self.subTest(operation=function['operation'], package=graph_data['packages'][0]['name']):
                    self.assertEqual(generated.count(permit), 1)
                    self.assertEqual(generated.count(call), 1)
                    if function['name'] == 'shutdown': self.assertIsNone(lane)

    def test_only_exact_async_network_connection_gets_direction_lanes(self):
        data, header = network_graph()
        graph = Graph(data, 'service', header, async_imports=True)
        self.assertTrue(java.network_connection(graph, 0))
        self.assertFalse(java.network_connection(graph, 1))
        self.assertEqual({f['name']: java.network_lane(graph, f) for f in graph.imports if f['interface'] == 0}, {
            'connect': None,
            'read': 'NETWORK_READ', 'write': 'NETWORK_WRITE', 'ready': 'NETWORK_READY',
            'shutdown': None, 'inspect': 'NETWORK_INSPECT',
            'close': None, 'chunk-bytes': None})
        generated = java.generate(graph)
        self.assertIn('class LatentNetworkStreamsConnection extends Resource { private LatentNetworkStreamsConnection(int handle) { super(handle, -1, true); } }', generated)
        self.assertIn('class LatentNetworkStreamsChunk extends Resource { private LatentNetworkStreamsChunk(int handle) { super(handle, -2); } }', generated)
        for name in ('NETWORK_READ', 'NETWORK_WRITE', 'NETWORK_READY', 'NETWORK_INSPECT'):
            self.assertRegex(generated, r'new BorrowPermit\((?:hostCall|null), [0-9]+, Wire\.' + name + r'\)')
        self.assertIn('arguments.call(hostCall,', generated)
        self.assertNotIn('arguments.call(hostCall::call,', generated)
        self.assertIn('private BorrowPermit(Wire.HostFunction function, int operation, int direction)', generated)
        self.assertIn('private final Wire.HostFunction function; private final int operation, direction;', generated)
        self.assertIn('return function == candidate && this.operation == operation;', generated)
        self.assertEqual(re.findall(r'(?m)^public (?:static )?BorrowPermit\s+[A-Za-z_]', generated), [])
        self.assertEqual([line for line in generated.splitlines()
                          if line.startswith('public ') and 'BorrowPermit' in line],
                         ['public static final class BorrowPermit {'])
        host = (ROOT/'sdk/java-guest/fibers/io/dev/latent/guest/runtime/HostCalls.java').read_text(encoding='utf-8')
        self.assertIn('public static final class Call implements AutoCloseable, Wire.HostFunction', host)
        self.assertIn('return Address.fromInt(suspend(operation, bytes, length, this));', host)
        self.assertIn('return Address.fromInt(suspendOwned(operation, bytes, length, this));', host)
        owned = host.split('private static void suspendOwned(', 1)[1].split('private static void finish(', 1)[0]
        self.assertIn('begin(operation, Address.ofData(bytes), length)', owned)

    def test_version_owner_and_incomplete_async_profiles_remain_exclusive(self):
        original, _ = network_graph()
        variants = []
        data = deepcopy(original); data['packages'][0]['name'] = 'latent:network@0.2.0'; variants.append(network_graph(data))
        data = deepcopy(original); data['interfaces'][0]['name'] = 'other'; variants.append(network_graph(data))
        data = deepcopy(original); borrow = data['interfaces'][0]['functions']['read']['params'][0]['type']; data['types'][borrow]['kind'] = {'handle': {'own': 0}}; variants.append(network_graph(data))
        data = deepcopy(original); borrow = data['interfaces'][0]['functions']['read']['params'][0]['type']; data['interfaces'][0]['functions']['write']['params'].append({'name':'other','type':borrow}); variants.append(network_graph(data))
        data = deepcopy(original); borrow = data['interfaces'][0]['functions']['read']['params'][0]['type']; data['types'].append({'name':None,'kind':{'option':borrow},'owner':None}); data['interfaces'][0]['functions']['ready']['params'].append({'name':'other','type':len(data['types'])-1}); variants.append(network_graph(data))
        variants.append(network_graph(deepcopy(original), synchronous_ready=True))
        for data, signature in variants:
            with self.subTest(package=data['packages'][0]['name'], interface=data['interfaces'][0]['name'], header=signature):
                graph = Graph(data, 'service', signature, async_imports=True)
                self.assertFalse(java.network_connection(graph, 0))
                self.assertTrue(all(java.network_lane(graph, f) is None for f in graph.imports))

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'native JDK controls')
    def test_actual_resource_and_writer_keep_borrows_until_terminal_ownership(self):
        sdk = ROOT/'sdk/java-guest'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            interop = root/'org/teavm/interop'
            interop.mkdir(parents=True)
            (interop/'Address.java').write_text(
                'package org.teavm.interop; public final class Address {'
                ' public static Address ofData(byte[] value) { return new Address(); }'
                ' public native int toInt(); public native Address add(int n);'
                ' public native byte getByte(); public native int getInt();'
                ' public native void putByte(byte value); }\n', encoding='utf-8')
            (interop/'Import.java').write_text(
                'package org.teavm.interop; public @interface Import { String name(); }\n', encoding='utf-8')
            data, header = network_graph()
            generated = java.generate(Graph(data, 'service', header, async_imports=True))
            start = generated.index('public static final class BorrowPermit {')
            end = generated.index('\n}', start) + 2
            binding = root/'dev/latent/generated/Bindings.java'
            binding.parent.mkdir(parents=True)
            binding.write_text('package dev.latent.generated; import dev.latent.guest.Wire; public final class Bindings {\n'
                               + generated[start:end] + '\n}\n', encoding='utf-8')
            sources = [sdk/'runtime/dev/latent/guest/Wire.java', sdk/'runtime/dev/latent/guest/Resource.java',
                       sdk/'tests/network/NetworkBorrowControl.java', interop/'Address.java', interop/'Import.java', binding]
            compiled = subprocess.run(['javac', '-proc:none', '-encoding', 'UTF-8', '-d', str(root),
                                       *map(str, sources)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            javap = shutil.which('javap')
            self.assertIsNotNone(javap, 'the selected JDK must include its bytecode inspector')
            disassembly = subprocess.run([javap, '-c', '-p', '-classpath', str(root),
                                          'dev.latent.guest.Resource'],
                                         capture_output=True, text=True, timeout=15)
            self.assertEqual(disassembly.returncode, 0, disassembly.stderr)
            for signature in ('final int borrow(int);', 'final void releaseBorrow(int);',
                              'final int consume();', 'public final void close();'):
                match = re.search(r'(?ms)^  ' + re.escape(signature) + r'\s*\n    Code:\n(.*?)(?=^  [^\n]+;\s*$|\Z)',
                                  disassembly.stdout)
                self.assertIsNotNone(match, signature)
                body = match.group(1)
                self.assertIn('monitorenter', body, signature)
                self.assertIn('monitorexit', body, signature)
                self.assertNotRegex(body, r'\b(?:tableswitch|lookupswitch|jsr|jsr_w)\b')
                for offset, target in re.findall(r'(?m)^\s*(\d+):\s+(?:if\w+|goto|goto_w)\s+(\d+)\b', body):
                    self.assertGreater(int(target), int(offset), signature + ': backward bytecode branch')
            result = subprocess.run(['java', '-Xmx128m', '-cp', str(root), 'dev.latent.guest.NetworkBorrowControl'],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('NETWORK_BORROW_CONTROL PASS directions;duplicate;exclusive;shutdown;consume;uncertain;pre-entry;permit;delegation;rooted-inputs;COMPONENT_QUALIFICATION=pending', result.stdout)
            untrusted = root/'Untrusted.java'
            untrusted.write_text('import dev.latent.generated.Bindings; class Untrusted {'
                                 ' Object forge() { return new Bindings.BorrowPermit(null, 1, 1); } }\n', encoding='utf-8')
            denied = subprocess.run(['javac', '-proc:none', '-cp', str(root), '-d', str(root), str(untrusted)],
                                    capture_output=True, text=True, timeout=30)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn('private access', denied.stderr)
            print(result.stdout.rstrip())


if __name__ == '__main__':
    unittest.main()
