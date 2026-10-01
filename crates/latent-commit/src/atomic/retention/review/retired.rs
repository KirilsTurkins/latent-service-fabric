use super::RetentionAudit;
use crate::atomic::{
    codec::{Decoder, Encoder},
    command_identity, incarnation, AtomicError, CommandRecord, Identity,
};
use latent_core::transaction_contract::CommandKey;

/// Compact ABA floor after an explicitly reviewed destructive release. It has
/// no result, dispatch authority, original source decoder or replay promise.
/// The original key reports expired; namespace incarnation remains unchanged.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RetiredCommand {
    pub(in crate::atomic) tenant: String,
    pub(in crate::atomic) namespace_name: String,
    pub(in crate::atomic) command: Identity,
    pub(in crate::atomic) fingerprint: Identity,
    pub(in crate::atomic) namespace: Identity,
    pub(in crate::atomic) incarnation: u64,
    pub(in crate::atomic) identity_expires: u64,
    pub(in crate::atomic) retired_at: u64,
    pub(in crate::atomic) audit_digest: Identity,
}
impl RetiredCommand {
    pub(super) fn new(
        record: &CommandRecord,
        audit: &RetentionAudit,
        now: u64,
    ) -> Result<Self, AtomicError> {
        audit.verify(record)?;
        if !audit.purging || audit.purged != record.effects.len() as u64 || now < audit.retain_until
        {
            return Err(AtomicError::Invalid);
        }
        let floor = Self {
            tenant: record.key.tenant.clone(),
            namespace_name: record.key.namespace.clone(),
            command: record.id,
            fingerprint: record.fingerprint,
            namespace: Self::namespace_identity(&record.key)?,
            incarnation: incarnation(&record.key)?,
            identity_expires: record.identity_expires,
            retired_at: now,
            audit_digest: Identity::derive(b"lsf-retention-audit-v1\0", &[&audit.encode()?]),
        };
        floor.validate()?;
        Ok(floor)
    }
    #[must_use]
    pub fn is_present(bytes: &[u8]) -> bool {
        bytes.starts_with(b"LCX\0")
    }
    #[must_use]
    pub const fn id(&self) -> Identity {
        self.command
    }
    #[must_use]
    pub const fn retired_at(&self) -> u64 {
        self.retired_at
    }
    pub fn namespace_identity(key: &CommandKey) -> Result<Identity, AtomicError> {
        Ok(Identity::derive(
            b"lsf-retired-namespace-v1\0",
            &[
                key.tenant.as_bytes(),
                key.namespace.as_bytes(),
                &incarnation(key)?.to_le_bytes(),
            ],
        ))
    }
    pub fn verify_key(&self, key: &CommandKey) -> Result<(), AtomicError> {
        if self.tenant != key.tenant
            || self.namespace_name != key.namespace
            || self.command != command_identity(key)?
            || self.namespace != Self::namespace_identity(key)?
            || self.incarnation != incarnation(key)?
        {
            return Err(AtomicError::Corrupt);
        }
        Ok(())
    }
    pub fn encode(&self) -> Result<Vec<u8>, AtomicError> {
        self.validate()?;
        let mut out = Encoder::new(b"LCX\0\x01");
        out.text(&self.tenant)?;
        out.text(&self.namespace_name)?;
        for identity in [
            self.command,
            self.fingerprint,
            self.namespace,
            self.audit_digest,
        ] {
            out.identity(identity);
        }
        for number in [self.incarnation, self.identity_expires, self.retired_at] {
            out.number(number);
        }
        out.finish(1024)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LCX\0\x01", 1024)?;
        let floor = Self {
            tenant: input.text(256)?,
            namespace_name: input.text(256)?,
            command: input.identity()?,
            fingerprint: input.identity()?,
            namespace: input.identity()?,
            audit_digest: input.identity()?,
            incarnation: input.number()?,
            identity_expires: input.number()?,
            retired_at: input.number()?,
        };
        input.finish()?;
        floor.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(floor)
    }
    fn validate(&self) -> Result<(), AtomicError> {
        crate::atomic::id(&self.tenant)?;
        crate::atomic::id(&self.namespace_name)?;
        if [
            self.command,
            self.fingerprint,
            self.namespace,
            self.audit_digest,
        ]
        .contains(&Identity([0; 32]))
            || self.incarnation == 0
            || self.identity_expires == 0
            || self.retired_at < self.identity_expires
            || self.namespace
                != Identity::derive(
                    b"lsf-retired-namespace-v1\0",
                    &[
                        self.tenant.as_bytes(),
                        self.namespace_name.as_bytes(),
                        &self.incarnation.to_le_bytes(),
                    ],
                )
        {
            return Err(AtomicError::Invalid);
        }
        Ok(())
    }
}
