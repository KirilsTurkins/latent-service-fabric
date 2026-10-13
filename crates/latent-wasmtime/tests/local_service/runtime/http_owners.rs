//! Existing bounded HTTP provider installed into the ordinary signed node.
use latent_capabilities::broker::{
    io::{IoLimits, IoRuntime, IoSnapshot},
    pools::{ProviderPoolLimits, ProviderPools},
    streaming_http::STREAMING_HTTP_CAPABILITY,
    ActivationCapabilityBroker, ActivationCapabilityRuntime, CapabilityBrokerLimits,
};
use latent_control_store::bindings::{BindingDefinition, ConfiguredBindingProvider};
use latent_core::{CapabilityId, PolicyId, PublicationId, ServiceId, TenantId};
use latent_http::{
    HttpAddressPolicy, HttpDestination, HttpLimits, HttpProviderConfig, HttpResolution,
    HttpStreamLimits, StreamingHttpProvider, STREAMING_HTTP_PROVIDER_PROFILE,
};
use latent_manifest::{BindingMode, CapabilityGrantSpec, JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{MutationRequest, PolicyStore, RecordKind};
use serde_json::json;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

const POLICY: &str = "fetch-http-policy";
const BINDING: &str = "fetch-http-installed";
const SERVICE: &str = "fetch-http-provider";
const OPERATIONS: [&str; 1] = ["open"];

pub struct Configuration {
    pub port: u16,
    pub permit: bool,
}

pub fn grants() -> Vec<CapabilityGrantSpec> {
    vec![CapabilityGrantSpec::new(
        CapabilityId(STREAMING_HTTP_CAPABILITY.into()),
        PolicyId(POLICY.into()),
    )]
}

pub struct Owners {
    provider: StreamingHttpProvider,
    pub pools: Arc<ProviderPools>,
    pub io: Arc<IoRuntime>,
}

impl Owners {
    pub fn install(
        broker: &Arc<ActivationCapabilityBroker>,
        policies: &PolicyStore,
        tenant: &TenantId,
        caller: &ServiceId,
        publication: &PublicationId,
        configuration: &Configuration,
    ) -> Self {
        let io = Arc::new(IoRuntime::new(IoLimits::default()).unwrap());
        let pools = Arc::new(
            ProviderPools::new(
                broker.clone(),
                io.clone(),
                tokio::runtime::Handle::current(),
                ProviderPoolLimits::default(),
            )
            .unwrap(),
        );
        let provider = StreamingHttpProvider::install(
            pools.clone(),
            SERVICE,
            1,
            0,
            HttpProviderConfig {
                format_version: 1,
                limits: HttpLimits::default(),
                public_roots: false,
                extra_roots: vec![],
                destinations: vec![HttpDestination {
                    origin: latent_policy::capability::HttpOrigin {
                        scheme: "http".into(),
                        host: "localhost".into(),
                        port: configuration.port,
                    },
                    addresses: HttpAddressPolicy {
                        networks: vec!["127.0.0.0/8".parse().unwrap()],
                        special_addresses: vec!["127.0.0.1".parse().unwrap()],
                    },
                    resolution: HttpResolution::Static {
                        addresses: vec!["127.0.0.1".parse().unwrap()],
                    },
                    allowed_request_headers: vec!["x-fetch-control".into()],
                    redirect_destinations: vec![],
                }],
            },
            HttpStreamLimits::default(),
            &[],
        )
        .unwrap();
        let reference = provider.reference();
        // A streaming operation authorizes its inline metadata window as well
        // as transfer bytes. Retain the existing broker/provider limits.
        let broker_limits = CapabilityBrokerLimits::default();
        let input_allowance = broker_limits.maximum_input_bytes as u64
            + HttpStreamLimits::default().maximum_input_bytes;
        let output_allowance = broker_limits.maximum_output_bytes as u64
            + HttpStreamLimits::default().maximum_output_bytes;
        for (id, kind, document) in [
            (
                POLICY,
                RecordKind::Policy,
                json!({"formatVersion":1,"tenant":tenant.0,"rules":[{
                    "id":"fetch", "effect":if configuration.permit {"allow"}else{"deny"},
                    "principals":[{"kind":"user","subject":"alice"}],"services":[caller.0],
                    "publications":[publication.as_str()],"capability":STREAMING_HTTP_CAPABILITY,
                    "operations":OPERATIONS,"resources":{"kind":"http","origins":[{"scheme":"http","host":"localhost","port":configuration.port}],
                        "methods":["GET","POST"],"paths":["/allowed"],"pathPrefixes":[]},
                    "requireAudit":false,"ceiling":{"operations":8,"inputBytes":input_allowance,"outputBytes":output_allowance,"wallTimeMillis":120_000}
                }]}),
            ),
            (
                BINDING,
                RecordKind::ProviderBinding,
                json!({"formatVersion":1,"tenant":tenant.0,
                "capability":STREAMING_HTTP_CAPABILITY,"providerProfile":STREAMING_HTTP_PROVIDER_PROFILE,
                "configurationDigest":reference.configuration_digest(),"configurationEpoch":1,"restriction":{"operations":[]}}),
            ),
        ] {
            let bytes = serde_json::to_vec(&document).unwrap();
            policies
                .mutate(
                    MutationRequest {
                        tenant: &tenant.0,
                        actor: "operator",
                        id,
                        kind,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&bytes),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
        Self {
            provider,
            pools,
            io,
        }
    }

    pub fn definition(tenant: &TenantId, caller: &ServiceId) -> BindingDefinition {
        let document = json!({"apiVersion":latent_manifest::MANIFEST_API_VERSION,"kind":"Binding",
            "metadata":{"name":"fetch-http-caller","tenant":tenant.0},
            "spec":{"consumer":{"service":caller.0,"contract":STREAMING_HTTP_CAPABILITY},
                "provider":{"service":SERVICE,"contract":STREAMING_HTTP_CAPABILITY},"mode":"host"}});
        BindingDefinition {
            manifest: JsonManifestCodec::default()
                .decode_binding(&serde_json::to_vec(&document).unwrap())
                .unwrap(),
            provider_binding_id: BINDING.into(),
            allowed_modes: vec![BindingMode::Host],
            restriction_json: br#"{"operations":[]}"#.to_vec(),
        }
    }
    pub fn provider(&self, tenant: &TenantId) -> ConfiguredBindingProvider {
        ConfiguredBindingProvider {
            tenant: tenant.clone(),
            service: ServiceId(SERVICE.into()),
            reference: self.provider.reference(),
            local_deployment: None,
        }
    }
    pub fn install_runtime(&self, runtime: &ActivationCapabilityRuntime) {
        runtime
            .install_streaming_http(Arc::new(self.provider.clone()))
            .unwrap();
    }
    pub fn idle(&self) {
        assert_eq!(self.io.snapshot(), IoSnapshot::default());
        let pools = self.pools.snapshot().unwrap();
        assert_eq!(pools.connections, 0);
        assert_eq!(pools.running_requests, 0);
    }
    pub async fn shutdown(&self) {
        self.idle();
        assert!(self
            .pools
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap()
            .is_clean());
    }
}
