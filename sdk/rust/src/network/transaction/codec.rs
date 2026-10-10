//! Allocation-free Protobuf shape checks before the maintained Prost decoder.
//! The original call lease reserves this graph allowance through retirement.

use latent_rpc::phase4::ValidationError;
use prost::bytes::Buf;
use prost::Message;
use tonic::codec::{BufferSettings, Codec, DecodeBuf, Decoder};
use tonic::Status;
use tonic_prost::{ProstCodec, ProstDecoder, ProstEncoder};

pub(super) const GRAPH_BYTES: usize = 8 * 1024 * 1024;
const MAX_NODES: usize = 4096;
const MAX_TAGS: usize = 65536;

pub(super) struct Budget {
    bytes: usize,
    nodes: usize,
    tags: usize,
}

impl Budget {
    pub(super) const fn new() -> Self {
        Self {
            bytes: GRAPH_BYTES,
            nodes: MAX_NODES,
            tags: MAX_TAGS,
        }
    }

    fn charge(&mut self, bytes: usize) -> Result<(), ValidationError> {
        self.bytes = self
            .bytes
            .checked_sub(bytes)
            .ok_or(ValidationError::Capacity)?;
        Ok(())
    }

    pub(super) fn node(&mut self, size: usize, depth: usize) -> Result<(), ValidationError> {
        if depth > 16 {
            return Err(ValidationError::Capacity);
        }
        self.nodes = self.nodes.checked_sub(1).ok_or(ValidationError::Capacity)?;
        self.charge(size)
    }

    pub(super) fn data(&mut self, bytes: usize) -> Result<(), ValidationError> {
        self.charge(bytes.checked_mul(3).ok_or(ValidationError::Capacity)?)
    }
}

#[derive(Clone, Copy)]
pub(super) enum Kind {
    Bool,
    U32,
    U64,
    I32,
    String,
    Bytes,
    Message(&'static Schema),
    Map(&'static Schema),
}

pub(super) struct Field {
    pub number: u32,
    pub kind: Kind,
    pub repeated: bool,
    pub maximum: u16,
    pub oneof: usize,
}

pub(super) struct Schema {
    pub allocation: usize,
    pub fields: &'static [Field],
}

fn varint(bytes: &mut &[u8]) -> Result<u64, ValidationError> {
    let mut result = 0_u64;
    for offset in 0..10 {
        let (&byte, rest) = bytes.split_first().ok_or(ValidationError::Shape)?;
        *bytes = rest;
        if offset == 9 && byte > 1 {
            return Err(ValidationError::Shape);
        }
        result |= u64::from(byte & 127) << (7 * offset);
        if byte < 128 {
            return Ok(result);
        }
    }
    Err(ValidationError::Shape)
}

fn take<'a>(bytes: &mut &'a [u8], size: usize) -> Result<&'a [u8], ValidationError> {
    if size > bytes.len() {
        return Err(ValidationError::Shape);
    }
    let (value, rest) = bytes.split_at(size);
    *bytes = rest;
    Ok(value)
}

fn delimited<'a>(bytes: &mut &'a [u8]) -> Result<&'a [u8], ValidationError> {
    let size = usize::try_from(varint(bytes)?).map_err(|_| ValidationError::Shape)?;
    take(bytes, size)
}

fn scalar(kind: Kind, value: u64) -> Result<(), ValidationError> {
    match kind {
        Kind::Bool if value <= 1 => Ok(()),
        Kind::U32 if u32::try_from(value).is_ok() => Ok(()),
        Kind::U64 => Ok(()),
        // Protobuf int32/enum negative values use sign-extended ten-byte varints.
        Kind::I32
            if i32::try_from(value).is_ok() || value >= i64::from(i32::MIN).cast_unsigned() =>
        {
            Ok(())
        }
        _ => Err(ValidationError::Shape),
    }
}

fn map_key(mut bytes: &[u8]) -> Result<&[u8], ValidationError> {
    let mut key = &[][..];
    let mut seen = false;
    while !bytes.is_empty() {
        let tag = varint(&mut bytes)?;
        if tag == 10 {
            if seen {
                return Err(ValidationError::Shape);
            }
            key = delimited(&mut bytes)?;
            seen = true;
        } else {
            skip((tag & 7) as u8, &mut bytes)?;
        }
    }
    Ok(key)
}

fn skip(wire: u8, bytes: &mut &[u8]) -> Result<(), ValidationError> {
    match wire {
        0 => {
            varint(bytes)?;
        }
        1 => {
            take(bytes, 8)?;
        }
        2 => {
            delimited(bytes)?;
        }
        5 => {
            take(bytes, 4)?;
        }
        _ => return Err(ValidationError::Shape),
    }
    Ok(())
}

