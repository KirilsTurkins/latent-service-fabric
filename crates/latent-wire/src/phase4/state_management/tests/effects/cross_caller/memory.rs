use super::*;
use latent_capabilities::namespace::RecoverySelection;
use latent_core::native_capacity::{
    NativeAdmissionClass, NativeBufferClass, NativeCapacityLimits, NativeCapacityOwner,
    NativeReservationRequest,
};

#[tokio::test]
async fn measured_binding_peak_and_all_selection_slices_fit_the_same_unchanged_resident_owner() {
    let mut effect = fixture::setup(false).await;
    let native = &effect.fixture.admission.native;
    let count = 8;
    let asset_bytes = latent_artifacts::TRANSACTION_ASSET_RESPONSE_BYTES;
    let selection_bytes = latent_control_store::CapturedTransactionSelection::METADATA_BYTES;
    let metadata_bytes = asset_bytes + 64 * 1024;
    let original = native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: count * (metadata_bytes + selection_bytes),
                ..NativeReservationRequest::default()
            },
            deadline(),
        )
        .unwrap();
    let metadata = Arc::new(
        original
            .reserve_buffer(NativeBufferClass::Work, count * metadata_bytes)
            .unwrap(),
    );
    let mut bindings = Vec::with_capacity(count as usize);
    for index in 0..count {
        let mut binding = fixture::binding(&effect.fixture.backend.0.bindings[0]);
        binding.incarnation += index;
        bindings.push(binding);
    }
    let peak = StateManagementBackend::captured_effect_binding_peak_bytes(&bindings).unwrap();
    assert!(count * asset_bytes + peak <= metadata.bytes());
    assert_eq!(
        StateManagementBackend::captured_effect_binding_bytes(bindings.len()).unwrap(),
        std::mem::size_of::<crate::phase4::state_management::captured_binding::CapturedBinding>()
            as u64
            * count
    );
    let backend = StateManagementBackend::new_with_captured_effect_recovery(
        fixture::services(&effect),
        bindings,
        &RecoverySelection::OriginalCaller,
        vec![Arc::clone(&metadata)],
        count * asset_bytes,
    )
    .unwrap();
    let mut selections = Vec::new();
    for _ in 0..count {
        selections.push(
            original
                .reserve_buffer(NativeBufferClass::Work, selection_bytes)
                .unwrap(),
        );
    }
    assert!(original.reserve_buffer(NativeBufferClass::Work, 1).is_err());
    drop(selections);
    drop(backend);
    drop(metadata);
    drop(original);
    effect.finish().await;
}

#[tokio::test]
async fn duplicate_foreign_and_wrong_subcharge_class_cannot_credit_captured_source_metadata() {
    let mut effect = fixture::setup(false).await;
    let native = &effect.fixture.admission.native;
    let original = native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 64 * 1024,
                response_bytes: 64 * 1024,
                ..NativeReservationRequest::default()
            },
            deadline(),
        )
        .unwrap();
    let work = Arc::new(
        original
            .reserve_buffer(NativeBufferClass::Work, 64 * 1024)
            .unwrap(),
    );
    let response = Arc::new(
        original
            .reserve_buffer(NativeBufferClass::Response, 64 * 1024)
            .unwrap(),
    );
    let foreign = NativeCapacityOwner::new(NativeCapacityLimits::default()).unwrap();
    let other = foreign
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 64 * 1024,
                ..NativeReservationRequest::default()
            },
            deadline(),
        )
        .unwrap();
    let foreign_work = Arc::new(
        other
            .reserve_buffer(NativeBufferClass::Work, 64 * 1024)
            .unwrap(),
    );
    for memory in [
        vec![Arc::clone(&work), Arc::clone(&work)],
        vec![response],
        vec![foreign_work],
    ] {
        let bindings = vec![fixture::binding(&effect.fixture.backend.0.bindings[0])];
        assert_eq!(
            StateManagementBackend::new_with_captured_effect_recovery(
                fixture::services(&effect),
                bindings,
                &RecoverySelection::OriginalCaller,
                memory,
                0
            )
            .err()
            .unwrap()
            .code,
            PlatformErrorCode::InvalidArgument
        );
    }
    drop(other);
    drop(work);
    drop(original);
    effect.finish().await;
}

#[tokio::test]
async fn already_occupied_asset_credit_and_spare_owned_capacity_cannot_hide_binding_transfer_peak()
{
    let mut effect = fixture::setup(false).await;
    let original = effect
        .fixture
        .admission
        .native
        .reserve(
            NativeAdmissionClass::Recovery,
            NativeReservationRequest {
                work_bytes: 128 * 1024,
                ..NativeReservationRequest::default()
            },
            deadline(),
        )
        .unwrap();
    let memory = Arc::new(
        original
            .reserve_buffer(NativeBufferClass::Work, 128 * 1024)
            .unwrap(),
    );
    let mut spare = Vec::with_capacity(128);
    spare.push(fixture::binding(&effect.fixture.backend.0.bindings[0]));
    let peak = StateManagementBackend::captured_effect_binding_peak_bytes(&spare).unwrap();
    assert!(peak >= (spare.capacity() * std::mem::size_of::<StateManagementBinding>()) as u64);
    assert!(peak <= memory.bytes());
    let bounded = StateManagementBackend::new_with_captured_effect_recovery(
        fixture::services(&effect),
        spare,
        &RecoverySelection::OriginalCaller,
        vec![Arc::clone(&memory)],
        0,
    )
    .unwrap();
    assert_eq!(bounded.0.bindings.capacity(), 1);
    drop(bounded);
    let bindings = vec![fixture::binding(&effect.fixture.backend.0.bindings[0])];
    assert_eq!(
        StateManagementBackend::new_with_captured_effect_recovery(
            fixture::services(&effect),
            bindings,
            &RecoverySelection::OriginalCaller,
            vec![Arc::clone(&memory)],
            memory.bytes()
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    let mut bindings = vec![fixture::binding(&effect.fixture.backend.0.bindings[0])];
    bindings[0].state.binding.reserve(128 * 1024);
    assert_eq!(
        StateManagementBackend::new_with_captured_effect_recovery(
            fixture::services(&effect),
            bindings,
            &RecoverySelection::OriginalCaller,
            vec![Arc::clone(&memory)],
            0
        )
        .err()
        .unwrap()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    drop(memory);
    drop(original);
    effect.finish().await;
}
