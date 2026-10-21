use std::io::Write;

use latent_core::PlatformError;
use wasmtime::component::{Type, Val};

use super::{charge, invalid_result, limit, unsupported, ValueCodecLimits};

pub(super) fn results(
    types: &[Type],
    values: &[Val],
    limits: ValueCodecLimits,
) -> Result<Vec<u8>, PlatformError> {
    write_results(types, values, limits, None).map(|output| output.bytes)
}

pub(super) fn results_accounted(
    types: &[Type],
    values: &[Val],
    limits: ValueCodecLimits,
    budget: &latent_core::ActivationBudget,
) -> Result<latent_core::ResultPayload, PlatformError> {
    let output = write_results(types, values, limits, Some(budget))?;
    match output.memory.take() {
        Some(memory) => latent_core::ResultPayload::from_reserved(output.bytes, memory, budget)
            .map_err(|error| error.to_platform_error()),
        None => Ok(output.bytes.into()), // explicit legacy Phase1 only
    }
}

fn write_results(
    types: &[Type],
    values: &[Val],
    limits: ValueCodecLimits,
    budget: Option<&latent_core::ActivationBudget>,
) -> Result<LimitedBytes, PlatformError> {
    if types.len() != values.len() {
        return Err(invalid_result());
    }
    let mut encoder = Encoder {
        output: LimitedBytes {
            bytes: Vec::new(),
            maximum: limits.max_output_bytes,
            memory: super::memory::Escrow::new(budget),
            refusal: None,
        },
        remaining_nodes: limits.max_nodes,
        depth: 0,
        limits,
    };
    let result = (|| {
        encoder.open(b'[', values.len())?;
        for (index, (ty, value)) in types.iter().zip(values).enumerate() {
            encoder.comma(index)?;
            encoder.value(ty, value)?;
        }
        encoder.close(b']')
    })();
    if let Err(error) = result {
        // serde_json wraps writer failures. Preserve the first original ledger
        // refusal instead of replacing its MemoryBytes metadata with a codec cap.
        return Err(encoder.output.refusal.take().unwrap_or(error));
    }
    Ok(encoder.output)
}

struct LimitedBytes {
    bytes: Vec<u8>,
    maximum: usize,
    memory: super::memory::Escrow,
    refusal: Option<PlatformError>,
}
impl LimitedBytes {
    fn refused(&mut self, error: PlatformError) -> std::io::Error {
        if self.refusal.is_none() {
            self.refusal = Some(error);
        }
        std::io::Error::other("original-host-memory-refusal")
    }
}

