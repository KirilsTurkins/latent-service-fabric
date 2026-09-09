use std::collections::{BTreeMap, BTreeSet};
use std::future::Future;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Barrier};
use std::task::{Context, Poll, Waker};
use std::time::{Duration, Instant};

use latent_core::{
    ActivationBudget, ActivationId, ClockSample, ContractId, FunctionId, InvocationPrincipal,
    Metadata, PlatformError, PlatformErrorCode as Code, PrincipalKind, ReleaseDigest,
    ResourceBudget, RevisionId, RouteGeneration, ServiceId, TenantId,
};
use latent_routing::revision_policy::{
    ExecutionBackendKind, ExecutionRequirements, PlacementPolicy, StateModel, ThreadingModel,
};
use latent_routing::{
    InvocationTarget, ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource,
};

use super::*;

mod diagnostics;
mod stress;
type PolicyMutation = (fn(&mut RevisionAdmissionPolicy), &'static str);

fn names(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| (*value).to_owned()).collect()
}

fn budget() -> ResourceBudget {
    ResourceBudget {
        cpu_fuel: 100,
        memory_bytes: 65_536,
        wall_time_limit_millis: Some(1000),
        child_calls: 0,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 16,
        effect_count: 0,
    }
}

fn limits() -> QuotaLimits {
    QuotaLimits {
        maximum_concurrent_activations: 32,
        maximum_queued_activations: 32,
        maximum_reserved_cpu_fuel: 1_000_000,
        maximum_reserved_memory_bytes: 1_073_741_824,
    }
}

fn node_policy() -> NodeAdmissionPolicy {
    let mut ceiling = budget();
    ceiling.cpu_fuel = 10_000;
    ceiling.memory_bytes = 8_388_608;
    ceiling.log_bytes = 64;
    let tenant = TenantAdmissionPolicy {
        limits: limits(),
        maximum_payload_bytes: 1024,
        maximum_priority: 200,
        allowed_subjects: names(&["alice"]),
        allowed_principal_kinds: vec![PrincipalKind::User],
        allowed_trust_classes: names(&["sandbox"]),
        allowed_cell_classes: names(&["tiny", "small", "standard", "large"]),
    };
    let mut second = tenant.clone();
    second.allowed_subjects = names(&["bob"]);
    NodeAdmissionPolicy {
        budget_ceiling: ceiling,
        limits: limits(),
        tenants: BTreeMap::from([
            (TenantId("tenant-a".to_owned()), tenant),
            (TenantId("tenant-b".to_owned()), second),
        ]),
        trust_classes: BTreeMap::from([(
            "sandbox".to_owned(),
            TrustClassPolicy {
                limits: limits(),
                allowed_cell_classes: names(&["tiny", "small", "standard", "large"]),
            },
        )]),
        queue_classes: BTreeMap::from([
            (
                "normal".to_owned(),
                QueueClassPolicy {
                    minimum_priority: 0,
                    maximum_priority: 127,
                    maximum_queued_activations: 32,
                },
            ),
            (
                "urgent".to_owned(),
                QueueClassPolicy {
                    minimum_priority: 128,
                    maximum_priority: 255,
                    maximum_queued_activations: 4,
                },
            ),
        ]),
        cell_classes: [
            ("tiny", 65_536, 2),
            ("small", 262_144, 2),
            ("standard", 1_048_576, 1),
            ("large", 4_194_304, 1),
            ("extra-large", 8_388_608, 1),
        ]
        .into_iter()
        .map(|(name, maximum_memory_bytes, parallelism)| {
            (
                name.to_owned(),
                CellClassPolicy {
                    maximum_memory_bytes,
                    parallelism,
                    threading_models: vec![ThreadingModel::SingleThreaded],
                    features: if name == "tiny" {
                        BTreeSet::new()
                    } else {
                        names(&["simd"])
                    },
                },
            )
        })
        .collect(),
        maximum_payload_bytes: 2048,
        maximum_priority: 255,
        maximum_identifier_bytes: 1024,
        maximum_metadata_entries: 32,
        maximum_metadata_bytes: 4096,
        overload: OverloadPolicy {
            maximum_cpu_pressure_milli: 900,
            maximum_memory_pressure_milli: 900,
            maximum_sample_age_millis: 10_000,
        },
        deadline: DeadlinePolicy {
            estimated_service_time_millis: 100,
            minimum_execution_time_millis: 5,
            safety_margin_millis: 5,
        },
        architecture: "x86_64".to_owned(),
        region: Some("local".to_owned()),
        zone: Some("a".to_owned()),
    }
}

fn revision(tenant: &str) -> ResolvedRevision {
    ResolvedRevision {
        target: InvocationTarget {
            tenant: TenantId(tenant.to_owned()),
            service: ServiceId("echo".to_owned()),
            contract: ContractId("example:echo/api@1.0.0".to_owned()),
            function: FunctionId("echo".to_owned()),
            route: None,
        },
        revision: RevisionId(format!("revision-v1:sha256:{}", "a".repeat(64))),
        release: ReleaseDigest(format!("sha256:{}", "a".repeat(64))),
        route_generation: RouteGeneration(1),
        attributes: Metadata::new(),
    }
}

