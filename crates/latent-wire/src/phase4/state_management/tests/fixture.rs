use super::*;
use latent_artifacts::{
    ArtifactDescriptor, CapsuleArtifact, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, ManagedPublicationUpload, ReleaseActor,
    ReleaseActorKind, ReleaseMutationContext, ReleaseOperationPrecondition,
};
use latent_core::{
    ActivationBudget, ArtifactReference, BudgetProfile, ClockSample, EffectiveActivationBudget,
    HostMemoryReservation, InvocationPrincipal, Metadata, PrincipalKind, ResourceBudget,
    SystemActivationClock, TenantId,
};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_policy::capability::{GrantRestriction, MutationRequest, PolicyStoreLimits, RecordKind};
use latent_state::protected_store::ProtectedStoreConfig;
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::PermissionsExt,
    path::PathBuf,
    sync::atomic::{AtomicUsize, Ordering},
};

/// The fixture retains both its original host-memory budget assertions and
/// actual affine reservations on the one installed global recovery owner.
pub(super) struct Admission {
    pub budget: ActivationBudget,
    pub native: latent_core::native_capacity::NativeCapacityOwner,
    pub calls: AtomicUsize,
    pub fences: Arc<AtomicUsize>,
    pub reject_after: Arc<AtomicUsize>,
}
struct Reservation {
    _memory: HostMemoryReservation,
    response_bytes: usize,
    fences: Arc<AtomicUsize>,
    reject_after: Arc<AtomicUsize>,
    native: latent_core::native_capacity::NativeReservation,
}
impl StateManagementReservation for Reservation {
    fn uses_native_capacity(
        &self,
        owner: &latent_core::native_capacity::NativeCapacityOwner,
    ) -> bool {
        self.native.is_from_owner(owner)
    }
    fn reserved_response_bytes(&self) -> usize {
        self.response_bytes
    }
    fn with_live(&self, action: &mut dyn FnMut()) -> Result<(), PlatformError> {
        let previous = self.fences.fetch_add(1, Ordering::Relaxed);
        if previous >= self.reject_after.load(Ordering::Relaxed) {
            return Err(expired());
        }
        self.native.with_live(action).map_err(|_| expired())
    }
}
impl StateManagementAdmission for Admission {
    fn native_capacity(&self) -> latent_core::native_capacity::NativeCapacityOwner {
        self.native.clone()
    }
    fn reserve_recovery(
        &self,
        request_bytes: usize,
        work_bytes: usize,
        response_bytes: usize,
        deadline: Instant,
    ) -> Result<Arc<dyn StateManagementReservation>, PlatformError> {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let bytes = request_bytes
            .checked_add(work_bytes)
            .and_then(|value| value.checked_add(response_bytes))
            .ok_or_else(capacity)?;
        let memory = self
            .budget
            .reserve_host_memory(u64::try_from(bytes).unwrap())
            .map_err(|error| error.to_platform_error())?;
        let native = self
            .native
            .reserve(
                latent_core::native_capacity::NativeAdmissionClass::Recovery,
                latent_core::native_capacity::NativeReservationRequest {
                    request_bytes: request_bytes as u64,
                    work_bytes: work_bytes as u64,
                    response_bytes: response_bytes as u64,
                },
                deadline,
            )
            .map_err(|_| capacity())?;
        Ok(Arc::new(Reservation {
            native,
            _memory: memory,
            response_bytes,
            fences: Arc::clone(&self.fences),
            reject_after: Arc::clone(&self.reject_after),
        }))
    }
}
impl Admission {
    fn new(native: latent_core::native_capacity::NativeCapacityOwner) -> Self {
        let request = ResourceBudget {
            cpu_fuel: 1,
            memory_bytes: 64 * 1024 * 1024,
            wall_time_limit_millis: Some(30000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase4,
            &request,
            &request,
            &request,
            None,
            ClockSample::system_now(),
        )
        .unwrap();
        Self {
            budget: ActivationBudget::with_profile(grant, BudgetProfile::Phase4).unwrap(),
            native,
            calls: AtomicUsize::new(0),
            fences: Arc::new(AtomicUsize::new(0)),
            reject_after: Arc::new(AtomicUsize::new(usize::MAX)),
        }
    }
}
pub(super) struct Fixture {
    pub backend: StateManagementBackend,
    pub policy: Arc<PolicyStore>,
    pub store: Arc<ProtectedStoreOwner>,
    pub admission: Arc<Admission>,
    pub config: ProtectedStoreConfig,
    pub policy_revision: u64,
    pub document: Value,
    pub audit: Option<(latent_audit::AuditHandle, latent_audit::AuditWorker)>,
    _directory: tempfile::TempDir,
}
impl Fixture {
    pub async fn new(audited: bool) -> Self {
        Self::with_io(audited, None).await
    }
    pub async fn with_io(audited: bool, io: Option<latent_state::store_io::StoreIoLimits>) -> Self {
        let mut limits = latent_core::native_capacity::NativeCapacityLimits::default();
        // Existing memory schedules deliberately retain several independent
        // responses; this finite fixture partition matches their 64 MiB budget.
        limits.recovery.bytes = 64 * 1024 * 1024;
        let owner = latent_core::native_capacity::NativeCapacityOwner::new(limits).unwrap();
        Self::with_io_and_native(audited, io, owner).await
    }
    pub async fn with_io_and_native(
        audited: bool,
        io: Option<latent_state::store_io::StoreIoLimits>,
        native: latent_core::native_capacity::NativeCapacityOwner,
    ) -> Self {
        let directory = std::env::var_os("LATENT_STATE_TEST_ROOT")
            .map_or_else(std::env::temp_dir, PathBuf::from);
        let directory = tempfile::tempdir_in(directory).unwrap();
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700)).unwrap();
        let catalog = Arc::new(
            DirectoryArtifactRepository::open(
                directory.path().join("artifacts"),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap(),
        );
        let publication = publish(&catalog, "first").await;
        let component = publication.1;
        let publication = publication.0;
        let policy = Arc::new(
            PolicyStore::open(
                &directory.path().join("policy"),
                PolicyStoreLimits::default(),
                catalog.lifecycle_authority(),
            )
            .unwrap(),
        );
        let document = json!({"formatVersion":1,"tenant":"a","rules":[rule("alice", &publication, audited),rule("bob", &publication, audited)]});
        let updated = policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: "policy-create",
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        let policy_revision = updated.value().revision;
        drop(updated);
        let binding_doc = json!({"formatVersion":1,"tenant":"a","capability":latent_capabilities::namespace::STATE_CONTRACT,"providerProfile":"namespace-v1","configurationDigest":digest(),"configurationEpoch":1,"restriction":{"operations":[]}});
        policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::ProviderBinding,
                    id: "binding",
                    operation_id: "binding-create",
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&binding_doc).unwrap()),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        let mut config = ProtectedStoreConfig::bounded_linux(directory.path().join("store"));
        if let Some(io) = io {
            config.io = io;
        }
        fs::create_dir(&config.root).unwrap();
        fs::set_permissions(&config.root, fs::Permissions::from_mode(0o700)).unwrap();
        config.create_if_missing = true;
        let store = Arc::new(start(config.clone()).await);
        store.bind_native_capacity(&native).unwrap();
        let admission = Arc::new(Admission::new(native));
        let audit = audited.then(|| open_audit(directory.path()));
        let binding = binding(publication, component);
        let backend = StateManagementBackend::new(
            StateManagementServices {
                store: Arc::clone(&store),
                namespaces: Arc::new(NamespaceCatalog::new()),
                policy: Arc::clone(&policy),
                artifacts: catalog.clone(),
                authorization: Arc::new(crate::management::LocalManagementPolicy),
                admission: admission.clone(),
                clock: Arc::new(SystemActivationClock),
                audit: audit.as_ref().map(|(handle, _)| handle.clone()),
            },
            vec![binding],
        )
        .unwrap();
        Self {
            backend,
            policy,
            store,
            admission,
            config,
            policy_revision,
            document,
            audit,
            _directory: directory,
        }
    }
    pub fn target(&self) -> c::InspectNamespaceRequest {
        let binding = &self.backend.0.bindings[0];
        c::InspectNamespaceRequest {
            profile: Some(contract::current_profile()),
            namespace: Some(latent_rpc::transaction::v1::NamespaceSelector {
                tenant: "a".into(),
                namespace: "orders".into(),
                incarnation: "1".into(),
            }),
            authorization_publication: Some(c::PublicationRef {
                id: binding.publication.id.as_str().into(),
                tenant: "a".into(),
            }),
        }
    }
    pub fn mutation(
        &self,
        operation: &str,
        kind: c::NamespaceMutationKind,
        generation: u64,
    ) -> c::MutateNamespaceRequest {
        c::MutateNamespaceRequest {
            namespace: Some(self.target()),
            operation_id: operation.into(),
            mutation: kind as i32,
            expected_generation: Some(generation),
            configuration: matches!(
                kind,
                c::NamespaceMutationKind::Create | c::NamespaceMutationKind::Recreate
            )
            .then(|| c::NamespaceConfiguration {
                state_schema: schema(),
                quota: Some(response::quota(NamespaceQuota::default())),
            }),
        }
    }
    pub async fn create(&self) -> super::super::super::OwnedPhase4Response {
        self.backend
            .execute_state(
                context("alice"),
                self.mutation("create-original", c::NamespaceMutationKind::Create, 0)
                    .into(),
            )
            .await
            .unwrap()
    }
    pub fn update(&mut self, document: Option<&Value>, operation: &str) {
        let bytes = document.map(|value| serde_json::to_vec(value).unwrap());
        let receipt = self
            .policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind: RecordKind::Policy,
                    id: "state",
                    operation_id: operation,
                    expected_revision: self.policy_revision,
                    document: bytes.as_deref(),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
        self.policy_revision = receipt.value().revision;
    }
    pub async fn finish(&mut self) {
        self.store.close();
        let report = tokio::time::timeout(
            Duration::from_secs(5),
            self.store
                .drain_async(deadline(), std::future::pending())
                .unwrap(),
        )
        .await
        .unwrap();
        assert!(report.clean);
        assert_eq!(report.snapshot.physical_owners, 0);
        if let Some((handle, worker)) = &mut self.audit {
            handle.close();
            assert!(worker.join_until(deadline()).unwrap());
        }
        assert_eq!(self.admission.budget.outstanding_reservations(), 0);
    }
}
fn open_audit(path: &std::path::Path) -> (latent_audit::AuditHandle, latent_audit::AuditWorker) {
    latent_audit::DirectoryPhase2AuditJournal::open(
        path.join("audit"),
        latent_audit::AuditLimits::default(),
    )
    .unwrap()
}
pub(super) fn binding(
    publication: PublicationRef,
    component: ReleaseDigest,
) -> StateManagementBinding {
    StateManagementBinding {
        publication,
        component,
        service: ServiceId("a/echo".into()),
        namespace: StateNamespaceId("orders".into()),
        incarnation: 1,
        state_schema: schema(),
        result_policy: "visibility-v1".into(),
        maximum_quota: NamespaceQuota::default(),
        state: PolicyCallBinding {
            policies: vec!["state".into()],
            binding: "binding".into(),
            profile: "namespace-v1".into(),
            configuration_digest: digest(),
            configuration_epoch: 1,
            operations: operations(),
            deployment: restriction(),
            provider_configuration: restriction(),
        },
    }
}
fn restriction() -> GrantRestriction {
    GrantRestriction::parse(
        br#"{"operations":[]}"#,
        latent_capabilities::namespace::STATE_CONTRACT,
    )
    .unwrap()
}
pub(super) async fn start(config: ProtectedStoreConfig) -> ProtectedStoreOwner {
    ProtectedStoreOwner::start_validated(config, 0, |key, bytes| {
        NamespaceCatalog::validate_row(key, bytes).map_err(inspection::native_namespace)
    })
    .unwrap()
    .await
    .unwrap()
}
pub(super) fn context(subject: &str) -> AuthenticatedInvocationContext {
    AuthenticatedInvocationContext::new(InvocationPrincipal {
        subject: subject.into(),
        kind: PrincipalKind::Administrator,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: Metadata::new(),
    })
}
pub(super) fn deadline() -> Instant {
    Instant::now() + Duration::from_secs(10)
}
pub(super) fn schema() -> String {
    format!("sha256:{}", "1".repeat(64))
}
fn digest() -> String {
    format!("sha256:{}", "2".repeat(64))
}
fn operations() -> Vec<String> {
    [
        "namespace-create",
        "namespace-quiesce",
        "namespace-retire",
        "namespace-destroy",
        "namespace-recreate",
        "namespace-inspect",
    ]
    .into_iter()
    .map(str::to_owned)
    .collect()
}
fn rule(subject: &str, publication: &PublicationRef, audited: bool) -> Value {
    let caller = latent_capabilities::namespace::CallerScope::derive(
        context(subject).principal(),
        &latent_capabilities::namespace::RecoverySelection::OriginalCaller,
    )
    .unwrap();
    json!({"id":subject,"effect":"allow","principals":[{"kind":"administrator","subject":subject}],"services":["a/echo"],"publications":[publication.id.as_str()],"capability":latent_capabilities::namespace::STATE_CONTRACT,"operations":operations(),"resources":{"kind":"state","scopes":[{"namespace":"orders","incarnation":1,"entity":null,"recoveryKind":"original-caller","recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},"requireAudit":audited,"ceiling":{"operations":8,"inputBytes":contract::MAX_REQUEST_BYTES,"outputBytes":contract::MAX_RESPONSE_BYTES,"wallTimeMillis":30000}})
}
async fn publish(
    catalog: &DirectoryArtifactRepository,
    label: &str,
) -> (PublicationRef, ReleaseDigest) {
    let component = b"\0asm\x0d\0\x01\0".to_vec();
    let digest = latent_artifacts::content_digest(&component);
    let mut value: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../latent-manifest/tests/fixtures/valid-capsule-v1alpha1.json"
    )))
    .unwrap();
    value["component"]["digest"] = digest.0.clone().into();
    value["metadata"]["tenant"] = "a".into();
    value["metadata"]["name"] = "a/echo".into();
    value["component"]["world"] = "a:echo/service@0.1.0".into();
    value["exports"] = json!(["a:echo/api@0.1.0"]);
    let manifest = JsonManifestCodec::default()
        .decode_capsule(&serde_json::to_vec(&value).unwrap())
        .unwrap();
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://tests/{label}")),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".into(),
            size_bytes: component.len() as u64,
            publisher: None,
            layers: vec![],
            annotations: Metadata::new(),
        },
        manifest,
        contracts: vec![],
        component_bytes: component,
    };
    let receipt = catalog
        .publish_managed(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("a".into())),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Administrator,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: label.into(),
                    expected_generation: 0,
                }),
            },
            ManagedPublicationUpload::Local(artifact),
            &mut |_| Ok(()),
        )
        .await
        .unwrap();
    (receipt.publication, digest)
}
