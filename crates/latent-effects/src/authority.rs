//! Bounded authority and physical ownership for deferred effects.
//!
//! The node installs rules from its authenticated policy/binding owners. Guest
//! requests never install rules. Durable envelopes are descriptions, not grants:
//! every attempt intersects their captured ceiling with the current rule under
//! one short acceptance/revocation fence. This owner contains no activation,
//! execution cell, guest store, reusable credential, or application timer.

use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

/// Opaque identities supplied by authenticated namespace/command admission.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectScope {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: u64,
    pub publication: String,
    pub binding: String,
    pub operation: String,
}

impl EffectScope {
    fn valid(&self) -> bool {
        self.incarnation != 0
            && [
                &self.tenant,
                &self.namespace,
                &self.publication,
                &self.binding,
                &self.operation,
            ]
            .into_iter()
            .all(|value| identity(value))
    }
}

/// Decoder and destination identity are independent of application state schema.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchProfile {
    pub provider: String,
    pub destination: String,
    pub adapter: String,
    pub intent_format: u32,
    pub payload_format: String,
    pub idempotency_profile: String,
}

impl DispatchProfile {
    fn valid(&self) -> bool {
        self.intent_format != 0
            && [
                &self.provider,
                &self.destination,
                &self.adapter,
                &self.payload_format,
                &self.idempotency_profile,
            ]
            .into_iter()
            .all(|value| identity(value))
    }
}

/// Finite durable lifetime, separately intersected with each current attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DispatchCeiling {
    pub maximum_payload_bytes: u64,
    pub maximum_response_bytes: u64,
    pub maximum_attempts: u32,
    pub maximum_age_millis: u64,
    pub attempt_timeout_millis: u64,
}

impl DispatchCeiling {
    fn valid(self) -> bool {
        self.maximum_payload_bytes > 0
            && self.maximum_payload_bytes <= 1_048_576
            && self.maximum_response_bytes > 0
            && self.maximum_response_bytes <= 1_048_576
            && self.maximum_attempts > 0
            && self.maximum_attempts <= 128
            && self.maximum_age_millis > 0
            && self.maximum_age_millis <= 604_800_000
            && self.attempt_timeout_millis > 0
            && self.attempt_timeout_millis <= 60_000
    }

    const fn intersection(self, current: Self) -> Self {
        Self {
            maximum_payload_bytes: minimum(
                self.maximum_payload_bytes,
                current.maximum_payload_bytes,
            ),
            maximum_response_bytes: minimum(
                self.maximum_response_bytes,
                current.maximum_response_bytes,
            ),
            maximum_attempts: if self.maximum_attempts < current.maximum_attempts {
                self.maximum_attempts
            } else {
                current.maximum_attempts
            },
            maximum_age_millis: minimum(self.maximum_age_millis, current.maximum_age_millis),
            attempt_timeout_millis: minimum(
                self.attempt_timeout_millis,
                current.attempt_timeout_millis,
            ),
        }
    }
}

const fn minimum(left: u64, right: u64) -> u64 {
    if left < right {
        left
    } else {
        right
    }
}

/// Trusted node configuration. A reference names a protected provider secret;
/// this structure never holds credential bytes or a caller bearer token.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectRule {
    pub scope: EffectScope,
    pub profile: DispatchProfile,
    pub policy_revision: u64,
    pub credential_epoch: u64,
    pub protected_credential_reference: String,
    pub ceiling: DispatchCeiling,
    pub enabled: bool,
}

