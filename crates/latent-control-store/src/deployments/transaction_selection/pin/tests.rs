//! Actual metadata-owner leaves, not a substitute for the signed-asset producer
//! or canonical node installation/recovery qualification. The existing injected
//! host authority supplies admission for these catalog races; it verifies no
//! signatures. Policy's original real signed-asset cases own that boundary.
use super::*;
use crate::deployments::tests::fixtures::{artifact, deployment, run, TempRoot};
use crate::DeploymentStore;
use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, LifecycleScope, PublicationRef, ReleaseActor,
    ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseMutationContext,
    ReleaseOperationPrecondition,
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeReservation,
        NativeReservationRequest,
    },
    ActivationClock, ClockSample, ContractId, FunctionId, PlatformErrorCode, ServiceId,
    StateNamespaceId, TenantId,
};
use latent_manifest::RuntimeCompatibilityProfile;
use latent_routing::{ResolvedRevision, RouteResolver};
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, RowMutation, StoreLimits},
    namespace::{
        catalog::{NamespaceMutation, NamespaceOperationContext},
        lifecycle::{NamespaceLifecycleLimits, NamespaceLifecycleRegistry},
        NamespaceQuota, NamespaceTransition,
    },
};
use std::{
    fs::OpenOptions,
    sync::{atomic::Ordering, Mutex},
    time::{Duration, Instant},
};

#[path = "../../../../tests/admission/support.rs"]
mod authority;

struct Clock(Mutex<Instant>);
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(100_000, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        *self.0.lock().unwrap()
    }
}
impl Clock {
    fn advance(&self, duration: Duration) {
        *self.0.lock().unwrap() += duration;
    }
}

struct Fixture {
    store: DirectoryDeploymentRepository,
    artifacts: Arc<DirectoryArtifactRepository>,
    authority: Arc<authority::Authority>,
    native: NativeCapacityOwner,
    clock: Arc<Clock>,
    namespaces: NamespaceCatalog,
    rows: EmbeddedStore,
    _roots: [TempRoot; 3],
}
impl Fixture {
    fn new() -> Self {
        let roots = [TempRoot::new(), TempRoot::new(), TempRoot::new()];
        let mut inputs = [artifact("selection-blue"), artifact("selection-green")];
        for input in &mut inputs {
            input.manifest.metadata.tenant = Some(TenantId("example".into()));
        }
        let authority = authority::Authority::new_many(inputs.to_vec());
        let artifacts = Arc::new(
            DirectoryArtifactRepository::open_enforced(
                &roots[0].0,
                DirectoryArtifactRepositoryConfig::default(),
                AdmissionStorageLimits::default(),
                authority.clone(),
            )
            .unwrap(),
        );
        let mut deployments = Vec::new();
        for (id, input) in ["blue", "green"].into_iter().zip(inputs) {
            let published = run(artifacts.admit_package(
                &TenantId("example".into()),
                authority::upload(&input),
                &mut |_| Ok(()),
            ))
            .unwrap();
            let mut selected = deployment(id, "example", &published.descriptor.release_digest);
            selected.publication = Some(published.publication.unwrap());
            deployments.push(selected);
        }
        let profile = Arc::new(
            RuntimeCompatibilityProfile::new(
                "wasmtime",
                "48.0.4",
                "x86_64-unknown-linux-gnu",
                &["x86_64.sse2"],
                65536,
                1000,
            )
            .unwrap(),
        );
        let store = run(DirectoryDeploymentRepository::open_with_catalog(
            &roots[1].0,
            artifacts.clone(),
            Default::default(),
            artifacts.lifecycle_authority(),
            profile,
        ))
        .unwrap();
        run(store.apply_many(deployments)).unwrap();
        let clock = Arc::new(Clock(Mutex::new(Instant::now())));
        let native =
            NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone())
                .unwrap();
        let bytes =
            NamespaceLifecycleRegistry::retained_memory_bytes(NamespaceLifecycleLimits::default())
                .unwrap();
        let resident = reservation(
            &native,
            NativeAdmissionClass::Recovery,
            bytes,
            clock.monotonic_now(),
            60,
        );
        let namespaces = NamespaceCatalog::with_retained_capacity(&native, resident).unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(roots[2].0.join("namespace.redb"))
            .unwrap();
        let rows = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
        let plan = namespaces
            .prepare(
                &rows,
                NamespaceOperationContext {
                    tenant: TenantId("example".into()),
                    actor: "fixture".into(),
                    operation_id: "create".into(),
                },
                &NamespaceMutation::Create {
                    id: StateNamespaceId("orders".into()),
                    state_schema: format!("sha256:{}", "1".repeat(64)),
                    quota: NamespaceQuota::default(),
                },
                0,
            )
            .unwrap();
        // Actual closed codec/CAS and opaque row read. These synchronous metadata
        // leaves do not claim the configured protected-worker installation path.
        rows.apply(plan.batch).unwrap();
        Self {
            store,
            artifacts,
            authority,
            native,
            clock,
            namespaces,
            rows,
            _roots: roots,
        }
    }
    fn target() -> InvocationTarget {
        InvocationTarget {
            tenant: TenantId("example".into()),
            service: ServiceId("echo".into()),
            contract: ContractId("example:echo/api@1.0.0".into()),
            function: FunctionId("echo".into()),
            route: None,
        }
    }
    fn read(&self) -> NamespaceRead {
        NamespaceCatalog::read_in(
            &self.rows.snapshot().unwrap(),
            &TenantId("example".into()),
            &StateNamespaceId("orders".into()),
        )
        .unwrap()
        .unwrap()
    }
    fn selected(&self) -> (ResolvedRevision, ReleaseUseEligibility) {
        let resolved = self
            .store
            .resolve(&Self::target(), Some("stable-key"))
            .unwrap();
        let publication = self
            .artifacts
            .execution_eligibility_selected(&resolved.release, resolved.publication.as_ref())
            .unwrap()
            .unwrap();
        (resolved, publication)
    }
    fn original(&self, bytes: u64) -> Arc<NativeReservation> {
        reservation(
            &self.native,
            NativeAdmissionClass::Recovery,
            bytes,
            self.clock.monotonic_now(),
            10,
        )
    }
    fn capture(&self, original: Arc<NativeReservation>) -> CapturedTransactionSelection {
        let (_, publication) = self.selected();
        CapturedTransactionSelection::capture_metadata(
            &self.store,
            &Self::target(),
            Some("stable-key"),
            Some("entity"),
            self.read(),
            &self.namespaces,
            &publication,
            false,
            &self.native,
            original,
        )
        .unwrap()
    }
}

