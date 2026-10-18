//! One real pre-start native refusal retains its original root outcome after cleanup.
use super::*;
use crate::standalone::state::installations::InstalledState;
use latent_activation::RetainedActivationOutcome;
use latent_core::{
    native_capacity::{NativeAdmissionClass, NativeReservationRequest},
    ActivationPhase, ActivationTerminalState, PlatformErrorCode,
};

struct HttpFixture {
    setup: Setup,
    loaded: InstalledState,
    metadata: latent_artifacts::VerifiedArtifactMetadata,
    factory: WasmtimeComponentEngineFactory,
    backend: Arc<latent_wasmtime::WasmtimeBackend>,
    manager: LocalActivationManager,
    quotas: LocalQuotaProvider,
    cleanup: latent_wire::invocation::ActivationCleanupOwner,
    owner: crate::standalone::http::HttpOwner,
}

impl HttpFixture {
    async fn new() -> Self {
        let mut setup = Setup::configured(None, true).await;
        setup.fixture.settings.operations[0].route = Some("deployment".into());
        let operation = setup.fixture.settings.operations[0].clone();
        allow_query(&setup, &operation);
        install_route(&setup, &operation);
        let loaded = load_current(&setup).await;
        create_namespace(&setup, &loaded, &operation).await;
        drop(loaded);
        let loaded = load_current(&setup).await;
        let metadata = setup
            .services
            .artifacts
            .fetch_verified_metadata_selected(&operation.component, Some(&operation.publication))
            .await
            .unwrap();
        let budget = metadata
            .manifest()
            .execution
            .resource_budget_ceiling
            .clone();
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            WasmtimeConfig {
                transactional_state: true,
                maximum_memory_bytes: budget.memory_bytes,
                maximum_fuel: budget.cpu_fuel,
                ..Default::default()
            },
            WasmtimeHostServices {
                clock: setup.fixture.clock.clone(),
                capabilities: None,
                currentness_read_wait: Some(Arc::new(latent_node::CurrentnessReadTimer)),
                log_sink: None,
            },
            setup.services.artifacts.lifecycle_authority(),
        )
        .unwrap();
        let backend = Arc::new(factory.create_backend_instance());
        let (manager, quotas) = manager(&setup, backend.clone(), &budget);
        let cleanup = latent_wire::invocation::ActivationCleanupOwner::start(
            8,
            Duration::from_millis(250),
            &tokio::runtime::Handle::current(),
        )
        .unwrap();
        let owner = start_owner(&setup, &loaded, &manager, &cleanup, budget);
        owner.handle().start_accepting().unwrap();
        Self {
            setup,
            loaded,
            metadata,
            factory,
            backend,
            manager,
            quotas,
            cleanup,
            owner,
        }
    }

    async fn finish(self) {
        self.owner
            .shutdown((Instant::now() + Duration::from_secs(5)).into())
            .await
            .unwrap();
        self.cleanup
            .shutdown((Instant::now() + Duration::from_secs(5)).into())
            .await
            .unwrap();
        drop(self.manager);
        drop(self.quotas);
        drop(self.backend);
        drop(self.factory);
        drop(self.metadata);
        drop(self.loaded);
        self.setup.finish().await;
    }
}

