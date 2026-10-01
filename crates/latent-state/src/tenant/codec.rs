use super::{
    guard_key, identity, quota_key, TenantQuota, TenantRecord, TenantUsage, GUARD_BYTES,
    MAXIMUM_TENANTS, RECORD_BYTES,
};
use crate::embedded::{ReadView, StoreError};
use latent_core::TenantId;
use sha2::{Digest, Sha256};
const GUARD_MAGIC: &[u8] = b"LTG\x01";
const RECORD_MAGIC: &[u8] = b"LTQ\x01";

pub(super) fn hash(bytes: &[u8]) -> [u8; 32] {
    Sha256::digest(bytes).into()
}
pub(super) fn text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(
        &u16::try_from(value.len())
            .expect("bounded identity")
            .to_le_bytes(),
    );
    bytes.extend_from_slice(value.as_bytes());
}
pub(super) fn quota_bytes(quota: &TenantQuota) -> Vec<u8> {
    let mut bytes = b"lt-quota-declaration-v1\0".to_vec();
    text(&mut bytes, &quota.tenant.0);
    for value in quota.limits.values() {
        bytes.extend_from_slice(&value.to_le_bytes());
    }
    bytes
}

#[derive(Clone)]
pub(super) struct Guard {
    pub entries: Vec<(TenantId, [u8; 32])>,
}
impl Guard {
    pub fn new(quotas: &[TenantQuota]) -> Result<Self, StoreError> {
        if quotas.is_empty() || quotas.len() > MAXIMUM_TENANTS {
            return Err(StoreError::Invalid);
        }
        let mut entries = quotas
            .iter()
            .map(|quota| Ok((quota.tenant.clone(), quota.digest()?)))
            .collect::<Result<Vec<_>, StoreError>>()?;
        entries.sort_by(|left, right| left.0 .0.cmp(&right.0 .0));
        if entries.windows(2).any(|pair| pair[0].0 == pair[1].0) {
            return Err(StoreError::Invalid);
        }
        Ok(Self { entries })
    }
    pub fn encode(&self) -> Vec<u8> {
        let mut bytes = GUARD_MAGIC.to_vec();
        bytes.push(u8::try_from(self.entries.len()).expect("bounded tenant count"));
        for (tenant, digest) in &self.entries {
            text(&mut bytes, &tenant.0);
            bytes.extend_from_slice(digest);
        }
        bytes.extend_from_slice(&hash(&bytes));
        bytes
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() > GUARD_BYTES {
            return Err(StoreError::Corrupt);
        }
        let mut input = Input::checked(bytes, GUARD_MAGIC)?;
        let count = usize::from(input.take(1)?[0]);
        if count == 0 || count > MAXIMUM_TENANTS {
            return Err(StoreError::Corrupt);
        }
        let mut entries = Vec::with_capacity(count);
        for _ in 0..count {
            let tenant = input.tenant()?;
            let digest = input
                .take(32)?
                .try_into()
                .map_err(|_| StoreError::Corrupt)?;
            if entries
                .last()
                .is_some_and(|previous: &(TenantId, [u8; 32])| previous.0 .0 >= tenant.0)
            {
                return Err(StoreError::Corrupt);
            }
            entries.push((tenant, digest));
        }
        if !input.bytes.is_empty() {
            return Err(StoreError::Corrupt);
        }
        Ok(Self { entries })
    }
    fn require(&self, quota: &TenantQuota) -> Result<(), StoreError> {
        let (_, digest) = self
            .entries
            .iter()
            .find(|(tenant, _)| *tenant == quota.tenant)
            .ok_or(StoreError::UnsupportedFormat)?;
        if *digest != quota.digest()? {
            return Err(StoreError::UnsupportedFormat);
        }
        Ok(())
    }
}

