mod execution;

use std::collections::{BTreeMap, BTreeSet};
use std::future::Future;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::task::{Context, Waker};
use std::time::{Duration, Instant};

use latent_admission::{
    AdmissionRequest, CellClassPolicy, DeadlinePolicy, LocalAdmissionController,
    LocalQuotaProvider, NodeAdmissionPolicy, NodeLoadSnapshot, NodeLoadState, OverloadPolicy,
    QueueClassPolicy, QuotaLimits, QuotaUsage, TenantAdmissionPolicy, TrustClassPolicy,
};
use latent_core::{
    ActivationBudget, ActivationId, CancelDisposition, ClockSample, ContractId, FunctionId,
    InvocationPrincipal, Metadata, PrincipalKind, RevisionId, RouteGeneration, ServiceId, TenantId,
};
use latent_manifest::ThreadingModel;
use latent_node::ActivationCancellationRegistry;
use latent_routing::{ResolvedRevision, RevisionPolicySource, RouteResolver};

use super::fixtures::*;
use crate::DeploymentStore;

fn names(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

fn controller(
    store: &Store,
    capacity: u32,
) -> (LocalAdmissionController, LocalQuotaProvider, ClockSample) {
    let pin = Arc::new(store.pin().unwrap());
    let revision = pin.resolve(&target("alice", None), None).unwrap();
    let ceiling = pin.admission_policy(&revision).unwrap().deployment_ceiling;
    let limits = QuotaLimits {
        maximum_concurrent_activations: capacity,
        maximum_queued_activations: capacity,
        maximum_reserved_cpu_fuel: u64::MAX,
        maximum_reserved_memory_bytes: u64::MAX,
    };
    let node = NodeAdmissionPolicy {
        budget_ceiling: ceiling,
        limits,
        tenants: BTreeMap::from([(
            TenantId("alice".to_owned()),
            TenantAdmissionPolicy {
                limits,
                maximum_payload_bytes: 1024,
                maximum_priority: 0,
                allowed_subjects: names(&["local-client"]),
                allowed_principal_kinds: vec![PrincipalKind::User],
                allowed_trust_classes: names(&["local"]),
                allowed_cell_classes: names(&["tiny"]),
            },
        )]),
        trust_classes: BTreeMap::from([(
            "local".to_owned(),
            TrustClassPolicy {
                limits,
                allowed_cell_classes: names(&["tiny"]),
            },
        )]),
        queue_classes: BTreeMap::from([(
            "default".to_owned(),
            QueueClassPolicy {
                minimum_priority: 0,
                maximum_priority: 0,
                maximum_queued_activations: capacity,
            },
        )]),
        cell_classes: BTreeMap::from([(
            "tiny".to_owned(),
            CellClassPolicy {
                maximum_memory_bytes: 65536,
                parallelism: 1,
                threading_models: vec![ThreadingModel::SingleThreaded],
                features: BTreeSet::new(),
            },
        )]),
        maximum_payload_bytes: 1024,
        maximum_priority: 0,
        maximum_identifier_bytes: 1024,
        maximum_metadata_entries: 32,
        maximum_metadata_bytes: 64 * 1024,
        overload: OverloadPolicy {
            maximum_cpu_pressure_milli: 900,
            maximum_memory_pressure_milli: 900,
            maximum_sample_age_millis: 10_000,
        },
        deadline: DeadlinePolicy {
            estimated_service_time_millis: 10,
            minimum_execution_time_millis: 1,
            safety_margin_millis: 1,
        },
        architecture: "x86_64".to_owned(),
        region: None,
        zone: None,
    };
    let quotas = LocalQuotaProvider::new(node).unwrap();
    let sample = ClockSample::new(10_000, Instant::now());
    let load = Arc::new(
        NodeLoadState::new(NodeLoadSnapshot {
            accepting: true,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            observed_at: sample.monotonic(),
        })
        .unwrap(),
    );
    (
        LocalAdmissionController::new(pin, quotas.clone(), load),
        quotas,
        sample,
    )
}

fn request(id: &str, revision: ResolvedRevision, quotas: &LocalQuotaProvider) -> AdmissionRequest {
    AdmissionRequest {
        activation_id: ActivationId(id.to_owned()),
        principal: InvocationPrincipal {
            subject: "local-client".to_owned(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("alice".to_owned())),
            service: None,
            claims: Metadata::new(),
        },
        revision,
        requested_budget: quotas.policy().budget_ceiling.clone(),
        deadline_unix_millis: None,
        payload_bytes: 8,
        priority: 0,
        attributes: Metadata::new(),
    }
}

#[test]
fn real_catalog_verifies_the_entire_pinned_identity_and_ignores_forged_attributes() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("admission-policy");
    let store = open(&root, &releases);
    let deployment = deployment("blue", "alice", &digest);
    run(store.apply_many(vec![deployment.clone(), deployment_for_bob(&digest)])).unwrap();
    let pin = store.pin().unwrap();
    let resolved = pin.resolve(&target("alice", Some("blue")), None).unwrap();
    let expected = pin.admission_policy(&resolved).unwrap();
    assert_eq!(expected.deployment_ceiling, deployment.resources);
    assert_eq!(expected.placement, deployment.placement);
    assert_eq!(
        expected.execution,
        releases.values.read().unwrap()[&digest].manifest.execution
    );
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let mut forged = resolved.clone();
    forged.attributes = Metadata::from([(
        "lsf.deployment".to_owned(),
        "forged unlimited privileged policy".to_owned(),
    )]);
    assert_eq!(pin.admission_policy(&forged).unwrap(), expected);
    let mutations: [fn(&mut ResolvedRevision); 8] = [
        |r| r.target.tenant = TenantId("bob".to_owned()),
        |r| r.target.service = ServiceId("different".to_owned()),
        |r| r.target.contract = ContractId("other:api/api@1.0.0".to_owned()),
        |r| r.target.function = FunctionId("missing".to_owned()),
        |r| r.target.route = Some("bob-blue".to_owned()),
        |r| r.revision = RevisionId("rev:missing".to_owned()),
        |r| r.release = latent_core::ReleaseDigest(format!("sha256:{}", "f".repeat(64))),
        |r| r.route_generation = RouteGeneration(123),
    ];
    for mutate in mutations {
        let mut forged = resolved.clone();
        mutate(&mut forged);
        assert!(pin.admission_policy(&forged).is_err());
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

fn deployment_for_bob(digest: &latent_core::ReleaseDigest) -> latent_manifest::DeploymentManifest {
    deployment("bob-blue", "bob", digest)
}

#[test]
fn generated_revision_identities_do_not_consume_the_route_identifier_budget() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("bounded-route-identifiers");
    let store = run(Store::open(
        &root.0,
        releases,
        Limits {
            max_identifier_bytes: 64,
            ..Limits::default()
        },
    ))
    .unwrap();
    let deployment = deployment("blue", "alice", &digest);
    run(store.apply(deployment.clone())).unwrap();
    let pin = store.pin().unwrap();
    let revision = pin.resolve(&target("alice", None), None).unwrap();
    assert!(revision.revision.0.len() > 64);
    assert!(revision.release.0.len() > 64);
    assert_eq!(
        pin.admission_policy(&revision).unwrap().deployment_ceiling,
        deployment.resources
    );
    let (controller, quotas, sample) = controller(&store, 1);
    drop(
        controller
            .admit_at(
                request("bounded-identifiers", revision.clone(), &quotas),
                sample,
            )
            .unwrap(),
    );
    assert_eq!(quotas.usage().unwrap(), QuotaUsage::default());

    let mut oversized_target = revision.clone();
    oversized_target.target.service = ServiceId("x".repeat(65));
    assert_eq!(
        pin.admission_policy(&oversized_target).unwrap_err().code,
        Code::InvalidArgument
    );
    for change_release in [false, true] {
        let mut forged = revision.clone();
        if change_release {
            forged.release.0 = "x".repeat(4096);
        } else {
            forged.revision.0 = "x".repeat(4096);
        }
        assert_eq!(
            pin.admission_policy(&forged).unwrap_err().code,
            Code::RouteUnavailable
        );
    }
}

#[test]
fn weighted_selection_preserves_each_exact_revisions_own_policy() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let one = releases.add("one-policy");
    let two = releases.add("two-policy");
    let store = open(&root, &releases);
    let mut blue = deployment("blue", "alice", &one);
    blue.resources.cpu_fuel = 250;
    let mut green = deployment("green", "alice", &two);
    green.resources.cpu_fuel = 500;
    run(store.apply_many(vec![blue, green])).unwrap();
    let pin = store.pin().unwrap();
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let mut seen = BTreeSet::new();
    for index in 0..200 {
        let revision = pin
            .resolve(&target("alice", None), Some(&index.to_string()))
            .unwrap();
        let policy = pin.admission_policy(&revision).unwrap();
        assert_eq!(
            policy.deployment_ceiling.cpu_fuel,
            if revision.release == one { 250 } else { 500 }
        );
        seen.insert(revision.release);
    }
    assert_eq!(seen.len(), 2);
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn catalog_replacement_and_restart_keep_policy_pins_and_do_not_reset_shared_quotas() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("pinned-admission");
    let store = open(&root, &releases);
    let original = deployment("blue", "alice", &digest);
    run(store.apply(original.clone())).unwrap();
    let first_pin = store.pin().unwrap();
    let first = first_pin.resolve(&target("alice", None), None).unwrap();
    let (controller, quotas, sample) = controller(&store, 1);
    let first_permit = controller
        .admit_at(request("old", first.clone(), &quotas), sample)
        .unwrap();
    let mut updated = original;
    updated.resources.cpu_fuel = 400;
    run(store.apply(updated.clone())).unwrap();
    let next_pin = Arc::new(store.pin().unwrap());
    let second = next_pin.resolve(&target("alice", None), None).unwrap();
    let next = controller.with_policy_source(next_pin.clone());
    assert!(next_pin.admission_policy(&first).is_err());
    assert_eq!(
        first_pin
            .admission_policy(&first)
            .unwrap()
            .deployment_ceiling
            .cpu_fuel,
        1000
    );
    assert_eq!(
        next_pin
            .admission_policy(&second)
            .unwrap()
            .deployment_ceiling
            .cpu_fuel,
        400
    );
    let error = next
        .admit_at(request("new", second.clone(), &quotas), sample)
        .unwrap_err();
    assert_eq!(error.code, Code::ResourceExhausted);
    assert_eq!(quotas.usage().unwrap().active_activations, 1);
    drop(first_permit);
    let second_permit = next
        .admit_at(request("new", second.clone(), &quotas), sample)
        .unwrap();
    assert_eq!(second_permit.granted_budget().cpu_fuel, 400);
    drop(second_permit);
    // Reopening reconstructs the same typed policy from verified release metadata.
    drop(store);
    let store = open(&root, &releases);
    let restarted = store.pin().unwrap();
    assert_eq!(
        restarted.resolve(&target("alice", None), None).unwrap(),
        second
    );
    assert_eq!(
        restarted.admission_policy(&second).unwrap(),
        next_pin.admission_policy(&second).unwrap()
    );
    run(store.delete(&updated.id)).unwrap();
    assert_eq!(
        first_pin
            .admission_policy(&first)
            .unwrap()
            .deployment_ceiling
            .cpu_fuel,
        1000
    );
    assert_eq!(
        next_pin
            .admission_policy(&second)
            .unwrap()
            .deployment_ceiling
            .cpu_fuel,
        400
    );
    drop(
        controller
            .admit_at(request("old-after-delete", first, &quotas), sample)
            .unwrap(),
    );
    assert_eq!(quotas.usage().unwrap(), QuotaUsage::default());
}

