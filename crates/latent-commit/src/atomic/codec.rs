use super::{AtomicError, Identity, ReplayPolicy, ResultPolicy};
use latent_core::transaction_contract::{self as contract, Value};

pub(super) const METADATA_BYTES: usize = 64 * 1024;
pub(super) const RESULT_BYTES: usize =
    contract::VALUE_BYTES + contract::METADATA_BYTES + METADATA_BYTES;

pub(super) struct Encoder(pub Vec<u8>);
impl Encoder {
    pub fn new(magic: &[u8]) -> Self {
        Self(magic.to_vec())
    }
    pub fn number(&mut self, value: u64) {
        self.0.extend_from_slice(&value.to_le_bytes());
    }
    pub fn identity(&mut self, value: Identity) {
        self.0.extend_from_slice(&value.0);
    }
    pub fn text(&mut self, value: &str) -> Result<(), AtomicError> {
        let len = u16::try_from(value.len()).map_err(|_| AtomicError::Limit)?;
        self.0.extend_from_slice(&len.to_le_bytes());
        self.0.extend_from_slice(value.as_bytes());
        Ok(())
    }
    pub fn optional(&mut self, value: Option<&str>) -> Result<(), AtomicError> {
        self.0.push(u8::from(value.is_some()));
        if let Some(value) = value {
            self.text(value)?;
        }
        Ok(())
    }
    pub fn value(&mut self, value: &Value) -> Result<(), AtomicError> {
        value.validate().map_err(|_| AtomicError::Limit)?;
        self.0.extend_from_slice(
            &u32::try_from(value.bytes.len())
                .map_err(|_| AtomicError::Limit)?
                .to_le_bytes(),
        );
        self.0.extend_from_slice(&value.bytes);
        self.text(&value.media_type)?;
        self.0
            .push(u8::try_from(value.metadata.len()).map_err(|_| AtomicError::Limit)?);
        let mut pairs: Vec<_> = value.metadata.iter().collect();
        pairs.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
        for (key, value) in pairs {
            self.text(key)?;
            self.text(value)?;
        }
        Ok(())
    }
    pub fn policy(&mut self, policy: ResultPolicy) {
        self.0.push(match policy.replay {
            ReplayPolicy::Full => 1,
            ReplayPolicy::ReceiptOnly => 2,
        });
        self.number(policy.maximum_result_bytes as u64);
        self.number(policy.result_millis);
        self.number(policy.identity_millis);
        self.number(policy.maximum_attempts);
    }
    pub fn finish(self, maximum: usize) -> Result<Vec<u8>, AtomicError> {
        if self.0.len() > maximum {
            Err(AtomicError::Limit)
        } else {
            Ok(self.0)
        }
    }
}

pub(super) struct Decoder<'a> {
    bytes: &'a [u8],
    offset: usize,
}
impl<'a> Decoder<'a> {
    pub fn new(bytes: &'a [u8], magic: &[u8], maximum: usize) -> Result<Self, AtomicError> {
        if bytes.len() > maximum {
            return Err(AtomicError::Corrupt);
        }
        if !bytes.starts_with(magic) {
            return Err(AtomicError::UnsupportedFormat);
        }
        Ok(Self {
            bytes,
            offset: magic.len(),
        })
    }
    pub fn take(&mut self, length: usize) -> Result<&'a [u8], AtomicError> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(AtomicError::Corrupt)?;
        let bytes = self
            .bytes
            .get(self.offset..end)
            .ok_or(AtomicError::Corrupt)?;
        self.offset = end;
        Ok(bytes)
    }
    pub fn byte(&mut self) -> Result<u8, AtomicError> {
        Ok(self.take(1)?[0])
    }
    pub fn number(&mut self) -> Result<u64, AtomicError> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| AtomicError::Corrupt)?,
        ))
    }
    pub fn identity(&mut self) -> Result<Identity, AtomicError> {
        Ok(Identity(
            self.take(32)?
                .try_into()
                .map_err(|_| AtomicError::Corrupt)?,
        ))
    }
    pub fn text(&mut self, maximum: usize) -> Result<String, AtomicError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| AtomicError::Corrupt)?,
        ));
        if length > maximum {
            return Err(AtomicError::Corrupt);
        }
        Ok(std::str::from_utf8(self.take(length)?)
            .map_err(|_| AtomicError::Corrupt)?
            .to_owned())
    }
    pub fn optional(&mut self) -> Result<Option<String>, AtomicError> {
        match self.byte()? {
            0 => Ok(None),
            1 => Ok(Some(self.text(contract::IDENTITY_BYTES)?)),
            _ => Err(AtomicError::Corrupt),
        }
    }
    pub fn value(&mut self) -> Result<Value, AtomicError> {
        let length = u32::from_le_bytes(self.take(4)?.try_into().map_err(|_| AtomicError::Corrupt)?)
            as usize;
        if length > contract::VALUE_BYTES {
            return Err(AtomicError::Corrupt);
        }
        let bytes = self.take(length)?.to_vec();
        let media_type = self.text(contract::MEDIA_TYPE_BYTES)?;
        let count = usize::from(self.byte()?);
        if count > contract::METADATA_PAIRS {
            return Err(AtomicError::Corrupt);
        }
        let mut metadata = Vec::with_capacity(count);
        let mut total = 0usize;
        for _ in 0..count {
            let key = self.text(contract::IDENTITY_BYTES)?;
            let value = self.text(1024)?;
            total = total
                .checked_add(key.len() + value.len())
                .ok_or(AtomicError::Corrupt)?;
            if total > contract::METADATA_BYTES
                || metadata
                    .last()
                    .is_some_and(|(previous, _): &(String, String)| {
                        previous.as_bytes() >= key.as_bytes()
                    })
            {
                return Err(AtomicError::Corrupt);
            }
            metadata.push((key, value));
        }
        let value = Value {
            bytes,
            media_type,
            metadata,
        };
        value.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(value)
    }
    pub fn policy(&mut self) -> Result<ResultPolicy, AtomicError> {
        let replay = match self.byte()? {
            1 => ReplayPolicy::Full,
            2 => ReplayPolicy::ReceiptOnly,
            _ => return Err(AtomicError::Corrupt),
        };
        let policy = ResultPolicy {
            replay,
            maximum_result_bytes: usize::try_from(self.number()?)
                .map_err(|_| AtomicError::Corrupt)?,
            result_millis: self.number()?,
            identity_millis: self.number()?,
            maximum_attempts: self.number()?,
        };
        policy.validate().map_err(|_| AtomicError::Corrupt)?;
        Ok(policy)
    }
    pub fn finish(self) -> Result<(), AtomicError> {
        if self.offset == self.bytes.len() {
            Ok(())
        } else {
            Err(AtomicError::Corrupt)
        }
    }
}