fn allow_query(setup: &Setup, operation: &OperationSettings) {
    let caller = InvocationPrincipal {
        subject: "alice".into(),
        kind: PrincipalKind::User,
        tenant: Some(operation.tenant.clone()),
        service: None,
        claims: latent_core::Metadata::new(),
    };
    let scope = latent_capabilities::namespace::CallerScope::derive(
        &caller,
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    let original_policy = setup
        .policy
        .get(
            "tests",
            RecordKind::Policy,
            "state",
            65536,
            Instant::now() + Duration::from_secs(10),
        )
        .unwrap();
    let record = original_policy.value().as_ref().unwrap();
    let policy_revision = record.revision;
    let mut document: serde_json::Value =
        serde_json::from_str(record.document.as_ref().unwrap()).unwrap();
    document["rules"].as_array_mut().unwrap().push(json!({"id":"alice","effect":"allow",
        "principals":[{"kind":"user","subject":"alice"}], "services":["tests/packaging"],
        "publications":[operation.publication.as_str()], "capability":latent_capabilities::namespace::STATE_CONTRACT,
        "operations":["acquire-query","query-info","read-result"],
        "resources":{"kind":"state","scopes":[{"namespace":"orders","incarnation":1,"entity":null,
            "recoveryKind":scope.kind,"recoveryScope":scope.scope,"resultPolicy":"owner"}]},
        "ceiling":{"operations":16,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":10_000}}));
    let bytes = serde_json::to_vec(&document).unwrap();
    drop(original_policy);
    setup
        .policy
        .mutate(
            MutationRequest {
                tenant: "tests",
                actor: "operator",
                kind: RecordKind::Policy,
                id: "state",
                operation_id: "http-query-policy",
                expected_revision: policy_revision,
                document: Some(&bytes),
            },
            Instant::now() + Duration::from_secs(10),
            |_| Ok(()),
        )
        .unwrap();
}

async fn load_current(setup: &Setup) -> InstalledState {
    load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap()
}

async fn create_namespace(setup: &Setup, loaded: &InstalledState, operation: &OperationSettings) {
    let quota = policy::maximum_quota(&setup.fixture.settings, operation).unwrap();
    loaded
        .management
        .as_ref()
        .unwrap()
        .execute_state(
            AuthenticatedInvocationContext::new(operator()),
            c::MutateNamespaceRequest {
                namespace: Some(c::InspectNamespaceRequest {
                    profile: Some(contract::current_profile()),
                    namespace: Some(t::NamespaceSelector {
                        tenant: "tests".into(),
                        namespace: "orders".into(),
                        incarnation: "1".into(),
                    }),
                    authorization_publication: Some(c::PublicationRef {
                        tenant: "tests".into(),
                        id: operation.publication.as_str().into(),
                    }),
                }),
                mutation: c::NamespaceMutationKind::Create as i32,
                operation_id: "http-query-create".into(),
                expected_generation: Some(0),
                configuration: Some(c::NamespaceConfiguration {
                    state_schema: format!("sha256:{}", "1".repeat(64)),
                    quota: Some(c::NamespaceQuota {
                        state_keys: quota.state_keys,
                        state_bytes: quota.state_bytes,
                        result_rows: quota.result_rows,
                        result_bytes: quota.result_bytes,
                        effect_rows: quota.effect_rows,
                        effect_bytes: quota.effect_bytes,
                        payload_bytes: quota.payload_bytes,
                        recovery_bytes: quota.recovery_bytes,
                    }),
                }),
            }
            .into(),
        )
        .await
        .unwrap();
}

fn start_owner(
    setup: &Setup,
    loaded: &InstalledState,
    manager: &LocalActivationManager,
    cleanup: &latent_wire::invocation::ActivationCleanupOwner,
    budget: latent_core::ResourceBudget,
) -> crate::standalone::http::HttpOwner {
    let mut config = json!({"formatVersion":1,"dataDirectory":setup.fixture.root().join("unused-http-node"),
        "nodeId":"signed-http-query","bind":"127.0.0.1:0","limits":{"maximumPayloadBytes":2_097_152},
        "httpIngress":{"formatVersion":1,"bind":"127.0.0.1:0","transport":{"mode":"loopback"},
            "authentication":{"mode":"bearer"},"limits":{}}});
    config["credentials"] = json!([
        {"token":"invoke-token-0000000000000000000000000000","subject":"alice","tenant":"tests","role":"invoke"},
        {"token":"second-token-0000000000000000000000000000","subject":"bob","tenant":"tests","role":"invoke"}]);
    let settings = serde_json::from_value::<crate::config::NodeConfig>(config)
        .unwrap()
        .derive()
        .unwrap();
    crate::standalone::http::HttpOwner::start(
        settings.http.unwrap(),
        crate::standalone::http::HttpServices {
            manager: manager.clone(),
            deployments: setup.services.deployments.clone(),
            cleanup: cleanup.handle(),
            clock: setup.fixture.clock.clone(),
            budget,
            transactions: Some(crate::standalone::http::transaction::Services {
                owners: setup.owners.clone(),
                installations: loaded.installations.clone().into(),
                operations: setup.fixture.settings.operations.clone().into(),
                management: loaded.management.as_ref().unwrap().clone(),
            }),
        },
    )
    .unwrap()
}

fn header_values<'a>(headers: &'a str, name: &str) -> Vec<&'a str> {
    headers
        .lines()
        .filter_map(|line| line.split_once(':'))
        .filter(|(field, _)| field.eq_ignore_ascii_case(name))
        .map(|(_, value)| value.trim())
        .collect()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_native_ingress_refusal_keeps_resource_exhausted_in_the_signed_http_root() {
    let fixture = HttpFixture::new().await;
    let native = fixture.setup.kernel.native.clone();
    let initial = native.snapshot().unwrap();
    let maximum = fixture.setup.fixture.settings.native.ordinary.slots;
    let deadline = fixture.setup.fixture.clock.monotonic_now() + Duration::from_secs(10);
    let held: Vec<_> = (initial.ordinary.slots..maximum)
        .map(|_| {
            native
                .reserve(
                    NativeAdmissionClass::Ordinary,
                    NativeReservationRequest {
                        work_bytes: 1,
                        ..Default::default()
                    },
                    deadline,
                )
                .unwrap()
        })
        .collect();
    let pressured = native.snapshot().unwrap();
    let held_count = held.len();
    let input = URL_SAFE_NO_PAD.encode(br#"[{"outcome":{"err":3},"count":7}]"#);
    let token = "invoke-token-0000000000000000000000000000";
    fixture.setup.fixture.clock.advance_to(Instant::now());
    let response = request(fixture.owner.local_addr(), &input, token).await;
    let stores = fixture.backend.resource_snapshot().stores_created;
    let journal = fixture.manager.journal();
    let roots = journal.inspect_roots(
        &TenantId("tests".into()),
        &ServiceId("tests/packaging".into()),
        None,
        8,
        None,
    );
    let root = roots.as_ref().ok().and_then(|page| page.nodes.first());
    let status = root.and_then(|root| {
        journal
            .status(&TenantId("tests".into()), &root.activation_id)
            .ok()
            .flatten()
    });
    let events = root.map(|root| journal.events(&TenantId("tests".into()), &root.activation_id));
    let rendered = format!("{roots:?}{status:?}{events:?}");
    let active = journal.snapshot().active;
    let quota = fixture
        .quotas
        .snapshot_now(&TenantId("tests".into()))
        .unwrap();
    drop(held);
    let released = native.snapshot().unwrap();
    fixture.finish().await;
    assert!(native.snapshot().unwrap().physically_retired());
    assert_eq!(initial.ordinary.slots, 0);
    assert_eq!(held_count, maximum);
    assert_eq!(pressured.ordinary.slots, maximum);
    assert!(pressured.ordinary.bytes > initial.ordinary.bytes);
    assert_eq!(released.ordinary, initial.ordinary);
    assert_eq!(stores, 0);
    assert_eq!(active, 0);
    assert_eq!(quota.active_activations, 0);
    assert_eq!(quota.queued_activations, 0);
    let body_at = response
        .windows(4)
        .position(|bytes| bytes == b"\r\n\r\n")
        .unwrap()
        + 4;
    let headers = std::str::from_utf8(&response[..body_at]).unwrap();
    assert!(headers.starts_with("HTTP/1.1 503 "));
    assert_eq!(header_values(headers, "content-length"), ["0"]);
    assert_eq!(header_values(headers, "cache-control"), ["no-store"]);
    assert!(header_values(headers, "content-type").is_empty());
    assert!(response[body_at..].is_empty());
    let roots = roots.unwrap();
    assert!(roots.history_available && !roots.cursor_expired && roots.next_page_token.is_none());
    assert_eq!(roots.nodes.len(), 1);
    let status = status.unwrap();
    assert_eq!(status.phase, ActivationPhase::Admitted);
    assert_eq!(
        status.terminal_state,
        Some(ActivationTerminalState::ResourceExhausted)
    );
    let Some(RetainedActivationOutcome::PlatformFailure(error)) = status.terminal_outcome else {
        panic!("original native refusal was not retained");
    };
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert!(!error.retryable && error.details.is_empty());
    assert_eq!(status.final_consumption.unwrap().cpu_fuel, 0);
    assert!(!rendered.contains(&input) && !rendered.contains(token));
    assert!(!rendered.contains(r#"[{"outcome":{"err":3},"count":7}]"#));
}