impl Write for LimitedBytes {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let needed = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .filter(|needed| *needed <= self.maximum)
            .ok_or_else(|| std::io::Error::other("invocation-value-limit"))?;
        if needed > self.bytes.capacity() {
            let capacity = needed
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.maximum);
            let old_capacity = self.bytes.capacity();
            // Keep the old allocation charged while a replacement is prepared.
            // Include conservative allocator bookkeeping before either path.
            let allocation = capacity
                .checked_add(64)
                .ok_or_else(|| std::io::Error::other("invocation-value-limit"))?;
            if let Err(error) = self.memory.add(allocation) {
                return Err(self.refused(error));
            }
            if let Err(error) = self.bytes.try_reserve_exact(capacity - self.bytes.len()) {
                if let Err(error) = self.memory.shrink(if old_capacity == 0 {
                    0
                } else {
                    old_capacity + 64
                }) {
                    return Err(self.refused(error));
                }
                return Err(std::io::Error::other(error));
            }
            self.memory.confirm();
            if let Err(error) = self.memory.shrink(self.bytes.capacity() + 64) {
                return Err(self.refused(error));
            }
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

struct Encoder {
    output: LimitedBytes,
    remaining_nodes: usize,
    depth: usize,
    limits: ValueCodecLimits,
}

impl Encoder {
    fn raw(&mut self, bytes: &[u8]) -> Result<(), PlatformError> {
        self.output.write_all(bytes).map_err(|_| limit())
    }
    fn comma(&mut self, index: usize) -> Result<(), PlatformError> {
        if index == 0 {
            Ok(())
        } else {
            self.raw(b",")
        }
    }
    fn node(&mut self) -> Result<(), PlatformError> {
        charge(&mut self.remaining_nodes, 1)
    }
    fn open(&mut self, delimiter: u8, length: usize) -> Result<(), PlatformError> {
        if self.depth == self.limits.max_depth || length > self.limits.max_collection_items {
            return Err(limit());
        }
        self.node()?;
        self.depth += 1;
        self.raw(&[delimiter])
    }
    fn close(&mut self, delimiter: u8) -> Result<(), PlatformError> {
        self.depth -= 1;
        self.raw(&[delimiter])
    }
    fn string(&mut self, value: &str) -> Result<(), PlatformError> {
        if value.len() > self.limits.max_string_bytes {
            return Err(limit());
        }
        self.node()?;
        serde_json::to_writer(&mut self.output, value).map_err(|_| limit())
    }
    fn formatted(&mut self, value: &impl std::fmt::Display) -> Result<(), PlatformError> {
        // Largest primitive f64 Display is under 384 UTF-8 bytes (including
        // subnormals and sign). Format in fixed stack storage before applying
        // the unchanged codec string ceiling; never allocate a hidden String.
        let mut scratch = [0u8; 384];
        let mut output = std::io::Cursor::new(scratch.as_mut_slice());
        write!(output, "{value}").map_err(|_| limit())?;
        let length = output.position() as usize;
        let value = std::str::from_utf8(&scratch[..length]).map_err(|_| invalid_result())?;
        self.string(value)
    }
    fn key(&mut self, name: &str) -> Result<(), PlatformError> {
        self.string(name)?;
        self.raw(b":")
    }
    fn primitive(&mut self, text: &[u8]) -> Result<(), PlatformError> {
        self.node()?;
        self.raw(text)
    }

    fn value(&mut self, ty: &Type, value: &Val) -> Result<(), PlatformError> {
        macro_rules! integer {
            ($value:expr) => {{
                self.node()?;
                write!(self.output, "{}", $value).map_err(|_| limit())
            }};
        }
        match (ty, value) {
            (Type::Bool, Val::Bool(value)) => {
                self.primitive(if *value { b"true" } else { b"false" })
            }
            (Type::U8, Val::U8(value)) => integer!(value),
            (Type::U16, Val::U16(value)) => integer!(value),
            (Type::U32, Val::U32(value)) => integer!(value),
            (Type::S8, Val::S8(value)) => integer!(value),
            (Type::S16, Val::S16(value)) => integer!(value),
            (Type::S32, Val::S32(value)) => integer!(value),
            (Type::U64, Val::U64(value)) => self.formatted(value),
            (Type::S64, Val::S64(value)) => self.formatted(value),
            (Type::Float32, Val::Float32(value)) => {
                if value.is_nan() {
                    self.string("nan")
                } else if *value == f32::INFINITY {
                    self.string("inf")
                } else if *value == f32::NEG_INFINITY {
                    self.string("-inf")
                } else {
                    self.formatted(value)
                }
            }
            (Type::Float64, Val::Float64(value)) => {
                if value.is_nan() {
                    self.string("nan")
                } else if *value == f64::INFINITY {
                    self.string("inf")
                } else if *value == f64::NEG_INFINITY {
                    self.string("-inf")
                } else {
                    self.formatted(value)
                }
            }
            (Type::Char, Val::Char(value)) => self.string(value.encode_utf8(&mut [0; 4])),
            (Type::String, Val::String(value)) => self.string(value),
            (Type::List(list), Val::List(values)) => self.list(list, values),
            (Type::Tuple(tuple), Val::Tuple(values)) => self.tuple(tuple, values),
            (Type::Record(record), Val::Record(values)) => self.record(record, values),
            (Type::Variant(variant), Val::Variant(name, value)) => {
                self.variant(variant, name, value.as_deref())
            }
            (Type::Enum(enumeration), Val::Enum(name)) => {
                if !enumeration.names().any(|candidate| candidate == name) {
                    return Err(invalid_result());
                }
                self.string(name)
            }
            (Type::Flags(flags), Val::Flags(names)) => self.flags(flags, names),
            (Type::Option(option), Val::Option(value)) => {
                self.open(b'{', 1)?;
                if let Some(value) = value {
                    self.key("some")?;
                    self.value(&option.ty(), value)?;
                } else {
                    self.key("none")?;
                    self.primitive(b"null")?;
                }
                self.close(b'}')
            }
            (Type::Result(result), Val::Result(value)) => {
                self.open(b'{', 1)?;
                match value {
                    Ok(value) => {
                        self.key("ok")?;
                        self.branch(result.ok(), value.as_deref())?;
                    }
                    Err(value) => {
                        self.key("err")?;
                        self.branch(result.err(), value.as_deref())?;
                    }
                }
                self.close(b'}')
            }
            (
                Type::FixedLengthList(_)
                | Type::Map(_)
                | Type::Own(_)
                | Type::Borrow(_)
                | Type::Future(_)
                | Type::Stream(_)
                | Type::ErrorContext,
                _,
            ) => Err(unsupported()),
            _ => Err(invalid_result()),
        }
    }

