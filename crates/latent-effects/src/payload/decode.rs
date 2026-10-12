use super::{
    effect_identity, AuthorityError, PayloadRecord, Value, IDENTITY_BYTES,
    MAXIMUM_ENCODED_VALUE_BYTES, MAXIMUM_PAYLOAD_RECORD_BYTES, MEDIA_TYPE_BYTES, METADATA_BYTES,
    METADATA_PAIRS, RECORD_FORMAT, VALUE_BYTES, VALUE_FORMAT,
};

struct Reader<'a>(&'a [u8]);

impl<'a> Reader<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], AuthorityError> {
        let (value, remaining) = self
            .0
            .split_at_checked(length)
            .ok_or(AuthorityError::Invalid)?;
        self.0 = remaining;
        Ok(value)
    }

    fn short(&mut self, maximum: usize) -> Result<&'a [u8], AuthorityError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?
                .try_into()
                .map_err(|_| AuthorityError::Invalid)?,
        ));
        if length > maximum {
            return Err(AuthorityError::Capacity);
        }
        self.take(length)
    }

    fn length(&mut self, maximum: usize) -> Result<usize, AuthorityError> {
        let length = usize::try_from(u32::from_le_bytes(
            self.take(4)?
                .try_into()
                .map_err(|_| AuthorityError::Invalid)?,
        ))
        .map_err(|_| AuthorityError::Capacity)?;
        if length > maximum {
            return Err(AuthorityError::Capacity);
        }
        Ok(length)
    }
}

pub(super) fn record(bytes: &[u8]) -> Result<PayloadRecord, AuthorityError> {
    if bytes.len() > MAXIMUM_PAYLOAD_RECORD_BYTES {
        return Err(AuthorityError::Capacity);
    }
    if !bytes.starts_with(RECORD_FORMAT) {
        return Err(AuthorityError::UnsupportedFormat);
    }
    let mut reader = Reader(&bytes[5..]);
    let identity = reader
        .take(32)?
        .try_into()
        .map_err(|_| AuthorityError::Invalid)?;
    let length = reader.length(MAXIMUM_ENCODED_VALUE_BYTES)?;
    let encoded = reader.take(length)?;
    if !reader.0.is_empty() {
        return Err(AuthorityError::Invalid);
    }
    let value = value(encoded)?;
    Ok(PayloadRecord {
        effect: effect_identity::render(&identity),
        value,
    })
}

fn value(bytes: &[u8]) -> Result<Value, AuthorityError> {
    if !bytes.starts_with(VALUE_FORMAT) {
        return Err(AuthorityError::UnsupportedFormat);
    }
    let mut reader = Reader(&bytes[5..]);
    let length = reader.length(VALUE_BYTES)?;
    let payload = reader.take(length)?;
    let media_type = text(reader.short(MEDIA_TYPE_BYTES)?)?;
    if media_type.is_empty() || !media_type.is_ascii() || media_type.contains('\0') {
        return Err(AuthorityError::Invalid);
    }
    let count = usize::from(u16::from_le_bytes(
        reader
            .take(2)?
            .try_into()
            .map_err(|_| AuthorityError::Invalid)?,
    ));
    if count > METADATA_PAIRS {
        return Err(AuthorityError::Capacity);
    }
    // At most 32 borrowed entries. Application buffers are allocated only
    // after every count, length, type, duplicate and trailing byte is checked.
    let mut metadata = Vec::with_capacity(count);
    let mut metadata_bytes = 0_usize;
    let mut previous: Option<&str> = None;
    for _ in 0..count {
        let key = text(reader.short(IDENTITY_BYTES)?)?;
        let value = text(reader.short(1024)?)?;
        if key.is_empty()
            || key.contains('\0')
            || previous.is_some_and(|previous| previous.as_bytes() >= key.as_bytes())
        {
            return Err(AuthorityError::Invalid);
        }
        previous = Some(key);
        metadata_bytes = metadata_bytes
            .checked_add(key.len())
            .and_then(|bytes| bytes.checked_add(value.len()))
            .ok_or(AuthorityError::Capacity)?;
        if metadata_bytes > METADATA_BYTES {
            return Err(AuthorityError::Capacity);
        }
        metadata.push((key, value));
    }
    if !reader.0.is_empty() {
        return Err(AuthorityError::Invalid);
    }
    Ok(Value {
        bytes: payload.to_vec(),
        media_type: media_type.into(),
        metadata: metadata
            .into_iter()
            .map(|(key, value)| (key.into(), value.into()))
            .collect(),
    })
}

fn text(bytes: &[u8]) -> Result<&str, AuthorityError> {
    std::str::from_utf8(bytes).map_err(|_| AuthorityError::Invalid)
}