fn revision_policy() -> RevisionAdmissionPolicy {
    let ceiling = node_policy().budget_ceiling;
    RevisionAdmissionPolicy {
        deployment_ceiling: ceiling.clone(),
        execution: ExecutionRequirements {
            backend: ExecutionBackendKind::WasmComponent,
            threading: ThreadingModel::SingleThreaded,
            state_model: StateModel::Stateless,
            resource_budget_ceiling: ceiling,
            host_call_depth_maximum: 8,
            component_call_depth_maximum: 8,
            snapshot_eligible: false,
            fusion_eligible: false,
        },
        placement: PlacementPolicy {
            trust_class: "sandbox".to_owned(),
            architectures: vec!["x86_64".to_owned()],
            regions: vec!["local".to_owned()],
            zones: vec!["a".to_owned()],
            required_features: vec![],
        },
    }
}

struct Source {
    policy: RevisionAdmissionPolicy,
    available: AtomicBool,
    calls: AtomicUsize,
}

impl RevisionPolicySource for Source {
    fn admission_policy(
        &self,
        supplied: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let mut supplied = supplied.clone();
        supplied.attributes.clear();
        if !self.available.load(Ordering::Relaxed)
            || ![revision("tenant-a"), revision("tenant-b")].contains(&supplied)
        {
            return Err(PlatformError {
                code: Code::RouteUnavailable,
                message: "other-tenant-secret".to_owned(),
                retryable: false,
                details: vec![],
            });
        }
        Ok(self.policy.clone())
    }
}

struct Harness {
    controller: LocalAdmissionController,
    quotas: LocalQuotaProvider,
    source: Arc<Source>,
    load: Arc<NodeLoadState>,
    sample: ClockSample,
}

impl Harness {
    fn new(policy: NodeAdmissionPolicy, revision_policy: RevisionAdmissionPolicy) -> Self {
        let sample = ClockSample::new(10_000, Instant::now());
        let source = Arc::new(Source {
            policy: revision_policy,
            available: AtomicBool::new(true),
            calls: AtomicUsize::new(0),
        });
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
        let quotas = LocalQuotaProvider::new(policy).unwrap();
        let controller =
            LocalAdmissionController::new(source.clone(), quotas.clone(), load.clone());
        Self {
            controller,
            quotas,
            source,
            load,
            sample,
        }
    }

    fn standard() -> Self {
        Self::new(node_policy(), revision_policy())
    }

    fn request(id: &str) -> AdmissionRequest {
        AdmissionRequest {
            activation_id: ActivationId(id.to_owned()),
            principal: InvocationPrincipal {
                subject: "alice".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(TenantId("tenant-a".to_owned())),
                service: None,
                claims: Metadata::new(),
            },
            revision: revision("tenant-a"),
            requested_budget: budget(),
            deadline_unix_millis: None,
            payload_bytes: 10,
            priority: 10,
            attributes: Metadata::new(),
        }
    }

    fn admit(&self, id: &str) -> Result<AdmissionPermit, PlatformError> {
        self.controller.admit_at(Self::request(id), self.sample)
    }

    fn assert_empty(&self) {
        assert_eq!(self.quotas.usage().unwrap(), QuotaUsage::default());
        assert_eq!(self.quotas.retained_tenant_count().unwrap(), 0);
        for (tenant, policy) in &self.quotas.policy().tenants {
            let snapshot = self.quotas.snapshot_now(tenant).unwrap();
            assert_eq!(snapshot.active_activations, 0);
            assert_eq!(snapshot.queued_activations, 0);
            assert_eq!(
                snapshot.remaining_cpu_fuel,
                policy.limits.maximum_reserved_cpu_fuel
            );
            assert_eq!(
                snapshot.remaining_memory_bytes,
                policy.limits.maximum_reserved_memory_bytes
            );
            assert_eq!(snapshot.reset_at_unix_millis, None);
        }
    }
}

fn detail(error: &PlatformError, name: &str) -> String {
    error.details[0].fields[name].clone()
}

#[test]
fn valid_admission_pins_identity_grants_smallest_cell_and_owns_quota() {
    let h = Harness::standard();
    let permit = h.admit("a").unwrap();
    assert_eq!(permit.revision(), &revision("tenant-a"));
    assert_eq!(permit.granted_budget(), &budget());
    assert_eq!(permit.obligations().cell_class, "tiny");
    assert_eq!(permit.obligations().queue_class, "normal");
    assert_eq!(permit.obligations().trust_class, "sandbox");
    assert_eq!(permit.deadline().unix_millis(), Some(11_000));
    assert_eq!(h.quotas.usage().unwrap().active_activations, 1);
    assert_eq!(h.quotas.usage().unwrap().queued_activations, 1);
    drop(permit);
    h.assert_empty();
}

