use crate::atomic::{
    codec::{Decoder, Encoder},
    record::row_key,
    AtomicError, Identity,
};
use latent_state::embedded::{Family, RowKey};

pub(in crate::atomic) const RETRY_INDEX_PREFIX: &[u8] = b"command-retry-index-v1\0";

/// Exact backpointer installed in the SAME retry admission transaction. It
/// permits bounded retirement without scanning unrelated retry identities.
pub(in crate::atomic) struct RetryIndex {
    pub command: Identity,
    pub attempt: u64,
    pub retry: Identity,
}
impl RetryIndex {
    pub fn new(command: Identity, attempt: u64, retry: Identity) -> Result<Self, AtomicError> {
        let index = Self {
            command,
            attempt,
            retry,
        };
        index.validate()?;
        Ok(index)
    }
    pub fn row_key(command: Identity, attempt: u64) -> RowKey {
        row_key(
            Family::Maintenance,
            RETRY_INDEX_PREFIX,
            command,
            Some(attempt),
        )
    }
    pub fn key(&self) -> RowKey {
        Self::row_key(self.command, self.attempt)
    }
    pub fn retry_key(&self) -> RowKey {
        row_key(Family::Maintenance, b"command-retry-v1\0", self.retry, None)
    }
    pub fn encode(&self) -> Result<Vec<u8>, AtomicError> {
        self.validate()?;
        let mut output = Encoder::new(b"LCI\0\x01");
        output.identity(self.command);
        output.number(self.attempt);
        output.identity(self.retry);
        output.finish(77)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LCI\0\x01", 77)?;
        let index = Self {
            command: input.identity()?,
            attempt: input.number()?,
            retry: input.identity()?,
        };
        input.finish()?;
        index.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(index)
    }
    fn validate(&self) -> Result<(), AtomicError> {
        if self.command == Identity([0; 32])
            || self.retry == Identity([0; 32])
            || !(2..=16).contains(&self.attempt)
        {
            return Err(AtomicError::Invalid);
        }
        Ok(())
    }
}
