"""Networking boundary controls; host models are not signed-guest qualification.

Run supplementary host controls with unittest. Run the required pinned gate with:
python -m tools.tests.test_typescript_network_boundary --frontend /path/to/tools
The gate runs the real bundler and both host suites, refusing missing tools,
skips and expected failures. It is compiler/model evidence, not signed execution.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.tests import test_typescript_node_net as socket_controls
from tools.typescript_guest import net_profile

ROOT = Path(__file__).resolve().parents[2]


def require_complete_controls(result):
    """Record observed execution without an exact test-count maintenance gate."""
    if (result.testsRun < 1 or not result.wasSuccessful() or result.skipped
            or result.expectedFailures or result.unexpectedSuccesses):
        raise ValueError('network-boundary-controls-incomplete')
    return {'testsRun': result.testsRun, 'skipped': 0, 'failures': 0, 'errors': 0,
            'expectedFailures': 0, 'unexpectedSuccesses': 0}


def pinned_frontend(frontend: Path):
    """Fail before compiler execution when the normal installed lock is absent."""
    tools = frontend.resolve(strict=True)
    node = shutil.which('node')
    if node is None:
        raise ValueError('network-boundary-pinned-node-required')
    specification = json.loads((ROOT/'sdk/typescript-guest/tools/package.json').read_bytes())
    version = subprocess.run([node, '--version'], capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
    if version != 'v' + specification['engines']['node']:
        raise ValueError('network-boundary-pinned-node-required')
    for name in ('package.json', 'package-lock.json'):
        if (tools/name).read_bytes() != (ROOT/'sdk/typescript-guest/tools'/name).read_bytes():
            raise ValueError('network-boundary-installed-lock-drift')
    lock = json.loads((tools/'package-lock.json').read_bytes())['packages']
    versions = {'node': version}
    for package, entrypoint in (('esbuild', 'lib/main.js'), ('acorn', 'dist/acorn.mjs'),
                                ('typescript', 'bin/tsc')):
        installed = tools/'node_modules'/package
        actual = json.loads((installed/'package.json').read_bytes())['version']
        if actual != lock['node_modules/' + package]['version'] or not (installed/entrypoint).is_file():
            raise ValueError('network-boundary-pinned-package-required:' + package)
        versions[package] = actual
    return tools, node, versions


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

    def test_required_gate_never_counts_skips_or_expected_failures_as_passes(self):
        # TestResult doubles check the gate only, not compiler execution.
        def successful():
            result = unittest.TestResult()
            result.testsRun = 1
            return result
        self.assertEqual(require_complete_controls(successful())['testsRun'], 1)
        with self.assertRaisesRegex(ValueError, 'controls-incomplete'):
            require_complete_controls(unittest.TestResult())
        for field in ('skipped', 'failures', 'errors', 'expectedFailures', 'unexpectedSuccesses'):
            result = successful()
            getattr(result, field).append(('synthetic-control', 'not an executed pass'))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'controls-incomplete'):
                require_complete_controls(result)

    def test_pinned_frontend_rejects_missing_node_wrong_version_and_changed_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            with patch.object(shutil, 'which', return_value=None), self.assertRaisesRegex(ValueError, 'pinned-node'):
                pinned_frontend(tools)
            with patch.object(shutil, 'which', return_value='node'), \
                    patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v0.0.0\n')), \
                    self.assertRaisesRegex(ValueError, 'pinned-node'):
                pinned_frontend(tools)
            (tools/'package.json').write_text('{}', encoding='utf-8')
            version = json.loads((ROOT/'sdk/typescript-guest/tools/package.json').read_bytes())['engines']['node']
            with patch.object(shutil, 'which', return_value='node'), \
                    patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'v' + version + '\n')), \
                    self.assertRaisesRegex(ValueError, 'installed-lock-drift'):
                pinned_frontend(tools)

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

    def test_once_registration_identity_and_nested_emit_match_node_socket(self):
        self.javascript(r"""