impl EffectRule {
    fn valid(&self) -> bool {
        self.scope.valid()
            && self.profile.valid()
            && self.policy_revision != 0
            && self.credential_epoch != 0
            && identity(&self.protected_credential_reference)
            && self.ceiling.valid()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthorityError {
    Invalid,
    Capacity,
    PolicyBlocked,
    UnsupportedFormat,
    Expired,
    ClockDiscontinuity,
    Stale,
    Unavailable,
}

/// Fields required to retain command/result provenance after result-body expiry.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommitLink {
    pub command: String,
    pub caller_scope: String,
    pub attempt: u64,
    pub commit: String,
    pub effect: String,
    pub sequence: u32,
}

impl CommitLink {
    fn valid(&self) -> bool {
        self.attempt != 0
            && self.sequence < 128
            && [
                &self.command,
                &self.caller_scope,
                &self.commit,
                &self.effect,
            ]
            .into_iter()
            .all(|value| identity(value))
    }
}

/// Immutable captured dispatch scope. Persist only after the atomic command
/// coordinator succeeds. Possession of this value cannot authorize an attempt.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DurableEffectAuthority {
    scope: EffectScope,
    profile: DispatchProfile,
    link: CommitLink,
    policy_revision: u64,
    ceiling: DispatchCeiling,
    committed_at_millis: u64,
    expires_at_millis: u64,
    payload_bytes: u64,
    payload_digest: String,
}

impl DurableEffectAuthority {
    /// Independent bounded authority-record format; application schema changes
    /// do not reinterpret it. Decoding never restores a permission or credential.
    pub fn encode(&self) -> Result<Vec<u8>, AuthorityError> {
        let body = serde_json::to_vec(self).map_err(|_| AuthorityError::Invalid)?;
        if body.len() > 8192 {
            return Err(AuthorityError::Capacity);
        }
        let mut bytes = Vec::with_capacity(body.len() + 5);
        bytes.extend_from_slice(b"LEA\0\x01");
        bytes.extend_from_slice(&body);
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, AuthorityError> {
        if bytes.len() > 8197 {
            return Err(AuthorityError::Capacity);
        }
        if !bytes.starts_with(b"LEA\0\x01") {
            return Err(AuthorityError::UnsupportedFormat);
        }
        let authority: Self =
            serde_json::from_slice(&bytes[5..]).map_err(|_| AuthorityError::Invalid)?;
        let expected_expiry = authority
            .committed_at_millis
            .checked_add(authority.ceiling.maximum_age_millis)
            .ok_or(AuthorityError::Invalid)?;
        if !authority.scope.valid()
            || !authority.profile.valid()
            || !authority.link.valid()
            || authority.policy_revision == 0
            || !authority.ceiling.valid()
            || authority.expires_at_millis != expected_expiry
            || authority.payload_bytes > authority.ceiling.maximum_payload_bytes
            || !digest(&authority.payload_digest)
        {
            return Err(AuthorityError::Invalid);
        }
        Ok(authority)
    }

    #[must_use]
    pub fn scope(&self) -> &EffectScope {
        &self.scope
    }

    #[must_use]
    pub fn profile(&self) -> &DispatchProfile {
        &self.profile
    }

    #[must_use]
    pub fn link(&self) -> &CommitLink {
        &self.link
    }

    #[must_use]
    pub const fn expires_at_millis(&self) -> u64 {
        self.expires_at_millis
    }

    #[must_use]
    pub fn payload_digest(&self) -> &str {
        &self.payload_digest
    }

    #[must_use]
    pub const fn ceiling(&self) -> DispatchCeiling {
        self.ceiling
    }

    #[must_use]
    pub const fn committed_at_millis(&self) -> u64 {
        self.committed_at_millis
    }
}

/// A trusted wall-clock observation carries persisted continuity. An ordinary
/// reboot may restore its floor; rollback/unknown clock continuity blocks work
/// until operator reconciliation. Forward jumps cannot erase dedup protection.
#[derive(Debug, Clone, Copy)]
pub struct EffectTime {
    pub unix_millis: u64,
    pub continuity_proven: bool,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DispatchOwners {
    pub physical: usize,
    pub quarantined: usize,
}

struct State {
    rules: BTreeMap<EffectScope, EffectRule>,
    physical: usize,
    quarantined: usize,
    clock_floor: u64,
    generation: u64,
}

struct Owner {
    state: Mutex<State>,
    maximum_rules: usize,
    maximum_physical: usize,
}

/// One fixed shared node owner. Rule publication and attempt acceptance share
/// the same no-I/O fence; revocation does not wait for a provider request.
#[derive(Clone)]
pub struct EffectAuthorityOwner(Arc<Owner>);

impl EffectAuthorityOwner {
    pub fn new(
        maximum_rules: usize,
        maximum_physical: usize,
        clock_floor: u64,
    ) -> Result<Self, AuthorityError> {
        if !(1..=4096).contains(&maximum_rules) || !(1..=128).contains(&maximum_physical) {
            return Err(AuthorityError::Invalid);
        }
        Ok(Self(Arc::new(Owner {
            state: Mutex::new(State {
                rules: BTreeMap::new(),
                physical: 0,
                quarantined: 0,
                clock_floor,
                generation: 1,
            }),
            maximum_rules,
            maximum_physical,
        })))
    }