#[test]
fn budget_intersection_includes_capsule_deployment_node_and_caller() {
    let mut node = node_policy();
    node.budget_ceiling.cpu_fuel = 80;
    node.budget_ceiling.memory_bytes = 262_144;
    node.budget_ceiling.log_bytes = 9;
    node.budget_ceiling.wall_time_limit_millis = Some(400);
    let mut policy = revision_policy();
    policy.deployment_ceiling.cpu_fuel = 90;
    policy.deployment_ceiling.memory_bytes = 200_000;
    policy.deployment_ceiling.wall_time_limit_millis = Some(300);
    policy.execution.resource_budget_ceiling.cpu_fuel = 70;
    policy.execution.resource_budget_ceiling.memory_bytes = 150_000;
    policy.execution.resource_budget_ceiling.log_bytes = 8;
    let h = Harness::new(node, policy);
    let mut request = Harness::request("a");
    request.requested_budget.memory_bytes = 1_000_000;
    request.deadline_unix_millis = Some(10_250);
    let permit = h.controller.admit_at(request, h.sample).unwrap();
    assert_eq!(permit.granted_budget().cpu_fuel, 70);
    assert_eq!(permit.granted_budget().memory_bytes, 150_000);
    assert_eq!(permit.granted_budget().log_bytes, 8);
    assert_eq!(permit.granted_budget().wall_time_limit_millis, Some(300));
    assert_eq!(permit.deadline().unix_millis(), Some(10_250));
    assert_eq!(permit.obligations().cell_class, "small");
    drop(permit);
    h.assert_empty();
}

#[test]
fn request_budget_boundaries_never_increase_any_grant() {
    let h = Harness::standard();
    for cpu in [0, 1, 100, 10_001, u64::MAX] {
        for memory in [0, 1, 65_536, 65_537, 262_144] {
            let mut request = Harness::request("boundary");
            request.requested_budget.cpu_fuel = cpu;
            request.requested_budget.memory_bytes = memory;
            let result = h.controller.admit_at(request, h.sample);
            if cpu == 0 || memory == 0 {
                assert_eq!(result.unwrap_err().code, Code::ResourceExhausted);
            } else {
                let permit = result.unwrap();
                assert_eq!(permit.granted_budget().cpu_fuel, cpu.min(10_000));
                assert_eq!(permit.granted_budget().memory_bytes, memory);
                assert_eq!(
                    permit.obligations().cell_class,
                    if memory <= 65_536 { "tiny" } else { "small" }
                );
            }
            h.assert_empty();
        }
    }
}

#[test]
fn every_later_phase_budget_dimension_is_rejected_without_reservation() {
    for index in 0..7 {
        let h = Harness::standard();
        let mut request = Harness::request("later");
        match index {
            0 => request.requested_budget.child_calls = 1,
            1 => request.requested_budget.outbound_requests = 1,
            2 => request.requested_budget.state_read_bytes = 1,
            3 => request.requested_budget.state_write_bytes = 1,
            4 => request.requested_budget.blob_read_bytes = 1,
            5 => request.requested_budget.blob_write_bytes = 1,
            _ => request.requested_budget.effect_count = 1,
        }
        let error = h.controller.admit_at(request, h.sample).unwrap_err();
        assert_eq!(error.code, Code::InvalidArgument);
        assert_eq!(detail(&error, "reason"), "unsupported-budget-dimension");
        h.assert_empty();
    }
}

#[test]
fn expired_zero_and_omitted_deadlines_have_distinct_semantics() {
    let h = Harness::standard();
    for deadline in [Some(0), Some(9999), Some(10_000)] {
        let mut request = Harness::request("expired");
        request.deadline_unix_millis = deadline;
        assert_eq!(
            h.controller.admit_at(request, h.sample).unwrap_err().code,
            Code::DeadlineExceeded
        );
        h.assert_empty();
    }
    let mut request = Harness::request("zero");
    request.requested_budget.wall_time_limit_millis = Some(0);
    assert_eq!(
        h.controller.admit_at(request, h.sample).unwrap_err().code,
        Code::DeadlineExceeded
    );
    let mut request = Harness::request("omitted");
    request.requested_budget.wall_time_limit_millis = None;
    let permit = h.controller.admit_at(request, h.sample).unwrap();
    assert_eq!(permit.deadline().unix_millis(), Some(11_000));
    drop(permit);
    h.assert_empty();
}

#[test]
fn deadline_feasibility_uses_atomically_reserved_backlog_and_observed_delay() {
    let h = Harness::standard();
    let first = h.admit("a").unwrap();
    let second = h.admit("b").unwrap();
    let mut request = Harness::request("c");
    request.deadline_unix_millis = Some(10_110);
    let error = h
        .controller
        .admit_at(request.clone(), h.sample)
        .unwrap_err();
    assert_eq!(error.code, Code::AdmissionRejected);
    assert_eq!(detail(&error, "reason"), "queue-deadline-infeasible");
    assert_eq!(h.quotas.usage().unwrap().active_activations, 2);
    request.deadline_unix_millis = Some(10_111);
    drop(h.controller.admit_at(request, h.sample).unwrap());
    drop((first, second));
    let mut load = h.load.snapshot().unwrap();
    load.queue_delay_millis = 990;
    h.load.publish(load).unwrap();
    assert_eq!(detail(&h.admit("d").unwrap_err(), "dimension"), "deadline");
    h.assert_empty();
}

