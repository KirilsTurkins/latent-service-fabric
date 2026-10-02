//! Actual protected startup ordering, including failed continuity recovery.
use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_core::{ActivationClock, ClockSample};
use latent_effects::{dispatch_store::DispatchCatalog, runtime::EffectTimeSource};
use latent_policy::supply_chain::{SupplyChainClock, SupplyChainPolicy};
use latent_signing::{BuilderPolicy, ProvenanceLimits, PublisherPolicy, SignatureLimits};
use latent_state::{embedded::EmbeddedStore, store_identity::ExternalCheckpoint};
use serde_json::json;
use std::{os::unix::fs::PermissionsExt, sync::Mutex, time::Duration};

pub(in crate::standalone::state) struct Clock(Mutex<ClockSample>);
impl Clock {
    pub(in crate::standalone::state) fn advance_to(&self, deadline: Instant) {
        let mut sample = self.0.lock().unwrap();
        let elapsed = deadline.duration_since(sample.monotonic()).as_millis();
        let millis = u64::try_from(elapsed).unwrap();
        *sample = ClockSample::new(sample.unix_millis().checked_add(millis).unwrap(), deadline);
    }
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().unwrap()
    }
    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}
impl SupplyChainClock for Clock {
    fn now(&self) -> Result<u64, PlatformError> {
        Ok(self.sample().unix_millis() / 1000)
    }
}

pub(in crate::standalone::state) struct Fixture {
    pub(in crate::standalone::state) settings: StateSettings,
    pub(in crate::standalone::state) clock: Arc<Clock>,
    pub(in crate::standalone::state) authority: Arc<SupplyChainAuthority>,
    _root: tempfile::TempDir,
}
impl Fixture {
    pub(in crate::standalone::state) fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let mut settings = crate::standalone::state::bootstrap::tests::settings(root.path());
        settings.startup_timeout = Duration::from_secs(20);
        for path in [&settings.store.root, &settings.checkpoint_root] {
            std::fs::create_dir(path).unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let clock = Arc::new(Clock(Mutex::new(ClockSample::new(
            1_100_000,
            Instant::now(),
        ))));
        let authority = Arc::new(
            SupplyChainAuthority::open(
                &root.path().join("actual-authority"),
                policy(),
                clock.clone(),
                5,
            )
            .unwrap(),
        );
        Self {
            settings,
            clock,
            authority,
            _root: root,
        }
    }
    pub(in crate::standalone::state) fn bootstrap(&self) -> StateBootstrap {
        let clock: Arc<dyn ActivationClock> = self.clock.clone();
        StateBootstrap::new_state(&self.settings, &clock).unwrap()
    }
    pub(in crate::standalone::state) fn checkpoint(&self) -> std::path::PathBuf {
        self.settings
            .checkpoint_root
            .join("transaction-checkpoint.v1")
    }
    pub(in crate::standalone::state) fn root(&self) -> &std::path::Path {
        self._root.path()
    }
    fn persisted_dispatch(&self) -> Option<(u64, u64)> {
        // Test-only inspection AFTER positive physical engine retirement.
        // Production startup uses the borrowed coherent worker projection.
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(
                self.settings
                    .store
                    .root
                    .join(&self.settings.store.file_name),
            )
            .unwrap();
        let engine = EmbeddedStore::open_file(file, self.settings.store.engine).unwrap();
        DispatchCatalog::checkpoint(&engine.snapshot().unwrap()).unwrap()
    }
}

fn policy() -> SupplyChainPolicy {
    let publisher_key = latent_signing::generate_signing_key().unwrap();
    let builder_key = latent_signing::generate_signing_key().unwrap();
    let publisher = json!({"formatVersion":1,"scope":"kernel-tests","generation":1,"validFrom":900,"validUntil":3000,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"publisherId":"publisher-a","publicKey":STANDARD.encode(publisher_key.public_key()),"validFrom":900,"validUntil":3000}]});
    let builder = json!({"formatVersion":1,"scope":"kernel-tests","generation":1,"validFrom":900,"validUntil":3000,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,
        "keys":[{"builderId":"builder-a","publicKey":STANDARD.encode(builder_key.public_key()),"validFrom":900,"validUntil":3000}],
        "requirements":[{"builderId":"builder-a","buildType":latent_signing::PROVENANCE_BUILD_TYPE,"sourceRepository":"https://example.com/source","requireReproducible":false}]});
    let publisher_digest = PublisherPolicy::from_json(
        &serde_json::to_vec(&publisher).unwrap(),
        SignatureLimits::default(),
    )
    .unwrap()
    .digest()
    .to_string();
    let builder_digest = BuilderPolicy::from_json(
        &serde_json::to_vec(&builder).unwrap(),
        ProvenanceLimits::default(),
    )
    .unwrap()
    .digest()
    .to_string();
    SupplyChainPolicy::from_json(&serde_json::to_vec(&json!({"formatVersion":1,"generation":1,"scope":"kernel-tests","validFrom":900,"validUntil":3000,
        "tenants":[{"tenant":"kernel-tests","publishers":["publisher-a"]}],"publisher":publisher,"builder":builder,
        "publisherRevocations":{"formatVersion":1,"scope":"kernel-tests","policyDigest":publisher_digest,"generation":1,"validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":"kernel-tests","policyDigest":builder_digest,"generation":1,"validFrom":900,"validUntil":3000,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}})).unwrap()).unwrap()
}

