//! Bind an exclusively starting protected store before publishing any consumer.
//! A configured label alone cannot identify the database restored from backup.

use crate::embedded::{
    AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError,
};

pub const KEY: &[u8] = b"transaction-store-identity-v1\0";
const FORMAT: &[u8] = b"LSI\0\x01";
const MAXIMUM_IDENTITY_BYTES: usize = 128;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoreIdentity(String);

impl StoreIdentity {
    pub fn new(identity: String) -> Result<Self, StoreError> {
        if identity.is_empty()
            || identity.len() > MAXIMUM_IDENTITY_BYTES
            || !identity
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
        {
            return Err(StoreError::Invalid);
        }
        Ok(Self(identity))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }

    #[must_use]
    pub fn row_key() -> RowKey {
        RowKey {
            family: Family::Maintenance,
            key: KEY.to_vec(),
        }
    }

    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut encoded = Vec::with_capacity(FORMAT.len() + 2 + self.0.len());
        encoded.extend_from_slice(FORMAT);
        // Constructor bounds this identity before allocation or conversion.
        encoded.extend_from_slice(
            &u16::try_from(self.0.len())
                .expect("validated store identity length")
                .to_be_bytes(),
        );
        encoded.extend_from_slice(self.0.as_bytes());
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, StoreError> {
        if !encoded.starts_with(FORMAT) {
            return Err(StoreError::UnsupportedFormat);
        }
        let Some(length) = encoded.get(FORMAT.len()..FORMAT.len() + 2) else {
            return Err(StoreError::Corrupt);
        };
        let length = usize::from(u16::from_be_bytes([length[0], length[1]]));
        if length == 0
            || length > MAXIMUM_IDENTITY_BYTES
            || encoded.len() != FORMAT.len() + 2 + length
        {
            return Err(StoreError::Corrupt);
        }
        let identity =
            std::str::from_utf8(&encoded[FORMAT.len() + 2..]).map_err(|_| StoreError::Corrupt)?;
        Self::new(identity.to_owned()).map_err(|_| StoreError::Corrupt)
    }

    pub fn validate_row(key: &RowKey, value: &[u8]) -> Result<(), StoreError> {
        if key.family != Family::Maintenance || key.key != KEY {
            return Err(StoreError::UnsupportedFormat);
        }
        Self::decode(value).map(|_| ())
    }

    pub fn inspect(view: &ReadView) -> Result<Option<Self>, StoreError> {
        view.get(&Self::row_key())?
            .as_deref()
            .map(Self::decode)
            .transpose()
    }

    /// Only the exclusive fresh startup may publish this preparation, before
    /// sharing the protected owner with any command, catalog or dispatcher.
    /// Existing rows without an installed identity require explicit migration;
    /// a mismatch, corrupt record or unknown format can never be overwritten.
    pub fn prepare_initialization(
        &self,
        view: &ReadView,
    ) -> Result<Option<AtomicBatch>, StoreError> {
        if let Some(current) = Self::inspect(view)? {
            return if current == *self {
                Ok(None)
            } else {
                Err(StoreError::Corrupt)
            };
        }
        for family in [
            Family::Namespace,
            Family::State,
            Family::Tombstone,
            Family::Command,
            Family::Result,
            Family::Outbox,
            Family::Attempt,
            Family::Inbox,
            Family::PayloadReference,
            Family::Maintenance,
        ] {
            if !view
                .scan_after(family, b"", None, 1, 2 * 1024 * 1024 + 8192)?
                .rows
                .is_empty()
            {
                return Err(StoreError::UnsupportedFormat);
            }
        }
        let key = Self::row_key();
        Ok(Some(AtomicBatch {
            expectations: vec![ExpectedRow {
                key: key.clone(),
                value: None,
            }],
            mutations: vec![RowMutation {
                key,
                value: Some(self.encode()),
            }],
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::embedded::{EmbeddedStore, StoreLimits};

    fn store() -> (EmbeddedStore, tempfile::TempDir) {
        let directory = tempfile::tempdir().unwrap();
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(directory.path().join("identity.redb"))
            .unwrap();
        (
            EmbeddedStore::open_file(file, StoreLimits::default()).unwrap(),
            directory,
        )
    }

    #[test]
    fn identity_initializes_only_an_empty_store_and_never_overwrites_a_mismatch() {
        let (store, _directory) = store();
        let identity = StoreIdentity::new("production-A".into()).unwrap();
        let view = store.snapshot().unwrap();
        let batch = identity.prepare_initialization(&view).unwrap().unwrap();
        drop(view);
        store.apply(batch).unwrap();
        let view = store.snapshot().unwrap();
        assert!(identity.prepare_initialization(&view).unwrap().is_none());
        assert_eq!(StoreIdentity::inspect(&view).unwrap(), Some(identity));
        assert_eq!(
            StoreIdentity::new("production-B".into())
                .unwrap()
                .prepare_initialization(&view)
                .unwrap_err(),
            StoreError::Corrupt
        );
        drop(view);

        let (unbound, _unbound_directory) = self::store();
        unbound
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: RowKey {
                        family: Family::Namespace,
                        key: b"existing".to_vec(),
                    },
                    value: Some(b"retained".to_vec()),
                }],
            })
            .unwrap();
        assert_eq!(
            StoreIdentity::new("production-A".into())
                .unwrap()
                .prepare_initialization(&unbound.snapshot().unwrap())
                .unwrap_err(),
            StoreError::UnsupportedFormat
        );
    }

    #[test]
    fn identity_decoder_rejects_unknown_truncated_noncanonical_and_foreign_rows() {
        let identity = StoreIdentity::new("production-A".into()).unwrap();
        let bytes = identity.encode();
        assert_eq!(StoreIdentity::decode(&bytes).unwrap(), identity);
        for length in FORMAT.len()..bytes.len() {
            assert_eq!(
                StoreIdentity::decode(&bytes[..length]),
                Err(StoreError::Corrupt)
            );
        }
        let mut unknown = bytes.clone();
        unknown[4] = 2;
        assert_eq!(
            StoreIdentity::decode(&unknown),
            Err(StoreError::UnsupportedFormat)
        );
        let mut noncanonical = bytes.clone();
        *noncanonical.last_mut().unwrap() = b'/';
        assert_eq!(
            StoreIdentity::decode(&noncanonical),
            Err(StoreError::Corrupt)
        );
        let mut trailing = bytes.clone();
        trailing.push(0);
        assert_eq!(StoreIdentity::decode(&trailing), Err(StoreError::Corrupt));
        let mut key = StoreIdentity::row_key();
        key.key.push(0);
        assert_eq!(
            StoreIdentity::validate_row(&key, &bytes),
            Err(StoreError::UnsupportedFormat)
        );
    }
}