#[test]
fn queue_estimate_arithmetic_overflow_fails_closed() {
    let mut node = node_policy();
    node.deadline.estimated_service_time_millis = u64::MAX;
    node.cell_classes.get_mut("tiny").unwrap().parallelism = 1;
    let h = Harness::new(node, revision_policy());
    let first = h.admit("a").unwrap();
    assert_eq!(
        detail(&h.admit("b").unwrap_err(), "reason"),
        "queue-estimate-overflow"
    );
    assert_eq!(h.quotas.usage().unwrap().active_activations, 1);
    drop(first);
    h.assert_empty();
}

#[test]
fn node_tenant_and_trust_quotas_are_independently_enforced_in_every_dimension() {
    for scope in ["node", "tenant", "trust-class"] {
        for dimension in ["concurrency", "queue", "cpu-fuel", "memory-bytes"] {
            let mut node = node_policy();
            let limit = match scope {
                "node" => &mut node.limits,
                "tenant" => {
                    &mut node
                        .tenants
                        .get_mut(&TenantId("tenant-a".to_owned()))
                        .unwrap()
                        .limits
                }
                _ => &mut node.trust_classes.get_mut("sandbox").unwrap().limits,
            };
            match dimension {
                "concurrency" => limit.maximum_concurrent_activations = 0,
                "queue" => limit.maximum_queued_activations = 0,
                "cpu-fuel" => limit.maximum_reserved_cpu_fuel = 99,
                _ => limit.maximum_reserved_memory_bytes = 65_535,
            }
            let h = Harness::new(node, revision_policy());
            let error = h.admit("a").unwrap_err();
            assert_eq!(error.code, Code::ResourceExhausted);
            assert_eq!(detail(&error, "scope"), scope);
            assert_eq!(detail(&error, "dimension"), dimension);
            h.assert_empty();
        }
    }
}

#[test]
fn queue_handoff_returns_only_queue_capacity_until_terminal_cleanup() {
    let mut node = node_policy();
    node.limits.maximum_queued_activations = 1;
    node.limits.maximum_concurrent_activations = 2;
    let h = Harness::new(node, revision_policy());
    let queued = h.admit("a").unwrap();
    assert_eq!(detail(&h.admit("b").unwrap_err(), "dimension"), "queue");
    let running = queued.start_execution_at(h.sample.monotonic()).unwrap();
    assert_eq!(h.quotas.usage().unwrap().queued_activations, 0);
    assert_eq!(h.quotas.usage().unwrap().reserved_cpu_fuel, 100);
    let second = h.admit("b").unwrap();
    assert_eq!(
        detail(&h.admit("c").unwrap_err(), "dimension"),
        "concurrency"
    );
    drop((running, second));
    h.assert_empty();
}

#[test]
fn expired_handoff_consumes_and_releases_the_permit() {
    let h = Harness::standard();
    let permit = h.admit("a").unwrap();
    let original_deadline = permit.deadline().monotonic().unwrap();
    assert!(permit
        .ensure_schedulable_at(
            original_deadline
                .checked_sub(Duration::from_nanos(1))
                .unwrap()
        )
        .is_ok());
    assert_eq!(
        permit
            .start_execution_at(original_deadline)
            .unwrap_err()
            .code,
        Code::DeadlineExceeded
    );
    h.assert_empty();
}

#[test]
fn queue_class_capacity_and_priority_authorization_are_independent() {
    let mut node = node_policy();
    node.queue_classes
        .get_mut("normal")
        .unwrap()
        .maximum_queued_activations = 1;
    let h = Harness::new(node, revision_policy());
    let normal = h.admit("normal").unwrap();
    assert_eq!(
        detail(&h.admit("overflow").unwrap_err(), "scope"),
        "queue-class"
    );
    let mut urgent = Harness::request("urgent");
    urgent.priority = 128;
    let urgent = h.controller.admit_at(urgent, h.sample).unwrap();
    assert_eq!(urgent.obligations().queue_class, "urgent");
    let mut forbidden = Harness::request("forbidden");
    forbidden.priority = 201;
    assert_eq!(
        detail(
            &h.controller.admit_at(forbidden, h.sample).unwrap_err(),
            "dimension"
        ),
        "priority"
    );
    drop((normal, urgent));
    h.assert_empty();
}

#[test]
fn payload_limits_are_exact_and_independent_for_node_and_tenant() {
    for (node_limit, tenant_limit, expected_scope) in [(9, 1024, "node"), (2048, 9, "tenant")] {
        let mut node = node_policy();
        node.maximum_payload_bytes = node_limit;
        node.tenants
            .get_mut(&TenantId("tenant-a".to_owned()))
            .unwrap()
            .maximum_payload_bytes = tenant_limit;
        let h = Harness::new(node, revision_policy());
        assert_eq!(
            detail(&h.admit("too-large").unwrap_err(), "scope"),
            expected_scope
        );
        let mut exact = Harness::request("exact");
        exact.payload_bytes = 9;
        drop(h.controller.admit_at(exact, h.sample).unwrap());
        let mut empty = Harness::request("empty");
        empty.payload_bytes = 0;
        drop(h.controller.admit_at(empty, h.sample).unwrap());
        h.assert_empty();
    }
}

