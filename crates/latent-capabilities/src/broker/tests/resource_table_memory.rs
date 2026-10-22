//! Actual sealed-session table backing competes in the original memory ledger.
use super::*;
use latent_core::{ActivationBudget, BudgetProfile, ClockSample, EffectiveActivationBudget};
use latent_executor::ExecutionRequest;

const BYTES: u64 = 8192;

fn selected(fixture: &Fixture, profile: BudgetProfile) -> (ExecutionRequest, Control) {
    let (mut request, mut control) = fixture.request("table-native");
    let limits = request.budget.clone();
    let grant = EffectiveActivationBudget::admit_profile_at(
        profile,
        &limits,
        &limits,
        &limits,
        None,
        ClockSample::system_now(),
    )
    .unwrap();
    control.budget = ActivationBudget::with_profile(grant, profile).unwrap();
    request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
    (request, control)
}

#[test]
fn resource_table_native_backing_original_ledger_and_phase1_are_distinct_from_metadata() {
    for profile in [BudgetProfile::Phase1, BudgetProfile::Phase3] {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = selected(&fixture, profile);
        let session = fixture.session(&request, &control);
        let baseline = fixture.broker.snapshot().metadata_bytes;
        let table = session.reserve_resource_table(BYTES as usize).unwrap();
        assert_eq!(control.budget.host_memory_bytes(), 0);
        assert_eq!(
            fixture.broker.snapshot().metadata_bytes,
            baseline + BYTES as usize
        );
        let native = table.reserve_native_backing(BYTES).unwrap();
        struct Backing {
            _bytes: Box<[u8]>,
            _table: SessionResourceTableReservation,
            native: Option<latent_core::HostMemoryReservation>,
        }
        let mut backing = Backing {
            _bytes: vec![0; BYTES as usize].into_boxed_slice(),
            _table: table,
            native,
        };
        let charged = if profile == BudgetProfile::Phase3 {
            let native = backing.native.as_mut().unwrap();
            assert!(native.is_from_budget(&control.budget));
            assert_eq!(native.bytes(), BYTES);
            native.confirm();
            BYTES
        } else {
            assert!(backing.native.is_none());
            0
        };
        assert_eq!(control.budget.host_memory_bytes(), charged);
        assert_eq!(fixture.broker.snapshot().calls, 0);
        drop(session);
        assert_eq!(control.budget.host_memory_bytes(), charged);
        assert_eq!(fixture.broker.snapshot().handles, 1);
        drop(backing);
        assert_eq!(control.budget.host_memory_bytes(), 0);
        assert_eq!(control.budget.outstanding_reservations(), 0);
        assert_eq!(fixture.broker.snapshot().handles, 0);
        assert_eq!(fixture.broker.snapshot().sessions, 0);
    }
}

#[test]
fn resource_table_native_backing_refusal_preserves_live_owners_and_closed_session_fence() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) = selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let table = session.reserve_resource_table(BYTES as usize).unwrap();
    let before = fixture.broker.snapshot();
    let held_bytes = request.budget.memory_bytes - BYTES + 1;
    let mut held = control.budget.reserve_host_memory(held_bytes).unwrap();
    let padding = vec![0u8; held_bytes as usize].into_boxed_slice();
    held.confirm();
    let error = table.reserve_native_backing(BYTES).unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(fixture.broker.snapshot(), before);
    assert_eq!(control.budget.host_memory_bytes(), held_bytes);
    assert_eq!(control.budget.outstanding_reservations(), 1);
    assert_eq!(
        control
            .budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes,
        held_bytes
    );
    drop(padding);
    drop(held);
    let native = table.reserve_native_backing(BYTES).unwrap().unwrap();
    assert!(native.is_from_budget(&control.budget));
    assert_eq!(control.budget.host_memory_bytes(), BYTES);
    drop(session);
    assert!(table.reserve_native_backing(1).is_err());
    assert_eq!(control.budget.host_memory_bytes(), BYTES);
    drop(native);
    drop(table);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert_eq!(fixture.broker.snapshot().sessions, 0);
}