import {Socket as ReferenceSocket} from 'node:net';
// No connect/DNS/OS handles: compare only the ordinary Socket event facade.
function observe(Socket, event, scenario) {
 const socket=new Socket(), trace=[];
 function listener(value) { assert.equal(this,socket);trace.push(value); }
 if(scenario==='duplicate-once-first') {
  socket.once(event,listener).on(event,listener);
  for(const value of ['first','second','third'])socket.emit(event,value);
 } else if(scenario==='duplicate-once-last') {
  socket.on(event,listener).once(event,listener);
  for(const value of ['first','second','third'])socket.emit(event,value);
 } else if(scenario==='nested-earlier-listener') {
  let nested=false;
  socket.on(event,function(value) {
   assert.equal(this,socket);trace.push('persistent:'+value);
   if(!nested) { nested=true;socket.emit(event,'nested');nested=false; }
  });
  socket.once(event,listener);socket.emit(event,'outer');
 } else if(scenario==='nested-same-function') {
  let nested=false;
  function shared(value) {
   assert.equal(this,socket);trace.push(value);
   if(!nested) { nested=true;socket.emit(event,'nested');nested=false; }
  }
  socket.once(event,shared).on(event,shared);socket.emit(event,'outer');
 } else if(scenario==='duplicate-once-registrations') {
  socket.once(event,listener).once(event,listener);
  socket.emit(event,'first');socket.emit(event,'second');
 } else throw new Error('unknown event scenario');
 return {trace,left:socket.listenerCount(event)};
}
for(const event of ['ready','timeout','drain','connect']) {
 for(const scenario of ['duplicate-once-first','duplicate-once-last',
     'nested-earlier-listener','nested-same-function','duplicate-once-registrations']) {
  const f=fixture(), expected=observe(ReferenceSocket,event,scenario);
  assert.deepEqual(observe(f.net.Socket,event,scenario),expected,event+':'+scenario);
  assert.deepEqual(f.calls,[]);f.transport.assertEmpty();
 }
}
""")

    def test_listener_snapshot_removal_and_replacement_match_node_socket(self):
        self.javascript(r"""
import {Socket as ReferenceSocket} from 'node:net';
function observe(Socket, scenario) {
 const socket=new Socket(), trace=[];
 function later(value) { assert.equal(this,socket);trace.push('later:'+value); }
 socket.on('ready',function(value) {
  trace.push('first:'+value);
  if(value!=='first')return;
  if(scenario==='replace-all')socket.removeAllListeners('ready');
  else socket.removeListener('ready',later);
  if(scenario!=='remove-only')socket.on('ready',later);
 });
 socket.once('ready',later);
 socket.emit('ready','first');socket.emit('ready','second');
 return {trace,left:socket.listenerCount('ready')};
}
for(const scenario of ['replace-all','replace-one','remove-only']) {
 const f=fixture();assert.deepEqual(observe(f.net.Socket,scenario),observe(ReferenceSocket,scenario),scenario);
 assert.deepEqual(f.calls,[]);f.transport.assertEmpty();
}
// Public removeListener/off still removes the newest registration of a
// function, unlike the private identity-based consumption of one once row.
for(const order of [['on','once'],['once','on']])for(const method of ['off','removeListener']) {
 function removed(Socket) {
  const socket=new Socket();let calls=0;const listener=()=>++calls;
  for(const add of order)socket[add]('ready',listener);
  assert.equal(socket[method]('ready',listener),socket);
  socket.emit('ready');socket.emit('ready');
  return {calls,left:socket.listenerCount('ready')};
 }
 const f=fixture();assert.deepEqual(removed(f.net.Socket),removed(ReferenceSocket));f.transport.assertEmpty();
}
""")

    def test_once_callback_fault_preserves_original_value_and_other_registrations(self):
        self.javascript(r"""
