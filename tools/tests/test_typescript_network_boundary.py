"""Networking boundary controls; host models are not signed-guest qualification.

Run host controls with unittest. Run the separate compiler control explicitly:
python -m tools.tests.test_typescript_network_boundary --frontend /path/to/tools
The latter requires actual frontend files and never substitutes a Node/browser shim.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.tests import test_typescript_node_net as socket_controls
from tools.typescript_guest import net_profile

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptNetworkBoundary(unittest.TestCase):
    def javascript(self, body):
        # Reuse the owning suite's explicitly modelled provider/ACK fixture;
        # importing the module does not rediscover its TestCase in this module.
        socket_controls.TypeScriptNodeNet.javascript(self, body)

    def test_standard_module_diagnostics_are_alias_and_package_independent(self):
        self.javascript(f"import {{netBuiltin}} from {json.dumps((ROOT/net_profile.RESOLVER).as_uri())};\n"
                        f"const source=await readFile(new URL({json.dumps((ROOT/net_profile.BACKEND).as_uri())}),'utf8');\n" + r"""
const families={
 dns:['dns','dns/promises'], tls:['tls'],
 stream:['stream','stream/promises','stream/web','stream/consumers',
         '_stream_duplex','_stream_passthrough','_stream_readable',
         '_stream_transform','_stream_wrap','_stream_writable']};
for(const enabled of [false,true]) {
 const backend=netBuiltin(source,enabled);
 for(const [family,names] of Object.entries(families))for(const name of names)for(const prefix of ['', 'node:']) {
  const path=prefix+name;
  for(const importer of ['/application/src/main.ts','/application/node_modules/outer/node_modules/inner/index.cjs']) {
   const result=backend.resolve({path,namespace:'file',importer,kind:'import-statement'});
   assert(result?.errors,'unsupported builtin must refuse before package resolution: '+path);
   assert.equal(result.errors[0].text,'standard-node-network-module-unavailable:node:'+name);
   const notes=result.errors[0].notes.map(note=>note.text).join('\n');
   assert(notes.includes('typescript-network-compatibility.md'));
   assert(notes.includes(family==='tls'?'TLS':family==='dns'?'DNS':'stream'));
   assert(!result.external&&!result.contents&&!result.path);
  }
 }
 for(const path of ['readable-stream','stream-browserify','dns-packet','tls-client',
                     '@vendor/net','net-client','./tls','../dns','stream/custom','net/promises'])
  assert.equal(backend.resolve({path,namespace:'file',importer:'/application/src/main.ts'}),undefined);
 for(const path of ['net','node:net']) {
  const result=backend.resolve({path,namespace:'file',importer:'/application/node_modules/arbitrary/index.js'});
  if(enabled)assert.deepEqual(result,{path:'node:net',namespace:'lsf-owned-node-net',sideEffects:false});
  else {
   assert.equal(result.errors[0].text,'standard-node-net-requires-exact-stream-runtime-and-declaration');
   assert(result.errors[0].notes.some(note=>note.text.includes('latent:network/streams@0.1.0')));
  }
 }
 assert(backend.resolve({path:NET_PRIVATE,namespace:'file',importer:'node:net'}).errors);
 assert(backend.resolve({path:NET_PRIVATE,namespace:'lsf-owned-node-net',importer:'arbitrary'}).errors);
}
""")

    def test_changed_resolver_invalidates_selected_source_receipt(self):
        identities = net_profile.identities(ROOT)
        # Selection is source-bound, never a package allow-list. A changed
        # compiler resolver cannot reuse an earlier selected-module receipt.
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary)
            for name in (net_profile.BACKEND, net_profile.TRANSPORT, net_profile.BINDINGS,
                         net_profile.RESOLVER, net_profile.DECLARATION, net_profile.WIT):
                target = copied/name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT/name).read_bytes())
            resolver = copied/net_profile.RESOLVER
            resolver.write_bytes(resolver.read_bytes() + b'\n// source-binding negative control\n')
            changed = net_profile.identities(copied)
            self.assertNotEqual(changed, identities)
            with self.assertRaises(ValueError):
                net_profile.selected({'standardNetModules': ['node:net'],
                    'standardNetProfile': net_profile.PROFILE,
                    'standardNetIdentities': identities}, changed)

    def test_profile_and_complete_interface_shape_are_required_not_package_names(self):
        # Synthetic parser-shaped unit graph: this checks the selection gate,
        # not whether a provider or the real stream contract is qualified.
        graph = {'packages': [{'name': 'latent:network@0.1.0'}], 'types': [],
            'interfaces': [{'name': 'streams', 'package': 0, 'types': {},
                'functions': {'connect': {'name': 'connect', 'kind': 'async-freestanding',
                                         'params': [], 'result': 'u32'}}}],
            'worlds': [{'name': 'contract-probe', 'package': 0,
                        'imports': {'interface-0': {'interface': {'id': 0}}}, 'exports': {}}]}
        world = 'latent:network/contract-probe@0.1.0'
        profile = net_profile.runtime.IMPORT_PROFILE
        for runtime in (net_profile.runtime.SYNC_PROFILE, net_profile.runtime.ASYNC_PROFILE):
            self.assertEqual(net_profile.configuration({}, graph, world, graph, runtime_profile=runtime), {})
        self.assertEqual(net_profile.configuration({}, graph, world, graph, runtime_profile=profile),
                         {'standardNetProfile': net_profile.PROFILE})
        absent = copy.deepcopy(graph)
        absent['worlds'][0]['imports'] = {}
        self.assertEqual(net_profile.configuration({}, absent, world, graph, runtime_profile=profile), {})
        for field, replacement in (('kind', 'freestanding'), ('result', 'u64')):
            changed = copy.deepcopy(graph)
            changed['interfaces'][0]['functions']['connect'][field] = replacement
            with self.assertRaisesRegex(ValueError, 'exact-stream-interface-required'):
                net_profile.configuration({}, changed, world, graph, runtime_profile=profile)
        for key in ('standardNetProfile', 'standardNetIdentities', 'standardNetBackend'):
            with self.assertRaisesRegex(ValueError, 'application-cannot-override'):
                net_profile.configuration({key: 'application-choice'}, graph, world, graph, runtime_profile=profile)

    def test_provider_failure_tags_preserve_cause_and_never_reconnect(self):
        self.javascript(r"""
