//! Fresh management permission for receipt lookup, separate from execution.
use super::{
    check_time, AuthorityError, DispatchCeiling, DispatchContext, DispatchGrant,
    DurableEffectAuthority, EffectAuthorityOwner, EffectRule, EffectTime, State,
};
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Duration, Instant},
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchPurpose {
    Execute,
    ReconcileOnly,
}

/// Trusted current operator, publication and result-read owners. The host
/// retains their original decisions and the original finite request capacity.
/// Callbacks are once-only short fences with no I/O, audit flush or await.
/// Order is Policy -> Namespace -> Effects -> Native, including prewrite checks.
pub trait ProviderLookupAuthorization: Send + Sync {
    fn with_current(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError>;
    fn with_live(
        &self,
        accept: &mut dyn FnMut() -> Result<(), AuthorityError>,
    ) -> Result<(), AuthorityError>;
}

impl EffectAuthorityOwner {
    /// Creates only a lookup context. Old execution enablement and expiry are
    /// never renewed. Its original provenance, attempt and profile stay exact;
    /// current management permission and the same installed provider rule are
    /// checked again before acceptance and protocol I/O. The immutable deadline
    /// belongs to the original management request, never to a retry.
    pub fn accept_lookup(
        &self,
        authority: &DurableEffectAuthority,
        attempt: u32,
        time: EffectTime,
        original_deadline: Instant,
        authorization: Arc<dyn ProviderLookupAuthorization>,
    ) -> Result<DispatchContext, AuthorityError> {
        let now = Instant::now();
        if original_deadline <= now
            || original_deadline.duration_since(now) > Duration::from_mins(1)
            || attempt == 0
            || attempt > authority.ceiling.maximum_attempts
        {
            return Err(AuthorityError::Invalid);
        }
        let mut result = None;
        let mut calls = 0;
        let gate = Arc::clone(&authorization);
        let mut retained_authorization = Some(authorization);
        gate.with_current(&mut || {
            calls += 1;
            if calls != 1 {
                return Err(AuthorityError::Invalid);
            }
            let mut state = self
                .0
                .state
                .lock()
                .map_err(|_| AuthorityError::Unavailable)?;
            check_time(&mut state, time)?;
            let rule = current_lookup_rule(&state, authority)?;
            let ceiling = lookup_ceiling(authority, rule)?;
            let deadline = now
                .checked_add(Duration::from_millis(ceiling.attempt_timeout_millis))
                .ok_or(AuthorityError::Invalid)?
                .min(original_deadline);
            let credential_epoch = rule.credential_epoch;
            let reference = rule.protected_credential_reference.clone();
            if state.lookup_physical >= Self::MAXIMUM_LOOKUP_OWNERS {
                return Err(AuthorityError::Capacity);
            }
            if time.unix_millis < authority.committed_at_millis {
                return Err(AuthorityError::ClockDiscontinuity);
            }
            result = Some(live_with(&gate, || {
                state.physical += 1;
                state.lookup_physical += 1;
                Ok(DispatchContext {
                    owner: Arc::clone(&self.0),
                    live: Arc::new(AtomicBool::new(true)),
                    scope: authority.scope.clone(),
                    profile: authority.profile.clone(),
                    effect: authority.link.effect.clone(),
                    attempt,
                    ceiling,
                    credential_epoch,
                    reference,
                    deadline,
                    retired: false,
                    grant_issued: false,
                    lookup: Some(
                        retained_authorization
                            .take()
                            .ok_or(AuthorityError::Invalid)?,
                    ),
                    retained_owner: None,
                })
            })?);
            Ok(())
        })?;
        if calls != 1 {
            return Err(AuthorityError::Invalid);
        }
        result.ok_or(AuthorityError::Invalid)
    }
}

fn current_lookup_rule<'a>(
    state: &'a State,
    authority: &DurableEffectAuthority,
) -> Result<&'a EffectRule, AuthorityError> {
    authority.validate()?;
    let rule = state
        .rules
        .get(&authority.scope)
        .ok_or(AuthorityError::PolicyBlocked)?;
    if rule.profile != authority.profile {
        return Err(AuthorityError::UnsupportedFormat);
    }
    if rule.policy_revision < authority.policy_revision {
        return Err(AuthorityError::Stale);
    }
    Ok(rule)
}

fn lookup_ceiling(
    authority: &DurableEffectAuthority,
    rule: &EffectRule,
) -> Result<DispatchCeiling, AuthorityError> {
    let mut ceiling = authority.ceiling.intersection(rule.ceiling);
    if authority.payload_bytes > ceiling.maximum_payload_bytes {
        return Err(AuthorityError::Capacity);
    }
    // This is a description of the original attempt, not permission for a new
    // attempt. Lower execution retry/age ceilings do not turn lookup into send.
    ceiling.maximum_attempts = authority.ceiling.maximum_attempts;
    ceiling.maximum_age_millis = authority.ceiling.maximum_age_millis;
    Ok(ceiling)
}

