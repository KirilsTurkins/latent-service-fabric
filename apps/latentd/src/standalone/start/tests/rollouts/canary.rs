mod component;
use super::*;
use latent_artifacts::{
    ArtifactRepository, CapsuleArtifact, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseMutationContext,
};
use latent_control_store::DeploymentStore;
use latent_core::{ActivationClock, ClockSample, ContractId, FunctionId, ServiceId, TenantId};
use latent_routing::{InvocationTarget, RouteResolver};
use latent_wire::{invocation::proto as invocation, management::deployment_manifest_from_proto};
use std::{
    sync::atomic::{AtomicU64, Ordering},
    time::Instant,
};

pub(super) struct Clock {
    elapsed: AtomicU64,
}
impl Clock {
    pub(super) fn new() -> Self {
        Self {
            elapsed: AtomicU64::new(0),
        }
    }
    fn finish_interval(&self) {
        self.elapsed.store(30_000, Ordering::Release);
    }
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        // The real transport derives RPC deadlines from this clock. Freezing
        // it at construction makes those deadlines expire during catalog setup
        // on a busy runner. Only fast-forward the observation after the call;
        // before then, keep progressing in the real monotonic time domain.
        Instant::now() + Duration::from_millis(self.elapsed.load(Ordering::Acquire))
    }
}

pub(super) fn request<T>(value: T) -> tonic::Request<T> {
    let mut request = tonic::Request::new(value);
    request.metadata_mut().insert(
        "authorization",
        "Bearer test-token-000000000000000000000000000000"
            .parse()
            .unwrap(),
    );
    request.set_timeout(Duration::from_secs(5));
    request
}

fn invoke_request(value: invocation::InvokeRequest) -> tonic::Request<invocation::InvokeRequest> {
    let mut value = request(value);
    // This fixture retains the node's default 1000 ms maximum invocation timeout.
    value.set_timeout(Duration::from_secs(1));
    value
}

pub(super) async fn prepare_invocation(
    node: &crate::standalone::StandaloneNode,
    artifacts: &dyn ArtifactRepository,
    component: &str,
) {
    use latent_executor::ExecutionBackend;
    let release = latent_core::ReleaseDigest(component.to_owned());
    let mut key = node.backend.preparation_key(&release).unwrap();
    key.publication = Some(
        artifacts
            .select_execution_publication(&TenantId("tests".into()), &release, None)
            .unwrap()
            .expect("published canary component")
            .id,
    );
    // Canary routing/outcome assertions use the normal one-second invocation
    // budget. Cold compilation is bounded setup, not a runner-speed assertion.
    let prepared = tokio::time::timeout(
        Duration::from_secs(10),
        node.backend.prepare_from_repository(artifacts, &key),
    )
    .await
    .expect("bounded canary compilation setup")
    .expect("canary component preparation");
    drop(prepared);
}

pub(super) fn configured(directory: &TempDir) -> NodeSettings {
    let mut value = settings(directory);
    value.audit = Some(AuditLimits::default());
    value.rollouts = Some(crate::config::RolloutSettings {
        store: RolloutLimits::default(),
        coordinator: CoordinatorLimits::default(),
        canary: Some(latent_telemetry::Phase2CanaryOutcomeWindowConfig::default()),
    });
    value.shutdown_grace = Duration::from_secs(5);
    value
}

