"""Exact pinned std platform selectors for the explicit owned-thread profile.

Source integration only until the jointly rebuilt sysroot, complete final graph,
original-ledger runtime and signed ordinary API programme are qualified.
"""
from __future__ import annotations
import hashlib
from tools.rust_standard_clock_profile import RUST,RUST_COMMIT,TARGET
from tools import rust_standard_tls_profile as tls
from tools.dev_workflow.common import require

PROFILE='lsf-rust-std-owned-thread-runtime-v1'
TLS_REFERENCE='b198ed15262ba83c837936955349ebf9faddff71a20e88ae3b4052dbc3dce540'
SELECTOR='all(target_arch = "wasm32", target_os = "unknown", target_vendor = "unknown", target_env = "", not(target_feature = "atomics"))'
LIFECYCLE='std/src/thread/lifecycle.rs'
LIFECYCLE_SHA='dd6611f792e01f967deb119f9d66f611fdefc78cc3044b3f71e8814cbb62c3af'
CURRENT='std/src/thread/current.rs'
CURRENT_SHA='1084535565799fa30c42320309fa2cf4d95aacdfb022ce301b17b0a299e52109'
ORIGINALS = {'std/src/sys/thread/mod.rs': '3590ca4dc8b112c787b14fcc5585add929a6e7c827ce01c329c2ef43e45587d6', 'std/src/sys/sync/mutex/mod.rs': '1c715675a2bc34471b96de58f7aaaf2db411289cf838d17edc61cb2d6b006aa2', 'std/src/sys/sync/condvar/mod.rs': 'af88b86441a57ae779ae0a01528bc4e8b0068f1e72978547c1a08ac4d7107c2d', 'std/src/sys/sync/thread_parking/mod.rs': '26f989d09efadae98b1fa6447b386d8eda21b9fc3ef99c8bea3154d6625788a3', 'std/src/sys/sync/rwlock/mod.rs': '5438fdbc0ade05b50d7350c252ccb9d37bea596355560fbdc695f4937d727ef3', 'std/src/sys/sync/once/mod.rs': '4e9b50925535fe54275f6e3aa1bb26b093d15e4a6168935bdb92d1117271293c'}
BRANCHES = {'std/src/sys/thread/mod.rs': 'pub(crate) mod lsf;\n        pub use lsf::*;', 'std/src/sys/sync/mutex/mod.rs': 'mod lsf;\n        pub use lsf::Mutex;', 'std/src/sys/sync/condvar/mod.rs': 'mod lsf;\n        pub use lsf::Condvar;', 'std/src/sys/sync/thread_parking/mod.rs': 'mod lsf;\n        pub use lsf::Parker;', 'std/src/sys/sync/rwlock/mod.rs': 'mod lsf;\n        pub use lsf::RwLock;', 'std/src/sys/sync/once/mod.rs': 'mod lsf;\n        pub use lsf::{Once, OnceState};'}
ORIGINALS[LIFECYCLE]=LIFECYCLE_SHA
ORIGINALS[CURRENT]=CURRENT_SHA
SOURCES={
 'std/src/sys/thread_local/key/lsf.rs':'sdk/rust-standard-runtime/thread_tls.rs',
 'std/src/sys/thread/lsf.rs':'sdk/rust-standard-runtime/thread.rs',
 'std/src/sys/thread/lsf/runtime.rs':'sdk/rust-standard-runtime/thread_runtime.rs',
 'std/src/sys/thread/lsf/runtime/owner.rs':'sdk/rust-standard-runtime/runtime_owner.rs',
 'std/src/sys/thread/lsf/runtime/registry.rs':'sdk/rust-standard-runtime/thread_registry.rs',
 'std/src/sys/thread/lsf/runtime/wait_registry.rs':'sdk/rust-standard-runtime/thread_wait_registry.rs',
 'std/src/sys/thread/lsf/runtime/wait_driver.rs':'sdk/rust-standard-runtime/thread_wait_driver.rs',
 'std/src/sys/thread/lsf/runtime/start.rs':'sdk/rust-standard-runtime/thread_start.rs',
 'std/src/sys/thread/lsf/runtime/executor_lifecycle.rs':'sdk/rust-standard-runtime/executor_lifecycle.rs',
 'std/src/sys/thread/lsf/runtime/executor_control.rs':'sdk/rust-standard-runtime/executor_control.rs',
 'std/src/sys/thread/lsf/runtime/executor_bridge.rs':'sdk/rust-standard-runtime/executor_bridge.rs',
 'std/src/sys/thread/lsf/runtime/executor_root.rs':'sdk/rust-standard-runtime/executor_root.rs',
 'std/src/sys/thread/lsf/runtime/executor_worker.rs':'sdk/rust-standard-runtime/executor_worker.rs',
 'std/src/sys/thread/lsf/wait.rs':'sdk/rust-standard-runtime/thread_wait.rs',
 'std/src/sys/sync/mutex/lsf.rs':'sdk/rust-standard-runtime/mutex.rs',
 'std/src/sys/sync/condvar/lsf.rs':'sdk/rust-standard-runtime/condvar.rs',
 'std/src/sys/sync/thread_parking/lsf.rs':'sdk/rust-standard-runtime/parker.rs',
 'std/src/sys/sync/rwlock/lsf.rs':'sdk/rust-standard-runtime/rwlock.rs',
 'std/src/sys/sync/once/lsf.rs':'sdk/rust-standard-runtime/once.rs',
}
EXECUTOR='futures-executor'
EXECUTOR_VERSION='0.3.31'
EXECUTOR_ARCHIVE_SHA256='1e28d1d997f585e54aebc3f97d39e72338912123a67330d723fdbb564d646c9f'
EXECUTOR_ORIGINALS={
 'src/lib.rs':'c72ebbb09e231175d1e8286ed258207ee384454436cc2261a712d208abef60c3',
 'src/thread_pool.rs':'6fec12d757b73a5dad7f1c711cf947de2968a8b2d9d549bfad0a3921e77d5fdc',
 'src/unpark_mutex.rs':'ac2b4083561807be8f42e211f7e91a0aa0bb6238df5d3b2cb9712d62bb886cee',
 'src/enter.rs':'ae3a196c0b32cf256e474a988b9fd9749fa645163b66915fbc894bea8e2efb56',
}
EXECUTOR_SOURCES={
 'src/lsf_thread_pool_impl.rs':'sdk/rust-standard-runtime/futures_thread_pool.rs',
 'src/lsf_thread_pool.rs':'sdk/rust-standard-runtime/futures_pool_link.rs',
}
RECIPE=('tools/rust_standard_thread_profile.py','sdk/rust-standard-runtime/tls.rs',
        *SOURCES.values(),*EXECUTOR_SOURCES.values())

