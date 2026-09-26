use super::{unauthenticated, BearerIdentity, Result};
use reqwest::header::HeaderValue;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};
use tokio::time::Instant;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BearerUsage {
    pub credential_epoch: u64,
    pub cached_tokens: usize,
    pub active_acquisitions: usize,
    pub waiting_acquisitions: usize,
    pub retained_token_bytes: usize,
    pub maximum_token_bytes: usize,
    pub reserved_acquisition_bytes: usize,
    pub closed: bool,
}

pub(super) struct Accounting {
    pub active: AtomicUsize,
    pub waiting: AtomicUsize,
    pub bytes: AtomicUsize,
    pub maximum: usize,
}

pub(super) struct Count<'a>(&'a AtomicUsize);
impl<'a> Count<'a> {
    pub fn new(counter: &'a AtomicUsize) -> Self {
        counter.fetch_add(1, Ordering::AcqRel);
        Self(counter)
    }
}
impl Drop for Count<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}

pub(in crate::http) struct Token {
    pub authorization: HeaderValue,
    pub epoch: u64,
    pub expires: Instant,
    accounting: Arc<Accounting>,
}

impl Token {
    pub(super) fn new(
        authorization: HeaderValue,
        epoch: u64,
        expires: Instant,
        accounting: &Arc<Accounting>,
    ) -> Result<Arc<Self>> {
        let bytes = authorization.as_bytes().len();
        accounting
            .bytes
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |current| {
                current
                    .checked_add(bytes)
                    .filter(|next| *next <= accounting.maximum)
            })
            .map_err(|_| super::exhausted("oci-token-retention-limit"))?;
        Ok(Arc::new(Self {
            authorization,
            epoch,
            expires,
            accounting: Arc::clone(accounting),
        }))
    }
}

impl Drop for Token {
    fn drop(&mut self) {
        let bytes = self.authorization.as_bytes().len();
        self.authorization = HeaderValue::from_static("");
        self.accounting.bytes.fetch_sub(bytes, Ordering::AcqRel);
    }
}

pub(super) struct Failure {
    pub error: latent_core::PlatformError,
    pub expires: Instant,
}

pub(super) struct State {
    pub identity: BearerIdentity,
    pub authorization: Option<HeaderValue>,
    pub cached: Option<Arc<Token>>,
    pub failed: Option<Failure>,
    pub closed: bool,
}

pub(super) struct Cache(pub Mutex<State>);

impl Cache {
    pub fn lock(&self) -> Result<std::sync::MutexGuard<'_, State>> {
        self.0.lock().map_err(|_| {
            crate::error(
                latent_core::PlatformErrorCode::Internal,
                "oci-token-state-unavailable",
            )
        })
    }

    pub fn current(&self, epoch: u64) -> Result<()> {
        let state = self.lock()?;
        state.check(epoch)
    }

    pub fn lookup(&self, epoch: u64) -> Result<Option<Arc<Token>>> {
        let mut state = self.lock()?;
        state.check(epoch)?;
        if state
            .cached
            .as_ref()
            .is_some_and(|token| Instant::now() >= token.expires)
        {
            state.cached = None;
        }
        Ok(state.cached.clone())
    }

    pub fn invalidate(&self, token: &Arc<Token>) -> Result<()> {
        let mut state = self.lock()?;
        state.check(token.epoch)?;
        if state
            .cached
            .as_ref()
            .is_some_and(|cached| Arc::ptr_eq(cached, token))
        {
            state.cached = None;
        }
        Ok(())
    }
}

impl State {
    pub fn check(&self, epoch: u64) -> Result<()> {
        if self.closed {
            return Err(crate::error(
                latent_core::PlatformErrorCode::Unavailable,
                "oci-client-closed",
            ));
        }
        if self.identity.credential_epoch != epoch {
            return Err(unauthenticated("oci-credential-rotated"));
        }
        Ok(())
    }
}
