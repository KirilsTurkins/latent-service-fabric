//! Capacities of the closed newly copied/normalized audit graph. Digest owners
//! expose actual retained String capacity; publication IDs own exact Box<str>.
//! Caller spare capacities are never used as retained allocation evidence.
use super::super::{capacity, model::*, Result};
use std::mem::size_of;
const BOOKKEEPING: usize = 64;

#[derive(Default)]
struct Sum(usize);
impl Sum {
    fn add(&mut self, bytes: usize) -> Result<()> {
        self.0 = self.0.checked_add(bytes).ok_or_else(capacity)?;
        Ok(())
    }
    fn allocation(&mut self, bytes: usize) -> Result<()> {
        if bytes > 0 {
            self.add(bytes.checked_add(BOOKKEEPING).ok_or_else(capacity)?)?;
        }
        Ok(())
    }
    fn string(&mut self, value: &String) -> Result<()> {
        self.allocation(value.capacity())
    }
    fn text(&mut self, value: &str) -> Result<()> {
        self.allocation(value.len())
    }
    fn vector<T>(&mut self, value: &Vec<T>) -> Result<()> {
        self.allocation(
            value
                .capacity()
                .checked_mul(size_of::<T>())
                .ok_or_else(capacity)?,
        )
    }
    fn scope(&mut self, value: &AuditScope) -> Result<()> {
        if let AuditScope::Tenant(t) = value {
            self.string(&t.0)?;
        }
        Ok(())
    }
    fn identities(&mut self, v: &AuditIdentities) -> Result<()> {
        if let Some(t) = &v.dispatcher {
            self.string(&t.actor_tenant)?;
        }
        if let Some(t) = &v.state {
            self.string(&t.namespace)?;
            self.allocation(t.state_schema.heap_capacity_bytes())?;
        }
        if let Some(t) = &v.static_web {
            self.allocation(t.web_manifest_digest.heap_capacity_bytes())?;
            self.allocation(t.assets_digest.heap_capacity_bytes())?;
        }
        if let Some(t) = &v.trigger {
            self.string(t)?;
        }
        if let Some(c) = &v.capability {
            for text in [
                &c.activation,
                &c.root_activation,
                &c.service,
                &c.provider_profile,
                &c.capability,
                &c.operation,
            ] {
                self.string(text)?;
            }
            if let Some(p) = &c.parent_activation {
                self.string(p)?;
            }
            self.allocation(c.binding_definition_digest.heap_capacity_bytes())?;
            self.string(&c.binding.id)?;
            self.allocation(c.binding.digest.heap_capacity_bytes())?;
            self.vector(&c.policies)?;
            for p in &c.policies {
                self.string(&p.id)?;
                self.allocation(p.digest.heap_capacity_bytes())?;
            }
            self.allocation(c.provider_configuration_digest.heap_capacity_bytes())?;
            if let Some(r) = &c.request {
                self.allocation(r.digest.heap_capacity_bytes())?;
            }
        }
        for p in [
            &v.publication,
            &v.base_publication,
            &v.candidate_publication,
        ]
        .into_iter()
        .flatten()
        {
            self.text(p.as_str())?;
        }
        for d in [
            &v.canary_evidence_digest,
            &v.received_manifest_digest,
            &v.evidence_revision_digest,
        ]
        .into_iter()
        .flatten()
        {
            self.allocation(d.heap_capacity_bytes())?;
        }
        if let Some(p) = &v.package {
            self.allocation(p.heap_capacity_bytes())?;
        }
        if let Some(c) = &v.component {
            self.string(&c.0)?;
        }
        if let Some(d) = &v.deployment {
            self.string(&d.0)?;
        }
        if let Some(r) = &v.rollout {
            self.string(r)?;
        }
        if let Some(r) = &v.revision {
            self.string(&r.0)?;
        }
        self.vector(&v.policies)?;
        for p in &v.policies {
            self.string(&p.scope)?;
            self.allocation(p.digest.heap_capacity_bytes())?;
        }
        Ok(())
    }
}

pub(crate) trait Heap {
    fn heap_bytes(&self) -> Result<usize>;
}
impl Heap for AuditOperationAttempt {
    fn heap_bytes(&self) -> Result<usize> {
        let mut s = Sum::default();
        s.scope(&self.scope)?;
        s.string(&self.actor.subject)?;
        s.string(&self.operation_id)?;
        s.allocation(self.request_digest.heap_capacity_bytes())?;
        if let Some(d) = &self.preview_receipt_digest {
            s.allocation(d.heap_capacity_bytes())?;
        }
        s.identities(&self.identities)?;
        Ok(s.0)
    }
}
impl Heap for AuditOperationConclusion {
    fn heap_bytes(&self) -> Result<usize> {
        let mut s = Sum::default();
        s.identities(&self.identities)?;
        if let Some(d) = &self.receipt_digest {
            s.allocation(d.heap_capacity_bytes())?;
        }
        Ok(s.0)
    }
}
impl Heap for AuditObservation {
    fn heap_bytes(&self) -> Result<usize> {
        let mut s = Sum::default();
        s.scope(&self.scope)?;
        s.string(&self.actor.subject)?;
        s.identities(&self.identities)?;
        Ok(s.0)
    }
}
impl Heap for DurableAuditAck {
    fn heap_bytes(&self) -> Result<usize> {
        let mut s = Sum::default();
        s.string(&self.epoch)?;
        s.allocation(self.digest.heap_capacity_bytes())?;
        Ok(s.0)
    }
}
impl Heap for AuditQueryRequest {
    fn heap_bytes(&self) -> Result<usize> {
        let mut s = Sum::default();
        s.scope(&self.scope)?;
        if let Some(a) = &self.filter.actor {
            s.string(a)?;
        }
        if let Some(c) = &self.cursor {
            s.string(&c.0)?;
        }
        Ok(s.0)
    }
}
impl Heap for AuditStoredRecord {
    fn heap_bytes(&self) -> Result<usize> {
        let mut s = Sum::default();
        s.string(&self.epoch)?;
        s.string(&self.previous_digest)?;
        s.scope(&self.scope)?;
        s.string(&self.actor.subject)?;
        s.add(match &self.data {
            AuditRecordData::Observation(o) => o.heap_bytes()?,
            AuditRecordData::Attempt(a) => a.heap_bytes()?,
            AuditRecordData::Outcome { conclusion, .. } => conclusion.heap_bytes()?,
        })?;
        Ok(s.0)
    }
}

// A sequence element cannot exceed its admitted owned-node envelope. These
// assertions track the actual original Vec element layouts, not JSON guesses.
const _: () = assert!(size_of::<AuditPolicyIdentity>() <= 64);
const _: () = assert!(size_of::<AuditCapabilityRevision>() <= 64);

impl AuditOperationAttempt {
    pub fn retained_heap_bytes(&self) -> Result<usize> {
        self.heap_bytes()
    }
}
impl AuditOperationConclusion {
    pub fn retained_heap_bytes(&self) -> Result<usize> {
        self.heap_bytes()
    }
}
impl AuditObservation {
    pub fn retained_heap_bytes(&self) -> Result<usize> {
        self.heap_bytes()
    }
}