#[test]
fn anonymous_forged_cross_tenant_and_unconfigured_principals_are_denied_before_lookup() {
    let mutations: [fn(&mut AdmissionRequest); 6] = [
        |r| r.principal.kind = PrincipalKind::Anonymous,
        |r| r.principal.kind = PrincipalKind::Administrator,
        |r| r.principal.tenant = None,
        |r| r.principal.tenant = Some(TenantId("tenant-b".to_owned())),
        |r| r.principal.subject = "mallory".to_owned(),
        |r| r.principal.subject = " ".to_owned(),
    ];
    for mutate in mutations {
        let h = Harness::standard();
        let mut request = Harness::request("principal");
        mutate(&mut request);
        request
            .principal
            .claims
            .insert("role".to_owned(), "administrator".to_owned());
        assert_eq!(
            h.controller.admit_at(request, h.sample).unwrap_err().code,
            Code::PermissionDenied
        );
        assert_eq!(h.source.calls.load(Ordering::Relaxed), 0);
        h.assert_empty();
    }
}

#[test]
fn service_principals_require_a_valid_service_identity() {
    let mut node = node_policy();
    node.tenants
        .get_mut(&TenantId("tenant-a".to_owned()))
        .unwrap()
        .allowed_principal_kinds = vec![PrincipalKind::Service];
    let h = Harness::new(node, revision_policy());
    let mut request = Harness::request("service");
    request.principal.kind = PrincipalKind::Service;
    assert_eq!(
        h.controller
            .admit_at(request.clone(), h.sample)
            .unwrap_err()
            .code,
        Code::PermissionDenied
    );
    request.principal.service = Some(ServiceId("caller".to_owned()));
    drop(h.controller.admit_at(request, h.sample).unwrap());
    h.assert_empty();
}

#[test]
fn exact_revision_release_generation_and_endpoint_must_exist() {
    let mutations: [fn(&mut AdmissionRequest); 6] = [
        |r| r.revision.revision = RevisionId("missing".to_owned()),
        |r| r.revision.release = ReleaseDigest(format!("sha256:{}", "b".repeat(64))),
        |r| r.revision.route_generation = RouteGeneration(2),
        |r| r.revision.target.contract = ContractId("missing:api/api@1.0.0".to_owned()),
        |r| r.revision.target.function = FunctionId("missing".to_owned()),
        |r| r.revision.target.route = Some("missing".to_owned()),
    ];
    for mutate in mutations {
        let h = Harness::standard();
        let mut request = Harness::request("forged");
        mutate(&mut request);
        let error = h.controller.admit_at(request, h.sample).unwrap_err();
        assert_eq!(error.code, Code::AdmissionRejected);
        assert!(!format!("{error:?}").contains("other-tenant-secret"));
        h.assert_empty();
    }
    let h = Harness::standard();
    h.source.available.store(false, Ordering::Relaxed);
    assert_eq!(
        h.admit("missing").unwrap_err().code,
        Code::AdmissionRejected
    );
    h.assert_empty();
}

#[test]
fn attributes_cannot_replace_catalog_policy_or_escape_in_error_details() {
    let h = Harness::standard();
    let mut request = Harness::request("spoof");
    request
        .attributes
        .insert("trust_class".to_owned(), "administrator-secret".to_owned());
    request.revision.attributes.insert(
        "lsf.deployment".to_owned(),
        "forged-resource-ceiling".to_owned(),
    );
    let permit = h.controller.admit_at(request, h.sample).unwrap();
    assert_eq!(permit.obligations().trust_class, "sandbox");
    assert!(permit.revision().attributes.is_empty());
    drop(permit);
    let mut request = Harness::request("denied");
    request
        .principal
        .claims
        .insert("secret".to_owned(), "private-token".to_owned());
    request.priority = 255;
    let error = h.controller.admit_at(request, h.sample).unwrap_err();
    assert!(!format!("{error:?}").contains("private-token"));
    assert_eq!(error.details[0].fields.len(), 3);
    h.assert_empty();
}

#[test]
fn short_name_limits_preserve_bounded_generated_revision_identities() {
    let mut policy = node_policy();
    policy.maximum_identifier_bytes = 64;
    let h = Harness::new(policy, revision_policy());
    let permit = h.admit("short-name").unwrap();
    assert_eq!(permit.revision().revision.0.len(), 83);
    assert_eq!(permit.revision().release.0.len(), 71);
    drop(permit);
    let lookups = h.source.calls.load(Ordering::Relaxed);

    for field in ["activation", "revision", "release"] {
        let mut request = Harness::request("invalid");
        match field {
            "activation" => request.activation_id.0 = "x".repeat(65),
            "revision" => request.revision.revision.0.push('x'),
            _ => request.revision.release.0 = "x".repeat(84),
        }
        assert_eq!(
            h.controller.admit_at(request, h.sample).unwrap_err().code,
            Code::InvalidArgument
        );
        assert_eq!(h.source.calls.load(Ordering::Relaxed), lookups);
    }

    let mut forged = Harness::request("forged");
    forged.revision.revision.0 = format!("revision-v1:sha256:{}", "b".repeat(64));
    assert_eq!(
        h.controller.admit_at(forged, h.sample).unwrap_err().code,
        Code::AdmissionRejected
    );
    h.assert_empty();
}

