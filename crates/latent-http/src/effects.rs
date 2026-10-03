//! A trusted, explicitly qualified put-once endpoint contract. Neither generic
//! HTTP, an idempotency header nor a decoded retained row establishes its grant.
//! Resource-only protocol permits remain subordinate to the sealed effect grant.

mod contract;
mod operation;
mod receipt;

pub use contract::{PutOnceContract, HTTP_EFFECT_ADAPTER, HTTP_EFFECT_OPERATION};
use latent_capabilities::broker::{
    pools::{ProviderMetadata, ProviderPools},
    secrets::ProviderCredential,
};
use latent_core::BoxFuture;
use latent_effects::{
    authority::{AuthorityError, DispatchGrant, DispatchProfile},
    dispatch::AttemptIdentity,
    payload::PayloadRecord,
    runtime::{AdapterOutcome, DeferredEffectAdapter, EffectTimeSource},
};
use std::sync::{Arc, Mutex};

use crate::{protocol::ProtocolTransport, HttpProvider};

pub const MAXIMUM_EFFECT_BODY_BYTES: usize = 65_536;
pub const MAXIMUM_EFFECT_RECEIPT_BYTES: usize = 1024;
const MAXIMUM_CREDENTIAL_BYTES: usize = 1024;
const OPERATION_METADATA_BYTES: usize = 32_768;

struct Credential {
    epoch: u64,
    binding: Arc<dyn ProviderCredential>,
}

struct Inner {
    contract: PutOnceContract,
    profile: DispatchProfile,
    transport: ProtocolTransport,
    pools: Arc<ProviderPools>,
    credentials: Mutex<Credential>,
    time: Arc<dyn EffectTimeSource>,
    _metadata: ProviderMetadata,
}

/// Installed by the trusted node composition from an operator-approved contract
/// and the existing configured HTTP provider. It creates no guest session, store,
/// dispatcher, autonomous retry loop or listener.
#[derive(Clone)]
pub struct QualifiedHttpEffectAdapter {
    inner: Arc<Inner>,
}

impl QualifiedHttpEffectAdapter {
    pub fn new(
        provider: &HttpProvider,
        contract: PutOnceContract,
        credential_epoch: u64,
        credential: Arc<dyn ProviderCredential>,
        time: Arc<dyn EffectTimeSource>,
    ) -> Result<Self, AuthorityError> {
        contract.validate(&provider.inner.config)?;
        contract.check_credential(credential_epoch, credential.as_ref())?;
        if provider.inner.streaming.is_some() {
            return Err(AuthorityError::UnsupportedFormat);
        }
        let pools = Arc::clone(&provider.inner.pools);
        let metadata = pools
            .reserve_protocol_metadata(16_384)
            .map_err(|error| operation::admission_error(&error))?;
        let profile = contract.profile(provider.reference().configuration_digest());
        let transport = ProtocolTransport::new(
            Arc::clone(&pools),
            &provider.inner.installed,
            provider.inner.config.clone(),
        )
        .map_err(operation::http_admission_error)?;
        Ok(Self {
            inner: Arc::new(Inner {
                contract,
                profile,
                transport,
                pools,
                credentials: Mutex::new(Credential {
                    epoch: credential_epoch,
                    binding: credential,
                }),
                time,
                _metadata: metadata,
            }),
        })
    }

    /// Trusted publication only. Pause dispatch while changing the credential
    /// binding and current effect rule. A mismatched epoch fails closed; secret
    /// bytes are resolved currently at each actual request and never retained.
    pub fn replace_credential(
        &self,
        epoch: u64,
        credential: Arc<dyn ProviderCredential>,
    ) -> Result<(), AuthorityError> {
        self.inner
            .contract
            .check_credential(epoch, credential.as_ref())?;
        let mut current = self
            .inner
            .credentials
            .try_lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        if epoch <= current.epoch {
            return Err(AuthorityError::Stale);
        }
        *current = Credential {
            epoch,
            binding: credential,
        };
        Ok(())
    }
}

impl DeferredEffectAdapter for QualifiedHttpEffectAdapter {
    fn profile(&self) -> &DispatchProfile {
        &self.inner.profile
    }

    fn accept(
        &self,
        grant: DispatchGrant,
        payload: PayloadRecord,
        attempt: AttemptIdentity,
    ) -> Result<BoxFuture<'static, AdapterOutcome>, AuthorityError> {
        operation::accept(Arc::clone(&self.inner), grant, payload, &attempt)
    }
}
