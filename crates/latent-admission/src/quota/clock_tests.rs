use std::sync::TryLockError;
use std::time::Instant;

use latent_core::{ActivationClock, ClockSample};

use super::*;

struct LockedClock<'a> {
    quotas: &'a LocalQuotaProvider,
    sample: ClockSample,
}

impl ActivationClock for LockedClock<'_> {
    fn sample(&self) -> ClockSample {
        panic!("reservation must not capture a new wall/monotonic anchor")
    }

    fn monotonic_now(&self) -> Instant {
        assert!(matches!(
            self.quotas.inner.state.try_lock(),
            Err(TryLockError::WouldBlock)
        ));
        self.sample.monotonic()
    }
}

#[test]
fn injected_feasibility_clock_is_read_while_the_actual_quota_mutex_is_held() {
    let quotas = LocalQuotaProvider::new(crate::tests::node_policy()).unwrap();
    let sample = ClockSample::new(1000, Instant::now());
    let budget = crate::tests::budget();
    let grant =
        EffectiveActivationBudget::admit_at(&budget, &budget, &budget, None, sample).unwrap();
    let id = ActivationId("clock-under-lock".to_owned());
    let tenant = TenantId("tenant-a".to_owned());
    let clock = LockedClock {
        quotas: &quotas,
        sample,
    };
    quotas
        .reserve(ReservationSpec {
            activation_id: &id,
            tenant: &tenant,
            trust_class: "sandbox",
            queue_class: "normal",
            cell_class: "tiny",
            grant: &grant,
            timing: crate::timing::ReservationTiming {
                clock: AdmissionClock::Injected(&clock),
                observed_queue_delay_millis: 0,
                load_observed_at: sample.monotonic(),
            },
        })
        .unwrap();
    assert_eq!(quotas.usage().unwrap().active_activations, 1);
    quotas.release(&id);
    assert_eq!(quotas.usage().unwrap(), QuotaUsage::default());
}