def complete_overlay(original,inputs):
 """Compose the original TLS selector and full thread PAL on one std source.

 Only this explicit no-atomics target branch changes. The ordinary TLS-only
 profile's selector and source helper remain byte-exact for its consumers.
 """
 changes=tls.overlay({name:original[name] for name in tls.ORIGINALS},
                     inputs['sdk/rust-standard-runtime/thread_tls.rs'])
 name='std/src/sys/thread_local/mod.rs'
 old=tls.SELECTOR
 new=SELECTOR.encode()
 require(changes[name].count(old)==3,'rust-thread-three-original-tls-selectors')
 changes[name]=changes[name].replace(old,new)
 changes.update(overlay({name:original[name] for name in ORIGINALS},
     {name:inputs[name] for name in SOURCES.values()},
     tls_reference=inputs['sdk/rust-standard-runtime/tls.rs']))
 return changes

def overlay(original,runtime,*,tls_reference,target=TARGET,rust=RUST):
 require(target==TARGET and rust==RUST,'rust-thread-maintained-target-and-compiler-only')
 require(type(tls_reference)is bytes and hashlib.sha256(tls_reference).hexdigest()==TLS_REFERENCE,
         'rust-thread-original-tls-profile-preimage')
 require(set(original)==set(ORIGINALS),'rust-thread-original-selector-closure')
 require(set(runtime)==set(SOURCES.values()),'rust-thread-runtime-source-closure')
 require(all(type(v)is bytes and 0<len(v)<=128*1024 for v in runtime.values()),'rust-thread-runtime-source-bounds')
 require(sum(map(len,runtime.values()))<=512*1024,'rust-thread-runtime-total-source-bound')
 selected={}
 for name,wanted in ORIGINALS.items():
  raw=original[name]
  require(type(raw)is bytes and hashlib.sha256(raw).hexdigest()==wanted,'rust-thread-upstream-selector-preimage')
  if name==LIFECYCLE:
   selected[name]=packet_lifecycle(raw)
   continue
  if name==CURRENT:
   selected[name]=logical_thread_id(raw)
   continue
  needle=b'cfg_select! {\n'
  require(raw.count(needle)==1,'rust-thread-one-original-selector')
  branch=('cfg_select! {\n    '+SELECTOR+' => {\n        '+BRANCHES[name]+'\n    }\n').encode()
  selected[name]=raw.replace(needle,branch,1)
 for target_path,source_path in SOURCES.items():selected[target_path]=runtime[source_path]
 return selected

