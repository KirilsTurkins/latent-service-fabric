//! Separate live view/schema fences. Immutable namespace operation receipts and
//! original command/effect identities keep their existing format and meaning.

use super::{frame, identity, Cursor, NamespaceError, NamespaceRecord};
use crate::embedded::{Family, ReadView, RowKey, StoreError};
use latent_core::{StateNamespaceId, TenantId};

pub const HISTORY_PREFIX: &[u8] = b"ns-history-v1\0";
pub const HISTORY_BYTES: usize = 1024;
const MAGIC: &[u8] = b"NSH\x01";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HistoryEpochs {
    pub schema: u64,
    pub recovery: u64,
}

impl Default for HistoryEpochs {
    fn default() -> Self {
        Self {
            schema: 1,
            recovery: 1,
        }
    }
}

impl HistoryEpochs {
    pub fn validate(self) -> Result<(), NamespaceError> {
        if self.schema == 0 || self.recovery == 0 {
            return Err(NamespaceError::Invalid);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HistoryStatus {
    Ready,
    /// Restored business history is descriptive, never renewed authority or
    /// proof that an old pending effect has not already executed remotely.
    ReconciliationRequired,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamespaceHistory {
    pub tenant: TenantId,
    pub namespace: StateNamespaceId,
    pub incarnation: u64,
    pub state_schema: String,
    pub epochs: HistoryEpochs,
    pub status: HistoryStatus,
}

impl NamespaceHistory {
    #[must_use]
    pub fn initial(namespace: &NamespaceRecord) -> Self {
        Self {
            tenant: namespace.tenant.clone(),
            namespace: namespace.id.clone(),
            incarnation: namespace.version.incarnation,
            state_schema: namespace.state_schema.clone(),
            epochs: HistoryEpochs::default(),
            status: HistoryStatus::Ready,
        }
    }

    pub fn validate(&self) -> Result<(), NamespaceError> {
        identity(&self.tenant.0)?;
        identity(&self.namespace.0)?;
        self.epochs.validate()?;
        if self.incarnation == 0
            || self.state_schema.len() != 71
            || !self.state_schema.starts_with("sha256:")
            || !self.state_schema.as_bytes()[7..]
                .iter()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
        {
            return Err(NamespaceError::Invalid);
        }
        Ok(())
    }

    pub fn check_namespace(&self, namespace: &NamespaceRecord) -> Result<(), NamespaceError> {
        self.validate()?;
        if self.tenant != namespace.tenant
            || self.namespace != namespace.id
            || self.incarnation != namespace.version.incarnation
            || self.state_schema != namespace.state_schema
        {
            return Err(NamespaceError::Corrupt);
        }
        Ok(())
    }

    /// The current source history must be observed from the quiesced actual
    /// store. Epoch exhaustion refuses; restoring never rewrites business IDs.
    pub fn restored_after(&self, current: &Self) -> Result<Self, NamespaceError> {
        self.validate()?;
        current.validate()?;
        if self.tenant != current.tenant
            || self.namespace != current.namespace
            || self.incarnation != current.incarnation
        {
            return Err(NamespaceError::Conflict);
        }
        let mut restored = self.clone();
        restored.epochs.recovery = self
            .epochs
            .recovery
            .max(current.epochs.recovery)
            .checked_add(1)
            .ok_or(NamespaceError::Capacity)?;
        restored.status = HistoryStatus::ReconciliationRequired;
        Ok(restored)
    }

    pub fn encode(&self) -> Result<Vec<u8>, NamespaceError> {
        self.validate()?;
        let mut bytes = MAGIC.to_vec();
        frame(&mut bytes, self.tenant.0.as_bytes())?;
        frame(&mut bytes, self.namespace.0.as_bytes())?;
        frame(&mut bytes, self.state_schema.as_bytes())?;
        for value in [self.incarnation, self.epochs.schema, self.epochs.recovery] {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        bytes.push(match self.status {
            HistoryStatus::Ready => 1,
            HistoryStatus::ReconciliationRequired => 2,
        });
        if bytes.len() > HISTORY_BYTES {
            return Err(NamespaceError::Capacity);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, NamespaceError> {
        if bytes.len() > HISTORY_BYTES || !bytes.starts_with(MAGIC) {
            return Err(NamespaceError::Corrupt);
        }
        let mut cursor = Cursor {
            bytes,
            offset: MAGIC.len(),
        };
        let history = Self {
            tenant: TenantId(cursor.text()?),
            namespace: StateNamespaceId(cursor.text()?),
            state_schema: cursor.text()?,
            incarnation: cursor.u64()?,
            epochs: HistoryEpochs {
                schema: cursor.u64()?,
                recovery: cursor.u64()?,
            },
            status: match cursor.take(1)?[0] {
                1 => HistoryStatus::Ready,
                2 => HistoryStatus::ReconciliationRequired,
                _ => return Err(NamespaceError::Corrupt),
            },
        };
        if cursor.offset != bytes.len() {
            return Err(NamespaceError::Corrupt);
        }
        history.validate().map_err(|_| NamespaceError::Corrupt)?;
        Ok(history)
    }

    /// Absence is the documented legacy epoch1. It is still included as an exact
    /// absent-row expectation at commit, so first history publication races fail.
    pub fn capture(
        view: &ReadView,
        namespace: &NamespaceRecord,
    ) -> Result<(Self, Option<Vec<u8>>), StoreError> {
        let bytes = view.get(
            &history_key(
                &namespace.tenant,
                &namespace.id,
                namespace.version.incarnation,
            )
            .map_err(|_| StoreError::Corrupt)?,
        )?;
        let history = bytes
            .as_deref()
            .map(Self::decode)
            .transpose()
            .map_err(|_| StoreError::Corrupt)?
            .unwrap_or_else(|| Self::initial(namespace));
        history
            .check_namespace(namespace)
            .map_err(|_| StoreError::Corrupt)?;
        Ok((history, bytes))
    }

    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), NamespaceError> {
        let history = Self::decode(bytes)?;
        if history_key(&history.tenant, &history.namespace, history.incarnation)? != *key {
            return Err(NamespaceError::Corrupt);
        }
        Ok(())
    }
}

pub fn history_key(
    tenant: &TenantId,
    namespace: &StateNamespaceId,
    incarnation: u64,
) -> Result<RowKey, NamespaceError> {
    identity(&tenant.0)?;
    identity(&namespace.0)?;
    if incarnation == 0 {
        return Err(NamespaceError::Invalid);
    }
    let mut key = HISTORY_PREFIX.to_vec();
    frame(&mut key, tenant.0.as_bytes())?;
    frame(&mut key, namespace.0.as_bytes())?;
    key.extend_from_slice(&incarnation.to_le_bytes());
    Ok(RowKey {
        family: Family::Namespace,
        key,
    })
}
