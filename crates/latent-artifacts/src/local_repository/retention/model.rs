mod lexical;
use super::{
    capacity, conflict, corrupt, unavailable_target, LifecycleScope, PlatformError, PublicationRef,
    PublicationRetentionAction, PublicationRetentionPin, PublicationRetentionReceipt,
    PublicationRetentionRequest, MAX_PUBLICATION_RETENTION_PINS,
    MAX_PUBLICATION_RETENTION_RECEIPTS,
};
use serde::{Deserialize, Serialize};

pub(super) const MAX_HEAD: usize = 4 * 1024 * 1024;
pub(super) const MAX_REQUEST: usize = 64 * 1024;
pub(super) const MAX_INTENT: usize = MAX_HEAD + 4096;
pub(super) const MARKER: &[u8] = b"lsf-release-lifecycle-retention-v1\n";
const VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Head {
    pub version: u32,
    pub authority: [u8; 32],
    pub mode: [u8; 32],
    pub revision: u64,
    pub pins: Vec<PublicationRetentionPin>,
    pub receipts: Vec<PublicationRetentionReceipt>,
}
impl Head {
    pub fn empty(mode: [u8; 32]) -> Self {
        Self {
            version: VERSION,
            authority: [0; 32],
            mode,
            revision: 0,
            pins: Vec::new(),
            receipts: Vec::new(),
        }
    }
    pub fn validate(&self, mode: [u8; 32]) -> Result<(), PlatformError> {
        if self.version != VERSION
            || self.mode != mode
            || self.pins.len() > MAX_PUBLICATION_RETENTION_PINS
            || self.receipts.len() > MAX_PUBLICATION_RETENTION_RECEIPTS
            || (self.revision == 0 && (!self.pins.is_empty() || !self.receipts.is_empty()))
            || (self.revision != 0 && self.receipts.is_empty())
        {
            return Err(corrupt());
        }
        for pin in &self.pins {
            pin.publication.scope.validate().map_err(|_| corrupt())?;
            pin.actor.validate().map_err(|_| corrupt())?;
            crate::publication_retention::token(&pin.operation_id).map_err(|_| corrupt())?;
            if pin.pinned_generation == 0 {
                return Err(corrupt());
            }
        }
        if self
            .pins
            .windows(2)
            .any(|p| p[0].publication.id >= p[1].publication.id)
        {
            return Err(corrupt());
        }
        let mut ids = std::collections::BTreeSet::new();
        let start = self
            .revision
            .checked_sub(self.receipts.len() as u64)
            .ok_or_else(corrupt)?;
        for (index, receipt) in self.receipts.iter().enumerate() {
            receipt.request.validate().map_err(|_| corrupt())?;
            encode(&receipt.request, MAX_REQUEST).map_err(|_| corrupt())?;
            if receipt.revision != start + index as u64 + 1
                || !ids.insert((&receipt.request.scope, &receipt.request.operation_id))
            {
                return Err(corrupt());
            }
        }
        Ok(())
    }
    pub fn pin(
        &self,
        reference: &PublicationRef,
    ) -> Result<Option<&PublicationRetentionPin>, PlatformError> {
        let found = self
            .pins
            .binary_search_by(|pin| pin.publication.id.cmp(&reference.id));
        match found {
            Ok(index) if self.pins[index].publication.scope == reference.scope => {
                Ok(Some(&self.pins[index]))
            }
            Ok(_) => Err(unavailable_target()),
            Err(_) => Ok(None),
        }
    }
    pub fn receipt(
        &self,
        scope: &LifecycleScope,
        id: &str,
    ) -> Option<&PublicationRetentionReceipt> {
        self.receipts
            .iter()
            .find(|r| r.request.scope == *scope && r.request.operation_id == id)
    }
    pub fn next(&self, request: &PublicationRetentionRequest) -> Result<Self, PlatformError> {
        let mut next = self.clone();
        next.revision = self.revision.checked_add(1).ok_or_else(capacity)?;
        for target in &request.targets {
            let index = next
                .pins
                .binary_search_by(|pin| pin.publication.id.cmp(&target.publication.id));
            match (request.action, index) {
                (PublicationRetentionAction::Pin, Err(index)) => {
                    if next.pins.len() == MAX_PUBLICATION_RETENTION_PINS {
                        return Err(capacity());
                    }
                    next.pins.insert(
                        index,
                        PublicationRetentionPin {
                            publication: target.publication.clone(),
                            pinned_generation: target.expected_generation,
                            actor: request.actor.clone(),
                            operation_id: request.operation_id.clone(),
                        },
                    );
                }
                (PublicationRetentionAction::Unpin, Ok(index)) => {
                    next.pins.remove(index);
                }
                _ => return Err(conflict()),
            }
        }
        if next.receipts.len() == MAX_PUBLICATION_RETENTION_RECEIPTS {
            next.receipts.remove(0);
        }
        next.receipts.push(PublicationRetentionReceipt {
            request: request.clone(),
            revision: next.revision,
        });
        next.validate(self.mode)?;
        encode(&next, MAX_HEAD)?;
        Ok(next)
    }
}

/// Hard byte limit applies while encoding, not after an unbounded allocation.
pub(super) fn encode<T: Serialize>(value: &T, maximum: usize) -> Result<Vec<u8>, PlatformError> {
    struct Bounded {
        bytes: Vec<u8>,
        maximum: usize,
    }
    impl std::io::Write for Bounded {
        fn write(&mut self, input: &[u8]) -> std::io::Result<usize> {
            let size = self
                .bytes
                .len()
                .checked_add(input.len())
                .filter(|n| *n <= self.maximum)
                .ok_or_else(|| std::io::Error::other("retention encoding bound"))?;
            self.bytes
                .try_reserve_exact(size - self.bytes.len())
                .map_err(|_| std::io::Error::other("retention allocation bound"))?;
            self.bytes.extend_from_slice(input);
            Ok(input.len())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }
    let mut writer = Bounded {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| capacity())?;
    Ok(writer.bytes)
}
pub(super) fn decode<T>(bytes: &[u8], maximum: usize) -> Result<T, PlatformError>
where
    T: serde::de::DeserializeOwned + Serialize,
{
    if bytes.len() > maximum {
        return Err(capacity());
    }
    lexical::check(bytes)?;
    let value: T = serde_json::from_slice(bytes).map_err(|_| corrupt())?;
    if encode(&value, maximum)? != bytes {
        return Err(corrupt());
    }
    Ok(value)
}
pub(super) fn digest(bytes: &[u8]) -> [u8; 32] {
    use sha2::Digest;
    sha2::Sha256::digest(bytes).into()
}