// Closed WIT error translation only: these are injected provider failures,
// not real DNS resolution, TLS handshakes or connection-refusal observations.
for(const [streamCode,code] of Object.entries({
 'connect-failed':'ERR_LSF_CONNECT_FAILED','dns-failed':'ERR_LSF_DNS_FAILED',
 'tls-failed':'ERR_LSF_TLS_FAILED',timeout:'ETIMEDOUT',cancelled:'ABORT_ERR',
 denied:'EACCES',revoked:'EACCES',exhausted:'ERR_LSF_RESOURCE_EXHAUSTED'})) {
 let connects=0;const original=Object.assign(Error('provider failure'),
  {payload:{code:streamCode,acceptedPrefixBytes:0,mayHaveApplied:false}});
 const f=fixture({connect(request){++connects;assert.equal(request.transport,'tcp');
  return {promise:Promise.reject(original),borrowReleased:Promise.resolve(),cancel(){return Promise.resolve()}}}});
 const socket=f.net.connect(32123,'localhost'),closed=deferred(),events=[];let failure;
 socket.on('connect',()=>events.push('connect')).on('error',error=>{failure=error;events.push('error')})
  .on('close',hadError=>{assert.equal(hadError,true);events.push('close');closed.resolve()});
 await closed.promise;assert.equal(connects,1);assert.deepEqual(events,['error','close']);
 assert.equal(failure.code,code);assert.equal(failure.streamCode,streamCode);assert.equal(failure.cause,original);
 assert.equal(failure.syscall,'connect');assert.equal(failure.acceptedPrefixBytes,0);assert.equal(failure.mayHaveApplied,false);
 assert.equal(socket.bytesWritten,0);f.transport.assertEmpty();
}
""")

    def test_idle_timeout_notifies_without_close_and_late_callbacks_are_inert(self):
        self.javascript(r"""
