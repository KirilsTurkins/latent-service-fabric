use super::{
    cache::{Count, Failure},
    token, BearerIdentity, ConfiguredBearer, Token,
};
use crate::http::{exhausted, invalid, RegistryActions, Result, Transport};
use reqwest::Method;
use std::{
    sync::{atomic::Ordering, Arc},
    time::{Duration, SystemTime},
};
use tokio::time::{timeout_at, Instant};
use zeroize::Zeroizing;

impl ConfiguredBearer {
    pub(in crate::http) fn epoch(&self) -> Result<u64> {
        let state = self.cache.lock()?;
        state.check(state.identity.credential_epoch)?;
        Ok(state.identity.credential_epoch)
    }

    pub(in crate::http) fn cached(&self, epoch: u64) -> Result<Option<Arc<Token>>> {
        self.cache.lookup(epoch)
    }

    pub(in crate::http) fn current(&self, token: &Token) -> Result<()> {
        self.cache.current(token.epoch)
    }

    pub(in crate::http) fn invalidate(&self, token: &Arc<Token>) -> Result<()> {
        self.cache.invalidate(token)
    }

    pub(in crate::http) fn require_method(&self, method: &Method) -> Result<()> {
        if !matches!(*method, Method::GET | Method::HEAD)
            && self.actions != RegistryActions::PullPush
        {
            return Err(crate::error(
                latent_core::PlatformErrorCode::PermissionDenied,
                "oci-bearer-write-not-authorized",
            ));
        }
        Ok(())
    }

    pub(in crate::http) async fn acquire(
        &self,
        transport: &Transport,
        epoch: u64,
        deadline: Instant,
    ) -> Result<Arc<Token>> {
        if let Some(token) = self.cached(epoch)? {
            return Ok(token);
        }
        let _waiter = self
            .waiters
            .try_acquire()
            .map_err(|_| exhausted("oci-token-waiter-limit"))?;
        let waiting = Count::new(&self.accounting.waiting);
        let _exclusive = timeout_at(deadline, self.acquisition.lock())
            .await
            .map_err(|_| deadline_error())?;
        drop(waiting);
        if let Some(token) = self.cached(epoch)? {
            return Ok(token);
        }
        let authorization = {
            let state = self.cache.lock()?;
            state.check(epoch)?;
            if let Some(failed) = &state.failed {
                if Instant::now() < failed.expires {
                    return Err(failed.error.clone());
                }
            }
            state
                .authorization
                .clone()
                .ok_or_else(|| invalid("oci-credential-unavailable"))?
        };
        let _active = Count::new(&self.accounting.active);
        let started = Instant::now();
        let result = timeout_at(deadline, async {
            let response = self
                .exchange(deadline, transport.limits.request_timeout, authorization)
                .await?;
            let body = Zeroizing::new(
                transport
                    .read_body(response, super::MAX_TOKEN_RESPONSE_BYTES, None)
                    .await?,
            );
            token::parse(&body, &self.scope, started, SystemTime::now())
        })
        .await
        .map_err(|_| deadline_error())
        .and_then(std::convert::identity);
        let mut state = self.cache.lock()?;
        state.check(epoch)?;
        match result {
            Ok((header, expires)) => {
                let token = Token::new(header, epoch, expires, &self.accounting)?;
                state.cached = Some(Arc::clone(&token));
                state.failed = None;
                Ok(token)
            }
            Err(error) => {
                if error.code != latent_core::PlatformErrorCode::DeadlineExceeded {
                    state.failed = Some(Failure {
                        error: error.clone(),
                        expires: Instant::now() + Duration::from_secs(1),
                    });
                }
                Err(error)
            }
        }
    }

    pub(in crate::http) fn rotate(
        &self,
        identity: BearerIdentity,
        username: &str,
        password: &str,
    ) -> Result<()> {
        identity.validate()?;
        let authorization =
            crate::http::transport::client::basic_authorization(username, password)?;
        let mut state = self.cache.lock()?;
        state.check(state.identity.credential_epoch)?;
        if identity.tenant != state.identity.tenant
            || identity.principal != state.identity.principal
            || identity.credential_epoch <= state.identity.credential_epoch
        {
            return Err(invalid("oci-credential-rotation-identity"));
        }
        state.identity = identity;
        state.authorization = Some(authorization);
        state.cached = None;
        state.failed = None;
        Ok(())
    }

    pub(in crate::http) fn usage(&self) -> super::BearerUsage {
        let state = self
            .cache
            .0
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        super::BearerUsage {
            credential_epoch: state.identity.credential_epoch,
            cached_tokens: usize::from(
                state
                    .cached
                    .as_ref()
                    .is_some_and(|token| token.expires > Instant::now()),
            ),
            active_acquisitions: self.accounting.active.load(Ordering::Acquire),
            waiting_acquisitions: self.accounting.waiting.load(Ordering::Acquire),
            retained_token_bytes: self.accounting.bytes.load(Ordering::Acquire),
            maximum_token_bytes: self.accounting.maximum,
            reserved_acquisition_bytes: self.accounting.active.load(Ordering::Acquire) * 64 * 1024,
            closed: state.closed,
        }
    }

    pub(in crate::http) fn close(&self) -> Result<()> {
        let mut state = self.cache.lock()?;
        state.closed = true;
        state.cached = None;
        state.failed = None;
        state.authorization = None;
        Ok(())
    }
}

fn deadline_error() -> latent_core::PlatformError {
    crate::error(
        latent_core::PlatformErrorCode::DeadlineExceeded,
        "oci-operation-deadline",
    )
}
