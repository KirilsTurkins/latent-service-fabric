use super::{incompatible, Comparison};
use latent_core::PlatformError;
use wit_parser::{Type, TypeDefKind};

impl Comparison<'_> {
    pub(super) fn ty(
        &mut self,
        left: Type,
        right: Type,
        depth: usize,
    ) -> Result<(), PlatformError> {
        self.node(depth)?;
        // Aliases are transparent, but interface type names and named projection
        // references are checked separately; complete nested structure remains authoritative.
        if let Type::Id(id) = left {
            if let TypeDefKind::Type(inner) = self.left.types[id].kind {
                return self.ty(inner, right, depth + 1);
            }
        }
        if let Type::Id(id) = right {
            if let TypeDefKind::Type(inner) = self.right.types[id].kind {
                return self.ty(left, inner, depth + 1);
            }
        }
        match (left, right) {
            (Type::Id(left_id), Type::Id(right_id)) => {
                let left = &self.left.types[left_id].kind;
                let right = &self.right.types[right_id].kind;
                match (left, right) {
                    (TypeDefKind::Record(a), TypeDefKind::Record(b))
                        if a.fields.len() == b.fields.len() =>
                    {
                        self.width(a.fields.len())?;
                        for (a, b) in a.fields.iter().zip(&b.fields) {
                            if a.name != b.name {
                                return Err(incompatible("component-record-field-mismatch"));
                            }
                            self.ty(a.ty, b.ty, depth + 1)?;
                        }
                    }
                    (TypeDefKind::Variant(a), TypeDefKind::Variant(b))
                        if a.cases.len() == b.cases.len() =>
                    {
                        self.width(a.cases.len())?;
                        for (a, b) in a.cases.iter().zip(&b.cases) {
                            if a.name != b.name {
                                return Err(incompatible("component-variant-case-mismatch"));
                            }
                            self.optional(a.ty, b.ty, depth + 1)?;
                        }
                    }
                    (TypeDefKind::Enum(a), TypeDefKind::Enum(b))
                        if a.cases.len() == b.cases.len() =>
                    {
                        self.width(a.cases.len())?;
                        if !a
                            .cases
                            .iter()
                            .map(|c| &c.name)
                            .eq(b.cases.iter().map(|c| &c.name))
                        {
                            return Err(incompatible("component-enum-case-mismatch"));
                        }
                    }
                    (TypeDefKind::Tuple(a), TypeDefKind::Tuple(b))
                        if a.types.len() == b.types.len() =>
                    {
                        self.width(a.types.len())?;
                        for (a, b) in a.types.iter().zip(&b.types) {
                            self.ty(*a, *b, depth + 1)?;
                        }
                    }
                    (TypeDefKind::Option(a), TypeDefKind::Option(b))
                    | (TypeDefKind::List(a), TypeDefKind::List(b)) => self.ty(*a, *b, depth + 1)?,
                    (TypeDefKind::Result(a), TypeDefKind::Result(b)) => {
                        self.optional(a.ok, b.ok, depth + 1)?;
                        self.optional(a.err, b.err, depth + 1)?;
                    }
                    // This also rejects resources/handles, flags, maps, fixed
                    // lists, async future/stream and unresolved unknown types.
                    _ => return Err(incompatible("unsupported-or-mismatched-component-type")),
                }
            }
            (Type::ErrorContext, _) | (_, Type::ErrorContext) => {
                return Err(incompatible("unsupported-component-type"))
            }
            (a, b) if a == b => (),
            _ => return Err(incompatible("component-value-type-mismatch")),
        }
        Ok(())
    }

    pub(super) fn optional(
        &mut self,
        left: Option<Type>,
        right: Option<Type>,
        depth: usize,
    ) -> Result<(), PlatformError> {
        match (left, right) {
            (Some(a), Some(b)) => self.ty(a, b, depth),
            (None, None) => Ok(()),
            _ => Err(incompatible("component-optional-type-mismatch")),
        }
    }

    fn width(&self, size: usize) -> Result<(), PlatformError> {
        if size > self.limits.max_type_members {
            return Err(super::exhausted("component-type-member-limit"));
        }
        Ok(())
    }
}
