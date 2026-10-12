//! A closed, bounded external recovery checkpoint. These are durable identity
//! and floor descriptions, never a live clock, dispatch grant or restore proof.

use sha2::{Digest, Sha256};

use super::{StoreError, StoreIdentity, MAXIMUM_IDENTITY_BYTES};

const FORMAT: &[u8] = b"LTC\0\x01";
const HEADER_BYTES: usize = 5 + 2 + 4 * 8;
const CHECKSUM_BYTES: usize = 32;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExternalCheckpoint {
    identity: StoreIdentity,
    generation: u64,
    protected_clock_epoch: u64,
    dispatch_owner_epoch: u64,
    clock_floor_millis: u64,
}

impl ExternalCheckpoint {
    pub const MAXIMUM_ENCODED_BYTES: usize = HEADER_BYTES + MAXIMUM_IDENTITY_BYTES + CHECKSUM_BYTES;

    pub fn initial(
        identity: StoreIdentity,
        protected_clock_epoch: u64,
        dispatch_owner_epoch: u64,
        clock_floor_millis: u64,
    ) -> Result<Self, StoreError> {
        Self::checked(
            identity,
            1,
            protected_clock_epoch,
            dispatch_owner_epoch,
            clock_floor_millis,
        )
    }

    fn checked(
        identity: StoreIdentity,
        generation: u64,
        protected_clock_epoch: u64,
        dispatch_owner_epoch: u64,
        clock_floor_millis: u64,
    ) -> Result<Self, StoreError> {
        if generation == 0
            || protected_clock_epoch == 0
            || dispatch_owner_epoch == 0
            || clock_floor_millis == 0
        {
            return Err(StoreError::Invalid);
        }
        Ok(Self {
            identity,
            generation,
            protected_clock_epoch,
            dispatch_owner_epoch,
            clock_floor_millis,
        })
    }

    #[must_use]
    pub fn identity(&self) -> &StoreIdentity {
        &self.identity
    }

    #[must_use]
    pub fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub fn protected_clock_epoch(&self) -> u64 {
        self.protected_clock_epoch
    }

    #[must_use]
    pub fn dispatch_owner_epoch(&self) -> u64 {
        self.dispatch_owner_epoch
    }

    #[must_use]
    pub fn clock_floor_millis(&self) -> u64 {
        self.clock_floor_millis
    }

    /// Advance all retained monotonic floors. The caller must still establish
    /// actual current clock/store ownership; constructing this metadata grants
    /// neither dispatch nor permission to overwrite an external checkpoint.
    pub fn advance(
        &self,
        protected_clock_epoch: u64,
        dispatch_owner_epoch: u64,
        clock_floor_millis: u64,
    ) -> Result<Self, StoreError> {
        if protected_clock_epoch < self.protected_clock_epoch
            || dispatch_owner_epoch < self.dispatch_owner_epoch
            || clock_floor_millis < self.clock_floor_millis
        {
            return Err(StoreError::Conflict);
        }
        let generation = self.generation.checked_add(1).ok_or(StoreError::Capacity)?;
        Self::checked(
            self.identity.clone(),
            generation,
            protected_clock_epoch,
            dispatch_owner_epoch,
            clock_floor_millis,
        )
    }

    /// Compare a retained external checkpoint with one actual coherent store
    /// observation. A later business floor is permitted; an older owner/floor
    /// requires explicit restore review and cannot establish continuity.
    pub fn check_store(
        &self,
        identity: &StoreIdentity,
        dispatch_owner_epoch: u64,
        clock_floor_millis: u64,
    ) -> Result<(), StoreError> {
        if self.identity != *identity {
            return Err(StoreError::Corrupt);
        }
        if dispatch_owner_epoch != self.dispatch_owner_epoch
            || clock_floor_millis < self.clock_floor_millis
        {
            return Err(StoreError::Conflict);
        }
        Ok(())
    }

    #[must_use]
    pub fn encode(&self) -> Vec<u8> {
        let mut encoded =
            Vec::with_capacity(HEADER_BYTES + self.identity.as_str().len() + CHECKSUM_BYTES);
        encoded.extend_from_slice(FORMAT);
        encoded.extend_from_slice(
            &u16::try_from(self.identity.as_str().len())
                .expect("validated checkpoint identity length")
                .to_be_bytes(),
        );
        for value in [
            self.generation,
            self.protected_clock_epoch,
            self.dispatch_owner_epoch,
            self.clock_floor_millis,
        ] {
            encoded.extend_from_slice(&value.to_be_bytes());
        }
        encoded.extend_from_slice(self.identity.as_str().as_bytes());
        let checksum = Sha256::digest(&encoded);
        encoded.extend_from_slice(&checksum);
        encoded
    }

    pub fn decode(encoded: &[u8]) -> Result<Self, StoreError> {
        if encoded.len() < FORMAT.len() || encoded.len() > Self::MAXIMUM_ENCODED_BYTES {
            return Err(StoreError::Corrupt);
        }
        if !encoded.starts_with(FORMAT) {
            return Err(StoreError::UnsupportedFormat);
        }
        if encoded.len() < HEADER_BYTES + 1 + CHECKSUM_BYTES {
            return Err(StoreError::Corrupt);
        }
        let identity_bytes = usize::from(u16::from_be_bytes([encoded[5], encoded[6]]));
        if identity_bytes == 0
            || identity_bytes > MAXIMUM_IDENTITY_BYTES
            || encoded.len() != HEADER_BYTES + identity_bytes + CHECKSUM_BYTES
        {
            return Err(StoreError::Corrupt);
        }
        let checksum_offset = encoded.len() - CHECKSUM_BYTES;
        let checksum: [u8; CHECKSUM_BYTES] = Sha256::digest(&encoded[..checksum_offset]).into();
        if checksum.as_slice() != &encoded[checksum_offset..] {
            return Err(StoreError::Corrupt);
        }
        let value = |index: usize| {
            u64::from_be_bytes(
                encoded[7 + index * 8..7 + (index + 1) * 8]
                    .try_into()
                    .expect("checked checkpoint header length"),
            )
        };
        let identity = std::str::from_utf8(&encoded[HEADER_BYTES..checksum_offset])
            .map_err(|_| StoreError::Corrupt)?;
        Self::checked(
            StoreIdentity::new(identity.to_owned()).map_err(|_| StoreError::Corrupt)?,
            value(0),
            value(1),
            value(2),
            value(3),
        )
        .map_err(|_| StoreError::Corrupt)
    }
}

#[cfg(test)]
mod tests;
