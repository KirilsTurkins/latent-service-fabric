//! Zero-before-write proof using a fixed memory with no clearing initializer.

#[path = "engine_memory/negative.rs"]
mod negative;

use latent_artifacts::CapsuleArtifact;
use latent_core::{CapabilityId, ContractId, TenantId};
use latent_executor::{
    BoundImport, ExecutionBackend, GuestInterruptionKind, GuestOutcome, PreparedComponent,
};
use latent_manifest::ContractImport;
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory};
use serde_json::json;

use super::engine_profiles::{finish, profiles};
use super::support::{
    artifact_bytes, budget, idle, request, returned, run, Cancellation, WATCHDOG,
};

const CONTRACT: &str = "tests:engine-memory/memory@0.1.0";
const LOG: &str = "latent:log/log@0.1.0";
const DIRTY_LOG: &str = "engine-memory-dirty-4194304-a5";
const CHECKSUM: u32 = 692_060_160;

fn bytes() -> Vec<u8> {
    let path = std::env::var_os("LSF_ENGINE_MEMORY_COMPONENT")
        .expect("contracts gate supplies engine memory fixture");
    std::fs::read(path).unwrap()
}

fn artifact(component: Vec<u8>, tenant: &str) -> CapsuleArtifact {
    let mut artifact = artifact_bytes(component, &[CONTRACT]);
    artifact.manifest.metadata.tenant = Some(TenantId(tenant.to_owned()));
    artifact.manifest.world = ContractId("tests:engine-memory/service@0.1.0".to_owned());
    artifact.manifest.imports = vec![ContractImport {
        contract: ContractId(LOG.to_owned()),
        optional: false,
    }];
    artifact.manifest.execution.resource_budget_ceiling.cpu_fuel = 10_000_000_000;
    artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .log_bytes = 4_096;
    artifact
}

fn invocation(
    prepared: &PreparedComponent,
    cancellation: &Cancellation,
    tenant: &str,
    mode: &str,
) -> latent_executor::ExecutionRequest {
    let mut grant = budget();
    grant.cpu_fuel = if mode == "cancel" {
        10_000_000_000
    } else {
        100_000_000
    };
    grant.memory_bytes = 8 * 1024 * 1024;
    grant.log_bytes = 4_096;
    grant.wall_time_limit_millis = Some(1_000);
    let mut invocation = request(
        prepared.clone(),
        &cancellation.id,
        CONTRACT,
        "run",
        &serde_json::to_vec(&[mode]).unwrap(),
        grant,
    );
    invocation.activation.target.tenant = TenantId(tenant.to_owned());
    invocation.activation.principal.tenant = Some(TenantId(tenant.to_owned()));
    invocation.imports = vec![BoundImport {
        capability: CapabilityId("engine-memory-log".to_owned()),
        contract: LOG.to_owned(),
        opaque_handle: "activation-scoped".to_owned(),
    }];
    invocation
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the engine memory component built by tools/validate_contracts.sh"]
async fn fresh_memory_is_zero_after_success_trap_and_cancel_across_tenants_and_profiles() {
    let component = bytes();
    for mut policy in profiles() {
        // Pooling has exactly one memory slot, not merely one live activation.
        // The component has one shared memory and two core module instances.
        policy.pooling_maximum_instances = 1;
        policy.pooling_maximum_memories_per_component = 1;
        policy.maximum_active_instances = 1;
        let factory = WasmtimeComponentEngineFactory::new(policy).unwrap();
        let backend = factory.create_backend_instance();
        let first = artifact(component.clone(), "memory-a");
        let second = artifact(component.clone(), "memory-b");
        let key = factory.preparation_key(first.descriptor.release_digest.clone());
        let first = backend.prepare(&first, &key).await.unwrap();
        let second = backend.prepare(&second, &key).await.unwrap();
        assert_ne!(first.opaque_handle, second.opaque_handle);
        for (index, mode) in ["success", "trap", "cancel"].into_iter().enumerate() {
            let cancellation = Cancellation::new(&format!("memory-dirty-{index}"));
            let outcome = execute(&backend, &first, &cancellation, "memory-a", mode).await;
            match (mode, outcome) {
                ("success", outcome) => assert_eq!(returned(outcome), json!([CHECKSUM])),
                ("trap", GuestOutcome::Trapped { trap, .. }) => assert_eq!(trap.code, "guest-trap"),
                ("cancel", GuestOutcome::Interrupted { kind, .. }) => {
                    assert_eq!(kind, GuestInterruptionKind::Cancelled)
                }
                (_, other) => panic!("unexpected memory fixture outcome: {other:?}"),
            }
            assert_dirty(&factory, &cancellation);
            idle(&backend);
            assert_eq!(backend.active_instance_reservations(), 0);
            let recovery = Cancellation::new(&format!("memory-clean-{index}"));
            let outcome = run(
                &backend,
                invocation(&second, &recovery, "memory-b", "success"),
                &recovery,
            )
            .await
            .unwrap();
            assert_eq!(returned(outcome), json!([CHECKSUM]));
            assert_dirty(&factory, &recovery);
            idle(&backend);
        }
        assert_eq!(backend.stores_created(), 6);
        finish(factory, backend).await;
    }
}

async fn execute(
    backend: &WasmtimeBackend,
    prepared: &PreparedComponent,
    cancellation: &Cancellation,
    tenant: &str,
    mode: &str,
) -> GuestOutcome {
    let call = run(
        backend,
        invocation(prepared, cancellation, tenant, mode),
        cancellation,
    );
    if mode != "cancel" {
        return call.await.unwrap();
    }
    let cancel = async {
        tokio::time::timeout(WATCHDOG, async {
            while !backend
                .log_sink()
                .snapshot_for(&cancellation.id)
                .iter()
                .any(|entry| entry.message == DIRTY_LOG)
            {
                tokio::task::yield_now().await;
            }
        })
        .await
        .unwrap();
        assert_eq!(backend.resource_snapshot().live_component_instances, 1);
        cancellation.cancel();
    };
    let (outcome, ()) = tokio::join!(call, cancel);
    outcome.unwrap()
}

fn assert_dirty(factory: &WasmtimeComponentEngineFactory, cancellation: &Cancellation) {
    let entries = factory.log_sink().snapshot_for(&cancellation.id);
    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].message, DIRTY_LOG);
    assert_eq!(entries[0].level, "info");
}