def logical_thread_id(raw):
 """Route Rust's persistent ThreadId through the selected logical TLS backend."""
 require(type(raw)is bytes and hashlib.sha256(raw).hexdigest()==CURRENT_SHA,
         'rust-thread-original-current-preimage')
 needle=b'    cfg_select! {\n        target_thread_local => {'
 branch=('    cfg_select! {\n        all(target_thread_local, not('+SELECTOR+')) => {').encode()
 require(raw.count(needle)==1,'rust-thread-one-current-native-tls-selector')
 selected=raw.replace(needle,branch,1)
 require(selected.replace(branch,needle,1)==raw,'rust-thread-current-id-selector-only')
 return selected

def packet_lifecycle(raw):
 require(type(raw)is bytes and hashlib.sha256(raw).hexdigest()==LIFECYCLE_SHA,
         'rust-thread-original-packet-lifecycle-preimage')
 ctor=b'Arc::new(Packet { scope: scope_data, result: UnsafeCell::new(None), _marker: PhantomData });'
 field=b"    _marker: PhantomData<Option<&'scope ScopeData>>,\n"
 require(raw.count(ctor)==1 and raw.count(field)==1,'rust-thread-exact-packet-field-construction')
 guard=('#[cfg('+SELECTOR+')]').encode()
 actual_ctor=(b'Arc::new(Packet { scope: scope_data, result: UnsafeCell::new(None), _marker: PhantomData,\n'
              b'            '+guard+b'\n'
              b'            _runtime_result: imp::lsf::runtime::PacketResult::admit()?,\n'
              b'        });')
 actual_field=field+b'    '+guard+b'\n    _runtime_result: imp::lsf::runtime::PacketResult,\n'
 selected=raw.replace(ctor,actual_ctor).replace(field,actual_field)
 # ThreadInit/init, original rust_start, Packet::Drop and JoinInner::join are
 # byte-exact. Only this selected logical-owner field and construction differ.
 require(selected.replace(actual_ctor,ctor).replace(actual_field,field)==raw,
         'rust-thread-packet-only-closed-owner-overlay')
 return selected


def executor_overlay(original,runtime,*,package,version,archive_sha256,target=TARGET,rust=RUST):
 """Closed target-side linkage for the captured ordinary ThreadPool.

 The unchanged crate remains the base. Only this selected wasm32 branch uses
 the port and its guest-local std linkage; host-side dependency compilations
 and configurations without the original thread-pool/std features keep their
 original module selection. No feature or executor is enabled by this overlay.
 Full private call/table target authentication remains a compiler gate.
 """
 require(target==TARGET and rust==RUST,'rust-thread-executor-maintained-target-and-compiler-only')
 require(package==EXECUTOR and version==EXECUTOR_VERSION and archive_sha256==EXECUTOR_ARCHIVE_SHA256,
         'rust-thread-executor-captured-package-and-archive')
 require(set(original)==set(EXECUTOR_ORIGINALS),'rust-thread-executor-original-source-closure')
 require(all(type(value)is bytes and hashlib.sha256(value).hexdigest()==EXECUTOR_ORIGINALS[name]
             for name,value in original.items()),'rust-thread-executor-original-source-preimage')
 require(set(runtime)==set(EXECUTOR_SOURCES.values()),'rust-thread-executor-runtime-source-closure')
 require(all(type(value)is bytes and 0<len(value)<=128*1024 for value in runtime.values()),
         'rust-thread-executor-runtime-source-bounds')
 raw=original['src/lib.rs']
 needle=b'#[cfg(feature = "thread-pool")]\n#[cfg_attr(docsrs, doc(cfg(feature = "thread-pool")))]\n#[cfg(feature = "std")]\nmod thread_pool;'
 require(raw.count(needle)==1,'rust-thread-executor-original-module-selector')
 selected=('#[cfg(all(feature = "thread-pool", feature = "std", '+SELECTOR+'))]\n'
           'mod lsf_thread_pool;\n').encode()+needle.replace(
              b'mod thread_pool;',('#[cfg_attr('+SELECTOR+', path = "lsf_thread_pool_impl.rs")]\nmod thread_pool;').encode())
 derived=raw.replace(needle,selected)
 require(derived.replace(selected,needle)==raw,'rust-thread-executor-selector-only-overlay')
 return {'src/lib.rs':derived,**{name:runtime[source] for name,source in EXECUTOR_SOURCES.items()}}
