use super::{denied, Inner, State};
use latent_artifacts::{AdmissionBinding, AdmissionGrant, AdmissionRecheck};
use latent_core::PlatformError;
use latent_signing::{VerifiedBuildProvenance, VerifiedPackageSignature};
use std::any::Any;
use std::cell::RefCell;
use std::sync::Arc;

pub(super) struct Grant {
    pub owner: Arc<Inner>,
    pub binding: AdmissionBinding,
    pub epoch: u64,
    pub publisher: VerifiedPackageSignature,
    pub builder: VerifiedBuildProvenance,
}
impl Grant {
    pub fn check(&self, owner: &Arc<Inner>, state: &mut State) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(owner, &self.owner) || state.floor.epoch != self.epoch {
            return Err(denied("admission-grant-stale"));
        }
        let now = owner.sample(state)?;
        state.publisher.check_current(&self.publisher, now)?;
        state.builder.check_current(&self.builder, now)?;
        if !state
            .policy
            .tenants
            .get(&self.binding.tenant.0)
            .is_some_and(|publishers| publishers.contains(&self.publisher.publisher().0))
        {
            return Err(denied("admission-tenant-publisher-denied"));
        }
        Ok(())
    }
}
impl AdmissionGrant for Grant {
    fn as_any(&self) -> &dyn Any {
        self
    }
    fn binding(&self) -> &AdmissionBinding {
        &self.binding
    }
    fn retained_bytes(&self) -> usize {
        // Fixed conservative charge covers bounded proof identities/source
        // fields, both state IDs, binding and Arc/control-block ownership.
        std::mem::size_of::<Self>() + self.binding.receipt.capacity() + 16 * 1024
    }
    fn check_current(&self) -> Result<(), PlatformError> {
        self.check(&self.owner, &mut *self.owner.lock()?)
    }
    fn with_current(
        &self,
        action: &mut dyn FnMut(&dyn AdmissionRecheck) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let mut state = self.owner.lock()?;
        self.check(&self.owner, &mut state)?;
        let checker = Checker {
            initial: self,
            state: RefCell::new(&mut *state),
        };
        action(&checker)
    }
}
struct Checker<'a> {
    initial: &'a Grant,
    state: RefCell<&'a mut State>,
}
impl AdmissionRecheck for Checker<'_> {
    fn check(&self) -> Result<(), PlatformError> {
        self.initial
            .check(&self.initial.owner, &mut self.state.borrow_mut())
    }
    fn check_grant(&self, grant: &dyn AdmissionGrant) -> Result<(), PlatformError> {
        let grant = grant
            .as_any()
            .downcast_ref::<Grant>()
            .ok_or_else(|| denied("admission-authority-mismatch"))?;
        grant.check(&self.initial.owner, &mut self.state.borrow_mut())
    }
}
