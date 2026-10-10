//! Node-owned, opt-in immutable public response cache. No background tasks.
//!
//! Unpublished fills, retired entries and active reads keep their reservations.
//! The only publication path is a successful `Delivery::finish`.
mod policy;
mod response;
#[cfg(test)]
mod tests;

use super::{Delivery, HttpError, Method, Request, Scheme, MAX_WIRE_BYTES};
use latent_core::PrincipalKind;
pub use policy::{DependencyProfile, PublicCachePolicy, VaryField, MAX_AGE_SECONDS, MAX_KEY_BYTES};
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};

pub const MAX_ENTRIES: usize = 32;
pub const MAX_OWNERS: usize = 64;
pub const MAX_ENTRY_BYTES: usize = MAX_WIRE_BYTES + MAX_KEY_BYTES + 512;
pub const MAX_CACHE_BYTES: usize = 16 * 1024 * 1024;

/// Supplied by trusted route selection, never by HTTP headers or the renderer.
pub struct CacheScope<'a> {
    pub tenant: &'a str,
    pub publication: &'a str,
    pub release: &'a str,
    pub revision: &'a str,
    pub renderer_profile: &'a str,
    pub trigger: &'a str,
    pub route_generation: u64,
    pub state_version: u64,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct CacheSnapshot {
    pub entries: usize,
    pub owners: usize,
    pub reserved_bytes: usize,
}
#[derive(Default)]
struct Accounting {
    entries: AtomicUsize,
    owners: AtomicUsize,
    bytes: AtomicUsize,
}
struct Owner(Arc<Accounting>);
impl Drop for Owner {
    fn drop(&mut self) {
        self.0.owners.fetch_sub(1, Ordering::AcqRel);
    }
}
struct Charge(Arc<Accounting>);
impl Drop for Charge {
    fn drop(&mut self) {
        self.0.bytes.fetch_sub(MAX_ENTRY_BYTES, Ordering::AcqRel);
        self.0.entries.fetch_sub(1, Ordering::AcqRel);
    }
}
struct Entry {
    key: String,
    wire: Vec<u8>,
    created: Instant,
    expires: Instant,
    generation: u64,
    eligibility: [u8; 32],
    // Refund only after the actual key and wire allocations have been freed.
    _charge: Charge,
}
struct State {
    entries: Vec<Arc<Entry>>,
    generation: u64,
    closed: bool,
}
struct Inner {
    state: Mutex<State>,
    policies: Vec<PublicCachePolicy>,
    accounting: Arc<Accounting>,
}
#[derive(Clone)]
pub struct ResponseCache(Arc<Inner>);

/// A single charged request key, consumed by lookup or delivery. Not Clone.
pub struct CacheRequest {
    key: String,
    cache: ResponseCache,
    policy: usize,
    generation: u64,
    created: Instant,
    eligibility: Option<[u8; 32]>,
    _owner: Owner,
}
pub enum CacheLookup {
    Hit(CacheHit),
    Miss(CacheRequest),
}
pub struct CacheHit {
    entry: Arc<Entry>,
    _request: CacheRequest,
}
impl CacheHit {
    pub(super) fn wire(&self) -> &[u8] {
        &self.entry.wire
    }
    pub(super) fn age(&self) -> u64 {
        self.entry.created.elapsed().as_secs()
    }
}
/// A fill remains private until the corresponding transport finishes. Drop is
/// cancellation: it releases bytes without making an entry visible.
pub(super) struct Pending {
    entry: Arc<Entry>,
    cache: ResponseCache,
    _owner: Owner,
}
impl Pending {
    pub(super) fn publish(self) {
        let Ok(mut state) = self.cache.0.state.lock() else {
            return;
        };
        if !state.closed
            && state.generation == self.entry.generation
            && Instant::now() < self.entry.expires
        {
            state.entries.retain(|entry| entry.key != self.entry.key);
            // All live entries (including this fill) were reserved before
            // allocation; the preallocated index cannot grow past MAX_ENTRIES.
            state.entries.push(self.entry);
        }
    }
}