pub(super) async fn seed(catalogs: &Catalogs, trust_class: &str) -> proto::StartRolloutRequest {
    let (base_publication, base_digest) = publish(catalogs, component::artifact(1)).await;
    let (candidate_publication, candidate_digest) = publish(catalogs, component::artifact(2)).await;
    let mut base = super::fixtures::deployment("base", "tests", "echo", &base_digest);
    base.publication = Some(base_publication);
    // The generic catalog fixture uses "local". Actual node admission permits
    // only the trust class derived from this node's operator configuration.
    base.placement.as_mut().unwrap().trust_class = trust_class.to_owned();
    let base = deployment_manifest_from_proto(base).unwrap();
    let base = catalogs
        .deployments
        .apply_versioned(&TenantId("tests".into()), base, Some(0))
        .await
        .unwrap();
    let mut candidate =
        super::fixtures::deployment("candidate", "tests", "echo", &candidate_digest);
    candidate.publication = Some(candidate_publication);
    candidate.release_digest.clear();
    candidate.placement.as_mut().unwrap().trust_class = trust_class.to_owned();
    candidate.route_weight = 5000;
    proto::StartRolloutRequest {
        expected_candidate_component_digest: Some(candidate_digest.0),
        id: "observed".into(),
        base_deployment_id: "base".into(),
        expected_base_generation: Some(base.deployment.generation),
        candidate: Some(candidate),
        candidate_weights: vec![5000, 10000],
        operation: Some(proto::RolloutOperationPrecondition {
            operation_id: "start".into(),
            expected_revision: Some(0),
        }),
        canary_policy: Some(proto::RolloutCanaryPolicy {
            format_version: 1,
            observation_millis: 30_000,
            minimum_candidate_samples: 1,
            maximum_failure_basis_points: Some(0),
            // This is a routing/outcome handoff test, not a latency benchmark.
            // Successful calls already obey the one-second invocation budget.
            latency_threshold_micros: 1_000_000,
            maximum_slow_basis_points: Some(0),
        }),
    }
}

async fn publish(
    catalogs: &Catalogs,
    artifact: CapsuleArtifact,
) -> (proto::PublicationRef, latent_core::ReleaseDigest) {
    let published = catalogs
        .artifacts
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "canary-fixture".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: None,
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    (
        proto::PublicationRef {
            id: published.publication.id.into_string(),
            tenant: "tests".into(),
        },
        published.release.descriptor.release_digest.clone(),
    )
}

