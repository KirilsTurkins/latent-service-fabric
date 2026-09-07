use latent_core::PlatformError;
use wasmtime::component::{Type, Val};

use super::{charge, limit, unsupported, ValueCodecLimits};

// Includes a Val, conservative Vec spare capacity, Box/allocator bookkeeping,
// and a String/field-pair slot. Dynamic string bytes are charged separately.
const NODE_BYTES: usize = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SignaturePlan {
    pub examined_type_nodes: usize,
    pub static_lift_bytes: usize,
    pub per_fuel_lift_multiplier: usize,
    pub maximum_lift_bytes: usize,
}

pub(crate) fn validate_signature(
    types: &[Type],
    limits: ValueCodecLimits,
    hostcall_fuel: usize,
) -> Result<SignaturePlan, PlatformError> {
    limits.validate()?;
    if types.len() > limits.max_collection_items || hostcall_fuel == 0 {
        return Err(limit());
    }
    let mut state = SchemaBudget {
        limits,
        remaining: limits.max_type_nodes,
        largest_element: NODE_BYTES,
    };
    let mut fixed = NODE_BYTES;
    for ty in types {
        fixed = fixed.checked_add(state.inline(ty, 1)?).ok_or_else(limit)?;
    }
    // UTF-16/Latin-1 lifting and String growth need at most a conservative 4x
    // source-byte allowance. Lists charge only size_of::<Val>() per element:
    // their uncharged inline records, tuples, boxes and names need amplification.
    let multiplier = state.largest_element.div_ceil(size_of::<Val>()).max(4);
    let maximum = hostcall_fuel
        .checked_mul(multiplier)
        .and_then(|dynamic| fixed.checked_add(dynamic))
        .ok_or_else(limit)?;
    if maximum > limits.max_lifted_bytes {
        return Err(limit());
    }
    Ok(SignaturePlan {
        examined_type_nodes: limits.max_type_nodes - state.remaining,
        static_lift_bytes: fixed,
        per_fuel_lift_multiplier: multiplier,
        maximum_lift_bytes: maximum,
    })
}

struct SchemaBudget {
    limits: ValueCodecLimits,
    remaining: usize,
    largest_element: usize,
}

impl SchemaBudget {
    fn name(&mut self, name: &str) -> Result<usize, PlatformError> {
        charge(&mut self.remaining, 1)?;
        if name.len()
            > self
                .limits
                .max_type_name_bytes
                .min(self.limits.max_string_bytes)
        {
            return Err(limit());
        }
        name.len().checked_mul(2).ok_or_else(limit)
    }

    fn width(&self, width: usize) -> Result<(), PlatformError> {
        if width > self.limits.max_collection_items {
            Err(limit())
        } else {
            Ok(())
        }
    }

    fn inline(&mut self, ty: &Type, depth: usize) -> Result<usize, PlatformError> {
        if depth > self.limits.max_depth {
            return Err(limit());
        }
        charge(&mut self.remaining, 1)?;
        let mut bytes = NODE_BYTES;
        match ty {
            Type::Bool
            | Type::S8
            | Type::U8
            | Type::S16
            | Type::U16
            | Type::S32
            | Type::U32
            | Type::S64
            | Type::U64
            | Type::Float32
            | Type::Float64
            | Type::Char
            | Type::String => {}
            Type::List(list) => {
                let element = self.inline(&list.ty(), depth + 1)?;
                self.largest_element = self.largest_element.max(element);
            }
            Type::Record(record) => {
                self.width(record.fields().len())?;
                for field in record.fields() {
                    bytes = bytes
                        .checked_add(self.name(field.name)?)
                        .ok_or_else(limit)?;
                    bytes = bytes
                        .checked_add(self.inline(&field.ty, depth + 1)?)
                        .ok_or_else(limit)?;
                }
            }
            Type::Tuple(tuple) => {
                self.width(tuple.types().len())?;
                for child in tuple.types() {
                    bytes = bytes
                        .checked_add(self.inline(&child, depth + 1)?)
                        .ok_or_else(limit)?;
                }
            }
            Type::Variant(variant) => {
                self.width(variant.cases().len())?;
                let mut largest = 0;
                for case in variant.cases() {
                    let mut branch = self.name(case.name)?;
                    if let Some(child) = case.ty {
                        branch = branch
                            .checked_add(self.inline(&child, depth + 1)?)
                            .ok_or_else(limit)?;
                    }
                    largest = largest.max(branch);
                }
                bytes = bytes.checked_add(largest).ok_or_else(limit)?;
            }
            Type::Enum(enumeration) => {
                self.width(enumeration.names().len())?;
                for name in enumeration.names() {
                    bytes = bytes.max(NODE_BYTES.checked_add(self.name(name)?).ok_or_else(limit)?);
                }
            }
            Type::Flags(flags) => {
                self.width(flags.names().len())?;
                for name in flags.names() {
                    let name_bytes = self.name(name)?;
                    bytes = bytes
                        .checked_add(NODE_BYTES)
                        .and_then(|value| value.checked_add(name_bytes))
                        .ok_or_else(limit)?;
                }
            }
            Type::Option(option) => {
                bytes = bytes
                    .checked_add(self.inline(&option.ty(), depth + 1)?)
                    .ok_or_else(limit)?;
            }
            Type::Result(result) => {
                let mut largest = 0;
                for child in [result.ok(), result.err()].into_iter().flatten() {
                    largest = largest.max(self.inline(&child, depth + 1)?);
                }
                bytes = bytes.checked_add(largest).ok_or_else(limit)?;
            }
            Type::Map(_)
            | Type::Own(_)
            | Type::Borrow(_)
            | Type::Future(_)
            | Type::Stream(_)
            | Type::ErrorContext => return Err(unsupported()),
        }
        Ok(bytes)
    }
}

pub(super) const fn node_bytes() -> usize {
    NODE_BYTES
}