fn live_with<T>(
    authorization: &Arc<dyn ProviderLookupAuthorization>,
    accept: impl FnOnce() -> Result<T, AuthorityError>,
) -> Result<T, AuthorityError> {
    let mut calls = 0;
    let mut accept = Some(accept);
    let mut result = None;
    authorization.with_live(&mut || {
        calls += 1;
        if calls != 1 {
            return Err(AuthorityError::Invalid);
        }
        result = Some(accept.take().ok_or(AuthorityError::Invalid)?()?);
        Ok(())
    })?;
    if calls != 1 {
        return Err(AuthorityError::Invalid);
    }
    result.ok_or(AuthorityError::Invalid)
}

pub(super) fn check_current(grant: &DispatchGrant, time: EffectTime) -> Result<(), AuthorityError> {
    let authorization = grant.lookup.as_ref().ok_or(AuthorityError::Invalid)?;
    let mut calls = 0;
    authorization.with_current(&mut || {
        calls += 1;
        if calls != 1 {
            return Err(AuthorityError::Invalid);
        }
        let mut state = grant
            .owner
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        if !grant.live.load(Ordering::Acquire) {
            return Err(AuthorityError::Stale);
        }
        check_time(&mut state, time)?;
        let rule = state
            .rules
            .get(&grant.scope)
            .ok_or(AuthorityError::PolicyBlocked)?;
        if rule.profile != grant.profile {
            return Err(AuthorityError::UnsupportedFormat);
        }
        if rule.credential_epoch != grant.credential_epoch
            || rule.protected_credential_reference != grant.reference
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        if rule.ceiling.maximum_payload_bytes < grant.ceiling.maximum_payload_bytes
            || rule.ceiling.maximum_response_bytes < grant.ceiling.maximum_response_bytes
            || rule.ceiling.attempt_timeout_millis < grant.ceiling.attempt_timeout_millis
        {
            return Err(AuthorityError::Capacity);
        }
        if time.unix_millis < grant.committed_at_millis {
            return Err(AuthorityError::ClockDiscontinuity);
        }
        if Instant::now() >= grant.deadline {
            return Err(AuthorityError::Expired);
        }
        live_with(authorization, || Ok(()))
    })?;
    if calls != 1 {
        return Err(AuthorityError::Invalid);
    }
    Ok(())
}

pub(super) fn accept_with<T>(
    context: &mut DispatchContext,
    authority: &DurableEffectAuthority,
    attempt: u32,
    time: EffectTime,
    accept: impl FnOnce(DispatchGrant) -> T,
) -> Result<T, AuthorityError> {
    if authority.scope != context.scope
        || authority.profile != context.profile
        || authority.link.effect != context.effect
        || attempt != context.attempt
    {
        return Err(AuthorityError::Invalid);
    }
    let authorization = Arc::clone(context.lookup.as_ref().ok_or(AuthorityError::Invalid)?);
    let mut accept = Some(accept);
    let mut result = None;
    let mut calls = 0;
    authorization.with_current(&mut || {
        calls += 1;
        if calls != 1 {
            return Err(AuthorityError::Invalid);
        }
        let mut state = context
            .owner
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        check_time(&mut state, time)?;
        let rule = current_lookup_rule(&state, authority)?;
        let ceiling = context
            .ceiling
            .intersection(lookup_ceiling(authority, rule)?);
        if Instant::now() >= context.deadline {
            return Err(AuthorityError::Expired);
        }
        if rule.credential_epoch != context.credential_epoch
            || rule.protected_credential_reference != context.reference
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        context.deadline = Instant::now()
            .checked_add(Duration::from_millis(ceiling.attempt_timeout_millis))
            .ok_or(AuthorityError::Invalid)?
            .min(context.deadline);
        context.ceiling = ceiling;
        context.grant_issued = true;
        let grant = DispatchGrant {
            owner: Arc::clone(&context.owner),
            live: Arc::clone(&context.live),
            scope: context.scope.clone(),
            profile: context.profile.clone(),
            effect: context.effect.clone(),
            payload_digest: authority.payload_digest.clone(),
            payload_bytes: authority.payload_bytes,
            committed_at_millis: authority.committed_at_millis,
            expires_at_millis: authority.expires_at_millis,
            attempt,
            ceiling,
            credential_epoch: context.credential_epoch,
            reference: context.reference.clone(),
            deadline: context.deadline,
            lookup: Some(Arc::clone(&authorization)),
            _retained_owner: context.retained_owner.as_ref().map(Arc::clone),
        };
        result = Some(live_with(&authorization, || {
            Ok(accept.take().ok_or(AuthorityError::Invalid)?(grant))
        })?);
        Ok(())
    })?;
    if calls != 1 {
        return Err(AuthorityError::Invalid);
    }
    result.ok_or(AuthorityError::Invalid)
}
