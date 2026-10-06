//! One original admission keeps native capacity and the actual command role.
use latent_activation::ActivationEnvelope;
use latent_commit::atomic::{AttemptRetirement, CommandTime};
use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeCapacityOwner, NativeReservation, NativeReservationRequest,
    },
    ActivationBudget, ActivationId, PlatformError,
};
use latent_effects::runtime::{CommandAdmission, CommandAdmissionSource};
use latent_node::transaction_runtime::CommandTimeSource;
use std::sync::{Arc, Mutex};

struct Original {
    activation: ActivationId,
    budget: ActivationBudget,
    native: Arc<NativeReservation>,
}
#[derive(Default)]
struct Retained {
    original: Option<Original>,
    role: Option<CommandAdmission>,
    captured: bool,
}
pub(super) struct AdmissionTime {
    source: CommandAdmissionSource,
    capacity: NativeCapacityOwner,
    retained: Mutex<Retained>,
}
impl AdmissionTime {
    pub fn new(source: CommandAdmissionSource, capacity: NativeCapacityOwner) -> Arc<Self> {
        Arc::new(Self {
            source,
            capacity,
            retained: Mutex::new(Retained::default()),
        })
    }
    /// Capture only after exact publication, namespace and both policy seals.
    pub fn capture(&self) -> Result<u64, PlatformError> {
        let mut retained = self.retained.lock().map_err(|_| super::denied())?;
        if retained.captured || retained.original.is_none() {
            return Err(super::denied());
        }
        let role = self.source.capture().map_err(|_| super::unavailable())?;
        let epoch = role.owner_epoch();
        retained.role = Some(role);
        retained.captured = true;
        Ok(epoch)
    }
    fn retire_role(&self) {
        let mut retained = self
            .retained
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(role) = retained.role.take() {
            role.retire();
        }
        // Native request/work/response capacity stays with this original owner.
        // Dropped accepted workers and final transport fences retain this Arc.
    }
}
impl Drop for AdmissionTime {
    fn drop(&mut self) {
        let retained = self
            .retained
            .get_mut()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if retained.role.is_some() {
            // Physical command retirement was not positively observed. Its
            // own affine role Drop quarantines the protected store. Preserve
            // the bounded global native reservation under the same refusal.
            self.capacity.quarantine();
            if let Some(original) = retained.original.take() {
                std::mem::forget(original.native);
            }
        }
    }
}
impl CommandTimeSource for AdmissionTime {
    fn sample(&self) -> CommandTime {
        match self.source.command_time() {
            Ok(time) => CommandTime {
                unix_millis: time.unix_millis,
                continuity_proven: time.continuity_proven,
            },
            Err(_) => CommandTime {
                unix_millis: 0,
                continuity_proven: false,
            },
        }
    }
    fn retain_admission(
        &self,
        envelope: &ActivationEnvelope,
        budget: &ActivationBudget,
    ) -> Result<(), PlatformError> {
        let mut retained = self.retained.lock().map_err(|_| super::denied())?;
        if let Some(original) = &retained.original {
            return if original.activation == envelope.activation_id
                && original.budget.is_same_instance(budget)
            {
                original
                    .native
                    .with_live(|| ())
                    .map_err(|_| super::unavailable())
            } else {
                Err(super::denied())
            };
        }
        if envelope.input.len() > 1_048_576
            || budget.profile() != latent_core::BudgetProfile::Phase4
        {
            return Err(super::denied());
        }
        let native = self
            .capacity
            .reserve(
                NativeAdmissionClass::Ordinary,
                NativeReservationRequest {
                    request_bytes: 2 * 1_048_576,
                    work_bytes: 24 * 1_048_576,
                    response_bytes: 1_048_576 + 65_536,
                },
                budget.deadline().monotonic().ok_or_else(super::denied)?,
            )
            .map_err(|_| super::capacity())?;
        retained.original = Some(Original {
            activation: envelope.activation_id.clone(),
            budget: budget.clone(),
            native: Arc::new(native),
        });
        Ok(())
    }
    fn with_delivery(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let retained = self.retained.lock().map_err(|_| super::denied())?;
        retained
            .original
            .as_ref()
            .ok_or_else(super::denied)?
            .native
            .with_live(action)
            .map_err(|_| super::unavailable())?
    }
    fn with_acceptance(
        &self,
        action: &mut dyn FnMut(CommandTime) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let retained = self.retained.lock().map_err(|_| super::denied())?;
        let original = retained.original.as_ref().ok_or_else(super::denied)?;
        let role = retained.role.as_ref().ok_or_else(super::denied)?;
        original
            .native
            .with_live(|| {
                role.with_current(|_, time| {
                    action(CommandTime {
                        unix_millis: time.unix_millis,
                        continuity_proven: time.continuity_proven,
                    })
                })
            })
            .map_err(|_| super::unavailable())?
            .map_err(|_| super::unavailable())?
    }
    fn retire_attempt(&self, original: &AttemptRetirement) {
        if original.physically_retired() {
            self.retire_role();
        }
    }
    fn retire_without_claim(&self) {
        self.retire_role();
    }
}