#[test]
fn real_catalog_rejections_create_no_cancellation_state_or_execution_work() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("reject-before-execution");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    let (controller, quotas, sample) = controller(&store, 1);
    let revision = store.resolve(&target("alice", None), None).unwrap();
    let cancellations = ActivationCancellationRegistry::default();
    let fetches = releases.fetches.load(Ordering::Relaxed);
    let execution_allocations = std::sync::atomic::AtomicUsize::new(0);
    for variant in 0..5 {
        let mut request = request("rejected", revision.clone(), &quotas);
        match variant {
            0 => request.principal.tenant = None,
            1 => request.payload_bytes = 1025,
            2 => request.deadline_unix_millis = Some(sample.unix_millis()),
            3 => request.requested_budget.cpu_fuel = 0,
            _ => request.revision.revision = RevisionId("not-in-catalog".to_owned()),
        }
        let result = controller.admit_at(request, sample).map(|permit| {
            let _cancellation = cancellations
                .register(permit.activation_id().clone())
                .unwrap();
            execution_allocations.fetch_add(1, Ordering::Relaxed);
            permit
        });
        assert!(result.is_err());
        assert_eq!(execution_allocations.load(Ordering::Relaxed), 0);
        assert_eq!(cancellations.snapshot().active_registrations, 0);
        assert_eq!(quotas.usage().unwrap(), QuotaUsage::default());
    }
    assert_eq!(releases.fetches.load(Ordering::Relaxed), fetches);
}

