use crate::web::{CheckedWebLayout, WebBackendProfile, WEB_CONTRACT, WEB_HTTP_CONTRACT};
use crate::{
    preparation_metadata_fingerprint, ArtifactDescriptor, ContractDescriptor, FieldDescriptor,
    FunctionDescriptor, InterfaceDescriptor, PreparationMetadataFingerprint, PublicationRef,
    ValueType,
};
use latent_core::{
    ArtifactReference, ContractId, FunctionId, InterfaceId, Metadata, PlatformError, ReleaseDigest,
    ResourceBudget,
};
use latent_manifest::{
    CapsuleManifest, ContractExport, ContractImport, ExecutionBackendKind, ExecutionRequirements,
    ObjectMetadata, RendererRequirement, RuntimeRequirements, StateModel, ThreadingModel,
    MANIFEST_API_VERSION, PHASE1_FABRIC_VERSION,
};

pub(super) const METADATA_BYTES: usize = 16 * 1024;

pub(in crate::local_repository::web) struct Projection {
    pub(super) descriptor: ArtifactDescriptor,
    pub(super) manifest: CapsuleManifest,
    pub(super) contracts: Vec<ContractDescriptor>,
    pub(super) fingerprint: PreparationMetadataFingerprint,
}

impl Projection {
    pub(in crate::local_repository::web) fn new(
        publication: &PublicationRef,
        layout: &CheckedWebLayout,
    ) -> Result<Option<std::sync::Arc<Self>>, PlatformError> {
        let Some(renderer) = &layout.manifest().renderer else {
            return Ok(None);
        };
        let tenant = publication.scope.tenant().ok_or_else(super::denied)?;
        let component = ReleaseDigest(renderer.digest.clone());
        let descriptor = ArtifactDescriptor {
            reference: ArtifactReference(format!("web-execution:{}", publication.id)),
            release_digest: component.clone(),
            media_type: crate::package::COMPONENT_MEDIA_TYPE.into(),
            size_bytes: renderer.size,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::from([
                ("latent.web.package".into(), layout.package().to_string()),
                (
                    "latent.web.manifest".into(),
                    layout.manifest_digest().to_string(),
                ),
                (
                    "latent.web.assets".into(),
                    layout.assets_digest().to_string(),
                ),
            ]),
        };
        let mut imports = vec![ContractImport {
            contract: ContractId("latent:context/context@0.1.0".into()),
            optional: false,
        }];
        let outbound_requests = match renderer.backend_profile {
            WebBackendProfile::None => 0,
            WebBackendProfile::ScopedHttpGetV1 => {
                imports.push(ContractImport {
                    contract: ContractId(WEB_HTTP_CONTRACT.into()),
                    optional: false,
                });
                1
            }
        };
        let manifest = CapsuleManifest {
            api_version: MANIFEST_API_VERSION.into(),
            metadata: ObjectMetadata {
                name: layout.name().into(),
                tenant: Some(tenant.clone()),
                namespace: None,
                labels: Metadata::new(),
                annotations: Metadata::new(),
            },
            semantic_version: layout.version().into(),
            component_digest: component,
            world: ContractId(renderer.backend_profile.world().into()),
            exports: vec![ContractExport {
                contract: ContractId(WEB_CONTRACT.into()),
            }],
            imports,
            execution: ExecutionRequirements {
                backend: ExecutionBackendKind::WasmComponent,
                threading: ThreadingModel::SingleThreaded,
                state_model: StateModel::Stateless,
                resource_budget_ceiling: ResourceBudget {
                    cpu_fuel: 2_000_000_000,
                    memory_bytes: 256 * 1024 * 1024,
                    wall_time_limit_millis: Some(5000),
                    child_calls: 0,
                    outbound_requests,
                    state_read_bytes: 0,
                    state_write_bytes: 0,
                    blob_read_bytes: 0,
                    blob_write_bytes: 0,
                    log_bytes: 0,
                    effect_count: 0,
                },
                host_call_depth_maximum: 1,
                component_call_depth_maximum: 1,
                snapshot_eligible: false,
                fusion_eligible: false,
            },
            minimum_fabric_version: PHASE1_FABRIC_VERSION.into(),
            runtime_requirements: RuntimeRequirements {
                renderer: Some(RendererRequirement {
                    profile: renderer.profile,
                    profile_digest: renderer.profile_digest.clone(),
                }),
                ..RuntimeRequirements::default()
            },
        };
        let contracts = vec![contract()];
        let fingerprint = preparation_metadata_fingerprint(
            &descriptor,
            &manifest,
            &contracts,
            METADATA_BYTES,
            8,
        )?;
        Ok(Some(std::sync::Arc::new(Self {
            descriptor,
            manifest,
            contracts,
            fingerprint,
        })))
    }

    pub(in crate::local_repository::web) fn retained_bytes(&self) -> usize {
        self.fingerprint.charged_bytes() + std::mem::size_of::<Self>() + 128
    }
}

fn contract() -> ContractDescriptor {
    let digest = crate::package::artifact_blob_digest(include_bytes!(
        "../../../../../../wit/platform/web/package.wit"
    ))
    .to_string();
    ContractDescriptor {
        id: ContractId(WEB_CONTRACT.into()),
        package_name: "latent:web".into(),
        semantic_version: "0.1.0".into(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId(WEB_CONTRACT.into()),
            functions: vec![FunctionDescriptor {
                id: FunctionId("handle".into()),
                name: "handle".into(),
                asynchronous: true,
                parameters: vec![field("request")],
                results: vec![field("response")],
                documentation: None,
                attributes: Metadata::new(),
            }],
            documentation: None,
            digest: digest.clone(),
        }],
        dependencies: Vec::new(),
        digest,
    }
}

fn field(name: &str) -> FieldDescriptor {
    FieldDescriptor {
        name: name.into(),
        value_type: ValueType::Record(name.into()),
        documentation: None,
    }
}
