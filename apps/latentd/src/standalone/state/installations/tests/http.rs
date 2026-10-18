//! Real signed component, installed scope and shared HTTP socket; no Java claim.
use super::*;
use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine,
};
use latent_admission::{
    LocalAdmissionController, LocalQuotaProvider, NodeLoadSnapshot, NodeLoadSource,
};
use latent_control_store::http_routes::{TriggerOperationContext, TriggerOperationRequest};
use latent_core::{InvocationPrincipal, NodeId, PrincipalKind};
use latent_node::{
    LocalActivationDependencies, LocalActivationManager, LocalActivationManagerConfig,
    LocalActivationServices,
};
use latent_routing::RouteResolver;
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};
use latent_wasmtime::{WasmtimeComponentEngineFactory, WasmtimeConfig, WasmtimeHostServices};
use std::collections::BTreeMap;
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::TcpStream,
};

#[path = "../../../../../../../crates/latent-node/tests/activation_lifecycle/model.rs"]
#[allow(dead_code)]
mod model;

struct Load(Arc<dyn ActivationClock>);
impl NodeLoadSource for Load {
    fn snapshot(&self) -> Result<NodeLoadSnapshot, PlatformError> {
        Ok(NodeLoadSnapshot {
            accepting: true,
            cpu_pressure_milli: 0,
            memory_pressure_milli: 0,
            queue_delay_millis: 0,
            observed_at: self.0.monotonic_now(),
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[expect(
    clippy::too_many_lines,
    reason = "One real signed fixture retains independent namespace, policy, guest and socket proof through clean shutdown"
)]
async fn actual_signed_http_query_keeps_snapshot_scope_and_denies_other_caller_without_guest_work()
{
    let mut setup = Setup::configured(None, true).await;
    setup.fixture.settings.operations[0].route = Some("deployment".into());
    let operation = setup.fixture.settings.operations[0].clone();
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
    install_route(&setup, &operation);
    let loaded = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
    let quota = policy::maximum_quota(&setup.fixture.settings, &operation).unwrap();
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
    drop(loaded);
    let loaded = load(
        &setup.kernel,
        &setup.fixture.settings,
        &setup.owners,
        setup.policy.clone(),
        setup.services(),
        &setup.effects,
    )
    .await
    .unwrap();
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
    let owner = crate::standalone::http::HttpOwner::start(
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
    .unwrap();
    owner.handle().start_accepting().unwrap();
    let input = URL_SAFE_NO_PAD.encode(br#"[{"outcome":{"err":3},"count":7}]"#);
    setup.fixture.clock.advance_to(Instant::now());
    let response = request(
        owner.local_addr(),
        &input,
        "invoke-token-0000000000000000000000000000",
    )
    .await;
    assert!(
        response.starts_with(b"HTTP/1.1 200"),
        "{}",
        String::from_utf8_lossy(&response)
    );
    let body = response.windows(4).position(|w| w == b"\r\n\r\n").unwrap() + 4;
    let result: serde_json::Value = serde_json::from_slice(&response[body..]).unwrap();
    assert_eq!(result["disposition"], "query");
    assert!(result["command-id"].is_null());
    assert!(STANDARD
        .decode(result["state-view"].as_str().unwrap())
        .unwrap()
        .starts_with(b"NV\x02"));
    assert_eq!(
        result["result"]["media-type"],
        latent_ingress::http::VALUE_MEDIA_TYPE
    );
    let stores = backend.resource_snapshot().stores_created;
    assert_eq!(stores, 1);
    setup.fixture.clock.advance_to(Instant::now());
    let refused = request(
        owner.local_addr(),
        &input,
        "second-token-0000000000000000000000000000",
    )
    .await;
    assert!(
        refused.starts_with(b"HTTP/1.1 403"),
        "{}",
        String::from_utf8_lossy(&refused)
    );
    assert_eq!(backend.resource_snapshot().stores_created, stores);
    owner
        .shutdown((Instant::now() + Duration::from_secs(5)).into())
        .await
        .unwrap();
    cleanup
        .shutdown((Instant::now() + Duration::from_secs(5)).into())
        .await
        .unwrap();
    drop(manager);
    drop(quotas);
    drop(backend);
    drop(factory);
    drop(metadata);
    drop(loaded);
    assert_eq!(setup.kernel.native.snapshot().unwrap().ordinary.slots, 0);
    setup.finish().await;
}

fn install_route(setup: &Setup, operation: &OperationSettings) {
    let revision = setup
        .services
        .deployments
        .resolve(
            &InvocationTarget {
                tenant: operation.tenant.clone(),
                service: ServiceId("tests/packaging".into()),
                contract: ContractId(operation.contract.clone()),
                function: FunctionId("inspect".into()),
                route: operation.route.clone(),
            },
            None,
        )
        .unwrap();
    let snapshot = setup
        .services
        .deployments
        .get_trigger(
            &operation.tenant,
            &latent_core::TriggerId("http-query".into()),
        )
        .unwrap();
    let value = json!({"apiVersion":"latent.dev/v1alpha1","kind":"HttpTrigger","metadata":{"name":"http-query","tenant":"tests"},
        "spec":{"target":{"service":"tests/packaging","contract":operation.contract,"function":"inspect","route":"deployment",
            "publication":operation.publication.as_str(),"revision":revision.revision.0,"deploymentGeneration":1},
            "configuration":{"profile":"transaction-http-v1","scheme":"http","host":"web.example.test","path":"/query","pathMatch":"exact","method":"GET",
                "transactionMode":"query","namespace":"orders","incarnation":"1","stateSchema":format!("sha256:{}","1".repeat(64)),
                "companionDigest":operation.companion_digest,"stateBinding":"binding","resultPolicy":"owner"}}});
    let prepared = setup
        .services
        .deployments
        .prepare_trigger_operation(TriggerOperationRequest::Apply {
            context: TriggerOperationContext {
                tenant: operation.tenant.clone(),
                actor: latent_artifacts::ReleaseActor {
                    subject: "operator".into(),
                    kind: latent_artifacts::ReleaseActorKind::Host,
                },
                operation_id: "http-query".into(),
                expected_state_version: snapshot.value().state_version,
            },
            manifest: JsonManifestCodec::default()
                .decode_trigger(&serde_json::to_vec(&value).unwrap())
                .unwrap(),
            expected_generation: 0,
        })
        .unwrap();
    setup
        .services
        .deployments
        .commit_trigger_operation(prepared)
        .unwrap();
}

fn manager(
    setup: &Setup,
    backend: Arc<latent_wasmtime::WasmtimeBackend>,
    budget: &latent_core::ResourceBudget,
) -> (LocalActivationManager, LocalQuotaProvider) {
    let mut policy = model::node_policy(1);
    policy.budget_ceiling = budget.clone();
    policy.architecture = std::env::consts::ARCH.into();
    policy.limits.maximum_reserved_cpu_fuel = budget.cpu_fuel * 8;
    policy.limits.maximum_reserved_memory_bytes = budget.memory_bytes * 8;
    let mut tenant = policy
        .tenants
        .remove(&TenantId(model::TENANT.into()))
        .unwrap();
    tenant.limits = policy.limits;
    tenant.allowed_subjects = model::names(&["alice", "bob"]);
    tenant.allowed_trust_classes = model::names(&["internal"]);
    policy.tenants = BTreeMap::from([(TenantId("tests".into()), tenant)]);
    for trust in policy.trust_classes.values_mut() {
        trust.limits = policy.limits;
    }
    let internal = policy.trust_classes.remove("sandbox").unwrap();
    policy.trust_classes.insert("internal".into(), internal);
    for cell in policy.cell_classes.values_mut() {
        cell.maximum_memory_bytes = budget.memory_bytes;
    }
    let quotas = LocalQuotaProvider::with_profile(
        policy,
        BudgetProfile::Phase4,
        latent_core::DelegationLimits::default(),
    )
    .unwrap();
    let admission = LocalAdmissionController::new(
        Arc::new(setup.services.deployments.pin().unwrap()),
        quotas.clone(),
        Arc::new(Load(setup.fixture.clock.clone())),
    );
    let scheduler = Arc::new(
        LocalScheduler::new(
            LocalSchedulerConfig {
                node: NodeId("signed-http-query".into()),
                queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 8)]),
                starvation_after: Duration::from_secs(1),
            },
            quotas.clone(),
        )
        .unwrap(),
    );
    (
        LocalActivationManager::with_services(
            LocalActivationManagerConfig::default(),
            LocalActivationDependencies {
                catalog: setup.services.deployments.clone(),
                admission,
                scheduler,
                artifacts: setup.services.artifacts.clone(),
                backend,
            },
            LocalActivationServices {
                clock: setup.fixture.clock.clone(),
                ..Default::default()
            },
        )
        .unwrap(),
        quotas,
    )
}

async fn request(address: std::net::SocketAddr, input: &str, token: &str) -> Vec<u8> {
    let mut socket = TcpStream::connect(address).await.unwrap();
    socket.write_all(format!("GET /query?input={input} HTTP/1.1\r\nHost: web.example.test\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n").as_bytes()).await.unwrap();
    let mut bytes = Vec::new();
    tokio::time::timeout(Duration::from_secs(10), socket.read_to_end(&mut bytes))
        .await
        .unwrap()
        .unwrap();
    bytes
}

mod refusal;
