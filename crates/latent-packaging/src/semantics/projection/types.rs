use latent_contracts::ValueType;
use latent_core::PlatformError;
use wit_parser::{Resolve, Type, TypeDefKind};

use super::{exhausted, incompatible, SemanticLimits};

pub(super) struct Budget {
    remaining: usize,
    limits: SemanticLimits,
}

impl Budget {
    pub(super) fn new(limits: SemanticLimits) -> Self {
        Self {
            remaining: limits.max_type_nodes,
            limits,
        }
    }

    pub(super) fn compare(
        &mut self,
        resolve: &Resolve,
        described: &ValueType,
        actual: Type,
        depth: usize,
    ) -> Result<(), PlatformError> {
        if depth > self.limits.max_type_depth {
            return Err(exhausted("contract-type-depth-limit"));
        }
        self.remaining = self
            .remaining
            .checked_sub(1)
            .ok_or_else(|| exhausted("contract-type-node-limit"))?;
        let equal = match (described, actual) {
            (ValueType::Bool, Type::Bool)
            | (ValueType::U8, Type::U8)
            | (ValueType::U16, Type::U16)
            | (ValueType::U32, Type::U32)
            | (ValueType::U64, Type::U64)
            | (ValueType::S8, Type::S8)
            | (ValueType::S16, Type::S16)
            | (ValueType::S32, Type::S32)
            | (ValueType::S64, Type::S64)
            | (ValueType::F32, Type::F32)
            | (ValueType::F64, Type::F64)
            | (ValueType::Char, Type::Char)
            | (ValueType::String, Type::String) => true,
            (_, Type::Id(id)) => {
                let definition = &resolve.types[id];
                match (&definition.kind, described) {
                    (TypeDefKind::Type(ty), _) => {
                        return self.compare(resolve, described, *ty, depth + 1)
                    }
                    (TypeDefKind::Record(_), ValueType::Record(name))
                    | (TypeDefKind::Variant(_) | TypeDefKind::Enum(_), ValueType::Variant(name)) => {
                        super::super::limits::name(name, self.limits)?;
                        definition.name.as_deref() == Some(name.as_str())
                    }
                    (TypeDefKind::List(ty), ValueType::Bytes) => {
                        return self.compare(resolve, &ValueType::U8, *ty, depth + 1)
                    }
                    (TypeDefKind::List(ty), ValueType::List(inner))
                    | (TypeDefKind::Option(ty), ValueType::Option(inner)) => {
                        return self.compare(resolve, inner, *ty, depth + 1)
                    }
                    (TypeDefKind::Result(result), ValueType::Result { ok, error }) => {
                        self.optional(resolve, ok.as_deref(), result.ok, depth + 1)?;
                        self.optional(resolve, error.as_deref(), result.err, depth + 1)?;
                        true
                    }
                    (TypeDefKind::Tuple(tuple), ValueType::Tuple(fields)) => {
                        if tuple.types.len() > self.limits.max_type_members {
                            return Err(exhausted("contract-type-member-limit"));
                        }
                        if fields.len() != tuple.types.len() {
                            return Err(mismatch());
                        }
                        for (field, ty) in fields.iter().zip(&tuple.types) {
                            self.compare(resolve, field, *ty, depth + 1)?;
                        }
                        true
                    }
                    (
                        TypeDefKind::Resource
                        | TypeDefKind::Handle(_)
                        | TypeDefKind::Flags(_)
                        | TypeDefKind::Map(_, _)
                        | TypeDefKind::FixedLengthList(_, _)
                        | TypeDefKind::Future(_)
                        | TypeDefKind::Stream(_)
                        | TypeDefKind::Unknown,
                        _,
                    ) => {
                        return Err(incompatible("unsupported-contract-value-type"));
                    }
                    _ => false,
                }
            }
            (_, Type::ErrorContext) => return Err(incompatible("unsupported-contract-value-type")),
            _ => false,
        };
        if equal {
            Ok(())
        } else {
            Err(mismatch())
        }
    }

    fn optional(
        &mut self,
        resolve: &Resolve,
        described: Option<&ValueType>,
        actual: Option<Type>,
        depth: usize,
    ) -> Result<(), PlatformError> {
        match (described, actual) {
            (Some(described), Some(actual)) => self.compare(resolve, described, actual, depth),
            (None, None) => Ok(()),
            _ => Err(mismatch()),
        }
    }
}

fn mismatch() -> PlatformError {
    incompatible("contract-value-type-mismatch")
}
