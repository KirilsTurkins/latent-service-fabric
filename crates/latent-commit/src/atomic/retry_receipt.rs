//! The same immutable retry receipt, with bounded original ownership only when
//! explicit tenant accounting is installed. Legacy LCT1 bytes remain unchanged.
use super::{
    codec::{Decoder, Encoder},
    AtomicError, CommandRecord, Identity,
};
use latent_state::embedded::{Family, ReadView, RowKey};

const LEGACY: &[u8] = b"LCT\0\x01";
const ACCOUNTED: &[u8] = b"LCT\0\x02";
const PREFIX: &[u8] = b"command-retry-v1\0";
struct Owner {
    tenant: String,
    namespace: String,
    incarnation: u64,
    command: Identity,
    retry: Identity,
}
pub(super) struct RetryReceipt {
    pub attempt: u64,
    pub abort_proof: Identity,
    pub fingerprint: Identity,
    owner: Option<Owner>,
}
impl RetryReceipt {
    pub fn create(
        record: &CommandRecord,
        retry: Identity,
        abort_proof: Identity,
        installed: bool,
    ) -> Result<Vec<u8>, AtomicError> {
        let mut bytes = Encoder::new(if installed { ACCOUNTED } else { LEGACY });
        bytes.number(record.attempt);
        bytes.identity(abort_proof);
        bytes.identity(record.fingerprint);
        if installed {
            bytes.text(&record.key.tenant)?;
            bytes.text(&record.key.namespace)?;
            bytes.number(super::incarnation(&record.key)?);
            bytes.identity(record.id);
            bytes.identity(retry);
        }
        bytes.finish(if installed { 1024 } else { 77 })
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let accounted = bytes.starts_with(ACCOUNTED);
        if !accounted && bytes.len() != 77 {
            return Err(AtomicError::Corrupt);
        }
        let mut input = Decoder::new(
            bytes,
            if accounted { ACCOUNTED } else { LEGACY },
            if accounted { 1024 } else { 77 },
        )?;
        let attempt = input.number()?;
        let abort_proof = input.identity()?;
        let fingerprint = input.identity()?;
        let owner = if accounted {
            Some(Owner {
                tenant: input.text(256)?,
                namespace: input.text(256)?,
                incarnation: input.number()?,
                command: input.identity()?,
                retry: input.identity()?,
            })
        } else {
            None
        };
        input.finish()?;
        if !(2..=16).contains(&attempt) {
            return Err(AtomicError::Corrupt);
        }
        if let Some(owner) = &owner {
            super::id(&owner.tenant).map_err(|_| AtomicError::Corrupt)?;
            super::id(&owner.namespace).map_err(|_| AtomicError::Corrupt)?;
            if owner.incarnation == 0
                || owner.command == Identity([0; 32])
                || owner.retry == Identity([0; 32])
            {
                return Err(AtomicError::Corrupt);
            }
        }
        Ok(Self {
            attempt,
            abort_proof,
            fingerprint,
            owner,
        })
    }
    pub fn validate_key(&self, key: &RowKey) -> Result<(), AtomicError> {
        if key.family != Family::Maintenance
            || key.key.len() != PREFIX.len() + 32
            || !key.key.starts_with(PREFIX)
            || self
                .owner
                .as_ref()
                .is_some_and(|owner| key.key[PREFIX.len()..] != owner.retry.0)
        {
            return Err(AtomicError::Corrupt);
        }
        Ok(())
    }
    pub fn verify(
        &self,
        record: &CommandRecord,
        index: &super::retention::RetryIndex,
    ) -> Result<(), AtomicError> {
        if self.attempt != record.attempt
            || self.fingerprint != record.fingerprint
            || index.command != record.id
            || index.attempt != record.attempt
            || self.owner.as_ref().is_some_and(|owner| {
                owner.command != record.id
                    || owner.retry != index.retry
                    || owner.tenant != record.key.tenant
                    || owner.namespace != record.key.namespace
                    || super::incarnation(&record.key).ok() != Some(owner.incarnation)
            })
        {
            return Err(AtomicError::Corrupt);
        }
        Ok(())
    }
    pub fn linked_tenant(
        &self,
        view: &ReadView,
        key: &RowKey,
    ) -> Result<latent_core::TenantId, AtomicError> {
        self.validate_key(key)?;
        let owner = self.owner.as_ref().ok_or(AtomicError::UnsupportedFormat)?;
        let record = CommandRecord::decode(
            &view
                .get(&super::attempt_row_key(owner.command, self.attempt))?
                .ok_or(AtomicError::Corrupt)?,
        )?;
        let index = super::retention::RetryIndex::decode(
            &view
                .get(&super::retention::RetryIndex::row_key(
                    owner.command,
                    self.attempt,
                ))?
                .ok_or(AtomicError::Corrupt)?,
        )?;
        self.verify(&record, &index)?;
        Ok(latent_core::TenantId(owner.tenant.clone()))
    }
    pub fn is_accounted(&self) -> bool {
        self.owner.is_some()
    }
}
