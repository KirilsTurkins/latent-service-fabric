use super::*;
use crate::broker::{CapabilityBindingSpec, ProviderConfiguration};
use latent_artifacts::ArtifactRepository;
use latent_policy::capability::{MutationRequest, RecordKind};
use serde_json::json;

pub struct Setup {
    pub fixture: Fixture,
    pub pools: ProviderPools,
    pub provider: InstalledProvider,
    pub client: Arc<ProviderClient<TcpStream>>,
}
impl Setup {
    pub fn new(limits: ProviderPoolLimits) -> Self {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let pools = ProviderPools::new(
            fixture.broker.clone(),
            Arc::new(IoRuntime::new(IoLimits::default()).unwrap()),
            tokio::runtime::Handle::current(),
            limits,
        )
        .unwrap();
        let provider = install(&pools, "secrets", 1, 0, b"test-secret-old");
        let client = pools.client(&provider, 0).unwrap();
        Self {
            fixture,
            pools,
            provider,
            client,
        }
    }
    pub fn session(&self, id: &str) -> (CapabilitySession, Control) {
        self.session_for(&self.provider, "a", id)
    }
    pub fn session_for(
        &self,
        provider: &InstalledProvider,
        tenant: &str,
        id: &str,
    ) -> (CapabilitySession, Control) {
        let (mut request, control) = self.fixture.request(id);
        let publication = if tenant == "a" {
            self.fixture.publication.clone()
        } else {
            let receipt = publish(&self.fixture.catalog, tenant, tenant);
            let publication = self
                .fixture
                .catalog
                .execution_eligibility_selected(
                    &receipt.operation.record.as_ref().unwrap().release,
                    Some(&receipt.publication.id),
                )
                .unwrap()
                .unwrap();
            let digest = format!("sha256:{}", "2".repeat(64));
            let policy = json!({"formatVersion":1,"tenant":tenant,"rules":[{
                "id":"allow","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
                "services":["echo"],"publications":[publication.publication().as_str()],"capability":CAP,
                "operations":["read"],"resources":{"kind":"secrets","references":["test-key"]},
                "ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":5000}}]});
            let binding = json!({"formatVersion":1,"tenant":tenant,"capability":CAP,"providerProfile":"local-secrets-v1",
                "configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}});
            for (name, kind, value) in [
                ("p", RecordKind::Policy, policy),
                ("binding", RecordKind::ProviderBinding, binding),
            ] {
                let bytes = serde_json::to_vec(&value).unwrap();
                self.fixture
                    .policies
                    .mutate(
                        MutationRequest {
                            tenant,
                            actor: "operator",
                            id: name,
                            kind,
                            operation_id: name,
                            expected_revision: 0,
                            document: Some(&bytes),
                        },
                        Instant::now() + Duration::from_secs(1),
                        |_| Ok(()),
                    )
                    .unwrap();
            }
            publication
        };
        let mut revision = self.fixture.revision.clone();
        revision.target.tenant = latent_core::TenantId(tenant.into());
        revision.target.contract = latent_core::ContractId(format!("{tenant}:echo/api@0.1.0"));
        revision.publication = Some(publication.publication().clone());
        revision.release = publication.release().clone();
        request.activation.principal.tenant = Some(revision.target.tenant.clone());
        request.activation.target = revision.target.clone();
        request.activation.resolved_revision = Some(revision.clone());
        request
            .prepared
            .key
            .publication
            .clone_from(&revision.publication);
        request.prepared.key.release = revision.release.clone();
        let plan = self
            .fixture
            .broker
            .compile_plan(
                &revision,
                &[CapabilityBindingSpec {
                    definition_digest: None,
                    provider: &provider.reference(),
                    imported_operations: &["read".into()],
                    policy_ids: &["p".into()],
                    provider_binding_id: "binding",
                    deployment_restriction_json: br#"{"operations":[]}"#,
                }],
                &publication,
                Instant::now() + Duration::from_secs(1),
            )
            .unwrap();
        let session = self
            .fixture
            .broker
            .open_session(plan, &request, &control, &publication)
            .unwrap();
        (session, control)
    }
    pub async fn call(&self, session: &CapabilitySession) -> PoolCall {
        start(&self.pools, &self.client, session).await
    }
}
pub fn install(
    pools: &ProviderPools,
    id: &str,
    epoch: u64,
    expected: u64,
    credentials: &[u8],
) -> InstalledProvider {
    pools
        .install(
            ProviderSetup {
                logical_id: id,
                credentials,
                authority: ProviderConfiguration {
                    capability: CAP,
                    profile: "local-secrets-v1",
                    configuration_digest: &format!("sha256:{}", "2".repeat(64)),
                    configuration_epoch: epoch,
                    restriction_json: br#"{"operations":[]}"#,
                    minimum_call_charges: &[],
                },
            },
            expected,
        )
        .unwrap()
}
pub fn dispatch(session: &CapabilitySession) -> ProviderCall {
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch(
            handle,
            "read",
            resource(),
            &[],
            CapabilityCallCost::new(128),
            |call| call,
        )
        .unwrap();
    session.close_handle(handle).unwrap();
    call
}
pub async fn start<T: Send + 'static>(
    pools: &ProviderPools,
    client: &Arc<ProviderClient<T>>,
    session: &CapabilitySession,
) -> PoolCall {
    pools
        .admit(client, session)
        .unwrap()
        .wait()
        .await
        .unwrap()
        .start(dispatch(session))
        .unwrap()
}
pub fn connect(
    client: &Arc<ProviderClient<TcpStream>>,
    call: &PoolCall,
) -> (PooledConnection<TcpStream>, TcpStream) {
    let reserved = client.reserve_connection(call).unwrap();
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (peer, _) = listener.accept().unwrap();
    peer.set_read_timeout(Some(Duration::from_millis(100)))
        .unwrap();
    (reserved.connected(stream).unwrap(), peer)
}
pub fn single() -> ProviderPoolLimits {
    ProviderPoolLimits {
        maximum_running_requests: 1,
        maximum_running_per_tenant: 1,
        maximum_running_per_provider: 1,
        ..ProviderPoolLimits::default()
    }
}
pub async fn clean(pools: &ProviderPools) {
    let report = pools
        .shutdown(Instant::now() + Duration::from_secs(2))
        .await
        .unwrap();
    assert!(report.closed);
    assert!(report.is_clean());
    assert_eq!(report.connections, 0);
    assert_eq!(report.pending_requests, 0);
    assert_eq!(report.running_requests, 0);
    assert_eq!(report.workers, 0);
    assert_eq!(report.cleanup_jobs, 0);
    assert_eq!(report.control_owners, 0);
}
