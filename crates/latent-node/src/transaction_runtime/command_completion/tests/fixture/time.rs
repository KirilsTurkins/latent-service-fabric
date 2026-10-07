use super::*;
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
    },
    ActivationBudget,
};
use latent_effects::runtime::CommandAdmission;
use std::sync::Mutex;

pub(super) struct Time {
    source: CommandAdmissionSource,
    native: NativeCapacityOwner,
    retained: Mutex<Option<CommandAdmission>>,
    original: Mutex<Option<Arc<NativeReservation>>>,
}
impl Time {
    pub fn new(source: CommandAdmissionSource, native: NativeCapacityOwner) -> Self {
        Self {
            source,
            native,
            retained: Mutex::new(None),
            original: Mutex::new(None),
        }
    }
    pub fn capture(&self, budget: &ActivationBudget) -> u64 {
        let native = self
            .native
            .reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest {
                    request_bytes: 2 * 1_048_576,
                    work_bytes: 24 * 1_048_576,
                    response_bytes: 1_048_576 + 65_536,
                },
                budget.deadline().monotonic().unwrap(),
            )
            .unwrap();
        let role = self.source.capture().unwrap();
        let epoch = role.owner_epoch();
        let mut retained = self.retained.lock().unwrap();
        assert!(retained.is_none());
        *retained = Some(role);
        let mut original = self.original.lock().unwrap();
        assert!(original.is_none());
        *original = Some(Arc::new(native));
        epoch
    }
    fn retire(&self) {
        if let Some(role) = self.retained.lock().unwrap().take() {
            role.retire();
        }
    }
}
impl crate::transaction_runtime::CommandTimeSource for Time {
    fn sample(&self) -> latent_commit::atomic::CommandTime {
        let time = self.source.command_time().unwrap();
        latent_commit::atomic::CommandTime {
            unix_millis: time.unix_millis,
            continuity_proven: time.continuity_proven,
        }
    }
    fn with_acceptance(
        &self,
        action: &mut dyn FnMut(
            latent_commit::atomic::CommandTime,
        ) -> Result<(), latent_core::PlatformError>,
    ) -> Result<(), latent_core::PlatformError> {
        let retained = self.retained.lock().unwrap();
        let role = retained
            .as_ref()
            .ok_or_else(crate::transaction_runtime::authorization::denied)?;
        let original = self.original.lock().unwrap();
        let native = original
            .as_ref()
            .ok_or_else(crate::transaction_runtime::authorization::denied)?;
        native
            .with_live(|| {
                role.with_current(|_, time| {
                    action(latent_commit::atomic::CommandTime {
                        unix_millis: time.unix_millis,
                        continuity_proven: time.continuity_proven,
                    })
                })
                .map_err(|_| crate::transaction_runtime::authorization::denied())?
            })
            .map_err(|_| crate::transaction_runtime::authorization::denied())?
    }
    fn retire_attempt(&self, retirement: &latent_commit::atomic::AttemptRetirement) {
        if retirement.physically_retired() {
            self.retire();
        }
    }
    fn retire_without_claim(&self) {
        self.retire();
    }
    fn with_delivery(
        &self,
        action: &mut dyn FnMut() -> Result<(), latent_core::PlatformError>,
    ) -> Result<(), latent_core::PlatformError> {
        self.original
            .lock()
            .unwrap()
            .as_ref()
            .ok_or_else(crate::transaction_runtime::authorization::denied)?
            .with_live(action)
            .map_err(|_| crate::transaction_runtime::authorization::denied())?
    }
}

impl Drop for Time {
    fn drop(&mut self) {
        if self.retained.get_mut().unwrap().is_some() {
            // Match the installed original-role owner: losing positive attempt
            // retirement cannot refund this bounded global native reservation.
            self.native.quarantine();
            if let Some(original) = self.original.get_mut().unwrap().take() {
                std::mem::forget(original);
            }
        }
    }
}