#[tokio::test]
#[allow(
    clippy::too_many_lines,
    reason = "one actual activation proves the node capture and promotion owner handoff"
)]
async fn actual_candidate_invocation_drives_only_the_matching_canary_promotion() {
    let directory = TempDir::new().unwrap();
    let settings = configured(&directory);
    let clock = Arc::new(Clock::new());
    let catalogs = Catalogs::open_with_control_and_clock(
        &settings,
        &tokio::runtime::Handle::current(),
        clock.clone(),
    )
    .await
    .unwrap();
    let input = seed(&catalogs, &settings.node.trust_classes[0]).await;
    let artifacts = catalogs.artifacts.clone();
    let deployments = catalogs.deployments.clone();
    let candidate = input.expected_candidate_component_digest.clone().unwrap();
    let node = Box::pin(
        super::super::super::super::StandaloneNode::start_with_catalogs(
            settings,
            catalogs,
            tokio::runtime::Handle::current(),
            crate::standalone::RuntimeThreads::default(),
        ),
    )
    .await
    .unwrap();
    prepare_invocation(&node, artifacts.as_ref(), &candidate).await;
    drop(artifacts);
    let endpoint = format!("http://{}", node.endpoint());
    let mut client = proto::rollout_service_client::RolloutServiceClient::connect(endpoint.clone())
        .await
        .unwrap();
    let started = client
        .start_rollout(request(input))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(
        started.observation.unwrap().state,
        proto::RolloutObservationState::Collecting as i32
    );
    let started = started.receipt.unwrap();
    assert!(client
        .change_rollout(request(proto::ChangeRolloutRequest {
            id: "observed".into(),
            operation: Some(proto::RolloutOperationPrecondition {
                operation_id: "bypass".into(),
                expected_revision: Some(started.revision)
            }),
            command: Some(proto::change_rollout_request::Command::Advance(
                proto::AdvanceRollout { next_step: 1 }
            )),
        }))
        .await
        .is_err());
    let target = InvocationTarget {
        tenant: TenantId("tests".into()),
        service: ServiceId("echo".into()),
        contract: ContractId("tests:echo/api@1.0.0".into()),
        function: FunctionId("echo".into()),
        route: None,
    };
    // Select one routing key using the actual immutable resolver, not guessed weights or repeated calls.
    let activation = (0..128)
        .map(|index| format!("canary-call-{index}"))
        .find(|key| deployments.resolve(&target, Some(key)).unwrap().release.0 == candidate)
        .unwrap();
    let called = invoke(&endpoint, activation).await;
    assert_eq!(called.release_digest, candidate);
    assert!(
        matches!(
            called.result,
            Some(invocation::invoke_response::Result::Success(_))
        ),
        "{called:?}"
    );
    assert!(called.consumption.unwrap().cpu_fuel > 0);
    clock.finish_interval();
    let evaluation = client
        .evaluate_rollout(request(proto::EvaluateRolloutRequest {
            id: "observed".into(),
            expected_revision: Some(started.revision),
        }))
        .await
        .unwrap()
        .into_inner()
        .report
        .unwrap();
    assert_eq!(
        evaluation.assessment.as_ref().unwrap().verdict,
        proto::CanaryVerdict::Healthy as i32
    );
    assert_eq!(evaluation.assessment.unwrap().successes, 1);
    assert_eq!(evaluation.terminal, 1);
    let promoted = client
        .change_rollout(request(proto::ChangeRolloutRequest {
            id: "observed".into(),
            operation: Some(proto::RolloutOperationPrecondition {
                operation_id: "promote".into(),
                expected_revision: Some(started.revision),
            }),
            command: Some(proto::change_rollout_request::Command::Promote(
                proto::PromoteRollout { next_step: 1 },
            )),
        }))
        .await
        .unwrap()
        .into_inner()
        .receipt
        .unwrap();
    assert_eq!(promoted.state, proto::RolloutState::Completed as i32);
    assert!(promoted.route_generation > started.route_generation);
    assert_eq!(
        promoted.canary_decision.unwrap().candidate.unwrap().success,
        1
    );
    drop(client);
    drop(deployments);
    assert!(node.shutdown().await.unwrap().clean);
}

pub(super) async fn invoke(endpoint: &str, activation: String) -> invocation::InvokeResponse {
    let mut client = invocation::invocation_service_client::InvocationServiceClient::connect(
        endpoint.to_owned(),
    )
    .await
    .unwrap();
    client
        .invoke(invoke_request(invocation::InvokeRequest {
            activation_id: Some(activation),
            target: Some(invocation::InvocationTarget {
                tenant: "tests".into(),
                service: "echo".into(),
                contract: "tests:echo/api@1.0.0".into(),
                function: "echo".into(),
                route: None,
            }),
            payload: b"[]".to_vec(),
            media_type: latent_wasmtime::WIT_VALUES_MEDIA_TYPE.into(),
            budget: Some(invocation::ResourceBudget {
                cpu_fuel: 1000,
                memory_bytes: 65_536,
                wall_time_limit_millis: Some(1000),
                log_bytes: 128,
                ..Default::default()
            }),
            ..Default::default()
        }))
        .await
        .unwrap()
        .into_inner()
}

#[tokio::test]
async fn canary_compose_rejects_a_different_clock_before_activation_services() {
    let directory = TempDir::new().unwrap();
    let mut settings = configured(&directory);
    let mut catalogs = Catalogs::open_with_control_and_clock(
        &settings,
        &tokio::runtime::Handle::current(),
        Arc::new(Clock::new()),
    )
    .await
    .unwrap();
    assert_eq!(
        super::super::super::super::StandaloneNode::compose(
            &mut settings,
            &mut catalogs,
            Arc::new(Clock::new())
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::PermissionDenied
    );
    assert!(catalogs
        .rollouts
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap()
        .clean());
    catalogs
        .audit
        .as_ref()
        .unwrap()
        .shutdown(Duration::from_secs(5))
        .await
        .unwrap();
}