pub(super) fn encode_record(record: &TenantRecord) -> Result<Vec<u8>, StoreError> {
    record.validate()?;
    let mut bytes = RECORD_MAGIC.to_vec();
    text(&mut bytes, &record.quota.tenant.0);
    bytes.extend_from_slice(&record.generation.to_le_bytes());
    for usage in [record.quota.limits, record.usage] {
        for value in usage.values() {
            bytes.extend_from_slice(&value.to_le_bytes());
        }
    }
    if bytes.len() > RECORD_BYTES - 32 {
        return Err(StoreError::Capacity);
    }
    bytes.resize(RECORD_BYTES - 32, 0);
    bytes.extend_from_slice(&hash(&bytes));
    Ok(bytes)
}
pub(super) fn decode_record(bytes: &[u8]) -> Result<TenantRecord, StoreError> {
    if bytes.len() != RECORD_BYTES {
        return Err(StoreError::Corrupt);
    }
    let mut input = Input::checked(bytes, RECORD_MAGIC)?;
    let tenant = input.tenant()?;
    let generation = input.number()?;
    let limits = input.usage()?;
    let usage = input.usage()?;
    if input.bytes.iter().any(|byte| *byte != 0) {
        return Err(StoreError::Corrupt);
    }
    let record = TenantRecord {
        quota: TenantQuota { tenant, limits },
        generation,
        usage,
    };
    record.validate().map_err(|_| StoreError::Corrupt)?;
    Ok(record)
}

pub(super) struct Captured {
    pub guard: Vec<u8>,
    pub record: TenantRecord,
    pub bytes: Vec<u8>,
}
pub(super) fn capture(view: &ReadView, tenant: &TenantId) -> Result<Option<Captured>, StoreError> {
    let guard = view.get_bounded(&guard_key(), GUARD_BYTES)?;
    let bytes = view.get_bounded(&quota_key(tenant)?, RECORD_BYTES)?;
    let Some(guard) = guard else {
        return if bytes.is_none() {
            Ok(None)
        } else {
            Err(StoreError::Corrupt)
        };
    };
    let declaration = Guard::decode(&guard)?;
    let bytes = bytes.ok_or(StoreError::UnsupportedFormat)?;
    let record = TenantRecord::decode(&bytes)?;
    if record.quota.tenant != *tenant {
        return Err(StoreError::Corrupt);
    }
    declaration.require(&record.quota)?;
    Ok(Some(Captured {
        guard,
        record,
        bytes,
    }))
}

struct Input<'a> {
    bytes: &'a [u8],
}
impl<'a> Input<'a> {
    fn checked(bytes: &'a [u8], magic: &[u8]) -> Result<Self, StoreError> {
        if bytes.len() < magic.len() + 32 {
            return Err(StoreError::Corrupt);
        }
        let (data, checksum) = bytes.split_at(bytes.len() - 32);
        if hash(data) != checksum {
            return Err(StoreError::Corrupt);
        }
        Ok(Self {
            bytes: data
                .strip_prefix(magic)
                .ok_or(StoreError::UnsupportedFormat)?,
        })
    }
    fn take(&mut self, length: usize) -> Result<&'a [u8], StoreError> {
        let value = self.bytes.get(..length).ok_or(StoreError::Corrupt)?;
        self.bytes = &self.bytes[length..];
        Ok(value)
    }
    fn number(&mut self) -> Result<u64, StoreError> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ))
    }
    fn tenant(&mut self) -> Result<TenantId, StoreError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ));
        if length == 0 || length > 256 {
            return Err(StoreError::Corrupt);
        }
        let tenant = TenantId(
            std::str::from_utf8(self.take(length)?)
                .map_err(|_| StoreError::Corrupt)?
                .to_owned(),
        );
        identity(&tenant).map_err(|_| StoreError::Corrupt)?;
        Ok(tenant)
    }
    fn usage(&mut self) -> Result<TenantUsage, StoreError> {
        let mut values = [0; 12];
        for value in &mut values {
            *value = self.number()?;
        }
        Ok(TenantUsage::from_values(values))
    }
}