impl ResponseCache {
    pub fn new(policies: Vec<PublicCachePolicy>) -> Result<Self, HttpError> {
        if policies.is_empty()
            || policies.len() > policy::MAX_POLICIES
            || policies.iter().any(|policy| !policy.validate())
            || policies.iter().enumerate().any(|(i, policy)| {
                policies[..i].iter().any(|other| {
                    policy.tenant == other.tenant
                        && policy.publication == other.publication
                        && policy.authority == other.authority
                        && policy.path == other.path
                })
            })
        {
            return Err(HttpError::InvalidLimits);
        }
        let mut entries = Vec::new();
        entries
            .try_reserve_exact(MAX_ENTRIES)
            .map_err(|_| HttpError::AllocationFailed)?;
        Ok(Self(Arc::new(Inner {
            state: Mutex::new(State {
                entries,
                generation: 0,
                closed: false,
            }),
            policies,
            accounting: Arc::default(),
        })))
    }
    /// A newer catalog invalidates all future hits/fills, without retaining a
    /// per-deployment tombstone map. Late requests cannot restore an older view.
    pub fn observe_generation(&self, generation: u64) -> bool {
        let Ok(mut state) = self.0.state.lock() else {
            return false;
        };
        if state.closed || generation < state.generation {
            return false;
        }
        if generation > state.generation {
            state.entries.clear();
            state.generation = generation;
        }
        true
    }
    pub fn close(&self) {
        if let Ok(mut state) = self.0.state.lock() {
            state.closed = true;
            state.entries.clear();
        }
    }
    #[must_use]
    pub fn snapshot(&self) -> CacheSnapshot {
        let accounting = &self.0.accounting;
        let owners = accounting.owners.load(Ordering::Acquire);
        CacheSnapshot {
            entries: accounting.entries.load(Ordering::Acquire),
            owners,
            reserved_bytes: accounting.bytes.load(Ordering::Acquire)
                + owners * (MAX_KEY_BYTES + 512),
        }
    }
    /// The caller must perform current publication eligibility and admission
    /// checks before using the resulting hit. This cache is not an authorizer.
    pub fn request(&self, request: &Request, scope: &CacheScope<'_>) -> Option<CacheRequest> {
        let principal = request.context().principal();
        if request.cache_sensitive
            || request.data.method != Method::Get
            || !request.body().is_empty()
            || request.data.query.as_ref().is_some()
            || request.data.media_type.as_ref().is_some()
            || principal.kind != PrincipalKind::Trigger
            || principal.service.is_some()
            || !principal.claims.is_empty()
            || principal.tenant.as_ref().map(|v| v.0.as_str()) != Some(scope.tenant)
            || !self.observe_generation(scope.state_version)
        {
            return None;
        }
        let (index, policy) = self.0.policies.iter().enumerate().find(|(_, policy)| {
            policy.tenant == scope.tenant
                && policy.publication == scope.publication
                && policy.release == scope.release
                && policy.renderer_profile == scope.renderer_profile
                && policy.authority == request.data.authority
                && policy.path == request.data.path
        })?;
        // Every application-visible header must have an approved finite domain.
        // Cookies, conditions, Range and request cache directives thus bypass.
        for header in &request.data.headers {
            let field = policy.vary.iter().find(|v| v.name == header.name.0)?;
            if !field
                .values
                .iter()
                .any(|v| v.as_bytes() == header.value.0.as_slice())
                || request
                    .data
                    .headers
                    .iter()
                    .filter(|v| v.name.0 == header.name.0)
                    .count()
                    != 1
            {
                return None;
            }
        }
        let owner = self.owner()?;
        let mut key = String::new();
        key.try_reserve_exact(MAX_KEY_BYTES).ok()?;
        for value in [
            scope.tenant,
            scope.publication,
            scope.release,
            scope.revision,
            scope.renderer_profile,
            scope.trigger,
            &scope.route_generation.to_string(),
            &scope.state_version.to_string(),
            &policy.generation.to_string(),
            &principal.subject,
            match request.data.scheme {
                Scheme::Http => "http",
                Scheme::Https => "https",
            },
            &request.data.authority,
            &request.data.path,
        ] {
            append(&mut key, value)?;
        }
        for field in &policy.vary {
            append(&mut key, &field.name)?;
            let value = request.data.headers.iter().find(|v| v.name.0 == field.name);
            append(&mut key, if value.is_some() { "present" } else { "absent" })?;
            if let Some(value) = value {
                append(&mut key, std::str::from_utf8(&value.value.0).ok()?)?;
            }
        }
        Some(CacheRequest {
            key,
            cache: self.clone(),
            policy: index,
            generation: scope.state_version,
            created: Instant::now(),
            eligibility: None,
            _owner: owner,
        })
    }
    fn owner(&self) -> Option<Owner> {
        self.0
            .accounting
            .owners
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                (n < MAX_OWNERS).then_some(n + 1)
            })
            .ok()?;
        Some(Owner(Arc::clone(&self.0.accounting)))
    }
}
impl CacheRequest {
    /// Bind the current sealed publication/signing-policy digest after admission.
    /// An unstamped request cannot hit or publish. The digest must come from the
    /// host authority, never a caller-supplied request or response field.
    #[must_use]
    pub fn bind_eligibility(mut self, digest: [u8; 32]) -> Self {
        self.eligibility = Some(digest);
        self
    }
    #[must_use]
    pub fn lookup(self) -> CacheLookup {
        let found = self.cache.0.state.lock().ok().and_then(|mut state| {
            let now = Instant::now();
            state.entries.retain(|entry| now < entry.expires);
            if state.closed || state.generation != self.generation {
                return None;
            }
            state
                .entries
                .iter()
                .find(|entry| entry.key == self.key && Some(entry.eligibility) == self.eligibility)
                .cloned()
        });
        match found {
            Some(entry) => CacheLookup::Hit(CacheHit {
                entry,
                _request: self,
            }),
            None => CacheLookup::Miss(self),
        }
    }
    pub(super) fn stage(self, delivery: &Delivery, wire: &[u8]) -> Option<Pending> {
        let eligibility = self.eligibility?;
        let policy = &self.cache.0.policies[self.policy];
        let ttl = response::ttl(delivery, policy)?;
        if wire.len() > MAX_WIRE_BYTES {
            return None;
        }
        let expires = self.created.checked_add(Duration::from_secs(ttl))?;
        let accounting = Arc::clone(&self.cache.0.accounting);
        let mut state = self.cache.0.state.lock().ok()?;
        if state.closed || state.generation != self.generation || Instant::now() >= expires {
            return None;
        }
        state.entries.retain(|entry| Instant::now() < entry.expires);
        while accounting.entries.load(Ordering::Acquire) >= MAX_ENTRIES
            || accounting.bytes.load(Ordering::Acquire) > MAX_CACHE_BYTES - MAX_ENTRY_BYTES
        {
            if state.entries.is_empty() {
                return None;
            }
            // Retired/pinned reads remain charged. Eviction does not manufacture
            // capacity, and new fills bypass when all capacity is still owned.
            state.entries.remove(0);
        }
        accounting.entries.fetch_add(1, Ordering::AcqRel);
        accounting
            .bytes
            .fetch_add(MAX_ENTRY_BYTES, Ordering::AcqRel);
        let charge = Charge(accounting);
        drop(state);
        let mut bytes = Vec::new();
        bytes.try_reserve_exact(wire.len()).ok()?;
        bytes.extend_from_slice(wire);
        Some(Pending {
            entry: Arc::new(Entry {
                key: self.key,
                wire: bytes,
                created: self.created,
                expires,
                generation: self.generation,
                eligibility,
                _charge: charge,
            }),
            cache: self.cache,
            _owner: self._owner,
        })
    }
}
fn append(key: &mut String, value: &str) -> Option<()> {
    use std::fmt::Write;
    let length = value.len().to_string();
    if key
        .len()
        .checked_add(length.len() + 1)?
        .checked_add(value.len())?
        > MAX_KEY_BYTES
    {
        return None;
    }
    write!(key, "{length}:{value}").ok()
}