fn walk<'a>(
    schema: &Schema,
    mut bytes: &'a [u8],
    depth: usize,
    budget: &mut Budget,
) -> Result<(), ValidationError> {
    budget.node(schema.allocation, depth)?;
    let mut counts = [0_u16; 64];
    let mut oneofs = 0_u64;
    // Map keys are borrowed from the input frame. No uncharged hash table or
    // allocation is created while checking duplicate keys.
    let mut keys: [(usize, &'a [u8]); 128] = [(usize::MAX, &[]); 128];
    let mut used_keys = 0;
    while !bytes.is_empty() {
        budget.tags = budget
            .tags
            .checked_sub(1)
            .ok_or(ValidationError::Capacity)?;
        let tag = varint(&mut bytes)?;
        let number = u32::try_from(tag >> 3).map_err(|_| ValidationError::Shape)?;
        if number == 0 || number > 0x1fff_ffff {
            return Err(ValidationError::Shape);
        }
        let wire = (tag & 7) as u8;
        let Some((index, field)) = schema
            .fields
            .iter()
            .enumerate()
            .find(|(_, field)| field.number == number)
        else {
            skip(wire, &mut bytes)?;
            continue;
        };
        counts[index] = counts[index]
            .checked_add(1)
            .ok_or(ValidationError::Capacity)?;
        let maximum = if matches!(field.kind, Kind::Map(_)) {
            32
        } else if field.repeated {
            field.maximum
        } else {
            1
        };
        if counts[index] > maximum {
            return Err(ValidationError::Capacity);
        }
        if field.repeated && !matches!(field.kind, Kind::Message(_) | Kind::Map(_)) {
            budget.charge(48)?;
        }
        if field.oneof > 0 {
            let offset = u32::try_from(field.oneof - 1).map_err(|_| ValidationError::Shape)?;
            let bit = 1_u64.checked_shl(offset).ok_or(ValidationError::Shape)?;
            if oneofs & bit != 0 {
                return Err(ValidationError::Shape);
            }
            oneofs |= bit;
        }
        match field.kind {
            kind @ (Kind::Bool | Kind::U32 | Kind::U64 | Kind::I32) if wire == 0 => {
                scalar(kind, varint(&mut bytes)?)?;
            }
            kind @ (Kind::Bool | Kind::U32 | Kind::U64 | Kind::I32)
                if wire == 2 && field.repeated =>
            {
                let mut packed = delimited(&mut bytes)?;
                let mut values = 0_u16;
                while !packed.is_empty() {
                    values = values.checked_add(1).ok_or(ValidationError::Capacity)?;
                    if values > 128 {
                        return Err(ValidationError::Capacity);
                    }
                    scalar(kind, varint(&mut packed)?)?;
                }
                counts[index] = counts[index]
                    .checked_add(values.saturating_sub(1))
                    .ok_or(ValidationError::Capacity)?;
                if counts[index] > 128 {
                    return Err(ValidationError::Capacity);
                }
                budget.charge(usize::from(values) * 16)?;
            }
            Kind::String | Kind::Bytes if wire == 2 => {
                let value = delimited(&mut bytes)?;
                if matches!(field.kind, Kind::String) {
                    std::str::from_utf8(value).map_err(|_| ValidationError::Shape)?;
                }
                budget.data(value.len())?;
            }
            Kind::Message(child) | Kind::Map(child) if wire == 2 => {
                let value = delimited(&mut bytes)?;
                if matches!(field.kind, Kind::Map(_)) {
                    let key = map_key(value)?;
                    if used_keys >= keys.len()
                        || keys[..used_keys]
                            .iter()
                            .any(|(owner, prior)| *owner == index && *prior == key)
                    {
                        return Err(ValidationError::Shape);
                    }
                    keys[used_keys] = (index, key);
                    used_keys += 1;
                }
                walk(child, value, depth + 1, budget)?;
            }
            _ => return Err(ValidationError::Shape),
        }
    }
    Ok(())
}

pub(super) fn preflight(
    schema: &Schema,
    bytes: &[u8],
    maximum: usize,
) -> Result<(), ValidationError> {
    if bytes.len() > maximum.min(latent_rpc::phase4::MAX_RESPONSE_BYTES) {
        return Err(ValidationError::Capacity);
    }
    walk(schema, bytes, 0, &mut Budget::new())
}

pub(super) struct BoundedCodec<Input, Output> {
    inner: ProstCodec<Input, Output>,
    schema: &'static Schema,
    maximum: usize,
}

impl<Input, Output> BoundedCodec<Input, Output> {
    pub(super) fn new(schema: &'static Schema, maximum: usize) -> Self {
        Self {
            inner: ProstCodec::new(),
            schema,
            maximum,
        }
    }
}

pub(super) struct BoundedDecoder<Output> {
    inner: ProstDecoder<Output>,
    schema: &'static Schema,
    maximum: usize,
}

impl<Input, Output> Codec for BoundedCodec<Input, Output>
where
    Input: Message + Send + 'static,
    Output: Message + Default + Send + 'static,
{
    type Encode = Input;
    type Decode = Output;
    type Encoder = ProstEncoder<Input>;
    type Decoder = BoundedDecoder<Output>;

    fn encoder(&mut self) -> Self::Encoder {
        self.inner.encoder()
    }
    fn decoder(&mut self) -> Self::Decoder {
        BoundedDecoder {
            inner: self.inner.decoder(),
            schema: self.schema,
            maximum: self.maximum,
        }
    }
}

impl<Output: Message + Default> Decoder for BoundedDecoder<Output> {
    type Item = Output;
    type Error = Status;

    fn decode(&mut self, buffer: &mut DecodeBuf<'_>) -> Result<Option<Self::Item>, Self::Error> {
        if buffer.remaining() != buffer.chunk().len() {
            return Err(Status::data_loss("unsupported fragmented message"));
        }
        preflight(self.schema, buffer.chunk(), self.maximum)
            .map_err(|_| Status::data_loss("invalid bounded transaction response"))?;
        self.inner.decode(buffer)
    }

    fn buffer_settings(&self) -> BufferSettings {
        self.inner.buffer_settings()
    }
}
