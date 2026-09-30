//! Bounded durable namespace metadata and lifecycle transitions for issue #384.
//!
//! Records, expected rows and receipts are descriptive. The configured host must
//! authenticate the caller, hold current policy/publication acceptance fences and
//! publish these bytes through the shared embedded store; knowing an ID or decoding
//! a record does not authorize an operation. Namespace rows are never physically
//! removed: an approved destruction leaves an incarnation-preserving tombstone.

use latent_core::{StateNamespaceId, TenantId};

pub const RECORD_FORMAT: u16 = 1;
pub const RECORD_BYTES: usize = 4096;
pub const IDENTITY_BYTES: usize = 256;
const RECORD_MAGIC: &[u8] = b"lsf-namespace-v1\0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NamespaceError {
    Invalid,
    Corrupt,
    UnsupportedFormat,
    Conflict,
    InUse,
    PermissionDenied,
    Capacity,
    Cancelled,
    Unavailable,
    RecoveryRequired,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NamespaceStatus {
    Active,
    Quiescing,
    Retired,
    Tombstone,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NamespaceVersion {
    pub incarnation: u64,
    pub generation: u64,
}

/// Namespace-specific ceilings further narrow the shared owner's physical quotas.
/// They are limits, not allocations or proof that recovery capacity was reserved.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NamespaceQuota {
    pub state_keys: u64,
    pub state_bytes: u64,
    pub result_rows: u64,
    pub result_bytes: u64,
    pub effect_rows: u64,
    pub effect_bytes: u64,
    pub payload_bytes: u64,
    pub recovery_bytes: u64,
}

impl Default for NamespaceQuota {
    fn default() -> Self {
        Self {
            state_keys: 4096,
            state_bytes: 8 * 1024 * 1024,
            result_rows: 4096,
            result_bytes: 8 * 1024 * 1024,
            effect_rows: 4096,
            effect_bytes: 8 * 1024 * 1024,
            payload_bytes: 8 * 1024 * 1024,
            recovery_bytes: 1024 * 1024,
        }
    }
}

impl NamespaceQuota {
    pub fn validate(self) -> Result<(), NamespaceError> {
        if [self.state_keys, self.result_rows, self.effect_rows]
            .iter()
            .any(|count| *count == 0 || *count > 1_000_000)
            || [
                self.state_bytes,
                self.result_bytes,
                self.effect_bytes,
                self.payload_bytes,
                self.recovery_bytes,
            ]
            .iter()
            .any(|bytes| *bytes == 0 || *bytes > 1024 * 1024 * 1024)
            || self.recovery_bytes > self.result_bytes
        {
            return Err(NamespaceError::Invalid);
        }
        Ok(())
    }
}

/// Updated in the same physical envelope as the dependent durable records.
/// Conservative over-retention is safe; decrementing from an unproven cleanup is not.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct NamespacePins {
    pub retained_results: u64,
    pub unresolved_effects: u64,
    pub payload_references: u64,
    pub inbox_protection: u64,
}