    /// Called by the trusted binding/policy owner, never from a guest host import.
    /// Same-revision changes and generation rollback fail. Destination/profile
    /// replacement remains incompatible with already captured intent envelopes.
    pub fn publish(&self, rule: EffectRule) -> Result<(), AuthorityError> {
        if !rule.valid() {
            return Err(AuthorityError::Invalid);
        }
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        if let Some(previous) = state.rules.get(&rule.scope) {
            if rule.policy_revision < previous.policy_revision
                || (rule.policy_revision == previous.policy_revision && rule != *previous)
                || rule.credential_epoch < previous.credential_epoch
            {
                return Err(AuthorityError::Stale);
            }
            if rule == *previous {
                return Ok(());
            }
        } else if state.rules.len() >= self.0.maximum_rules {
            return Err(AuthorityError::Capacity);
        }
        let generation = state
            .generation
            .checked_add(1)
            .ok_or(AuthorityError::Capacity)?;
        state.rules.insert(rule.scope.clone(), rule);
        state.generation = generation;
        Ok(())
    }

    /// Seal descriptive provenance while current authority is fenced. Final
    /// command commitment must repeat this check under its atomic writer fence.
    pub fn capture(
        &self,
        scope: &EffectScope,
        link: CommitLink,
        payload_bytes: u64,
        payload_digest: String,
        time: EffectTime,
    ) -> Result<DurableEffectAuthority, AuthorityError> {
        if !scope.valid() || !link.valid() || !digest(&payload_digest) {
            return Err(AuthorityError::Invalid);
        }
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        check_time(&mut state, time)?;
        let rule = state
            .rules
            .get(scope)
            .filter(|rule| rule.enabled)
            .ok_or(AuthorityError::PolicyBlocked)?;
        if payload_bytes > rule.ceiling.maximum_payload_bytes {
            return Err(AuthorityError::Capacity);
        }
        let expires_at_millis = time
            .unix_millis
            .checked_add(rule.ceiling.maximum_age_millis)
            .ok_or(AuthorityError::Invalid)?;
        Ok(DurableEffectAuthority {
            scope: scope.clone(),
            profile: rule.profile.clone(),
            link,
            policy_revision: rule.policy_revision,
            ceiling: rule.ceiling,
            committed_at_millis: time.unix_millis,
            expires_at_millis,
            payload_bytes,
            payload_digest,
        })
    }