#[test]
fn metadata_identifier_and_empty_revision_boundaries_are_checked() {
    let h = Harness::standard();
    for field in ["activation", "revision", "function"] {
        let mut request = Harness::request("invalid");
        match field {
            "activation" => request.activation_id.0.clear(),
            "revision" => request.revision.revision.0 = "x".repeat(1025),
            _ => request.revision.target.function.0 = "bad function".to_owned(),
        }
        assert_eq!(
            h.controller.admit_at(request, h.sample).unwrap_err().code,
            Code::InvalidArgument
        );
    }
    let mut request = Harness::request("metadata");
    request
        .principal
        .claims
        .insert("key".to_owned(), "x".repeat(4096));
    assert_eq!(
        detail(
            &h.controller.admit_at(request, h.sample).unwrap_err(),
            "dimension"
        ),
        "metadata"
    );
    let mut request = Harness::request("generation");
    request.revision.route_generation = RouteGeneration(0);
    assert_eq!(
        h.controller.admit_at(request, h.sample).unwrap_err().code,
        Code::AdmissionRejected
    );
    h.assert_empty();
}

#[test]
fn incompatible_backends_state_threading_features_and_placement_are_independent() {
    let mutations: [PolicyMutation; 6] = [
        (
            |p| p.execution.backend = ExecutionBackendKind::Container,
            "backend",
        ),
        (
            |p| p.execution.state_model = StateModel::Entity,
            "state-model",
        ),
        (
            |p| p.execution.threading = ThreadingModel::Cooperative,
            "threading",
        ),
        (
            |p| p.placement.required_features = vec!["missing".to_owned()],
            "required-features",
        ),
        (
            |p| p.placement.architectures = vec!["aarch64".to_owned()],
            "architecture",
        ),
        (|p| p.placement.zones = vec!["b".to_owned()], "zone"),
    ];
    for (mutate, dimension) in mutations {
        let mut policy = revision_policy();
        mutate(&mut policy);
        let h = Harness::new(node_policy(), policy);
        assert_eq!(
            detail(&h.admit("unsupported").unwrap_err(), "dimension"),
            dimension
        );
        h.assert_empty();
    }
}

#[test]
fn execution_features_can_require_a_larger_cell_than_memory_alone() {
    let mut policy = revision_policy();
    policy.placement.required_features = vec!["simd".to_owned()];
    let h = Harness::new(node_policy(), policy);
    let permit = h.admit("simd").unwrap();
    assert_eq!(permit.obligations().cell_class, "small");
    assert_eq!(permit.obligations().required_features, ["simd"]);
    drop(permit);
    h.assert_empty();
}

#[test]
fn extra_large_requires_explicit_tenant_and_trust_permission() {
    for permit_tenant in [false, true] {
        for permit_trust in [false, true] {
            let mut node = node_policy();
            if permit_tenant {
                node.tenants
                    .get_mut(&TenantId("tenant-a".to_owned()))
                    .unwrap()
                    .allowed_cell_classes
                    .insert("extra-large".to_owned());
            }
            if permit_trust {
                node.trust_classes
                    .get_mut("sandbox")
                    .unwrap()
                    .allowed_cell_classes
                    .insert("extra-large".to_owned());
            }
            let h = Harness::new(node, revision_policy());
            let mut request = Harness::request("large");
            request.requested_budget.memory_bytes = 8_388_608;
            let result = h.controller.admit_at(request, h.sample);
            if permit_tenant && permit_trust {
                assert_eq!(result.unwrap().obligations().cell_class, "extra-large");
            } else {
                assert_eq!(result.unwrap_err().code, Code::PermissionDenied);
            }
            h.assert_empty();
        }
    }
}

#[test]
fn trust_class_permission_cannot_be_granted_by_request_metadata() {
    let mut policy = revision_policy();
    policy.placement.trust_class = "privileged".to_owned();
    let h = Harness::new(node_policy(), policy);
    let mut request = Harness::request("trust");
    request
        .attributes
        .insert("trust_class".to_owned(), "sandbox".to_owned());
    assert_eq!(
        detail(
            &h.controller.admit_at(request, h.sample).unwrap_err(),
            "dimension"
        ),
        "trust-class"
    );
    h.assert_empty();
}

#[test]
fn overload_pressure_thresholds_are_exact_and_independent() {
    for cpu in [false, true] {
        let h = Harness::standard();
        let mut load = h.load.snapshot().unwrap();
        if cpu {
            load.cpu_pressure_milli = 899;
        } else {
            load.memory_pressure_milli = 899;
        }
        h.load.publish(load).unwrap();
        drop(h.admit("below").unwrap());
        if cpu {
            load.cpu_pressure_milli = 900;
        } else {
            load.memory_pressure_milli = 900;
        }
        h.load.publish(load).unwrap();
        let error = h.admit("at-threshold").unwrap_err();
        assert_eq!(error.code, Code::ResourceExhausted);
        assert_eq!(
            detail(&error, "dimension"),
            if cpu {
                "cpu-pressure"
            } else {
                "memory-pressure"
            }
        );
        h.assert_empty();
    }
}