impl NamespacePins {
    #[must_use]
    pub fn is_empty(self) -> bool {
        self == Self::default()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NamespaceRecord {
    pub tenant: TenantId,
    /// Host/admin resource identity, independent of component/package/revision.
    pub id: StateNamespaceId,
    pub version: NamespaceVersion,
    pub state_schema: String,
    pub status: NamespaceStatus,
    pub quota: NamespaceQuota,
    pub pins: NamespacePins,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NamespaceTransition {
    Quiesce,
    Retire,
    /// Explicitly approved destruction; implementation retains the metadata tombstone.
    Destroy,
    /// An attributable explicit approval, never an automatic side effect of deployment.
    Recreate {
        state_schema: String,
        quota: NamespaceQuota,
    },
}

impl NamespaceRecord {
    pub fn create(
        tenant: TenantId,
        id: StateNamespaceId,
        state_schema: String,
        quota: NamespaceQuota,
    ) -> Result<Self, NamespaceError> {
        let record = Self {
            tenant,
            id,
            version: NamespaceVersion {
                incarnation: 1,
                generation: 1,
            },
            state_schema,
            status: NamespaceStatus::Active,
            quota,
            pins: NamespacePins::default(),
        };
        record.validate()?;
        Ok(record)
    }

    pub fn validate(&self) -> Result<(), NamespaceError> {
        identity(&self.tenant.0)?;
        identity(&self.id.0)?;
        if self.version.incarnation == 0
            || self.version.generation == 0
            || self.state_schema.len() != 71
            || !self.state_schema.starts_with("sha256:")
            || !self.state_schema.as_bytes()[7..]
                .iter()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(byte))
            || (self.status == NamespaceStatus::Tombstone && !self.pins.is_empty())
        {
            return Err(NamespaceError::Invalid);
        }
        self.quota.validate()
    }

    /// Compute a complete replacement, without mutating the original record.
    /// The root store must compare the exact encoded old row and recheck actual
    /// active-commit ownership at its final no-I/O policy/lifecycle acceptance fence.
    pub fn transition(
        &self,
        expected: NamespaceVersion,
        action: &NamespaceTransition,
        active_commits: u64,
    ) -> Result<Self, NamespaceError> {
        self.validate()?;
        if expected != self.version {
            return Err(NamespaceError::Conflict);
        }
        let mut next = self.clone();
        next.version.generation = next
            .version
            .generation
            .checked_add(1)
            .ok_or(NamespaceError::Capacity)?;
        match action {
            NamespaceTransition::Quiesce if self.status == NamespaceStatus::Active => {
                next.status = NamespaceStatus::Quiescing;
            }
            NamespaceTransition::Retire if self.status == NamespaceStatus::Quiescing => {
                if active_commits != 0 {
                    return Err(NamespaceError::InUse);
                }
                next.status = NamespaceStatus::Retired;
            }
            NamespaceTransition::Destroy if self.status == NamespaceStatus::Retired => {
                if active_commits != 0 || !self.pins.is_empty() {
                    return Err(NamespaceError::InUse);
                }
                next.status = NamespaceStatus::Tombstone;
            }
            NamespaceTransition::Recreate {
                state_schema,
                quota,
            } if self.status == NamespaceStatus::Tombstone => {
                if active_commits != 0 || !self.pins.is_empty() {
                    return Err(NamespaceError::InUse);
                }
                next.version.incarnation = next
                    .version
                    .incarnation
                    .checked_add(1)
                    .ok_or(NamespaceError::Capacity)?;
                next.state_schema.clone_from(state_schema);
                next.quota = *quota;
                next.status = NamespaceStatus::Active;
            }
            _ => return Err(NamespaceError::Conflict),
        }
        next.validate()?;
        Ok(next)
    }

    pub fn encode(&self) -> Result<Vec<u8>, NamespaceError> {
        self.validate()?;
        let mut bytes = Vec::with_capacity(768);
        bytes.extend_from_slice(RECORD_MAGIC);
        bytes.extend_from_slice(&RECORD_FORMAT.to_le_bytes());
        frame(&mut bytes, self.tenant.0.as_bytes())?;
        frame(&mut bytes, self.id.0.as_bytes())?;
        frame(&mut bytes, self.state_schema.as_bytes())?;
        bytes.push(match self.status {
            NamespaceStatus::Active => 1,
            NamespaceStatus::Quiescing => 2,
            NamespaceStatus::Retired => 3,
            NamespaceStatus::Tombstone => 4,
        });
        for value in [
            self.version.incarnation,
            self.version.generation,
            self.quota.state_keys,
            self.quota.state_bytes,
            self.quota.result_rows,
            self.quota.result_bytes,
            self.quota.effect_rows,
            self.quota.effect_bytes,
            self.quota.payload_bytes,
            self.quota.recovery_bytes,
            self.pins.retained_results,
            self.pins.unresolved_effects,
            self.pins.payload_references,
            self.pins.inbox_protection,
        ] {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
        if bytes.len() > RECORD_BYTES {
            return Err(NamespaceError::Capacity);
        }
        Ok(bytes)
    }

    pub fn decode(bytes: &[u8]) -> Result<Self, NamespaceError> {
        if bytes.len() > RECORD_BYTES || !bytes.starts_with(RECORD_MAGIC) {
            return Err(NamespaceError::Corrupt);
        }
        let mut cursor = Cursor {
            bytes,
            offset: RECORD_MAGIC.len(),
        };
        if cursor.u16()? != RECORD_FORMAT {
            return Err(NamespaceError::UnsupportedFormat);
        }
        let tenant = TenantId(cursor.text()?);
        let id = StateNamespaceId(cursor.text()?);
        let state_schema = cursor.text()?;
        let status = match cursor.take(1)?[0] {
            1 => NamespaceStatus::Active,
            2 => NamespaceStatus::Quiescing,
            3 => NamespaceStatus::Retired,
            4 => NamespaceStatus::Tombstone,
            _ => return Err(NamespaceError::Corrupt),
        };
        let version = NamespaceVersion {
            incarnation: cursor.u64()?,
            generation: cursor.u64()?,
        };
        let quota = NamespaceQuota {
            state_keys: cursor.u64()?,
            state_bytes: cursor.u64()?,
            result_rows: cursor.u64()?,
            result_bytes: cursor.u64()?,
            effect_rows: cursor.u64()?,
            effect_bytes: cursor.u64()?,
            payload_bytes: cursor.u64()?,
            recovery_bytes: cursor.u64()?,
        };
        let pins = NamespacePins {
            retained_results: cursor.u64()?,
            unresolved_effects: cursor.u64()?,
            payload_references: cursor.u64()?,
            inbox_protection: cursor.u64()?,
        };
        if cursor.offset != bytes.len() {
            return Err(NamespaceError::Corrupt);
        }
        let record = Self {
            tenant,
            id,
            version,
            state_schema,
            status,
            quota,
            pins,
        };
        record.validate().map_err(|_| NamespaceError::Corrupt)?;
        Ok(record)
    }
}

/// The `Namespace` row family is selected by the shared owner. Length framing
/// distinguishes tenants/IDs, prevents slash/path interpretation and supports a
/// bounded authenticated tenant prefix without disclosing global counts.
pub fn namespace_record_key(
    tenant: &TenantId,
    id: &StateNamespaceId,
) -> Result<Vec<u8>, NamespaceError> {
    let mut key = namespace_tenant_prefix(tenant)?;
    identity(&id.0)?;
    frame(&mut key, id.0.as_bytes())?;
    Ok(key)
}

pub fn namespace_tenant_prefix(tenant: &TenantId) -> Result<Vec<u8>, NamespaceError> {
    identity(&tenant.0)?;
    let mut key = b"ns-v1\0".to_vec();
    frame(&mut key, tenant.0.as_bytes())?;
    Ok(key)
}

/// Separate from namespace IDs and business commands. Actor comes from
/// authentication and must be checked again before receipt lookup/disclosure.
pub fn namespace_operation_key(
    tenant: &TenantId,
    actor: &str,
    operation_id: &str,
) -> Result<Vec<u8>, NamespaceError> {
    identity(&tenant.0)?;
    identity(actor)?;
    identity(operation_id)?;
    let mut key = b"ns-op-v1\0".to_vec();
    for value in [
        tenant.0.as_bytes(),
        actor.as_bytes(),
        operation_id.as_bytes(),
    ] {
        frame(&mut key, value)?;
    }
    Ok(key)
}

fn identity(value: &str) -> Result<(), NamespaceError> {
    if value.is_empty() || value.len() > IDENTITY_BYTES || value.chars().any(char::is_control) {
        return Err(NamespaceError::Invalid);
    }
    Ok(())
}

fn frame(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), NamespaceError> {
    let length = u16::try_from(value.len()).map_err(|_| NamespaceError::Capacity)?;
    bytes.extend_from_slice(&length.to_le_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl Cursor<'_> {
    fn take(&mut self, length: usize) -> Result<&[u8], NamespaceError> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(NamespaceError::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(NamespaceError::Corrupt)?;
        self.offset = end;
        Ok(value)
    }
    fn u16(&mut self) -> Result<u16, NamespaceError> {
        Ok(u16::from_le_bytes(
            self.take(2)?
                .try_into()
                .map_err(|_| NamespaceError::Corrupt)?,
        ))
    }
    fn u64(&mut self) -> Result<u64, NamespaceError> {
        Ok(u64::from_le_bytes(
            self.take(8)?
                .try_into()
                .map_err(|_| NamespaceError::Corrupt)?,
        ))
    }
    fn text(&mut self) -> Result<String, NamespaceError> {
        let length = usize::from(self.u16()?);
        if length > IDENTITY_BYTES {
            return Err(NamespaceError::Corrupt);
        }
        String::from_utf8(self.take(length)?.to_vec()).map_err(|_| NamespaceError::Corrupt)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record() -> NamespaceRecord {
        NamespaceRecord::create(
            TenantId("a".into()),
            StateNamespaceId("opaque-id".into()),
            format!("sha256:{}", "1".repeat(64)),
            NamespaceQuota::default(),
        )
        .unwrap()
    }

    #[test]
    fn namespace_record_round_trip_is_bounded_and_independent_of_revision() {
        let record = record();
        let bytes = record.encode().unwrap();
        assert!(bytes.len() <= RECORD_BYTES);
        assert_eq!(NamespaceRecord::decode(&bytes).unwrap(), record);
        assert_eq!(
            namespace_record_key(&record.tenant, &record.id).unwrap(),
            b"ns-v1\0\x01\0a\x09\0opaque-id"
        );
    }

    #[test]
    fn wrong_format_truncation_unknown_status_and_trailing_bytes_fail_closed() {
        let bytes = record().encode().unwrap();
        for length in 0..bytes.len() {
            assert!(NamespaceRecord::decode(&bytes[..length]).is_err());
        }
        let mut wrong = bytes.clone();
        wrong[RECORD_MAGIC.len()] = 2;
        assert_eq!(
            NamespaceRecord::decode(&wrong),
            Err(NamespaceError::UnsupportedFormat)
        );
        let mut trailing = bytes;
        trailing.push(0);
        assert_eq!(
            NamespaceRecord::decode(&trailing),
            Err(NamespaceError::Corrupt)
        );
        let mut unknown = record();
        unknown.version.generation = 0;
        assert_eq!(unknown.encode(), Err(NamespaceError::Invalid));
    }

    #[test]
    fn create_quiesce_retire_destroy_recreate_never_reuses_aba_version() {
        let mut record = record();
        let original = record.version;
        for action in [
            NamespaceTransition::Quiesce,
            NamespaceTransition::Retire,
            NamespaceTransition::Destroy,
            NamespaceTransition::Recreate {
                state_schema: record.state_schema.clone(),
                quota: record.quota,
            },
        ] {
            record = record.transition(record.version, &action, 0).unwrap();
        }
        assert_eq!(record.status, NamespaceStatus::Active);
        assert_eq!(record.version.incarnation, original.incarnation + 1);
        assert!(record.version.generation > original.generation);
        assert_eq!(
            record.transition(original, &NamespaceTransition::Quiesce, 0),
            Err(NamespaceError::Conflict)
        );
    }

    #[test]
    fn destruction_cannot_drop_required_results_effects_payloads_or_inbox() {
        for pins in [
            NamespacePins {
                retained_results: 1,
                ..NamespacePins::default()
            },
            NamespacePins {
                unresolved_effects: 1,
                ..NamespacePins::default()
            },
            NamespacePins {
                payload_references: 1,
                ..NamespacePins::default()
            },
            NamespacePins {
                inbox_protection: 1,
                ..NamespacePins::default()
            },
        ] {
            let mut record = record();
            record.status = NamespaceStatus::Retired;
            record.pins = pins;
            assert_eq!(
                record.transition(record.version, &NamespaceTransition::Destroy, 0),
                Err(NamespaceError::InUse)
            );
            assert_eq!(
                record.transition(record.version, &NamespaceTransition::Destroy, 1),
                Err(NamespaceError::InUse)
            );
        }
    }

    #[test]
    fn active_commit_blocks_retirement_and_lifecycle_preconditions_reject_races() {
        let initial = record();
        let quiesced = initial
            .transition(initial.version, &NamespaceTransition::Quiesce, 1)
            .unwrap();
        assert_eq!(
            quiesced.transition(quiesced.version, &NamespaceTransition::Retire, 1),
            Err(NamespaceError::InUse)
        );
        assert_eq!(
            quiesced.transition(initial.version, &NamespaceTransition::Retire, 0),
            Err(NamespaceError::Conflict)
        );
        assert_eq!(
            initial.transition(initial.version, &NamespaceTransition::Destroy, 0),
            Err(NamespaceError::Conflict)
        );
    }

    #[test]
    fn generation_and_incarnation_exhaustion_refuse_without_mutation() {
        let mut record = record();
        record.version.generation = u64::MAX;
        assert_eq!(
            record.transition(record.version, &NamespaceTransition::Quiesce, 0),
            Err(NamespaceError::Capacity)
        );
        record.version.generation = 1;
        record.version.incarnation = u64::MAX;
        record.status = NamespaceStatus::Tombstone;
        assert_eq!(
            record.transition(
                record.version,
                &NamespaceTransition::Recreate {
                    state_schema: record.state_schema.clone(),
                    quota: record.quota
                },
                0
            ),
            Err(NamespaceError::Capacity)
        );
    }

    #[test]
    fn tenant_actor_and_operation_key_framing_cannot_alias_or_leak_cross_scope() {
        let a = namespace_operation_key(&TenantId("a".into()), "bc", "d").unwrap();
        let b = namespace_operation_key(&TenantId("ab".into()), "c", "d").unwrap();
        assert_ne!(a, b);
        assert_ne!(
            a,
            namespace_operation_key(&TenantId("a".into()), "bob", "d").unwrap()
        );
        assert_eq!(
            namespace_tenant_prefix(&TenantId(String::new())),
            Err(NamespaceError::Invalid)
        );
        assert_eq!(
            namespace_operation_key(&TenantId("a".into()), "alice", "\0"),
            Err(NamespaceError::Invalid)
        );
    }
}
