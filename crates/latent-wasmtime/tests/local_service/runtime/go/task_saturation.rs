//! Original Task16 refusal from an ordinary signed Go component.
use super::*;
use latent_core::diagnostic::ActivationDiagnosticSink;
use std::sync::{atomic::AtomicBool, Arc, Mutex};

const VARIABLE: &str = "LSF_GO_TASK_SATURATION_FIXTURE";
const PROFILE: &str = "go-component-activation-v5";
const SATURATION: &str = "go-task16-saturation";

#[derive(Default)]
struct Witness {
    records: Mutex<Vec<(TenantId, ActivationId, ActivationDiagnostic)>>,
    incomplete: AtomicBool,
}

impl ActivationDiagnosticSink for Witness {
    fn record(
        &self,
        tenant: &TenantId,
        activation: &ActivationId,
        diagnostic: ActivationDiagnostic,
    ) {
        if !diagnostic.is_runtime_resource_refusal() {
            return;
        }
        if let Ok(mut records) = self.records.try_lock() {
            if records.len() < 4 {
                records.push((tenant.clone(), activation.clone(), diagnostic));
                return;
            }
        }
        // Observation cannot change the original host response; a lost or
        // ambiguous witness fails the independent assertion below.
        self.incomplete.store(true, Ordering::Release);
    }
}

fn verify_idle(f: &Fixture, created: u64) {
    let state = f.backend.resource_snapshot();
    assert_eq!(state.stores_created, created);
    assert_eq!(state.live_stores, 0);
    assert_eq!(state.live_component_instances, 0);
    assert_eq!(f.backend.active_instance_reservations(), 0);
    let quota = f.quotas.usage().unwrap();
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.reserved_cpu_fuel, 0);
    assert_eq!(quota.reserved_memory_bytes, 0);
}

fn row(case: &str, outcome: &str, created: u64) {
    println!(
        "GO_TASK_SATURATION_CASE {}",
        serde_json::json!({
            "case":case,"outcome":outcome,"storesCreated":created,
            "liveStores":0,"liveInstances":0,"reservations":0,
            "reservedFuel":0,"reservedMemory":0
        })
    );
}

#[tokio::test]
#[ignore = "requires captured ordinary v5 Go Task16 fixture and original diagnostic journal"]
async fn signed_task16_saturation_reports_original_refusal_and_fresh_retirement() {
    assert_eq!(std::env::var("LSF_GUEST_SDK_LANGUAGE").as_deref(), Ok("go"));
    let root = tempfile::tempdir().unwrap();
    // Same Task16/Wait4 and package/request budgets as the existing v5 lane.
    let f = prepare_owned_fixture(root.path(), VARIABLE, PROFILE, 16).await;
    let witness = Arc::new(Witness::default());
    f.broker.install_diagnostic_sink(witness.clone()).unwrap();

    let first = f
        .manager
        .start(f.request("go-task16-baseline", 0))
        .unwrap()
        .await;
    let revision = first
        .resolved_revision
        .as_ref()
        .expect("original publication");
    let release = revision.release.clone();
    let publication = revision.publication.clone().expect("original publication");
    let baseline = success(first);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&baseline.output).unwrap(),
        [42]
    );
    assert!(baseline.consumption.cpu_fuel > 0);
    assert!(baseline.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    f.idle().await;
    verify_idle(&f, 1);
    assert!(witness.records.lock().unwrap().is_empty());
    row("seven-live", "success", 1);

    let denied = f.manager.start(f.request(SATURATION, 1)).unwrap().await;
    let selected = denied
        .resolved_revision
        .as_ref()
        .expect("original publication");
    assert_eq!(selected.release, release);
    assert_eq!(selected.publication.as_ref(), Some(&publication));
    assert_eq!(denied.activation_id.0, SATURATION);
    // The typed observation is an actual refusal, not by itself a claim about
    // the terminal cause of this subsequent GuestTrap.
    assert_eq!(failure(denied).code, PlatformErrorCode::GuestTrap);
    f.idle().await;
    verify_idle(&f, 2);
    assert!(!witness.incomplete.load(Ordering::Acquire));
    let records = witness.records.lock().unwrap();
    assert_eq!(records.len(), 1, "one original runtime refusal required");
    let (tenant, activation, diagnostic) = &records[0];
    assert_eq!(tenant.0, "tenant-a");
    assert_eq!(activation.0, SATURATION);
    let mut expected = ActivationDiagnostic::new(
        DiagnosticStage::Execution,
        DiagnosticReason::RuntimeTaskLimit,
    );
    expected.configured_bound = Some(16);
    expected.calculated_requirement = Some(17);
    assert_eq!(*diagnostic, expected);
    println!(
        "GO_TASK_SATURATION_REFUSAL {}",
        serde_json::json!({
            "tenant":"tenant-a","activation":SATURATION,"stage":"execution",
            "reason":"runtime-task-limit","configuredBound":16,"requestedOwners":17,
            "terminalCauseEstablished":false
        })
    );
    drop(records);
    row("eighth-refused", "guest-trap", 2);

    let fresh = f
        .manager
        .start(f.request("go-task16-fresh", 0))
        .unwrap()
        .await;
    let selected = fresh
        .resolved_revision
        .as_ref()
        .expect("original publication");
    assert_eq!(selected.release, release);
    assert_eq!(selected.publication.as_ref(), Some(&publication));
    let fresh_result = success(fresh);
    assert_eq!(
        serde_json::from_slice::<Vec<u32>>(&fresh_result.output).unwrap(),
        [42]
    );
    assert!(fresh_result.consumption.cpu_fuel > 0);
    assert!(fresh_result.consumption.peak_memory_bytes <= packages::budget().memory_bytes);
    f.idle().await;
    verify_idle(&f, 3);
    assert!(!witness.incomplete.load(Ordering::Acquire));
    assert_eq!(witness.records.lock().unwrap().len(), 1);
    row("fresh-after-refusal", "success", 3);
}
