use std::collections::{BTreeMap, VecDeque};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Instant;

use latent_core::{StateNamespaceId, TenantId};

use super::owner::OwnerStamp;
use super::{
    EntityLaneError, EntityLaneLimits, EntityLaneRequest, EntityRejected, EntityRejection,
    EntityScope,
};

pub(super) struct Queued<T> {
    pub request: EntityLaneRequest<T>,
    pub ticket: u64,
    pub wait_until: Instant,
    pub charge: u64,
}

pub(super) struct Lane<T> {
    pub queue: VecDeque<Queued<T>>,
    pub active: Option<Arc<OwnerStamp>>,
}

impl<T> Lane<T> {
    pub fn retained_bytes(&self) -> u64 {
        self.queue.iter().map(|q| q.charge).sum::<u64>()
            + self.active.as_ref().map_or(0, |a| a.charge)
    }
}

pub(super) struct State<T> {
    pub limits: EntityLaneLimits,
    pub lanes: BTreeMap<EntityScope, Lane<T>>,
    pub ready: VecDeque<EntityScope>,
    pub next_ticket: u64,
    pub next_generation: u64,
    pub identity: Arc<()>,
}

impl<T> State<T> {
    pub fn new(limits: EntityLaneLimits) -> Self {
        Self {
            limits,
            lanes: BTreeMap::new(),
            ready: VecDeque::new(),
            next_ticket: 0,
            next_generation: 0,
            identity: Arc::new(()),
        }
    }

    pub fn insert(&mut self, queued: Queued<T>) {
        let scope = queued.request.scope.clone();
        let lane = self.lanes.entry(scope.clone()).or_insert_with(|| Lane {
            queue: VecDeque::new(),
            active: None,
        });
        if lane.active.is_none() && lane.queue.is_empty() {
            self.ready.push_back(scope);
        }
        lane.queue.push_back(queued);
    }

    pub fn remove_empty(&mut self, scope: &EntityScope) {
        if self
            .lanes
            .get(scope)
            .is_some_and(|lane| lane.active.is_none() && lane.queue.is_empty())
        {
            self.lanes.remove(scope);
            self.ready.retain(|key| key != scope);
        }
        if self.lanes.is_empty() {
            self.ready = VecDeque::new();
        }
    }

    pub fn remove_queued(
        &mut self,
        scope: &EntityScope,
        ticket: u64,
    ) -> Option<EntityLaneRequest<T>> {
        let lane = self.lanes.get_mut(scope)?;
        let index = lane
            .queue
            .iter()
            .position(|queued| queued.ticket == ticket)?;
        let request = lane.queue.remove(index)?.request;
        self.remove_empty(scope);
        Some(request)
    }

    pub fn take_expired(&mut self, now: Instant) -> Option<EntityRejected<T>> {
        let expired = self.lanes.iter().find_map(|(scope, lane)| {
            lane.queue
                .iter()
                .find(|queued| queued.wait_until <= now)
                .map(|queued| (scope.clone(), queued.ticket))
        });
        let (scope, ticket) = expired?;
        let request = self.remove_queued(&scope, ticket)?;
        Some(EntityRejected {
            reason: EntityRejection::WaitExpired,
            request,
        })
    }

    pub fn validate_fence(&self, stamp: &Arc<OwnerStamp>) -> Result<(), EntityLaneError> {
        if self
            .lanes
            .get(&stamp.scope)
            .and_then(|lane| lane.active.as_ref())
            .is_some_and(|current| Arc::ptr_eq(current, stamp))
            && !stamp.revoked.load(Ordering::Acquire)
        {
            Ok(())
        } else {
            Err(EntityLaneError::StaleFence)
        }
    }

    pub fn retire(&mut self, stamp: &Arc<OwnerStamp>) {
        let Some(lane) = self.lanes.get_mut(&stamp.scope) else {
            return;
        };
        if !lane
            .active
            .as_ref()
            .is_some_and(|active| Arc::ptr_eq(active, stamp))
        {
            return;
        }
        lane.active = None;
        if !lane.queue.is_empty() {
            self.ready.push_back(stamp.scope.clone());
        }
        self.remove_empty(&stamp.scope);
    }

    pub fn revoke_namespace(
        &mut self,
        tenant: &TenantId,
        namespace: &StateNamespaceId,
        incarnation: u64,
    ) -> Vec<EntityRejected<T>> {
        let scopes: Vec<_> = self
            .lanes
            .keys()
            .filter(|scope| {
                &scope.tenant == tenant
                    && &scope.namespace == namespace
                    && scope.incarnation == incarnation
            })
            .cloned()
            .collect();
        let mut rejected = Vec::new();
        for scope in scopes {
            if let Some(lane) = self.lanes.get_mut(&scope) {
                if let Some(active) = &lane.active {
                    active.revoked.store(true, Ordering::Release);
                    active.cancelled.store(true, Ordering::Release);
                }
                rejected.extend(lane.queue.drain(..).map(|queued| EntityRejected {
                    reason: EntityRejection::AuthorityChanged,
                    request: queued.request,
                }));
            }
            self.remove_empty(&scope);
        }
        self.ready.retain(|scope| {
            self.lanes
                .get(scope)
                .is_some_and(|lane| lane.active.is_none() && !lane.queue.is_empty())
        });
        rejected
    }
}
