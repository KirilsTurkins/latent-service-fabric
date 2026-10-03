//! Actual signed package/catalog selection and original physical owner tests.
use super::*;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use latent_artifacts::{
    AdmissionStorageLimits, ArtifactRepository, DirectoryArtifactRepository,
    DirectoryArtifactRepositoryConfig, SelectedTransactionAsset, TRANSACTION_ASSET_RESPONSE_BYTES,
    TRANSACTION_ASSET_WORK_BYTES,
};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBuffer, NativeCapacityLimits, NativeCapacityOwner,
        NativeReservation, NativeReservationRequest,
    },
    ActivationClock, ClockSample, PlatformErrorCode, TenantId,
};
use latent_manifest::{ManifestValidationProfile, RuntimeCompatibilityProfile};

struct NativeClock(Mutex<Instant>);
impl NativeClock {
    fn advance(&self, duration: Duration) {
        *self.0.lock().unwrap() += duration;
    }
}
impl ActivationClock for NativeClock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(NOW * 1000, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        *self.0.lock().unwrap()
    }
}
fn native() -> (
    NativeCapacityOwner,
    Arc<NativeClock>,
    Arc<NativeReservation>,
) {
    let clock = Arc::new(NativeClock(Mutex::new(Instant::now())));
    let owner =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone()).unwrap();
    let original = Arc::new(
        owner
            .reserve(
                NativeAdmissionClass::Recovery,
                request(),
                clock.monotonic_now() + Duration::from_secs(10),
            )
            .unwrap(),
    );
    (owner, clock, original)
}
fn request() -> NativeReservationRequest {
    NativeReservationRequest {
        work_bytes: TRANSACTION_ASSET_WORK_BYTES,
        response_bytes: TRANSACTION_ASSET_RESPONSE_BYTES,
        ..NativeReservationRequest::default()
    }
}
fn declaration() -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!({
        "apiVersion":"latent.dev/v1", "kind":"TransactionBinding",
        "capsule":"tests/packaging", "deployment":"deployment", "binding":"binding",
        "profile": latent_core::transaction_contract::PROFILE,
        "hostAbiDigest":latent_manifest::phase4_host_abi_digest(),
        "namespace":"orders", "stateSchema":format!("sha256:{}", "1".repeat(64)),
        "operations":[{"operation":"inspect", "mode":"fresh-query", "inputFormat":"input-v1", "resultFormat":"result-v1"}]
    })).unwrap()
}
fn profile() -> ManifestValidationProfile {
    ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap()
}
struct Setup {
    fixture: Fixture,
    repo: DirectoryArtifactRepository,
    authority: Arc<SupplyChainAuthority>,
    release: latent_core::ReleaseDigest,
    publication: latent_core::PublicationId,
    _root: tempfile::TempDir,
}
impl Setup {
    fn new(fixture: Fixture) -> Self {
        let root = tempfile::tempdir().unwrap();
        let authority = Arc::new(
            SupplyChainAuthority::open_with_runtime_and_manifest_profile(
                &root.path().join("trust"),
                fixture.approved(),
                fixture.clock.clone(),
                5,
                Arc::new(
                    RuntimeCompatibilityProfile::new(
                        "wasmtime",
                        "48.0.3",
                        "x86_64-unknown-linux-gnu",
                        &["x86_64.sse2"],
                        64 * 1024 * 1024,
                        100_000_000,
                    )
                    .unwrap(),
                ),
                profile(),
            )
            .unwrap(),
        );
        let repo = DirectoryArtifactRepository::open_enforced(
            root.path().join("catalog"),
            DirectoryArtifactRepositoryConfig {
                manifest_profile: profile(),
                ..DirectoryArtifactRepositoryConfig::default()
            },
            AdmissionStorageLimits::default(),
            authority.clone(),
        )
        .unwrap();
        let summary = super::catalog::ready(repo.admit_package(
            &TenantId("tests".into()),
            fixture.upload(),
            &mut |_| Ok(()),
        ))
        .unwrap();
        Self {
            fixture,
            repo,
            authority,
            release: summary.descriptor.release_digest,
            publication: summary.publication.unwrap(),
            _root: root,
        }
    }
    fn capture(
        &self,
        owner: &NativeCapacityOwner,
        original: Arc<NativeReservation>,
    ) -> Result<NativeBuffer<SelectedTransactionAsset>, PlatformError> {
        self.repo.capture_selected_transaction_asset(
            &TenantId("tests".into()),
            &self.release,
            &self.publication,
            owner,
            original,
        )
    }
    fn directory(&self) -> std::path::PathBuf {
        self.repo
            .root()
            .join("publications")
            .join(self.publication.hex())
    }
}