// Deterministic application-idle-timer model. The actual activation/root clock
// and physical timer retirement are qualified by their separate engine owner.
for(let activation=0;activation<2;++activation) {
 const callbacks=new Map();let next=0;
 const t={...target(),setTimeout(fn,milliseconds){assert.equal(milliseconds,7);callbacks.set(++next,fn);return next},
  clearTimeout(id){callbacks.delete(id)}};
 const native={connect:()=>settled({}),read:()=>settled(undefined),write:(_,bytes)=>settled(bytes.length),
  ready:()=>settled({writable:true}),chunkBytes:()=>settled(new Uint8Array()),shutdown:()=>settled({}),close:()=>settled({})};
 const transport=createNodeNetTransport(native,t,()=>({}));
 const net=createNodeNetModule(transport,Buffer,()=>false,t),socket=new net.Socket(),closed=deferred();let timeouts=0;
 socket.on('error',closed.reject).on('close',closed.resolve).setTimeout(7,()=>++timeouts).connect(32123,'localhost');
 await turn();assert.equal(callbacks.size,1);
 const first=[...callbacks.entries()][0];callbacks.delete(first[0]);first[1]();
 assert.equal(timeouts,1);assert.equal(socket.destroyed,false);assert.throws(transport.assertEmpty,/unclosed/);
 await new Promise((yes,no)=>socket.write('a',error=>error?no(error):yes()));assert.equal(callbacks.size,1);
 const late=[...callbacks.values()][0];socket.destroy();await closed.promise;
 assert.equal(callbacks.size,0);late();assert.equal(timeouts,1);transport.assertEmpty();
}
""")


def compiler_controls(frontend: Path) -> None:
    """Real bundler control, required tools rather than a successful skip."""
    self = unittest.TestCase()
    tools = frontend.resolve(strict=True)
    node = shutil.which('node')
    self.assertIsNotNone(node)
    expected_node = json.loads((ROOT/'sdk/typescript-guest/tools/package.json').read_bytes())['engines']['node']
    actual_node = subprocess.run([node, '--version'], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    self.assertEqual(actual_node, 'v' + expected_node, 'normal pinned compiler Node required')
    lock = json.loads((ROOT/'sdk/typescript-guest/tools/package-lock.json').read_bytes())['packages']
    for package in ('esbuild', 'acorn'):
        installed = json.loads((tools/'node_modules'/package/'package.json').read_bytes())
        self.assertEqual(installed['version'], lock['node_modules/' + package]['version'])
    for name in ('esbuild/lib/main.js', 'acorn/dist/acorn.mjs'):
        self.assertTrue((tools/'node_modules'/name).is_file(), 'normal pinned frontend required: ' + name)
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        imports = work/'imports.json'
        imports.write_text(json.dumps([net_profile.INTERFACE]), encoding='utf-8')
        configuration = {'runtimeProfile': 'spidermonkey-activation-promises-clocks-imports-v1',
            'nativeClockInterfaces': ['latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'],
            'standardNetProfile': net_profile.PROFILE, 'standardNetIdentities': net_profile.identities(ROOT)}

        def bundle(source, configured=None, passed=True):
            (work/'src').mkdir(exist_ok=True)
            (work/'src/main.ts').write_text(source, encoding='utf-8')
            config = work/'config.json'
            config.write_text(json.dumps(configured or configuration), encoding='utf-8')
            output = work/'application.mjs'
            for path in (output, work/'application.mjs.inputs.json', work/'application.mjs.map'):
                path.unlink(missing_ok=True)
            result = subprocess.run([node, ROOT/'tools/typescript_guest/bundle.mjs',
                tools/'node_modules/esbuild/lib/main.js', work, work/'src/main.ts', output,
                imports, config, tools/'node_modules/acorn/dist/acorn.mjs'],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode == 0, passed, result.stdout + result.stderr)
            if not passed:
                return result.stderr
            return output.read_text(encoding='utf-8'), json.loads((work/'application.mjs.inputs.json').read_bytes())

        # The same compiler boundary serves ordinary direct/transitive
        # modules. Fake npm fallbacks must never satisfy a standard builtin.
        # These local packages test resolution, not published-library evidence.
        for name in ('tls', 'node:tls', 'dns', 'node:dns/promises',
                     'stream', 'node:stream/promises', 'node:stream/web', 'stream/consumers'):
            message = bundle(f'import * as api from {json.dumps(name)}; export const value=api;', passed=False)
            canonical = name.removeprefix('node:')
            self.assertIn('standard-node-network-module-unavailable:node:' + canonical, message)
            self.assertIn('typescript-network-compatibility.md', message)
        captured = {**configuration, 'moduleRoot': 'node_modules'}
        packages = work/'node_modules'
        sources = {
            'outer/package.json': {'name': 'outer', 'type': 'module', 'main': './index.js',
                                   'browser': './browser.js'},
            'outer/index.js': "export {default} from 'inner';",
            'outer/browser.js': "export default 'browser-fallback-must-not-run';",
            'inner/package.json': {'name': 'inner', 'main': './index.cjs'},
            'inner/index.cjs': "module.exports = require('node:net');",
            'dns/package.json': {'name': 'dns', 'main': './index.js'},
            'dns/index.js': "module.exports = {lookup(){return 'fake-dns-success'}};",
        }
        for name, content in sources.items():
            target = packages/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(content) if isinstance(content, dict) else content, encoding='utf-8')
        transitive, observation = bundle("import net from 'outer'; export const Socket=net.Socket;", captured)
        self.assertEqual(observation['standardNetModules'], ['node:net'])
        self.assertIn('node_modules/outer/index.js', observation['inputs'])
        self.assertIn('node_modules/inner/index.cjs', observation['inputs'])
        self.assertNotIn('browser-fallback-must-not-run', transitive)
        for name in ('dns', 'node:tls', 'node:stream/consumers'):
            (packages/'inner/index.cjs').write_text('module.exports = require(' + json.dumps(name) + ');', encoding='utf-8')
            message = bundle("import api from 'outer'; export const value=api;", captured, passed=False)
            self.assertIn('standard-node-network-module-unavailable:node:' + name.removeprefix('node:'), message)
        # A relative filename resembling a builtin remains ordinary input.
        (packages/'inner/index.cjs').write_text("module.exports = require('./dns.cjs');", encoding='utf-8')
        (packages/'inner/dns.cjs').write_text("module.exports = 42;", encoding='utf-8')
        _, observation = bundle("import value from 'outer'; export const answer=value;", captured)
        self.assertNotIn('standardNetModules', observation)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the actual networking module bundler control (not signed qualification).')
    parser.add_argument('--frontend', required=True, type=Path, help='Normal installed pinned TypeScript tools directory')
    compiler_controls(parser.parse_args().frontend)