#[test]
fn stale_future_malformed_and_unavailable_load_samples_fail_closed() {
    let h = Harness::standard();
    let stale = ClockSample::new(20_001, h.sample.monotonic() + Duration::from_millis(10_001));
    assert_eq!(
        h.controller
            .admit_at(Harness::request("stale"), stale)
            .unwrap_err()
            .code,
        Code::Unavailable
    );
    let future = ClockSample::new(
        9999,
        h.sample
            .monotonic()
            .checked_sub(Duration::from_millis(1))
            .unwrap(),
    );
    assert_eq!(
        h.controller
            .admit_at(Harness::request("future"), future)
            .unwrap_err()
            .code,
        Code::Unavailable
    );
    let mut load = h.load.snapshot().unwrap();
    load.cpu_pressure_milli = 1001;
    assert!(h.load.publish(load).is_err());
    load.cpu_pressure_milli = 0;
    load.accepting = false;
    h.load.publish(load).unwrap();
    assert_eq!(h.admit("closed").unwrap_err().code, Code::Unavailable);
    h.assert_empty();
}

#[test]
fn duplicate_activation_ids_do_not_replace_or_refund_live_reservations() {
    let h = Harness::standard();
    let original = h.admit("same").unwrap();
    let mut request = Harness::request("same");
    request.principal.subject = "bob".to_owned();
    request.principal.tenant = Some(TenantId("tenant-b".to_owned()));
    request.revision = revision("tenant-b");
    assert_eq!(
        h.controller.admit_at(request, h.sample).unwrap_err().code,
        Code::AlreadyExists
    );
    assert_eq!(h.quotas.usage().unwrap().active_activations, 1);
    drop(original);
    drop(h.admit("same").unwrap());
    h.assert_empty();
}

#[test]
fn tenant_counters_are_isolated_while_node_and_trust_limits_are_shared() {
    let h = Harness::standard();
    let first = h.admit("alice").unwrap();
    let mut request = Harness::request("bob");
    request.principal.subject = "bob".to_owned();
    request.principal.tenant = Some(TenantId("tenant-b".to_owned()));
    request.revision = revision("tenant-b");
    let second = h.controller.admit_at(request, h.sample).unwrap();
    for tenant in ["tenant-a", "tenant-b"] {
        assert_eq!(
            h.quotas
                .snapshot_now(&TenantId(tenant.to_owned()))
                .unwrap()
                .active_activations,
            1
        );
    }
    assert_eq!(h.quotas.usage().unwrap().active_activations, 2);
    drop(first);
    assert_eq!(h.quotas.retained_tenant_count().unwrap(), 1);
    drop(second);
    h.assert_empty();
}

#[test]
fn reservation_guard_is_outcome_agnostic_and_outlives_accounting() {
    let h = Harness::standard();
    for outcome in [
        "success",
        "declared-error",
        "trap",
        "deadline",
        "cancelled",
        "platform-failure",
        "cleanup-failure",
    ] {
        let permit = h.admit(outcome).unwrap();
        let accounting = ActivationBudget::new(permit.effective_budget().clone());
        let running = permit.start_execution_at(h.sample.monotonic()).unwrap();
        assert_eq!(h.quotas.usage().unwrap().reserved_cpu_fuel, 100);
        let _finalized = accounting.finalize_at(None, h.sample.monotonic());
        drop(running);
        h.assert_empty();
    }
    // Enqueue failure has no execution transition and releases its queue slot too.
    drop(h.admit("enqueue-failure").unwrap());
    h.assert_empty();
}

#[test]
fn dropped_unpolled_queued_running_and_ready_futures_leave_no_quota_state() {
    let h = Harness::standard();
    drop(h.controller.admit(Harness::request("unpolled")));
    h.assert_empty();
    for running in [false, true] {
        let controller = h.controller.clone();
        let request = Harness::request("abandoned");
        let sample = h.sample;
        let mut future = Box::pin(async move {
            let permit = controller.admit_at(request, sample).unwrap();
            if running {
                let permit = permit.start_execution_at(sample.monotonic()).unwrap();
                std::future::pending::<()>().await;
                drop(permit);
            } else {
                std::future::pending::<()>().await;
                drop(permit);
            }
        });
        let mut context = Context::from_waker(Waker::noop());
        assert!(future.as_mut().poll(&mut context).is_pending());
        assert_eq!(h.quotas.usage().unwrap().active_activations, 1);
        drop(future);
        h.assert_empty();
    }
    let mut future = h.controller.admit(Harness::request("ready"));
    let mut context = Context::from_waker(Waker::noop());
    let result = future.as_mut().poll(&mut context);
    assert!(matches!(&result, Poll::Ready(Ok(_))));
    drop(result);
    h.assert_empty();
}

