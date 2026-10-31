//! Explicit allocation admission for dynamic component values.
//!
//! This optional embedding extension leaves the ordinary Wasmtime API unchanged.
//! A scope must outlive every value allocated under it, including queued results.
use crate::component::Val;
use crate::prelude::*;
use alloc::sync::Arc;

/// Original-owner allocation admission for a dynamic component call.
///
/// `reserve` runs before allocation; `confirm` runs after successful allocation.
/// `release` is called only after storage is destroyed or allocation fails.
/// Implementations must retain admitted bytes until the last scope owner dies.
pub trait DynamicValueMemory: Send + Sync {
    /// Reserve additional capacity or return the original admission error.
    fn reserve(&self, bytes: usize) -> Result<()>;
    /// Confirm all currently admitted allocations that have completed.
    fn confirm(&self);
    /// Retire storage that has physically been destroyed (or never allocated).
    fn release(&self, bytes: usize);
    /// Create an independent, refundable owner for the queued parameter copy.
    fn fork(&self) -> Result<Arc<dyn DynamicValueMemory>>;
}

pub(crate) const ALLOCATION_METADATA: usize = 64;
pub(crate) fn allocation_bytes<T>(count: usize) -> Result<usize> {
    if count == 0 || size_of::<T>() == 0 {
        return Ok(0);
    }
    count
        .checked_mul(size_of::<T>())
        .and_then(|n| n.checked_add(ALLOCATION_METADATA))
        .ok_or_else(|| crate::format_err!("dynamic-value-allocation-overflow"))
}

struct Pending<'a> {
    memory: Option<&'a Arc<dyn DynamicValueMemory>>,
    bytes: usize,
}
impl<'a> Pending<'a> {
    fn new(memory: Option<&'a Arc<dyn DynamicValueMemory>>, bytes: usize) -> Result<Self> {
        if let Some(memory) = memory {
            memory.reserve(bytes)?;
        }
        Ok(Self { memory, bytes })
    }
    fn allocated(mut self) {
        if let Some(memory) = self.memory.take() {
            memory.confirm();
        }
    }
}
impl Drop for Pending<'_> {
    fn drop(&mut self) {
        if let Some(memory) = self.memory {
            memory.release(self.bytes);
        }
    }
}

pub(crate) fn vector<T>(
    memory: Option<&Arc<dyn DynamicValueMemory>>,
    count: usize,
) -> Result<Vec<T>> {
    let pending = Pending::new(memory, allocation_bytes::<T>(count)?)?;
    let mut values = Vec::new();
    values.try_reserve_exact(count)?;
    // Global RawVec's exact-reserve uses the requested Layout. This check also
    // prevents exposing a capacity inconsistent with that pinned allocator proof.
    ensure!(
        values.capacity() == count || size_of::<T>() == 0,
        "dynamic-value-capacity-proof"
    );
    pending.allocated();
    Ok(values)
}

pub(crate) fn text(memory: Option<&Arc<dyn DynamicValueMemory>>, value: &str) -> Result<String> {
    let mut bytes = vector::<u8>(memory, value.len())?;
    bytes.extend_from_slice(value.as_bytes());
    // The source was a valid str; constructing its owned copy performs no allocation.
    Ok(String::from_utf8(bytes)?)
}

pub(crate) fn decoded_text(
    memory: Option<&Arc<dyn DynamicValueMemory>>,
    bytes: &[u8],
    utf16: bool,
) -> Result<String> {
    let count = if utf16 {
        let mut count = 0usize;
        for ch in core::char::decode_utf16(
            bytes
                .chunks_exact(2)
                .map(|b| u16::from_le_bytes([b[0], b[1]])),
        ) {
            count = count
                .checked_add(ch?.len_utf8())
                .ok_or_else(|| crate::format_err!("dynamic-value-allocation-overflow"))?;
        }
        count
    } else {
        bytes
            .iter()
            .try_fold(0usize, |n, b| n.checked_add(char::from(*b).len_utf8()))
            .ok_or_else(|| crate::format_err!("dynamic-value-allocation-overflow"))?
    };
    let result = vector::<u8>(memory, count)?;
    let mut result = String::from_utf8(result)?;
    if utf16 {
        for ch in core::char::decode_utf16(
            bytes
                .chunks_exact(2)
                .map(|b| u16::from_le_bytes([b[0], b[1]])),
        ) {
            result.push(ch?);
        }
    } else {
        for b in bytes {
            result.push(char::from(*b));
        }
    }
    debug_assert_eq!(result.len(), count);
    Ok(result)
}

pub(crate) fn boxed<T>(memory: Option<&Arc<dyn DynamicValueMemory>>, value: T) -> Result<Box<T>> {
    let pending = Pending::new(memory, allocation_bytes::<T>(1)?)?;
    let value = Box::new(value);
    pending.allocated();
    Ok(value)
}

/// Actual values always die before their scope, including an abandoned queued result.
pub(crate) struct DynamicValues {
    pub values: Vec<Val>,
    pub memory: Option<Arc<dyn DynamicValueMemory>>,
}
impl DynamicValues {
    pub fn as_slice(&self) -> &[Val] {
        &self.values
    }
    pub fn clone_params(
        values: &[Val],
        memory: Option<Arc<dyn DynamicValueMemory>>,
    ) -> Result<Self> {
        let Some(memory) = memory else {
            return Ok(Self {
                values: values.to_vec(),
                memory: None,
            });
        };
        let memory = memory.fork()?;
        let mut owner = Self {
            values: vector(Some(&memory), values.len())?,
            memory: Some(memory),
        };
        for value in values {
            owner
                .values
                .push(clone_value(value, owner.memory.as_ref(), 0)?);
        }
        Ok(owner)
    }
}
fn clone_value(
    value: &Val,
    memory: Option<&Arc<dyn DynamicValueMemory>>,
    depth: usize,
) -> Result<Val> {
    ensure!(depth <= 64, "dynamic-value-depth-limit");
    let child = |value: &Val| clone_value(value, memory, depth + 1);
    let sequence = |values: &[Val]| -> Result<Vec<Val>> {
        let mut result = vector(memory, values.len())?;
        for value in values {
            result.push(child(value)?);
        }
        Ok(result)
    };
    let payload = |value: &Option<Box<Val>>| -> Result<Option<Box<Val>>> {
        value
            .as_deref()
            .map(|v| boxed(memory, child(v)?))
            .transpose()
    };
    Ok(match value {
        Val::String(s) => Val::String(text(memory, s)?),
        Val::Enum(s) => Val::Enum(text(memory, s)?),
        Val::List(v) => Val::List(sequence(v)?),
        Val::Tuple(v) => Val::Tuple(sequence(v)?),
        Val::Record(v) => {
            let mut result = vector(memory, v.len())?;
            for (name, value) in v {
                result.push((text(memory, name)?, child(value)?));
            }
            Val::Record(result)
        }
        Val::Variant(name, v) => Val::Variant(text(memory, name)?, payload(v)?),
        Val::Option(v) => Val::Option(payload(v)?),
        Val::Result(Ok(v)) => Val::Result(Ok(payload(v)?)),
        Val::Result(Err(v)) => Val::Result(Err(payload(v)?)),
        Val::Flags(names) => {
            let mut result = vector(memory, names.len())?;
            for name in names {
                result.push(text(memory, name)?);
            }
            Val::Flags(result)
        }
        Val::Map(_)
        | Val::Resource(_)
        | Val::Future(_)
        | Val::Stream(_)
        | Val::ErrorContext(_)
        | Val::FixedLengthList(_) => bail!("unsupported-accounted-dynamic-value"),
        _ => value.clone(),
    })
}