    /// Accept one physical attempt. Local expiry of this owner never permits a
    /// concurrent resend; the dispatcher owns claim/attempt CAS and passes the
    /// resulting once-only attempt here. Provider uncertainty is not abort proof.
    pub fn accept(
        &self,
        authority: &DurableEffectAuthority,
        attempt: u32,
        time: EffectTime,
    ) -> Result<DispatchContext, AuthorityError> {
        let mut state = self
            .0
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        check_time(&mut state, time)?;
        let rule = state
            .rules
            .get(&authority.scope)
            .filter(|rule| rule.enabled)
            .ok_or(AuthorityError::PolicyBlocked)?;
        if rule.profile != authority.profile {
            return Err(AuthorityError::UnsupportedFormat);
        }
        if rule.policy_revision < authority.policy_revision {
            return Err(AuthorityError::Stale);
        }
        let ceiling = authority.ceiling.intersection(rule.ceiling);
        let current_expiry = authority
            .committed_at_millis
            .checked_add(ceiling.maximum_age_millis)
            .ok_or(AuthorityError::Invalid)?;
        if time.unix_millis >= authority.expires_at_millis.min(current_expiry) {
            return Err(AuthorityError::Expired);
        }
        if attempt == 0
            || attempt > ceiling.maximum_attempts
            || authority.payload_bytes > ceiling.maximum_payload_bytes
        {
            return Err(AuthorityError::Capacity);
        }
        if state.physical >= self.0.maximum_physical {
            return Err(AuthorityError::Capacity);
        }
        let credential_epoch = rule.credential_epoch;
        let reference = rule.protected_credential_reference.clone();
        let expiry_remaining = authority.expires_at_millis.min(current_expiry) - time.unix_millis;
        let timeout = Duration::from_millis(ceiling.attempt_timeout_millis.min(expiry_remaining));
        let deadline = Instant::now()
            .checked_add(timeout)
            .ok_or(AuthorityError::Invalid)?;
        state.physical += 1;
        Ok(DispatchContext {
            owner: Arc::clone(&self.0),
            profile: authority.profile.clone(),
            scope: authority.scope.clone(),
            effect: authority.link.effect.clone(),
            ceiling,
            credential_epoch,
            reference,
            deadline,
            retired: false,
        })
    }

    pub fn owners(&self) -> Result<DispatchOwners, AuthorityError> {
        let state = self
            .0
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        Ok(DispatchOwners {
            physical: state.physical,
            quarantined: state.quarantined,
        })
    }
}

/// Owned transport work, moved into the actual fixed worker. Dropping a waiter
/// cannot release this owner; an unretired context conservatively quarantines its
/// capacity. `retire` belongs to physical completion/cleanup, not RPC completion.
pub struct DispatchContext {
    owner: Arc<Owner>,
    scope: EffectScope,
    profile: DispatchProfile,
    effect: String,
    ceiling: DispatchCeiling,
    credential_epoch: u64,
    reference: String,
    deadline: Instant,
    retired: bool,
}

impl DispatchContext {
    #[must_use]
    pub fn scope(&self) -> &EffectScope {
        &self.scope
    }

    #[must_use]
    pub fn profile(&self) -> &DispatchProfile {
        &self.profile
    }

    #[must_use]
    pub fn effect(&self) -> &str {
        &self.effect
    }

    #[must_use]
    pub const fn ceiling(&self) -> DispatchCeiling {
        self.ceiling
    }

    #[must_use]
    pub const fn credential_epoch(&self) -> u64 {
        self.credential_epoch
    }

    /// Only the provider owner resolves this reference through protected storage.
    #[must_use]
    pub fn protected_credential_reference(&self) -> &str {
        &self.reference
    }

    #[must_use]
    pub const fn deadline(&self) -> Instant {
        self.deadline
    }

    pub fn retire(mut self) -> Result<(), AuthorityError> {
        let mut state = self
            .owner
            .state
            .lock()
            .map_err(|_| AuthorityError::Unavailable)?;
        state.physical = state
            .physical
            .checked_sub(1)
            .ok_or(AuthorityError::Unavailable)?;
        self.retired = true;
        Ok(())
    }
}

impl Drop for DispatchContext {
    fn drop(&mut self) {
        if !self.retired {
            if let Ok(mut state) = self.owner.state.lock() {
                // Keep the physical permit occupied. No timeout/lease path may
                // turn this diagnostic owner into an automatic retry.
                state.quarantined += 1;
            }
        }
    }
}

fn check_time(state: &mut State, time: EffectTime) -> Result<(), AuthorityError> {
    if !time.continuity_proven || time.unix_millis < state.clock_floor {
        return Err(AuthorityError::ClockDiscontinuity);
    }
    state.clock_floor = time.unix_millis;
    Ok(())
}

fn identity(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}

fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[cfg(test)]
mod tests;