#[test]
fn selected_signed_companion_retains_exact_asset_and_streams_larger_payload() {
    let bytes = declaration();
    let expected = latent_manifest::TransactionBinding::decode(&bytes).unwrap();
    let digest = latent_artifacts::package::artifact_blob_digest(&bytes);
    let setup = Setup::new(Fixture::transactional_with_companion(bytes, true));
    let (owner, _, original) = native();
    let before = setup.repo.verification_snapshot();
    let captured = setup.capture(&owner, original).unwrap();
    assert_eq!(captured.reserved_bytes(), TRANSACTION_ASSET_RESPONSE_BYTES);
    assert_eq!(captured.get().declaration(), &expected);
    assert_eq!(captured.get().asset_digest(), &digest);
    assert_eq!(captured.get().metadata().verified_digest(), &setup.release);
    assert_eq!(
        captured.get().publication().publication(),
        &setup.publication
    );
    assert!(captured.get().publication().admission().is_some());
    let after = setup.repo.verification_snapshot();
    assert_eq!(after.full_fetch_attempts, before.full_fetch_attempts);
    assert_eq!(
        after.component_bytes_hashed - before.component_bytes_hashed,
        captured.get().metadata().descriptor().size_bytes
    );
    let mut entered = 0;
    captured
        .get()
        .with_current(&mut |checker| {
            checker.check_eligibility(captured.get().publication())?;
            entered += 1;
            Ok(())
        })
        .unwrap();
    assert_eq!(entered, 1);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    drop(captured);
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn original_asset_requires_same_recovery_owner_and_prepaid_parts_before_filesystem_read() {
    let setup = Setup::new(Fixture::transactional_with_companion(declaration(), false));
    let (owner, clock, original) = native();
    let foreign =
        NativeCapacityOwner::with_clock(NativeCapacityLimits::default(), clock.clone()).unwrap();
    let path = setup.directory().join("COMPLETE");
    let before = std::fs::read(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    assert_eq!(
        setup
            .capture(&foreign, original.clone())
            .err()
            .unwrap()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(original);
    for (class, request) in [
        (NativeAdmissionClass::Ordinary, request()),
        (
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: TRANSACTION_ASSET_WORK_BYTES - 1,
                ..request()
            },
        ),
        (
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                response_bytes: TRANSACTION_ASSET_RESPONSE_BYTES - 1,
                ..request()
            },
        ),
    ] {
        let bad = Arc::new(
            owner
                .reserve(
                    class,
                    request,
                    clock.monotonic_now() + Duration::from_secs(10),
                )
                .unwrap(),
        );
        assert_eq!(
            setup.capture(&owner, bad.clone()).err().unwrap().code,
            PlatformErrorCode::ResourceExhausted
        );
        drop(bad);
        assert!(owner.snapshot().unwrap().physically_retired());
    }
    std::fs::write(path, before).unwrap();
}

#[test]
fn original_signed_companion_cannot_retarget_identical_republication_or_retired_authority() {
    let setup = Setup::new(Fixture::transactional_with_companion(declaration(), false));
    let (owner, _, original) = native();
    let captured = setup.capture(&owner, original.clone()).unwrap();
    let original_identity = captured.get().publication().cache_digest();
    let publication = super::catalog::ready(setup.repo.admit_package(
        &TenantId("tests".into()),
        setup.fixture.upload(),
        &mut |_| Ok(()),
    ))
    .unwrap();
    assert_eq!(publication.publication.as_ref(), Some(&setup.publication));
    assert_eq!(
        captured.get().publication().cache_digest(),
        original_identity
    );
    setup.authority.retire();
    let mut entered = 0;
    assert!(captured
        .get()
        .with_current(&mut |_| {
            entered += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(entered, 0);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    drop(captured);
    assert!(setup.capture(&owner, original).is_err());
    assert!(owner.snapshot().unwrap().physically_retired());
}

#[test]
fn missing_malformed_oversized_and_wrong_capsule_companions_fail_closed() {
    for case in ["missing", "malformed", "oversized", "capsule", "abi"] {
        let fixture = if case == "missing" {
            Fixture::transactional()
        } else {
            let bytes = match case {
                "malformed" => b"{}".to_vec(),
                "oversized" => vec![b' '; 128 * 1024 + 1],
                _ => {
                    let mut value: serde_json::Value =
                        serde_json::from_slice(&declaration()).unwrap();
                    if case == "capsule" {
                        value["capsule"] = serde_json::json!("another/capsule");
                    } else {
                        value["hostAbiDigest"] =
                            serde_json::json!(format!("sha256:{}", "0".repeat(64)));
                    }
                    serde_json::to_vec(&value).unwrap()
                }
            };
            Fixture::transactional_with_companion(bytes, false)
        };
        let setup = Setup::new(fixture);
        let (owner, _, original) = native();
        assert!(setup.capture(&owner, original).is_err(), "{case}");
        assert!(owner.snapshot().unwrap().physically_retired(), "{case}");
    }
}

#[test]
fn selected_companion_and_complete_corruption_cannot_use_cached_admission() {
    for case in ["asset", "complete"] {
        let setup = Setup::new(Fixture::transactional_with_companion(declaration(), false));
        let (owner, _, original) = native();
        let captured = setup.capture(&owner, original.clone()).unwrap();
        let cached = captured.get().publication().clone();
        drop(captured);
        let directory = setup.directory();
        let path = if case == "complete" {
            directory.join("COMPLETE")
        } else {
            let record: serde_json::Value =
                serde_json::from_slice(&std::fs::read(directory.join("admission.json")).unwrap())
                    .unwrap();
            let layer = record["layers"]
                .as_array()
                .unwrap()
                .iter()
                .find(|layer| layer["path"] == "transaction-binding.json")
                .unwrap();
            directory.join(layer["blob"]["file"].as_str().unwrap())
        };
        let mut bytes = std::fs::read(&path).unwrap();
        bytes[0] ^= 1;
        std::fs::write(path, bytes).unwrap();
        cached.check_current().unwrap();
        assert_eq!(
            setup.capture(&owner, original).err().unwrap().code,
            PlatformErrorCode::CorruptArtifact,
            "{case}"
        );
        assert!(owner.snapshot().unwrap().physically_retired());
    }
}

#[test]
fn native_expiry_close_and_last_physical_capture_drop_remain_original() {
    let setup = Setup::new(Fixture::transactional_with_companion(declaration(), false));
    let (owner, clock, original) = native();
    let captured = setup.capture(&owner, original.clone()).unwrap();
    let bytes = owner.snapshot().unwrap().recovery.bytes;
    clock.advance(Duration::from_secs(11));
    let mut entered = 0;
    assert!(captured
        .get()
        .with_current(&mut |_| {
            entered += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(entered, 0);
    assert!(setup.capture(&owner, original.clone()).is_err());
    owner.close();
    drop(original);
    assert!(captured
        .get()
        .with_current(&mut |_| {
            entered += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(entered, 0);
    assert_eq!(owner.snapshot().unwrap().recovery.bytes, bytes);
    assert_eq!(owner.snapshot().unwrap().recovery.slots, 1);
    drop(captured);
    assert!(owner.snapshot().unwrap().physically_retired());
}
