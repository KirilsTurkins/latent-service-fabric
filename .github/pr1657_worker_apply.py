from pathlib import Path
import json, os, shutil, subprocess, sys
root=Path.cwd()
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()=='6994c4c4c7f0bb40aa405d804e47850a2dd60081'
source=Path(os.environ['RUNNER_TEMP'])/'pr1657-worker-stage'
paths=[]
def edit(path, old, new):
 p=root/path;s=p.read_text();assert s.count(old)==1,(path,s.count(old));p.write_text(s.replace(old,new))
 if path not in paths:paths.append(path)
for path in ('crates/latent-wasmtime/src/native_stacks/combined.rs','crates/latent-wasmtime/src/native_stacks/tests/combined.rs'):
 dest=root/path;assert not dest.exists();dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/path,dest);paths.append(path)
edit('crates/latent-wasmtime/src/backend.rs','''            runtime.surface.hostcall_fuel,
            #[cfg(feature = "rust-thread-trap-diagnostic")]
            crate::rust_thread_fault::scheduler_observer(&runtime.threading),''','''            &runtime,''')
edit('crates/latent-wasmtime/src/backend.rs','''        hostcall_fuel: usize,
        #[cfg(feature = "rust-thread-trap-diagnostic")] scheduler_observer: Option<
            fn(&wasmtime::AsyncDeadlockSnapshot),
        >,''','''        runtime: &PreparedRuntime,''')
edit('crates/latent-wasmtime/src/backend.rs','''                !self.config.owned_native_threads,
            )?;''','''                !self.config.owned_native_threads,
                #[cfg(feature = "development-rust-http-combined")]
                matches!(runtime.threading,
                    crate::component_threading::Authentication::RustCombinedHttpVerified(_))
                    .then_some((&runtime.threading, &runtime.descriptor)),
            )?;''')
edit('crates/latent-wasmtime/src/backend.rs','''                scheduler_observer,
            )''','''                crate::rust_thread_fault::scheduler_observer(&runtime.threading),
            )''')
edit('crates/latent-wasmtime/src/backend.rs','''        store.set_hostcall_fuel(hostcall_fuel);''','''        store.set_hostcall_fuel(runtime.surface.hostcall_fuel);''')
edit('crates/latent-wasmtime/src/host/runtime.rs','''    async_workers: bool,
) -> Result<Arc<crate::native_stacks::StackContext>, PlatformError> {''','''    async_workers: bool,
    #[cfg(feature = "development-rust-http-combined")]
    combined: Option<(&crate::component_threading::Authentication, &latent_executor::PreparedComponent)>,
) -> Result<Arc<crate::native_stacks::StackContext>, PlatformError> {''')
edit('crates/latent-wasmtime/src/host/runtime.rs','''    let context = if async_workers {''','''    #[cfg(feature = "development-rust-http-combined")]
    if let Some((proof, descriptor)) = combined {
        let maximum = maximum_native.expect("initialized original runtime limits") as usize;
        if async_workers || maximum_children != maximum.saturating_sub(1) {
            return Err(failure(PlatformErrorCode::Internal, "native-stack-profile-conflict"));
        }
        let context = crate::native_stacks::StackContext::with_combined_http(
            budget, table.runtime.clone(), size, maximum, proof, descriptor,
        )?;
        table.native_stacks = Some(Arc::clone(&context));
        return Ok(context);
    }
    let context = if async_workers {''')
edit('crates/latent-wasmtime/src/native_stacks.rs','''mod children;
mod workers;''','''mod children;
#[cfg(feature = "development-rust-http-combined")]
mod combined;
mod workers;''')
edit('crates/latent-wasmtime/src/native_stacks/workers.rs','''//! This path is selected only while canonical thread creation stays disabled.''','''//! Ordinary profiles keep canonical thread creation disabled on this path.
//! The fixed combined diagnostic additionally requires its immutable graph proof;
//! its explicit child starts still use the original conservative admission.''')
edit('crates/latent-wasmtime/src/native_stacks/workers.rs','''        // a parent or capacity, and no guest C thread can reach this profile.''','''        // a parent or capacity. Ordinary guest C profiles cannot reach this path.
        // The fixed combined graph cannot create a child without its separately
        // granted pre-start call, even when an engine worker uses this path.''')
edit('crates/latent-wasmtime/src/native_stacks/tests.rs','''struct Signal;''','''#[cfg(feature = "development-rust-http-combined")]
mod combined;

struct Signal;''')
edit('docs/testing/rust-combined-http-diagnostic.md','''The original HTTP response headers stay withheld until the independent''','''The authenticated fixed graph uses both explicitly admitted child stacks and
engine-owned HTTP completion fibers. Both draw from the original eight-Native-owner
ceiling and the same 16 MiB activation ledger. Child admission still requires its
separate native grant and a distinct original Task; accepted child-start capacity
is not recycled on logical completion. Every actual mapping and its metadata
remain charged until physical drop, and cached child permits remain charged
until Store destruction. Other native-thread profiles keep refusing unadmitted
stack creation; a configuration name or package inspection cannot select this
combined path without the immutable final-graph proof.

The original HTTP response headers stay withheld until the independent''')
f='.github/workflows/rust-combined-host-diagnostic.yml'
edit(f,'''      - name: Check diagnostic node selection without raising its budgets''','''      - name: Check original stack admission and fixed combined worker ownership
        shell: bash
        run: |
          set -euo pipefail
          cargo test --locked -p latent-wasmtime --lib native_stacks:: -- --nocapture --test-threads=1 2>&1 | tee "$RUNNER_TEMP/rust-combined-host/stacks-ordinary.log"
          cargo test --locked -p latent-wasmtime --lib --features development-rust-http-combined native_stacks:: -- --nocapture --test-threads=1 2>&1 | tee "$RUNNER_TEMP/rust-combined-host/stacks-combined.log"
      - name: Check diagnostic node selection without raising its budgets''')
sys.path.insert(0,str(root))
from tools import ci_contracts
p='tools/ci/contracts/workflows/rust-combined-host-diagnostic.yml/jobs/diagnostic.json'
x=root/p;v=json.loads(x.read_bytes());v['definition']=ci_contracts.observed_workflows(root)[f]['jobs']['diagnostic'];v['reviewReason']='Retain original strict stack admission and verify fixed-graph child/engine-worker ownership under shared limits.';x.write_text(json.dumps(v,indent=2)+'\n');paths.append(p)
(source/'paths.json').write_text(json.dumps(paths,indent=2)+'\n')