fn reservation(
    native: &NativeCapacityOwner,
    class: NativeAdmissionClass,
    bytes: u64,
    now: Instant,
    seconds: u64,
) -> Arc<NativeReservation> {
    Arc::new(
        native
            .reserve(
                class,
                NativeReservationRequest {
                    work_bytes: bytes,
                    ..NativeReservationRequest::default()
                },
                now + Duration::from_secs(seconds),
            )
            .unwrap(),
    )
}
fn assert_code<T>(value: Result<T, PlatformError>, code: PlatformErrorCode) {
    assert_eq!(
        value.err().expect("opposing actual owner must refuse").code,
        code
    );
}

#[test]
fn actual_weighted_selection_keeps_only_weak_catalog_pins_and_exact_original_source() {
    let fixture = Fixture::new();
    let (resolved, publication) = fixture.selected();
    let captured = fixture.capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES));
    assert_eq!(captured.pin.revision, resolved.revision);
    assert_eq!(captured.pin.generation, resolved.route_generation);
    assert_eq!(
        captured.pin.publication.cache_digest(),
        publication.cache_digest()
    );
    assert_eq!(fixture.namespaces.lifecycle().retained_owners(), 1);
    assert_eq!(
        Arc::strong_count(&fixture.store.read_catalog()),
        2,
        "only current catalog plus this temporary observation; capture is weak"
    );
    let mut observed = 0;
    captured
        .with_current(&mut || {
            observed += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(observed, 1);
    let original_routes = captured.pin.catalog.clone();
    let mut added = deployment("third", "example", publication.release());
    added.publication = Some(publication.publication().clone());
    run(fixture.store.apply(added)).unwrap();
    assert!(
        original_routes.upgrade().is_none(),
        "retired catalog is not retained by the pin"
    );
    assert_code(
        captured.with_current(&mut || {
            observed += 1;
            Ok(())
        }),
        PlatformErrorCode::PermissionDenied,
    );
    assert_eq!(observed, 1);
}

#[test]
fn retained_old_route_snapshot_cannot_replace_the_actual_current_repository_owner() {
    let fixture = Fixture::new();
    let old = fixture.store.pin().unwrap();
    let captured = fixture.capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES));
    let Fixture {
        store,
        artifacts: _artifacts,
        namespaces: _namespaces,
        _roots,
        ..
    } = fixture;
    drop(store);
    assert!(old.resolve(&Fixture::target(), Some("stable-key")).is_ok());
    assert_code(
        captured.with_current(&mut || Ok(())),
        PlatformErrorCode::PermissionDenied,
    );
}

