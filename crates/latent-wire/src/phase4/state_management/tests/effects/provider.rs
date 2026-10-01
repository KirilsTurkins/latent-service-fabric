//! Controlled provider on the actual dispatcher workers. These native-owner
//! schedules are separate from the HTTP/TLS provider qualification.
use super::*;
use latent_core::BoxFuture;
use latent_effects::{
    authority::{AuthorityError, DispatchGrant, DispatchProfile, DispatchPurpose},
    dispatch::{AttemptIdentity, AttemptReceipt, Disposition},
    payload::PayloadRecord,
    runtime::{
        AdapterOutcome, DeferredEffectAdapter, ProviderConfirmation, ProviderReconciliationOutcome,
        ProviderReconciliationReason, ProviderReconciliationRequest,
    },
};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};

pub(super) struct ControlledProvider {
    pub profile: DispatchProfile,
    pub time: Arc<AtomicU64>,
    pub sends: AtomicUsize,
    pub lookups: AtomicUsize,
    pub hold: AtomicBool,
    pub positive: AtomicBool,
    pub entered: tokio::sync::Notify,
    pub release: tokio::sync::Notify,
    pub original: Disposition,
}
pub(super) struct Adapter(pub Arc<ControlledProvider>);
struct Accepted {
    _payload: PayloadRecord,
    attempt: AttemptIdentity,
    version: [u8; 32],
    // Actual original buffers and attempt metadata retire before the grant.
    grant: DispatchGrant,
}
impl ControlledProvider {
    pub fn new(profile: DispatchProfile, time: Arc<AtomicU64>, original: Disposition) -> Self {
        Self {
            profile,
            time,
            sends: AtomicUsize::new(0),
            lookups: AtomicUsize::new(0),
            hold: AtomicBool::new(false),
            positive: AtomicBool::new(true),
            entered: tokio::sync::Notify::new(),
            release: tokio::sync::Notify::new(),
            original,
        }
    }
}
impl DeferredEffectAdapter for Adapter {
    fn profile(&self) -> &DispatchProfile {
        &self.0.profile
    }
    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        grant.require_execution()?;
        payload.verify_grant(&grant)?;
        let owned = Accepted {
            _payload: payload,
            attempt,
            version: [0; 32],
            grant,
        };
        let provider = Arc::clone(&self.0);
        Ok(Box::pin(async move {
            provider.sends.fetch_add(1, Ordering::SeqCst);
            let receipt = AttemptReceipt {
                disposition: provider.original,
                reason: "controlled-native-outcome".into(),
                provider_receipt: None,
                observed_at_millis: provider.time.load(Ordering::SeqCst),
            };
            drop(owned);
            AdapterOutcome {
                receipt,
                retry: None,
            }
        }))
    }
    fn accept_reconciliation(
        &self,
        grant: DispatchGrant,
        request: ProviderReconciliationRequest,
    ) -> Result<BoxFuture<'static, ProviderReconciliationOutcome>, AuthorityError> {
        if grant.purpose() != DispatchPurpose::ReconcileOnly {
            return Err(AuthorityError::PolicyBlocked);
        }
        request.payload().verify_grant(&grant)?;
        let (payload, attempt, version) = request.into_parts();
        let owned = Accepted {
            _payload: payload,
            attempt,
            version,
            grant,
        };
        let provider = Arc::clone(&self.0);
        Ok(Box::pin(async move {
            provider.lookups.fetch_add(1, Ordering::SeqCst);
            provider.entered.notify_one();
            if provider.hold.load(Ordering::SeqCst) {
                provider.release.notified().await;
            }
            let time = latent_effects::authority::EffectTime {
                unix_millis: provider.time.load(Ordering::SeqCst),
                continuity_proven: true,
            };
            let valid = owned.grant.check_current(time).is_ok();
            let original = owned.attempt.clone();
            let version = owned.version;
            drop(owned);
            if !valid || !provider.positive.load(Ordering::SeqCst) {
                return ProviderReconciliationOutcome::Uncertain(
                    ProviderReconciliationReason::NotFound,
                );
            }
            ProviderReconciliationOutcome::Confirmed(
                ProviderConfirmation::new(
                    original,
                    version,
                    "controlled-positive-provider-receipt".into(),
                    time.unix_millis,
                )
                .unwrap(),
            )
        }))
    }
}
