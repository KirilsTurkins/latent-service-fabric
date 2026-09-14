//! Sealed activation authority. Numeric handles and legacy DTOs are lookup data.
//!
//! Lock order is broker -> installed provider -> session -> policy -> catalog ->
//! publisher authority -> original budget ledger. Authority admission uses
//! try-locks. The final fence only commits the already-reserved ledger group and
//! marks work started; no ledger callback acquires an authority fence. No provider
//! I/O or await holds a fence.

use latent_artifacts::LifecycleAuthorityHandle;
use latent_core::{ActivationClock, PlatformError, PlatformErrorCode};
use latent_policy::capability::PolicyStore;
use std::sync::{Arc, Mutex, RwLock, Weak};

mod audit;
pub mod diagnostics;
pub use audit::{reconcile_capability_audit, CapabilityAuditDurability, CapabilityRequestDigest};
mod invocation;
pub mod io;
mod limits;
mod local_service;
mod ownership;
mod plan;
pub mod pools;
mod provider;
mod runtime;
mod session;
mod waiting;
mod work;

pub use invocation::{
    InvocationBindingTarget, LOCAL_SERVICE_INVOCATION_PROFILE, SERVICE_INVOCATION_CAPABILITY,
};
pub use latent_audit::AuditProviderOutcome;
pub use limits::{CapabilityBrokerLimits, CapabilityBrokerSnapshot};
pub use local_service::{
    LocalServiceCompletion, LocalServiceInvocation, LocalServiceInvoker, LocalServiceRequest,
};
pub use plan::{
    CapabilityBindingSpec, CapabilityPlanSource, CapabilityRouteFence, CompiledCapabilityPlan,
};
pub use provider::{
    ProviderBudgetRequirement, ProviderConfiguration, ProviderReference, ProviderRegistration,
};
pub use runtime::ActivationCapabilityRuntime;
pub use session::{CapabilitySession, CapabilitySessionObserver, GuestCapabilityHandle};
pub use work::{CapabilityCallCost, CapabilityDispatch, OwnedCapabilityResponse, ProviderCall};

use ownership::{Charge, Counters, Kind};

/// One configured node owner. It owns neither an executor nor a provider pool.
pub struct ActivationCapabilityBroker {
    inner: Arc<Inner>,
}
struct Inner {
    audit: Option<audit::Configuration>,
    catalog: LifecycleAuthorityHandle,
    policies: Arc<PolicyStore>,
    clock: Arc<dyn ActivationClock>,
    live: RwLock<bool>,
    limits: CapabilityBrokerLimits,
    counters: Arc<Counters>,
    sessions: Mutex<Vec<session::RegistryEntry>>,
    pool_diagnostics: std::sync::OnceLock<Weak<pools::Inner>>,
    pool_registered: std::sync::atomic::AtomicBool,
}
impl ActivationCapabilityBroker {
    pub fn new(
        catalog: LifecycleAuthorityHandle,
        policies: Arc<PolicyStore>,
        clock: Arc<dyn ActivationClock>,
        limits: CapabilityBrokerLimits,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        if !policies.catalog_owner_matches(&catalog) {
            return Err(denied());
        }
        Ok(Self {
            inner: Arc::new(Inner {
                audit: None,
                catalog,
                policies,
                clock,
                live: RwLock::new(true),
                limits,
                counters: Arc::new(Counters::new(limits)),
                pool_registered: std::sync::atomic::AtomicBool::new(false),
                sessions: Mutex::new(
                    std::iter::repeat_with(session::RegistryEntry::default)
                        .take(limits.maximum_sessions)
                        .collect(),
                ),
                pool_diagnostics: std::sync::OnceLock::new(),
            }),
        })
    }
    #[must_use]
    pub fn catalog_owner_matches(&self, catalog: &LifecycleAuthorityHandle) -> bool {
        self.inner.catalog.same_owner(catalog)
    }
    #[must_use]
    pub fn clock_owner_matches(&self, clock: &Arc<dyn ActivationClock>) -> bool {
        Arc::ptr_eq(&self.inner.clock, clock)
    }
    #[must_use]
    pub fn policy_owner_matches(&self, policies: &Arc<PolicyStore>) -> bool {
        Arc::ptr_eq(&self.inner.policies, policies)
    }
    #[must_use]
    pub fn same_owner(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.inner, &other.inner)
    }
    #[must_use]
    pub fn limits(&self) -> CapabilityBrokerLimits {
        self.inner.limits
    }
    #[must_use]
    pub fn snapshot(&self) -> CapabilityBrokerSnapshot {
        self.inner.counters.snapshot()
    }
    /// Stops new sessions/binds/calls. Existing work keeps its actual owners.
    pub fn retire(&self) {
        *self
            .inner
            .live
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = false;
    }
}
impl Drop for ActivationCapabilityBroker {
    fn drop(&mut self) {
        self.retire();
    }
}
fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
fn invalid() -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, "capability-invalid")
}
fn denied() -> PlatformError {
    error(PlatformErrorCode::PermissionDenied, "capability-denied")
}
fn busy() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "capability-busy")
}
fn capacity() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "capability-capacity")
}
fn stopped() -> PlatformError {
    error(PlatformErrorCode::Cancelled, "capability-session-stopped")
}
fn token(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"-_.:/@".contains(&b))
}
fn checked_text(value: &str) -> Result<String, PlatformError> {
    if !token(value) {
        return Err(invalid());
    }
    Ok(value.to_owned())
}

#[cfg(all(test, target_os = "linux"))]
mod tests;