#[test]
fn exact_original_publication_and_admission_cannot_be_replaced_after_revocation() {
    let fixture = Fixture::new();
    let captured = fixture.capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES));
    let other = Fixture::new();
    let (_, foreign) = other.selected();
    assert_eq!(
        captured.pin.publication.publication(),
        foreign.publication()
    );
    assert_eq!(captured.pin.publication.release(), foreign.release());
    assert_ne!(
        captured.pin.publication.cache_digest(),
        foreign.cache_digest()
    );
    assert!(
        captured.pin.with_current(&foreign, &mut || Ok(())).is_err(),
        "equal descriptive IDs cannot replace the actual original owner"
    );
    let reference = PublicationRef {
        scope: LifecycleScope::Tenant(TenantId("example".into())),
        id: captured.pin.publication.publication().clone(),
    };
    fixture
        .artifacts
        .change_publication_lifecycle(
            ReleaseMutationContext {
                scope: reference.scope.clone(),
                actor: ReleaseActor {
                    subject: "fixture".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "revoke".into(),
                    expected_generation: 1,
                }),
            },
            &reference,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_code(
        captured.with_current(&mut || Ok(())),
        PlatformErrorCode::PermissionDenied,
    );
    assert!(fixture
        .artifacts
        .publication_execution_eligibility(&reference)
        .is_err());
    assert!(captured.pin.with_current(&foreign, &mut || Ok(())).is_err());
    let admitted = Fixture::new();
    let admitted_capture =
        admitted.capture(admitted.original(CapturedTransactionSelection::METADATA_BYTES));
    admitted_capture.with_current(&mut || Ok(())).unwrap();
    admitted
        .authority
        .state
        .active
        .store(false, Ordering::SeqCst);
    assert!(admitted_capture.with_current(&mut || Ok(())).is_err());
}

#[test]
fn actual_namespace_lifecycle_acceptance_invalidates_selection_before_commit_io() {
    let fixture = Fixture::new();
    let captured = fixture.capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES));
    let before = fixture.read();
    let after = before
        .record()
        .transition(before.record().version, &NamespaceTransition::Quiesce, 0)
        .unwrap();
    let completion = fixture
        .namespaces
        .lifecycle()
        .begin_transition(&before, &after, false)
        .unwrap();
    assert_code(
        captured.with_current(&mut || Ok(())),
        PlatformErrorCode::PermissionDenied,
    );
    fixture
        .rows
        .apply(AtomicBatch {
            expectations: vec![before.expectation()],
            mutations: vec![RowMutation {
                key: before.expectation().key,
                value: Some(after.encode().unwrap()),
            }],
        })
        .unwrap();
    completion.resolve(&fixture.read()).unwrap();
    assert_code(
        captured.with_current(&mut || Ok(())),
        PlatformErrorCode::PermissionDenied,
    );
}

#[test]
fn original_work_prepay_is_required_before_any_namespace_or_catalog_pin() {
    let fixture = Fixture::new();
    let (_, publication) = fixture.selected();
    let original = fixture.original(CapturedTransactionSelection::METADATA_BYTES - 1);
    let before = fixture.namespaces.lifecycle().retained_owners();
    assert_code(
        CapturedTransactionSelection::capture_metadata(
            &fixture.store,
            &Fixture::target(),
            Some("stable-key"),
            None,
            fixture.read(),
            &fixture.namespaces,
            &publication,
            false,
            &fixture.native,
            original,
        ),
        PlatformErrorCode::ResourceExhausted,
    );
    assert_eq!(fixture.namespaces.lifecycle().retained_owners(), before);
    let original = fixture.original(CapturedTransactionSelection::METADATA_BYTES);
    let occupied = original
        .reserve_buffer(
            NativeBufferClass::Work,
            CapturedTransactionSelection::METADATA_BYTES,
        )
        .unwrap();
    assert_code(
        CapturedTransactionSelection::capture_metadata(
            &fixture.store,
            &Fixture::target(),
            None,
            None,
            fixture.read(),
            &fixture.namespaces,
            &publication,
            false,
            &fixture.native,
            original,
        ),
        PlatformErrorCode::ResourceExhausted,
    );
    assert_eq!(fixture.namespaces.lifecycle().retained_owners(), before);
    drop(occupied);
}

