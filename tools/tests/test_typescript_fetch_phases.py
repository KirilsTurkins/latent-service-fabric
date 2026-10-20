"""Phase-adapter source/reference controls; no signed V7 component claim."""
import unittest
from tools.typescript_guest import fetch_profile as profile
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE,SYNC_PROFILE
from tools.tests import test_typescript_fetch as original


class TypeScriptFetchPhaseTests(unittest.TestCase):
    def javascript(self, source):
        original.TypeScriptFetchTests().run_javascript(source)

    def test_phase_selection_requires_owned_async_profile_and_declared_contract(self):
        for selected in (SYNC_PROFILE,IMPORT_PROFILE):
            for imports in ([],[profile.INTERFACE],[profile.PHASE_INTERFACE],
                            [profile.INTERFACE,profile.PHASE_INTERFACE]):
                observed=profile.bundle_configuration({},selected,imports)
                expected=(profile.PHASE_PROFILE if profile.PHASE_INTERFACE in imports else
                          profile.PROFILE if profile.INTERFACE in imports else None)
                self.assertEqual(observed.get('standardFetchProfile'),expected if selected==IMPORT_PROFILE else None)
        for override in (profile.PROFILE,profile.PHASE_PROFILE,'foreign'):
            with self.assertRaisesRegex(ValueError,'cannot-override'):
                profile.bundle_configuration({'standardFetchProfile':override},IMPORT_PROFILE,[profile.PHASE_INTERFACE])

    def test_exact_latin1_empty_and_unavailable_reason_with_clone_and_original_call_arities(self):
        self.javascript(r'''
for (const [selected, reason, expected] of [
  ['lsf-fetch-phase-buffered-v2',new Uint8Array([32,79,75,9,255,32]),' OK\t\xff '],
  ['lsf-fetch-phase-buffered-v2',new Uint8Array(), ''],
  ['lsf-fetch-phase-buffered-v2',undefined,undefined],
  ['lsf-fetch-buffered-v1',new Uint8Array([79,75]),undefined]
]) {
  const calls=[], drops=[];
  const owned = name => ({[Symbol.dispose ?? Symbol.for('dispose')](){drops.push(name);}});
  const http={
    async open(...args){calls.push(['open',args.length]);return owned('upload');},
    async finish(...args){calls.push(['finish',args.length]);return {status:200,headers:[],reasonPhrase:reason,body:owned('body')};},
    async read(...args){calls.push(['read',args.length]);return undefined;}
  };
  const target={TextEncoder,TextDecoder,URL,URLSearchParams,AbortSignal,AbortController};
  installFetch(http,()=>false,target,selected);
  const response=await target.fetch('https://example.test/');
  const clone=response.clone();
  if(expected===undefined){assert.throws(()=>response.statusText,TypeError);assert.throws(()=>clone.statusText,TypeError);}
  else{assert.equal(response.statusText,expected);assert.equal(clone.statusText,expected);}
  assert.equal(await response.text(),'');assert.equal(await clone.text(),'');
  assert.deepEqual(drops,['body']);
  assert.deepEqual(calls,selected==='lsf-fetch-buffered-v1' ? [['open',1],['finish',1],['read',2]] :
    [['open',2],['finish',2],['read',3]]);
}
''')

    def test_malformed_or_oversized_wire_reason_refuses_after_actual_resource_drop(self):
        self.javascript(r'''
for(const reason of [null,'OK',new Uint16Array([79]),new Uint8Array(513),new Uint8Array([0]),new Uint8Array([127])]){
  let drops=0;
  const target={TextEncoder,TextDecoder,URL,URLSearchParams,AbortSignal,AbortController};
  const http={async open(){return {};},async finish(){return {status:200,headers:[],reasonPhrase:reason,
    body:{[Symbol.dispose ?? Symbol.for('dispose')](){drops++;}}};},async read(){return undefined;}};
  installFetch(http,()=>false,target,'lsf-fetch-phase-buffered-v2');
  await assert.rejects(target.fetch('https://example.test/'),/invalid-http-reason-phrase/);
  assert.equal(drops,1);
}
''')

    def test_phase_nested_uncertainty_and_dispatched_read_timeout_preserve_original_cause(self):
        self.javascript(r'''
for(const [payload,uncertain] of [[{tag:'http',val:{tag:'uncertain'}},true],
  [{tag:'read-timeout',val:true},true],[{tag:'read-timeout',val:false},false],
  [{tag:'connect-timeout'},false],[{tag:'unsupported-phase-timing'},false]]){
  const cause={payload};let contacts=0;
  const target={TextEncoder,TextDecoder,URL,URLSearchParams,AbortSignal,AbortController};
  installFetch({async open(){contacts++;throw cause;}},()=>false,target,'lsf-fetch-phase-buffered-v2');
  await assert.rejects(target.fetch('https://example.test/'),error=>
    error instanceof TypeError && error.cause===cause && error.uncertain===uncertain);
  assert.equal(contacts,1);
}
''')
