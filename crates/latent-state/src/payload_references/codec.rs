use super::{
    LocalPayloadIdentity, PayloadOwner, PayloadOwnerKind, PayloadReference, StoreError,
    MAX_REFERENCE_BYTES,
};
const FORMAT: &[u8; 5] = b"LBR\0\x01";
pub(super) fn kind(value: PayloadOwnerKind) -> u8 {
    match value {
        PayloadOwnerKind::State => 1,
        PayloadOwnerKind::Result => 2,
        PayloadOwnerKind::Effect => 3,
        PayloadOwnerKind::Snapshot => 4,
    }
}
pub(super) fn encode(reference: &PayloadReference) -> Result<Vec<u8>, StoreError> {
    let mut bytes = Vec::with_capacity(MAX_REFERENCE_BYTES);
    bytes.extend_from_slice(FORMAT);
    bytes.push(kind(reference.owner.kind));
    bytes.extend_from_slice(&reference.owner.incarnation.to_le_bytes());
    bytes.extend_from_slice(&reference.owner.identity);
    bytes.extend_from_slice(&reference.owner.generation.to_le_bytes());
    bytes.extend_from_slice(&reference.payload.provider_epoch.to_le_bytes());
    bytes.extend_from_slice(&reference.payload.provider_configuration);
    bytes.extend_from_slice(&reference.payload.digest);
    bytes.extend_from_slice(&reference.payload.size.to_le_bytes());
    for value in [
        &reference.owner.tenant,
        &reference.owner.namespace,
        &reference.owner.format,
        &reference.payload.tenant,
        &reference.payload.provider,
        &reference.payload.blob_namespace,
        &reference.payload.media_type,
    ] {
        bytes.extend_from_slice(
            &u16::try_from(value.len())
                .map_err(|_| StoreError::Capacity)?
                .to_le_bytes(),
        );
        bytes.extend_from_slice(value.as_bytes());
    }
    if bytes.len() > MAX_REFERENCE_BYTES {
        return Err(StoreError::Capacity);
    }
    Ok(bytes)
}
pub(super) fn decode(bytes: &[u8]) -> Result<PayloadReference, StoreError> {
    if bytes.len() > MAX_REFERENCE_BYTES || !bytes.starts_with(b"LBR\0") {
        return Err(StoreError::Corrupt);
    }
    if !bytes.starts_with(FORMAT) {
        return Err(StoreError::UnsupportedFormat);
    }
    let mut cursor = Cursor {
        bytes,
        position: FORMAT.len(),
    };
    let kind = match cursor.take(1)?[0] {
        1 => PayloadOwnerKind::State,
        2 => PayloadOwnerKind::Result,
        3 => PayloadOwnerKind::Effect,
        4 => PayloadOwnerKind::Snapshot,
        _ => return Err(StoreError::Corrupt),
    };
    let incarnation = cursor.number()?;
    let identity = cursor.identity()?;
    let generation = cursor.number()?;
    let provider_epoch = cursor.number()?;
    let provider_configuration = cursor.identity()?;
    let digest = cursor.identity()?;
    let size = cursor.number()?;
    let reference = PayloadReference {
        owner: PayloadOwner {
            tenant: cursor.text()?,
            namespace: cursor.text()?,
            incarnation,
            kind,
            identity,
            generation,
            format: cursor.text()?,
        },
        payload: LocalPayloadIdentity {
            tenant: cursor.text()?,
            provider: cursor.text()?,
            provider_epoch,
            provider_configuration,
            blob_namespace: cursor.text()?,
            digest,
            size,
            media_type: cursor.text()?,
        },
    };
    if cursor.position != bytes.len() {
        return Err(StoreError::Corrupt);
    }
    reference.validate().map_err(|_| StoreError::Corrupt)?;
    Ok(reference)
}
struct Cursor<'a> {
    bytes: &'a [u8],
    position: usize,
}
impl<'a> Cursor<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], StoreError> {
        let end = self
            .position
            .checked_add(length)
            .ok_or(StoreError::Corrupt)?;
        let value = self
            .bytes
            .get(self.position..end)
            .ok_or(StoreError::Corrupt)?;
        self.position = end;
        Ok(value)
    }
    fn number(&mut self) -> Result<u64, StoreError> {
        Ok(u64::from_le_bytes(
            self.take(8)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ))
    }
    fn identity(&mut self) -> Result<[u8; 32], StoreError> {
        self.take(32)?.try_into().map_err(|_| StoreError::Corrupt)
    }
    fn text(&mut self) -> Result<String, StoreError> {
        let length = usize::from(u16::from_le_bytes(
            self.take(2)?.try_into().map_err(|_| StoreError::Corrupt)?,
        ));
        if length == 0 || length > 128 {
            return Err(StoreError::Corrupt);
        }
        let value = std::str::from_utf8(self.take(length)?).map_err(|_| StoreError::Corrupt)?;
        super::checked_text(value).map_err(|_| StoreError::Corrupt)?;
        Ok(value.to_owned())
    }
}
