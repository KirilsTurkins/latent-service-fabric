//! Observe the real installed provider without synthesizing a denial or grant.
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::broker::{
    http::{HttpError, HttpInvocation, HttpRequest, OutboundHttpInvoker, HTTP_CAPABILITY},
    io::{IoLimits, IoRuntime, IoSnapshot},
    pools::{ProviderPoolLimits, ProviderPools},
    ActivationCapabilityBroker, ActivationCapabilityRuntime, CapabilitySession,
};
use latent_control_store::bindings::{BindingDefinition, ConfiguredBindingProvider};
use latent_core::{CapabilityId, PolicyId, ServiceId, TenantId};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProvider, HttpProviderConfig,
    HttpResolution,
};
use latent_manifest::{BindingMode, CapabilityGrantSpec, JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{HttpOrigin, MutationRequest, PolicyStore, RecordKind};
use serde_json::json;
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

const POLICY: &str = "native-guest-http-policy";
const BINDING: &str = "native-guest-http-binding";
const PROVIDER: &str = "native-guest-http";

struct CountedHttp {
    provider: HttpProvider,
    starts: AtomicUsize,
}
impl OutboundHttpInvoker for CountedHttp {
    fn start(
        &self,
        session: &CapabilitySession,
        request: HttpRequest,
    ) -> Result<HttpInvocation, HttpError> {
        // Count even a synchronous failure in the real provider. Zero therefore
        // proves the transaction gate ran before any provider or network owner.
        self.starts.fetch_add(1, Ordering::AcqRel);
        self.provider.start(session, request)
    }
}

pub struct HttpOwner {
    provider: Arc<CountedHttp>,
    pools: Arc<ProviderPools>,
    io: Arc<IoRuntime>,
}
impl HttpOwner {
    pub fn new(
        broker: &Arc<ActivationCapabilityBroker>,
        policies: &PolicyStore,
        publication: &ReleaseUseEligibility,
        service: &str,
    ) -> Self {
        let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
        let pools = Arc::new(
            ProviderPools::new(
                broker.clone(),
                io.clone(),
                tokio::runtime::Handle::current(),
                ProviderPoolLimits {
                    maximum_configurations: 2,
                    maximum_clients: 2,
                    maximum_clients_per_provider: 2,
                    maximum_connections: 2,
                    maximum_connections_per_client: 2,
                    maximum_idle_connections: 2,
                    maximum_pending_requests: 2,
                    maximum_running_requests: 2,
                    maximum_requests_per_tenant: 2,
                    maximum_requests_per_provider: 2,
                    maximum_running_per_tenant: 2,
                    maximum_running_per_provider: 2,
                    maximum_workers: 2,
                    maximum_cleanup_jobs: 2,
                    maximum_metadata_bytes: 256 * 1024,
                    ..Default::default()
                },
            )
            .unwrap(),
        );
        let origin = HttpOrigin {
            scheme: "http".into(),
            host: "127.0.0.1".into(),
            port: 1,
        };
        let provider = HttpProvider::install(
            pools.clone(),
            PROVIDER,
            1,
            0,
            HttpProviderConfig {
                format_version: 1,
                limits: HttpLimits::default(),
                public_roots: false,
                extra_roots: vec![],
                destinations: vec![HttpDestination {
                    origin: origin.clone(),
                    addresses: HttpAddressPolicy {
                        networks: vec!["127.0.0.0/8".parse().unwrap()],
                        special_addresses: vec!["127.0.0.1".parse().unwrap()],
                    },
                    resolution: HttpResolution::Static {
                        addresses: vec!["127.0.0.1".parse().unwrap()],
                    },
                    allowed_request_headers: vec![],
                    redirect_destinations: vec![],
                }],
            },
            &[],
        )
        .unwrap();
        let tenant = publication.tenant().unwrap().0.as_str();
        for (kind, id, value) in [
            (
                RecordKind::Policy,
                POLICY,
                json!({"formatVersion":1,"tenant":tenant,"rules":[{
                    "id":"exact-http","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
                    "services":[service],"publications":[publication.publication().as_str()],
                    "capability":HTTP_CAPABILITY,"operations":["send"],
                    "resources":{"kind":"http","origins":[origin],"methods":["GET"],
                        "paths":["/forbidden-transaction-effect"],"pathPrefixes":[]},
                    "ceiling":{"operations":1,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":5000}
                }]}),
            ),
            (
                RecordKind::ProviderBinding,
                BINDING,
                json!({"formatVersion":1,"tenant":tenant,"capability":HTTP_CAPABILITY,
                    "providerProfile":provider.reference().profile(),
                    "configurationDigest":provider.reference().configuration_digest(),
                    "configurationEpoch":1,"restriction":{"operations":["send"]}}),
            ),
        ] {
            policies
                .mutate(
                    MutationRequest {
                        tenant,
                        actor: "native-guest-test-operator",
                        kind,
                        id,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&serde_json::to_vec(&value).unwrap()),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
        Self {
            provider: Arc::new(CountedHttp {
                provider,
                starts: AtomicUsize::new(0),
            }),
            pools,
            io,
        }
    }

    pub fn grant(&self) -> CapabilityGrantSpec {
        CapabilityGrantSpec::new(
            CapabilityId(HTTP_CAPABILITY.into()),
            PolicyId(POLICY.into()),
        )
    }
    pub fn definition(&self, tenant: &TenantId, service: &str) -> BindingDefinition {
        let document = json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,"kind":"Binding",
            "metadata":{"name":BINDING,"tenant":tenant.0.as_str()},
            "spec":{"consumer":{"service":service,"contract":HTTP_CAPABILITY},
                "provider":{"service":PROVIDER,"contract":HTTP_CAPABILITY},"mode":"host"}});
        BindingDefinition {
            manifest: JsonManifestCodec::default()
                .decode_binding(&serde_json::to_vec(&document).unwrap())
                .unwrap(),
            provider_binding_id: BINDING.into(),
            allowed_modes: vec![BindingMode::Host],
            restriction_json: br#"{"operations":["send"]}"#.to_vec(),
        }
    }
    pub fn configured(&self, tenant: &TenantId) -> ConfiguredBindingProvider {
        ConfiguredBindingProvider {
            tenant: tenant.clone(),
            service: ServiceId(PROVIDER.into()),
            reference: self.provider.provider.reference(),
            local_deployment: None,
        }
    }
    pub fn install(&self, runtime: &ActivationCapabilityRuntime) {
        runtime.install_http(self.provider.clone()).unwrap();
    }
    pub fn assert_not_started(&self) {
        assert_eq!(self.provider.starts.load(Ordering::Acquire), 0);
        assert_eq!(self.io.snapshot(), IoSnapshot::default());
        let pools = self.pools.snapshot().unwrap();
        assert_eq!(pools.configurations, 1, "real provider remains installed");
        assert_eq!(pools.clients, 0);
        assert_eq!(pools.connections, 0);
        assert_eq!(pools.pending_requests, 0);
        assert_eq!(pools.running_requests, 0);
        assert_eq!(pools.workers, 0);
        assert_eq!(pools.cleanup_jobs, 0);
        assert_eq!(pools.failed_cleanup, 0);
    }
    pub async fn shutdown(self, deadline: Instant) {
        self.assert_not_started();
        assert!(self.pools.shutdown(deadline).await.unwrap().is_clean());
        assert_eq!(self.io.snapshot(), IoSnapshot::default());
    }
}
