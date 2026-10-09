use super::super::{
    codec::{Decoder, Encoder},
    record::outcome_tag,
    AtomicError, CommandRecord, Identity, Outcome,
};

/// The original body digest and disposition survive expiry. This is a closed
/// protective receipt, never a replayable business response or a fresh claim.
pub(in crate::atomic) struct ExpiredResult {
    pub command: Identity,
    pub attempt: u64,
    outcome: Outcome,
    digest: Identity,
    expires: u64,
    retired: u64,
}
impl ExpiredResult {
    pub fn new(record: &CommandRecord, now: u64) -> Result<Self, AtomicError> {
        if record.outcome == Outcome::Pending || now < record.result_expires {
            return Err(AtomicError::Invalid);
        }
        Ok(Self {
            command: record.id,
            attempt: record.attempt,
            outcome: record.outcome,
            digest: record.result_digest,
            expires: record.result_expires,
            retired: now,
        })
    }
    pub fn encode(&self) -> Vec<u8> {
        let mut out = Encoder::new(b"LCE\0\x01");
        out.identity(self.command);
        out.number(self.attempt);
        out.0.push(outcome_tag(self.outcome));
        out.identity(self.digest);
        out.number(self.expires);
        out.number(self.retired);
        out.0
    }
    pub fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LCE\0\x01", 94)?;
        let command = input.identity()?;
        let attempt = input.number()?;
        let outcome = match input.byte()? {
            1 => Outcome::Committed,
            2 => Outcome::Rejected,
            3 => Outcome::Aborted,
            _ => return Err(AtomicError::Corrupt),
        };
        let digest = input.identity()?;
        let expires = input.number()?;
        let retired = input.number()?;
        input.finish()?;
        if attempt == 0 || retired < expires {
            return Err(AtomicError::Corrupt);
        }
        Ok(Self {
            command,
            attempt,
            outcome,
            digest,
            expires,
            retired,
        })
    }
    pub fn verify(&self, record: &CommandRecord) -> Result<(), AtomicError> {
        if self.command != record.id
            || self.attempt != record.attempt
            || self.outcome != record.outcome
            || self.digest != record.result_digest
            || self.expires != record.result_expires
            || self.retired > record.clock_floor
        {
            return Err(AtomicError::Corrupt);
        }
        Ok(())
    }
}