#[test]
fn unwinding_reclaims_queued_and_running_reservations() {
    let h = Harness::standard();
    for running in [false, true] {
        let permit = h.admit("panic").unwrap();
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            if running {
                let _permit = permit.start_execution_at(h.sample.monotonic()).unwrap();
                panic!("downstream panic");
            }
            let _permit = permit;
            panic!("enqueue panic");
        }));
        assert!(result.is_err());
        h.assert_empty();
    }
}

#[test]
fn concurrent_admission_never_exceeds_any_configured_limit() {
    for dimension in ["concurrency", "queue", "cpu-fuel", "memory-bytes"] {
        let mut node = node_policy();
        match dimension {
            "concurrency" => node.limits.maximum_concurrent_activations = 4,
            "queue" => node.limits.maximum_queued_activations = 4,
            "cpu-fuel" => node.limits.maximum_reserved_cpu_fuel = 400,
            _ => node.limits.maximum_reserved_memory_bytes = 4 * 65_536,
        }
        let h = Harness::new(node, revision_policy());
        let start = Arc::new(Barrier::new(65));
        let admitted = Arc::new(Barrier::new(65));
        let release = Arc::new(Barrier::new(65));
        let winners = AtomicUsize::new(0);
        std::thread::scope(|scope| {
            for index in 0..64 {
                let start = start.clone();
                let admitted = admitted.clone();
                let release = release.clone();
                let controller = h.controller.clone();
                let request = Harness::request(&format!("race-{index}"));
                let sample = h.sample;
                let winners = &winners;
                scope.spawn(move || {
                    start.wait();
                    let permit = controller.admit_at(request, sample).ok();
                    if permit.is_some() {
                        winners.fetch_add(1, Ordering::SeqCst);
                    }
                    admitted.wait();
                    release.wait();
                    drop(permit);
                });
            }
            start.wait();
            admitted.wait();
            let winner_count = winners.load(Ordering::SeqCst);
            let usage = h.quotas.usage().unwrap();
            release.wait();
            assert_eq!(winner_count, 4, "{dimension}");
            assert_eq!(usage.active_activations, 4);
            assert_eq!(usage.queued_activations, 4);
            assert_eq!(usage.reserved_cpu_fuel, 400);
            assert_eq!(usage.reserved_memory_bytes, 4 * 65_536);
        });
        h.assert_empty();
    }
}

#[test]
fn controller_replacement_shares_existing_quota_reservations() {
    let mut node = node_policy();
    node.limits.maximum_concurrent_activations = 1;
    let h = Harness::new(node, revision_policy());
    let original = h.admit("old").unwrap();
    let next = h.controller.with_policy_source(h.source.clone());
    assert_eq!(
        detail(
            &next
                .admit_at(Harness::request("new"), h.sample)
                .unwrap_err(),
            "dimension"
        ),
        "concurrency"
    );
    drop(original);
    drop(next.admit_at(Harness::request("new"), h.sample).unwrap());
    h.assert_empty();
}

#[test]
fn maximum_integer_reservations_cannot_wrap_or_double_refund() {
    let mut node = node_policy();
    node.budget_ceiling.cpu_fuel = u64::MAX;
    node.limits.maximum_reserved_cpu_fuel = u64::MAX;
    for tenant in node.tenants.values_mut() {
        tenant.limits.maximum_reserved_cpu_fuel = u64::MAX;
    }
    node.trust_classes
        .get_mut("sandbox")
        .unwrap()
        .limits
        .maximum_reserved_cpu_fuel = u64::MAX;
    let mut policy = revision_policy();
    policy.deployment_ceiling.cpu_fuel = u64::MAX;
    policy.execution.resource_budget_ceiling.cpu_fuel = u64::MAX;
    let h = Harness::new(node, policy);
    let mut request = Harness::request("maximum");
    request.requested_budget.cpu_fuel = u64::MAX;
    let permit = h.controller.admit_at(request, h.sample).unwrap();
    assert_eq!(h.quotas.usage().unwrap().reserved_cpu_fuel, u64::MAX);
    assert_eq!(
        detail(&h.admit("overflow").unwrap_err(), "dimension"),
        "cpu-fuel"
    );
    drop(permit);
    h.assert_empty();
    drop(h.admit("reused").unwrap());
    h.assert_empty();
}

#[test]
fn invalid_startup_policies_are_rejected_before_any_state_exists() {
    let mutations: [fn(&mut NodeAdmissionPolicy); 7] = [
        |p| p.budget_ceiling.wall_time_limit_millis = None,
        |p| p.overload.maximum_cpu_pressure_milli = 1001,
        |p| p.deadline.minimum_execution_time_millis = 0,
        |p| p.queue_classes.get_mut("urgent").unwrap().minimum_priority = 127,
        |p| p.queue_classes.remove("urgent").map(drop).unwrap(),
        |p| p.cell_classes.get_mut("tiny").unwrap().parallelism = 0,
        |p| {
            p.cell_classes
                .get_mut("small")
                .unwrap()
                .maximum_memory_bytes = 1;
        },
    ];
    for mutate in mutations {
        let mut policy = node_policy();
        mutate(&mut policy);
        assert!(LocalQuotaProvider::new(policy).is_err());
    }
}