#[tokio::test]
async fn fresh_protected_kernel_creates_checkpoint_before_one_paused_same_owner_dispatcher() {
    let fixture = Fixture::new();
    let bootstrap = fixture.bootstrap();
    let original = bootstrap.native.clone();
    let early = bootstrap.authority.clone();
    let adapter_clock = AdapterClock::default();
    let (kernel, mut effects) = StateKernel::start(
        bootstrap,
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &adapter_clock,
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    assert!(kernel.native.is_same_owner(&original));
    assert!(kernel.store.uses_native_capacity(&original));
    assert!(kernel.namespaces.uses_native_capacity(&original));
    let source = effects.command_admission_source();
    assert!(source.uses_store(&kernel.store));
    assert!(source.uses_native_capacity(&original));
    assert!(source.uses_effect_authority(&early));
    let snapshot = effects.snapshot().unwrap();
    assert!(snapshot.paused && !snapshot.admission_closed);
    assert_eq!(snapshot.claims, 0);
    let mode = std::fs::read(
        fixture
            .settings
            .store
            .root
            .join(latent_state::protected_store::STATE_MODE_FILE),
    )
    .unwrap();
    assert!(mode.starts_with(b"LSM\0\x01"));
    assert_eq!(
        latent_state::store_identity::StoreIdentity::decode(&mode[5..]).unwrap(),
        fixture.settings.store_identity
    );
    let checkpoint =
        ExternalCheckpoint::decode(&std::fs::read(fixture.checkpoint()).unwrap()).unwrap();
    assert_eq!(checkpoint.identity(), &fixture.settings.store_identity);
    assert!(checkpoint.dispatch_owner_epoch() > 0);
    assert_eq!(adapter_clock.observe(), kernel.clock.observe());
    // The returned clock binds once. A second owner/clock cannot replace it.
    assert!(adapter_clock.bind(Arc::clone(&kernel.clock)).is_err());
    let deadline = fixture.clock.monotonic_now() + Duration::from_secs(20);
    let report = effects.shutdown(deadline).await.unwrap();
    assert!(report.clean && report.physically_retired);
    drop(source);
    drop(effects);
    let report = kernel.shutdown(deadline).await.unwrap();
    assert!(report.clean);
    assert!(report.store.snapshot.physically_retired());
    assert!(report.native.snapshot.physically_retired());
    assert_eq!(report.namespace_owners, 0);
}

#[tokio::test]
async fn missing_persisted_state_mode_refuses_restart_before_any_dispatch_epoch_write() {
    let fixture = Fixture::new();
    let (kernel, mut effects) = StateKernel::start(
        fixture.bootstrap(),
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &AdapterClock::default(),
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    let deadline = fixture.clock.monotonic_now() + Duration::from_secs(20);
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    assert!(kernel.shutdown(deadline).await.unwrap().clean);
    let checkpoint = std::fs::read(fixture.checkpoint()).unwrap();
    let dispatch = fixture.persisted_dispatch();
    let mode = fixture
        .settings
        .store
        .root
        .join(latent_state::protected_store::STATE_MODE_FILE);
    std::fs::remove_file(&mode).unwrap();
    let failure = StateKernel::start(
        fixture.bootstrap(),
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &AdapterClock::default(),
        tokio::runtime::Handle::current(),
    )
    .await;
    assert!(failure.is_err());
    assert!(!mode.exists());
    assert_eq!(std::fs::read(fixture.checkpoint()).unwrap(), checkpoint);
    assert_eq!(fixture.persisted_dispatch(), dispatch);
}

#[tokio::test]
async fn missing_checkpoint_on_actual_restart_never_recreates_fresh_evidence_or_advances_dispatch()
{
    let fixture = Fixture::new();
    let adapter_clock = AdapterClock::default();
    let (kernel, mut effects) = StateKernel::start(
        fixture.bootstrap(),
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &adapter_clock,
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    let deadline = fixture.clock.monotonic_now() + Duration::from_secs(20);
    assert!(effects.shutdown(deadline).await.unwrap().clean);
    drop(effects);
    assert!(kernel.shutdown(deadline).await.unwrap().clean);
    let before = fixture.persisted_dispatch().unwrap();
    // Explicit loss of this fixture's private file, after actual retirement.
    std::fs::remove_file(fixture.checkpoint()).unwrap();
    let bootstrap = fixture.bootstrap();
    let native = bootstrap.native.clone();
    let adapter_clock = AdapterClock::default();
    assert!(StateKernel::start(
        bootstrap,
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &adapter_clock,
        tokio::runtime::Handle::current()
    )
    .await
    .is_err());
    let retired = native
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(!retired.clean && retired.snapshot.physically_retired());
    assert!(!fixture.checkpoint().exists());
    assert!(!adapter_clock.observe().continuity_proven);
    assert_eq!(fixture.persisted_dispatch(), Some(before));
}

#[tokio::test]
async fn existing_corrupt_checkpoint_is_preserved_and_cannot_publish_a_dispatch_owner() {
    let fixture = Fixture::new();
    let malformed = b"existing operator data is not checkpoint evidence";
    std::fs::write(fixture.checkpoint(), malformed).unwrap();
    std::fs::set_permissions(fixture.checkpoint(), std::fs::Permissions::from_mode(0o600)).unwrap();
    let bootstrap = fixture.bootstrap();
    let native = bootstrap.native.clone();
    let deadline = bootstrap.deadline;
    let adapter_clock = AdapterClock::default();
    assert!(StateKernel::start(
        bootstrap,
        &fixture.settings,
        fixture.authority.clone(),
        Vec::new(),
        &adapter_clock,
        tokio::runtime::Handle::current()
    )
    .await
    .is_err());
    let retired = native
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    assert!(!retired.clean && retired.snapshot.physically_retired());
    assert_eq!(std::fs::read(fixture.checkpoint()).unwrap(), malformed);
    assert_eq!(fixture.persisted_dispatch(), None);
    assert!(!adapter_clock.observe().continuity_proven);
}