import {Socket as ReferenceSocket} from 'node:net';
for(const fault of [undefined,null,false,0,'',Object.freeze({original:true}),new Error('original')]) {
 function observed(Socket) {
  const socket=new Socket();let calls=0,caught=0;
  function listener(){assert.equal(this,socket);++calls;throw fault;}
  socket.once('ready',listener).on('ready',listener);
  for(let turn=0;turn<3;++turn) {
   let threw=false;
   try { socket.emit('ready'); }
   catch(value) { threw=true;++caught;assert.equal(value,fault); }
   assert.equal(threw,true,'a listener exception must escape unchanged');
  }
  return {calls,caught,left:socket.listenerCount('ready')};
 }
 const f=fixture();assert.deepEqual(observed(f.net.Socket),observed(ReferenceSocket));f.transport.assertEmpty();
}
// A previously consumed one-shot callback stays consumed even if a later
// nested callback throws and the outer emission is resumed by its caller.
function reentry(Socket) {
 const socket=new Socket(),fault={},trace=[];let nested=false;
 socket.on('ready',()=>{if(!nested){nested=true;try{socket.emit('ready')}catch(value){assert.equal(value,fault)}nested=false;}});
 socket.once('ready',()=>trace.push('once'));
 socket.on('ready',()=>{if(nested)throw fault;trace.push('last')});
 socket.emit('ready');return trace;
}
const f=fixture();assert.deepEqual(reentry(f.net.Socket),reentry(ReferenceSocket));f.transport.assertEmpty();
""")

    def test_caught_once_fault_keeps_existing_socket_tail_and_fresh_state(self):
        self.javascript(r"""