#[test]
fn real_catalog_cancellation_enqueue_failure_expiry_and_future_drop_reclaim_all_guards() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let digest = releases.add("terminal-guards");
    let store = open(&root, &releases);
    run(store.apply(deployment("blue", "alice", &digest))).unwrap();
    let (controller, quotas, sample) = controller(&store, 2);
    let revision = store.resolve(&target("alice", None), None).unwrap();
    let cancellations = ActivationCancellationRegistry::default();
    for running in [false, true] {
        let permit = controller
            .admit_at(request("cancelled", revision.clone(), &quotas), sample)
            .unwrap();
        let cancellation = cancellations
            .register(permit.activation_id().clone())
            .unwrap();
        let accounting = ActivationBudget::new(permit.effective_budget().clone());
        assert_eq!(
            cancellations.cancel(permit.activation_id(), "cancel"),
            CancelDisposition::Accepted
        );
        if running {
            let permit = permit.start_execution_at(sample.monotonic()).unwrap();
            // The backend has stopped before its execution reservation is dropped.
            let _ = accounting.finalize_at(None, sample.monotonic());
            drop(permit);
        } else {
            drop(permit);
        }
        drop(cancellation);
        assert_eq!(cancellations.snapshot().active_registrations, 0);
        assert_eq!(quotas.usage().unwrap(), QuotaUsage::default());
    }
    let permit = controller
        .admit_at(
            request("enqueue-failure", revision.clone(), &quotas),
            sample,
        )
        .unwrap();
    drop(permit);
    let permit = controller
        .admit_at(request("expired", revision.clone(), &quotas), sample)
        .unwrap();
    assert!(permit
        .start_execution_at(sample.monotonic() + Duration::from_secs(1))
        .is_err());
    let future = async {
        let permit = controller
            .admit_at(request("dropped-task", revision, &quotas), sample)
            .unwrap();
        let cancellation = cancellations
            .register(permit.activation_id().clone())
            .unwrap();
        std::future::pending::<()>().await;
        drop(cancellation);
        drop(permit);
    };
    let mut future = Box::pin(future);
    let mut context = Context::from_waker(Waker::noop());
    assert!(future.as_mut().poll(&mut context).is_pending());
    assert_eq!(cancellations.snapshot().active_registrations, 1);
    assert_eq!(quotas.usage().unwrap().active_activations, 1);
    drop(future);
    assert_eq!(cancellations.snapshot().active_registrations, 0);
    assert_eq!(quotas.usage().unwrap(), QuotaUsage::default());
    assert_eq!(quotas.retained_tenant_count().unwrap(), 0);
}