    fn list(
        &mut self,
        list: &wasmtime::component::types::List,
        values: &[Val],
    ) -> Result<(), PlatformError> {
        self.open(b'[', values.len())?;
        for (index, value) in values.iter().enumerate() {
            self.comma(index)?;
            self.value(&list.ty(), value)?;
        }
        self.close(b']')
    }

    fn tuple(
        &mut self,
        tuple: &wasmtime::component::types::Tuple,
        values: &[Val],
    ) -> Result<(), PlatformError> {
        if tuple.types().len() != values.len() {
            return Err(invalid_result());
        }
        self.open(b'[', values.len())?;
        for (index, (ty, value)) in tuple.types().zip(values).enumerate() {
            self.comma(index)?;
            self.value(&ty, value)?;
        }
        self.close(b']')
    }

    fn record(
        &mut self,
        record: &wasmtime::component::types::Record,
        values: &[(String, Val)],
    ) -> Result<(), PlatformError> {
        if record.fields().len() != values.len() {
            return Err(invalid_result());
        }
        self.open(b'{', values.len())?;
        for (index, field) in record.fields().enumerate() {
            // Wasmtime produces declaration order. Reject malformed host-created
            // values rather than hiding duplicate names or guessing their order.
            let (name, value) = &values[index];
            if name != field.name {
                return Err(invalid_result());
            }
            self.comma(index)?;
            self.key(field.name)?;
            self.value(&field.ty, value)?;
        }
        self.close(b'}')
    }

    fn variant(
        &mut self,
        variant: &wasmtime::component::types::Variant,
        name: &str,
        value: Option<&Val>,
    ) -> Result<(), PlatformError> {
        let case = variant
            .cases()
            .find(|case| case.name == name)
            .ok_or_else(invalid_result)?;
        self.open(b'{', if case.ty.is_some() { 2 } else { 1 })?;
        self.key("case")?;
        self.string(name)?;
        match (case.ty, value) {
            (Some(ty), Some(value)) => {
                self.raw(b",")?;
                self.key("value")?;
                self.value(&ty, value)?;
            }
            (None, None) => {}
            _ => return Err(invalid_result()),
        }
        self.close(b'}')
    }

    fn flags(
        &mut self,
        flags: &wasmtime::component::types::Flags,
        names: &[String],
    ) -> Result<(), PlatformError> {
        self.open(b'[', names.len())?;
        for (index, name) in names.iter().enumerate() {
            if !flags.names().any(|candidate| candidate == name) || names[..index].contains(name) {
                return Err(invalid_result());
            }
        }
        let mut index = 0;
        for name in flags.names() {
            if names.iter().any(|candidate| candidate == name) {
                self.comma(index)?;
                self.string(name)?;
                index += 1;
            }
        }
        self.close(b']')
    }

    fn branch(&mut self, ty: Option<Type>, value: Option<&Val>) -> Result<(), PlatformError> {
        match (ty, value) {
            (Some(ty), Some(value)) => self.value(&ty, value),
            (None, None) => self.primitive(b"null"),
            _ => Err(invalid_result()),
        }
    }
}