// Actual LSF facade/transport source with the owning suite's ACK doubles.
// This is not native socket or physical-retirement evidence.
for(let activation=0;activation<2;++activation) {
 const f=fixture(),connected=deferred(),closed=deferred();
 const socket=f.net.connect(32123,'localhost');
 socket.once('connect',connected.resolve).once('close',closed.resolve).on('error',closed.reject);
 await connected.promise;await turn();
 const fault=Object.freeze({activation});let calls=0;
 function listener(){assert.equal(this,socket);++calls;throw fault;}
 socket.once('timeout',listener).on('timeout',listener);
 for(let attempt=0;attempt<2;++attempt) {
  let caught=false;
  try { socket.emit('timeout'); } catch(value) { caught=true;assert.equal(value,fault); }
  assert(caught);assert.equal(socket.listenerCount('timeout'),1);
 }
 assert.equal(calls,2);assert.equal(socket.destroyed,false);
 assert.throws(f.transport.assertEmpty,/unclosed/);
 socket.removeListener('timeout',listener);socket.destroy();await closed.promise;
 assert.deepEqual(f.calls,['connect','close']);f.transport.assertEmpty();
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


    def timer_javascript(self, body):
        # Real facade and transport; only the clock/provider/ACKs are doubles.
        self.javascript(r"""
function timedFixture(options={}) {
 const timers=new Map(), calls=[];let next=0, refuse=false;
 const timerFault=Object.freeze({timerAdmissionRefused:true});
 const t={...target(),setTimeout(callback,milliseconds){
  if(refuse)throw timerFault;
  const id=++next;timers.set(id,{callback,milliseconds});return id;
 },clearTimeout(id){timers.delete(id)}};
 const native={connect:request=>{calls.push(['connect',request]);return options.connect?.(request)??settled({})},
  read:()=>settled(undefined),write:(_,bytes)=>settled(bytes.length),
  ready:()=>settled({writable:true}),chunkBytes:()=>settled(new Uint8Array()),
  shutdown:()=>{calls.push(['shutdown']);return settled({})},
  close:()=>{calls.push(['close']);return settled({})}};
 const transport=createNodeNetTransport(native,t,()=>({}));
 const net=createNodeNetModule(transport,Buffer,()=>options.snapshot===true,t);
 return {net,transport,timers,calls,timerFault,refuse(value=true){refuse=value},
  fire(id){const row=timers.get(id);assert(row);timers.delete(id);row.callback()}};
}
"""+body)

    def test_timeout_zero_removes_only_requested_callback_like_node(self):
        self.timer_javascript(r"""
import {Socket as ReferenceSocket} from 'node:net';
function observe(Socket) {
 const s=new Socket(),trace=[];
 function same(){trace.push('same')};function other(){trace.push('other')};
 s.once('timeout',same).on('timeout',same).once('timeout',other);
 s.setTimeout(0,same);const afterDisable=s.listenerCount('timeout');
 s.emit('timeout');s.emit('timeout');
 const afterEmit=s.listenerCount('timeout');s.destroy();
 // A destroyed socket must not retain a newly supplied timeout callback.
 s.setTimeout(7,same);const afterDestroy=s.listenerCount('timeout');
 return {trace,afterDisable,afterEmit,afterDestroy};
}
const f=timedFixture();assert.deepEqual(observe(f.net.Socket),observe(ReferenceSocket));
assert.equal(f.timers.size,0);f.transport.assertEmpty();
""")

    def test_idle_timeout_notifies_before_connect_without_network_effects(self):
        self.timer_javascript(r"""
import {Socket as ReferenceSocket} from 'node:net';
// Actual Node timer on an unconnected Socket; a bounded watchdog keeps the
// reference process alive. No connect(), DNS or peer is used by this control.
const reference=new ReferenceSocket();let referenceCount=0;
await new Promise((yes,no)=>{
 const watchdog=setTimeout(()=>{reference.destroy();no(Error('reference timeout absent'))},2000);
 reference.setTimeout(7,function(){assert.equal(this,reference);++referenceCount;clearTimeout(watchdog);yes()});
});reference.destroy();
const f=timedFixture(),s=new f.net.Socket();let actual=0;
s.setTimeout(7,function(){assert.equal(this,s);++actual});
assert.equal(f.timers.size,1);assert.equal(f.calls.length,0);
f.fire([...f.timers.keys()][0]);assert.equal(actual,referenceCount);
assert.equal(s.destroyed,false);assert.equal(s.listenerCount('timeout'),0);
s.destroy();await turn();f.transport.assertEmpty();
""")

    def test_pending_connect_timeout_keeps_original_cancellation_and_borrow_acks(self):
        self.timer_javascript(r"""
for(let activation=0;activation<2;++activation){
 const logical=deferred(),borrow=deferred(),cancelled=deferred();let cancellations=0;
 const f=timedFixture({connect:()=>({promise:logical.promise,borrowReleased:borrow.promise,
  cancel(){++cancellations;return cancelled.promise}})}),s=new f.net.Socket();
 const events=[],closed=deferred();
 s.on('connect',()=>events.push('connect')).on('error',closed.reject)
  .on('close',()=>{events.push('close');closed.resolve()})
  .setTimeout(7,()=>events.push('timeout')).connect(32123,'localhost');
 await turn();assert.equal(f.timers.size,1);assert.equal(s.connecting,true);
 f.fire([...f.timers.keys()][0]);assert.deepEqual(events,['timeout']);
 assert.equal(s.destroyed,false);assert.equal(cancellations,0);
 assert.equal(f.calls.length,1);assert.throws(f.transport.assertEmpty,/unclosed/);
 s.destroy();await turn();assert.equal(cancellations,1);
 // Local cancellation is not result, borrow, close, or retirement evidence.
 cancelled.resolve();await turn();assert.deepEqual(events,['timeout']);
 logical.resolve({});await turn();assert.deepEqual(events,['timeout']);
 assert.equal(f.calls.length,1);assert.throws(f.transport.assertEmpty,/unclosed/);
 borrow.resolve();await closed.promise;
 assert.deepEqual(events,['timeout','close']);assert.equal(cancellations,1);
 assert.deepEqual(f.calls.map(row=>row[0]),['connect','close']);
 assert.equal(f.timers.size,0);f.transport.assertEmpty();
}
""")

    def test_replaced_and_disabled_timeout_callbacks_cannot_steal_current_timer(self):
        self.timer_javascript(r"""
const f=timedFixture(),s=new f.net.Socket(),connected=deferred(),closed=deferred();let notifications=0;
s.on('timeout',()=>++notifications).on('error',closed.reject)
 .once('connect',connected.resolve).once('close',closed.resolve).connect(32123,'localhost');
await connected.promise;await turn();s.setTimeout(7);
const old=[...f.timers.values()][0].callback;s.setTimeout(11);
const current=[...f.timers.entries()][0];assert.equal(current[1].milliseconds,11);
old();assert.equal(notifications,0);assert.equal(f.timers.size,1);
f.fire(current[0]);assert.equal(notifications,1);assert.equal(s.destroyed,false);
s.setTimeout(13);const disabled=[...f.timers.values()][0].callback;
s.setTimeout(0);assert.equal(f.timers.size,0);disabled();assert.equal(notifications,1);
s.setTimeout(17);const replaced=[...f.timers.values()][0].callback;
await new Promise((yes,no)=>s.write('x',error=>error?no(error):yes()));
assert.equal(f.timers.size,1);replaced();assert.equal(notifications,1);
s.destroy();await closed.promise;assert.equal(f.timers.size,0);f.transport.assertEmpty();
""")

    def test_timeout_admission_refusal_does_not_publish_callback_or_dispatch(self):
        self.timer_javascript(r"""
const f=timedFixture(),s=new f.net.Socket();let notified=0;
f.refuse();let caught=false;
try{s.setTimeout(7,()=>++notified)}catch(fault){caught=true;assert.equal(fault,f.timerFault)}
assert(caught);assert.equal(s.listenerCount('timeout'),0);assert.equal(f.timers.size,0);
assert.equal(f.calls.length,0);f.transport.assertEmpty();
f.refuse(false);s.setTimeout(7,()=>++notified);
const stale=[...f.timers.values()][0].callback;
f.refuse();caught=false;
try{s.connect(32123,'localhost')}catch(fault){caught=true;assert.equal(fault,f.timerFault)}
assert(caught);assert.equal(s.connecting,false);assert.equal(f.calls.length,0);
assert.equal(f.timers.size,0);stale();assert.equal(notified,0);f.transport.assertEmpty();
s.destroy();await turn();f.transport.assertEmpty();
""")


    def test_timeout_snapshot_and_invalid_arguments_have_no_timer_or_connect_effect(self):
        self.timer_javascript(r"""
const f=timedFixture(),s=new f.net.Socket();let calls=0;
for(const milliseconds of [-1,0.5,Infinity,NaN,2147483648,'7',null,undefined]) {
 assert.throws(()=>s.setTimeout(milliseconds,()=>++calls),error=>error.code==='ERR_INVALID_ARG_VALUE');
}
assert.throws(()=>s.setTimeout(7,{}),error=>error.code==='ERR_INVALID_ARG_VALUE');
assert.equal(s.timeout,undefined);assert.equal(s.listenerCount('timeout'),0);
assert.equal(f.timers.size,0);assert.equal(f.calls.length,0);assert.equal(calls,0);f.transport.assertEmpty();
const frozen=timedFixture({snapshot:true}),image=new frozen.net.Socket();
assert.throws(()=>image.setTimeout(7,()=>++calls),error=>error.code==='ERR_LSF_SNAPSHOT_EFFECT');
assert.equal(image.timeout,undefined);assert.equal(image.listenerCount('timeout'),0);
assert.equal(frozen.timers.size,0);assert.equal(frozen.calls.length,0);frozen.transport.assertEmpty();
assert.equal(image.setTimeout(0),image);assert.equal(frozen.timers.size,0);
s.destroy();image.destroy();await turn();
""")

    def test_timeout_callback_failure_keeps_original_fault_and_socket_custody(self):
        self.timer_javascript(r"""
for(const fault of [undefined,null,false,0,'',Object.freeze({original:true})]) {
 const f=timedFixture(),s=new f.net.Socket(),connected=deferred();let later=0;
 s.once('connect',connected.resolve).connect(32123,'localhost');await connected.promise;await turn();
 s.setTimeout(7,function(){assert.equal(this,s);throw fault}).on('timeout',()=>++later);
 let caught=false;
 try {f.fire([...f.timers.keys()][0])}catch(value){caught=true;assert.equal(value,fault)}
 assert(caught);assert.equal(later,0);assert.equal(f.timers.size,0);
 assert.equal(s.destroyed,false);assert.equal(s.listenerCount('timeout'),1);
 // The original transport poisons an escaped callback. No facade timer path
 // may convert that into successful root settlement or a fictional refund.
 caught=false;try{f.transport.beginAcceptedClose()}catch(value){caught=true;assert.equal(value,fault)}
 assert(caught);assert.throws(f.transport.assertEmpty,/unclosed/);
 s.destroy();await turn();assert.deepEqual(f.calls.map(row=>row[0]),['connect']);
 assert.throws(f.transport.assertEmpty,/unclosed/);
 const fresh=timedFixture();fresh.transport.assertEmpty();
}
""")

    def test_timeout_callback_can_rearm_without_old_callback_clearing_replacement(self):
        self.timer_javascript(r"""
const f=timedFixture(),s=new f.net.Socket();let notifications=0;
s.setTimeout(7,function(){
 ++notifications;this.setTimeout(11,function(){++notifications;this.destroy()});
});
const first=[...f.timers.entries()][0];f.fire(first[0]);assert.equal(notifications,1);
const replacement=[...f.timers.entries()][0];assert.equal(replacement[1].milliseconds,11);
first[1].callback();assert.equal(notifications,1);assert.equal(f.timers.size,1);
f.fire(replacement[0]);await turn();assert.equal(notifications,2);assert.equal(s.destroyed,true);
replacement[1].callback();assert.equal(notifications,2);assert.equal(f.timers.size,0);
assert.equal(f.calls.length,0);f.transport.assertEmpty();
""")


def compiler_controls(frontend: Path) -> dict:
    """Real bundler control, required tools rather than a successful skip."""
    self = unittest.TestCase()
    tools, node, versions = pinned_frontend(frontend)
    attempts = []
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        imports = work/'imports.json'
        imports.write_text(json.dumps([net_profile.INTERFACE]), encoding='utf-8')
        configuration = {'runtimeProfile': 'spidermonkey-activation-promises-clocks-imports-v1',
            'nativeClockInterfaces': ['latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'],
            'standardNetProfile': net_profile.PROFILE, 'standardNetIdentities': net_profile.identities(ROOT)}

        def bundle(label, source, configured=None, passed=True):
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
            attempts.append({'case': label, 'expected': 'compiled' if passed else 'refused',
                             'returncode': result.returncode})
            if not passed:
                for path in (output, work/'application.mjs.inputs.json', work/'application.mjs.map'):
                    self.assertFalse(path.exists(), 'refused build left a successful-looking output')
                return result.stderr
            observation = json.loads((work/'application.mjs.inputs.json').read_bytes())
            # Exercise the normal source-bound reader, not only a string in the bundle.
            net_profile.selected(observation, net_profile.identities(ROOT))
            return output.read_text(encoding='utf-8'), observation

        # The same compiler boundary serves ordinary direct/transitive
        # modules. Fake npm fallbacks must never satisfy a standard builtin.
        # These local packages test resolution, not published-library evidence.
        for name in ('tls', 'node:tls', 'dns', 'node:dns/promises',
                     'stream', 'node:stream/promises', 'node:stream/web', 'stream/consumers'):
            message = bundle('direct-' + name, f'import * as api from {json.dumps(name)}; export const value=api;', passed=False)
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
        transitive, observation = bundle('transitive-net', "import net from 'outer'; export const Socket=net.Socket;", captured)
        self.assertEqual(observation['standardNetModules'], ['node:net'])
        self.assertIn('node_modules/outer/index.js', observation['inputs'])
        self.assertIn('node_modules/inner/index.cjs', observation['inputs'])
        self.assertNotIn('browser-fallback-must-not-run', transitive)
        for name in ('dns', 'node:tls', 'node:stream/consumers'):
            (packages/'inner/index.cjs').write_text('module.exports = require(' + json.dumps(name) + ');', encoding='utf-8')
            message = bundle('transitive-' + name, "import api from 'outer'; export const value=api;", captured, passed=False)
            self.assertIn('standard-node-network-module-unavailable:node:' + name.removeprefix('node:'), message)
        # A library catching require() failures must not turn an unavailable
        # builtin into a successful npm/browser fallback during compilation.
        for name in ('dns', 'node:tls', 'node:stream'):
            (packages/'inner/index.cjs').write_text(
                'try { module.exports = require(' + json.dumps(name) +
                '); } catch { module.exports = "fake-success"; }', encoding='utf-8')
            message = bundle('caught-' + name, "import api from 'outer'; export const value=api;", captured, passed=False)
            self.assertIn('standard-node-network-module-unavailable:node:' + name.removeprefix('node:'), message)
        # The selected package can shadow a builtin name only as a file, never
        # as standard net. Profile disablement applies at transitive depth too.
        (packages/'inner/index.cjs').write_text("module.exports = require('net');", encoding='utf-8')
        disabled = {key: value for key, value in captured.items() if not key.startswith('standardNet')}
        message = bundle('transitive-disabled-net', "import api from 'outer'; export const value=api;", disabled, passed=False)
        self.assertIn('standard-node-net-requires-exact-stream-runtime-and-declaration', message)
        for name in ('dns', 'node:tls', 'node:stream/web'):
            message = bundle('side-effect-' + name, 'import ' + json.dumps(name) + '; export const value=7;', passed=False)
            self.assertIn('standard-node-network-module-unavailable:node:' + name.removeprefix('node:'), message)
        # A relative filename resembling a builtin remains ordinary input.
        (packages/'inner/index.cjs').write_text("module.exports = require('./dns.cjs');", encoding='utf-8')
        (packages/'inner/dns.cjs').write_text("module.exports = 42;", encoding='utf-8')
        _, observation = bundle('relative-lookalike', "import value from 'outer'; export const answer=value;", captured)
        self.assertNotIn('standardNetModules', observation)
    return {'versions': versions, 'cases': attempts}


def pinned_gate(frontend: Path) -> dict:
    """Use the existing frontend; preserve all original socket tests unchanged."""
    from tools.typescript_guest.build import RECIPE
    paths = sorted(set((*RECIPE, 'tools/tests/test_typescript_node_net.py',
        'tools/tests/test_typescript_network_boundary.py',
        'tools/tests/fixtures/typescript_node_net_generated.json',
        'sdk/typescript-guest/tools/package.json', 'sdk/typescript-guest/tools/package-lock.json')))
    def source_identities():
        return {name: 'sha256:' + hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in paths}
    before = source_identities()
    compiler = compiler_controls(frontend)
    tools = frontend.resolve(strict=True)
    with patch.dict(os.environ, {'LSF_TYPESCRIPT_FRONTEND': str(tools),
                                 'LSF_TYPESCRIPT_ACORN': str(tools/'node_modules/acorn/dist/acorn.mjs')}):
        suite = unittest.TestSuite((unittest.defaultTestLoader.loadTestsFromModule(socket_controls),
                                   unittest.defaultTestLoader.loadTestsFromTestCase(TypeScriptNetworkBoundary)))
        controls = require_complete_controls(unittest.TextTestRunner(verbosity=2).run(suite))
    if source_identities() != before:
        raise ValueError('network-boundary-source-drift')
    return {'schemaVersion': 'latent.typescript.network-boundary.v1', 'status': 'passed',
            'scope': 'compiler-and-host-controls-only', 'signedExecution': False,
            'providerQualification': False, 'sourceInputs': before,
            'compiler': compiler, 'hostControls': controls}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run the required pinned networking compiler and host gate (not signed qualification).')
    parser.add_argument('--frontend', required=True, type=Path, help='Normal installed pinned TypeScript tools directory')
    # A success observation is emitted only after every real compiler/model
    # control passes without skips. Stderr retains the ordinary test failures.
    print(json.dumps(pinned_gate(parser.parse_args().frontend), sort_keys=True))