#[test]
fn actual_resident_transfer_requires_same_node_distinct_recovery_and_original_live_fences() {
    let fixture = Fixture::new();
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let foreign_resident = reservation(
        &foreign,
        NativeAdmissionClass::Recovery,
        CapturedTransactionSelection::METADATA_BYTES,
        Instant::now(),
        20,
    );
    assert_code(
        fixture
            .capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES))
            .into_resident(&fixture.native, foreign_resident),
        PlatformErrorCode::PermissionDenied,
    );
    let ordinary = reservation(
        &fixture.native,
        NativeAdmissionClass::Ordinary,
        CapturedTransactionSelection::METADATA_BYTES,
        fixture.clock.monotonic_now(),
        20,
    );
    assert_code(
        fixture
            .capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES))
            .into_resident(&fixture.native, ordinary),
        PlatformErrorCode::PermissionDenied,
    );
    let original = fixture.original(2 * CapturedTransactionSelection::METADATA_BYTES);
    assert_code(
        fixture
            .capture(Arc::clone(&original))
            .into_resident(&fixture.native, original),
        PlatformErrorCode::PermissionDenied,
    );
    let captured = fixture.capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES));
    let resident = reservation(
        &fixture.native,
        NativeAdmissionClass::Recovery,
        CapturedTransactionSelection::METADATA_BYTES,
        fixture.clock.monotonic_now(),
        20,
    );
    fixture.clock.advance(Duration::from_secs(11));
    assert_code(
        captured.into_resident(&fixture.native, resident),
        PlatformErrorCode::Unavailable,
    );
    assert_eq!(fixture.namespaces.lifecycle().retained_owners(), 0);
}

#[test]
fn installed_selection_checks_actual_tenant_namespace_entity_incarnation_revision_and_generation() {
    let fixture = Fixture::new();
    let (resolved, publication) = fixture.selected();
    let installed = fixture
        .capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES))
        .into_resident(
            &fixture.native,
            reservation(
                &fixture.native,
                NativeAdmissionClass::Recovery,
                CapturedTransactionSelection::METADATA_BYTES,
                fixture.clock.monotonic_now(),
                20,
            ),
        )
        .unwrap();
    installed.check_resolved(&resolved, &publication).unwrap();
    installed
        .check_selectors("orders", 1, Some("entity"), "echo")
        .unwrap();
    for change in 0..7 {
        let mut wrong = resolved.clone();
        match change {
            0 => wrong.target.tenant.0 = "foreign".into(),
            1 => wrong.target.route = Some("retargeted".into()),
            2 => wrong.target.function.0 = "retargeted".into(),
            3 => wrong.revision.0 = "equal-dto-is-not-source".into(),
            4 => wrong.route_generation.0 += 1,
            5 => wrong.target.service.0 = "foreign".into(),
            _ => wrong.target.contract.0 = "foreign".into(),
        }
        assert_code(
            installed.check_resolved(&wrong, &publication),
            PlatformErrorCode::PermissionDenied,
        );
    }
    for (namespace, incarnation, entity, operation) in [
        ("foreign", 1, Some("entity"), "echo"),
        ("orders", 2, Some("entity"), "echo"),
        ("orders", 1, Some("other"), "echo"),
        ("orders", 1, None, "echo"),
        ("orders", 1, Some("entity"), "other"),
    ] {
        assert_code(
            installed.check_selectors(namespace, incarnation, entity, operation),
            PlatformErrorCode::PermissionDenied,
        );
    }
    let other = Fixture::new();
    assert!(installed.uses_namespace(&fixture.namespaces));
    assert!(!installed.uses_namespace(&other.namespaces));
    assert!(installed.uses_native_capacity(&fixture.native));
    assert!(!installed.uses_native_capacity(&other.native));
    let caller = fixture.original(CapturedTransactionSelection::METADATA_BYTES);
    fixture.clock.advance(Duration::from_secs(21));
    // Resident expiry remains physical metadata, not a renewable caller grant.
    // Source metadata can remain current, but the exact original caller still
    // has to pass its own final Native fence before any accepted action.
    installed.check_resolved(&resolved, &publication).unwrap();
    let mut observed = 0;
    assert_code(
        installed.with_current(&publication, &mut || {
            caller
                .with_live(|| observed += 1)
                .map_err(|_| unavailable())
        }),
        PlatformErrorCode::Unavailable,
    );
    assert_eq!(observed, 0);
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 3);
}

#[test]
fn original_deadline_and_node_close_do_not_refund_physically_retained_selection_metadata() {
    let fixture = Fixture::new();
    let captured = fixture.capture(fixture.original(CapturedTransactionSelection::METADATA_BYTES));
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 2);
    fixture.clock.advance(Duration::from_secs(11));
    assert_code(
        captured.with_current(&mut || Ok(())),
        PlatformErrorCode::Unavailable,
    );
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 2);
    fixture.native.close();
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 2);
    drop(captured);
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 1);
    let native = fixture.native.clone();
    drop(fixture);
    assert!(native.snapshot().unwrap().physically_retired());
}
