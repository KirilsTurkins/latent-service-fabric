use super::{Code, Level, Walker};
use latent_contracts::Analysis;
use latent_core::PlatformError;
use wit_parser::{Function, FunctionKind, InterfaceId, Resolve, Type, TypeDefKind, TypeOwner};

pub(super) fn inspect_interface(
    resolve: &Resolve,
    id: InterfaceId,
    a: &mut Analysis,
) -> Result<(), PlatformError> {
    let interface = &resolve.interfaces[id];
    a.node(1)?;
    for (name, id) in &interface.types {
        a.name(name)?;
        a.edge(1)?;
        inspect_type(resolve, Type::Id(*id), a, 1)?;
    }
    for (name, function) in &interface.functions {
        a.node(1)?;
        a.name(name)?;
        if function.kind != FunctionKind::Freestanding {
            a.issue(Level::Unsupported, Code::UnsupportedType, &[name]);
        }
        for parameter in &function.params {
            a.name(&parameter.name)?;
            a.edge(1)?;
            inspect_type(resolve, parameter.ty, a, 1)?;
        }
        if let Some(result) = function.result {
            a.edge(1)?;
            inspect_type(resolve, result, a, 1)?;
        }
    }
    Ok(())
}
fn inspect_type(
    resolve: &Resolve,
    ty: Type,
    a: &mut Analysis,
    depth: usize,
) -> Result<(), PlatformError> {
    a.node(depth)?;
    let Type::Id(id) = ty else {
        if ty == Type::ErrorContext {
            a.issue(Level::Unsupported, Code::UnsupportedType, &[]);
        }
        return Ok(());
    };
    let ty = &resolve.types[id];
    if let Some(name) = &ty.name {
        a.name(name)?;
    }
    match &ty.kind {
        TypeDefKind::Type(inner) | TypeDefKind::List(inner) | TypeDefKind::Option(inner) => {
            a.edge(1)?;
            inspect_type(resolve, *inner, a, depth + 1)?;
        }
        TypeDefKind::Record(record) => {
            for field in &record.fields {
                a.name(&field.name)?;
                a.edge(1)?;
                inspect_type(resolve, field.ty, a, depth + 1)?;
            }
        }
        TypeDefKind::Variant(variant) => {
            for case in &variant.cases {
                a.name(&case.name)?;
                a.edge(1)?;
                if let Some(ty) = case.ty {
                    inspect_type(resolve, ty, a, depth + 1)?;
                }
            }
        }
        TypeDefKind::Enum(value) => {
            for case in &value.cases {
                a.name(&case.name)?;
                a.edge(1)?;
            }
        }
        TypeDefKind::Tuple(tuple) => {
            for ty in &tuple.types {
                a.edge(1)?;
                inspect_type(resolve, *ty, a, depth + 1)?;
            }
        }
        TypeDefKind::Result(result) => {
            for ty in [result.ok, result.err].into_iter().flatten() {
                a.edge(1)?;
                inspect_type(resolve, ty, a, depth + 1)?;
            }
        }
        _ => a.issue(Level::Unsupported, Code::UnsupportedType, &[]),
    }
    Ok(())
}

impl Walker<'_, '_> {
    pub(super) fn function(
        &mut self,
        old: &Function,
        new: &Function,
    ) -> Result<bool, PlatformError> {
        if old.kind != new.kind || old.params.len() != new.params.len() {
            return Ok(false);
        }
        for (old, new) in old.params.iter().zip(&new.params) {
            self.analysis.edge(1)?;
            if !self.equal(&old.name, &new.name)? || !self.ty(old.ty, new.ty, 1)? {
                return Ok(false);
            }
        }
        self.optional(old.result, new.result, 1)
    }
    fn equal(&mut self, left: &str, right: &str) -> Result<bool, PlatformError> {
        self.analysis.text(left)?;
        self.analysis.text(right)?;
        Ok(left == right)
    }
    pub(super) fn ty(
        &mut self,
        left: Type,
        right: Type,
        depth: usize,
    ) -> Result<bool, PlatformError> {
        self.analysis.node(depth)?;
        self.analysis.edge(1)?;
        // Transparent aliases do not erase public named declarations or the
        // final named record/variant owner identity checked below.
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
            (Type::Id(left), Type::Id(right)) => {
                let old = &self.left.types[left];
                let new = &self.right.types[right];
                // Named definitions are not interchangeable solely because their
                // current layouts happen to match.
                if matches!(
                    old.kind,
                    TypeDefKind::Record(_) | TypeDefKind::Variant(_) | TypeDefKind::Enum(_)
                ) {
                    match (&old.name, &new.name) {
                        (Some(old), Some(new)) if self.equal(old, new)? => (),
                        (None, None) => (),
                        _ => return Ok(false),
                    }
                    if !owner_equal(self.left, old.owner, self.right, new.owner, self.analysis)? {
                        return Ok(false);
                    }
                }
                match (&old.kind, &new.kind) {
                    (TypeDefKind::Record(old), TypeDefKind::Record(new)) => {
                        if old.fields.len() != new.fields.len() {
                            return Ok(false);
                        }
                        for (old, new) in old.fields.iter().zip(&new.fields) {
                            if !self.equal(&old.name, &new.name)?
                                || !self.ty(old.ty, new.ty, depth + 1)?
                            {
                                return Ok(false);
                            }
                        }
                        Ok(true)
                    }
                    (TypeDefKind::Variant(old), TypeDefKind::Variant(new)) => {
                        if old.cases.len() != new.cases.len() {
                            return Ok(false);
                        }
                        for (old, new) in old.cases.iter().zip(&new.cases) {
                            if !self.equal(&old.name, &new.name)?
                                || !self.optional(old.ty, new.ty, depth + 1)?
                            {
                                return Ok(false);
                            }
                        }
                        Ok(true)
                    }
                    (TypeDefKind::Enum(old), TypeDefKind::Enum(new)) => {
                        if old.cases.len() != new.cases.len() {
                            return Ok(false);
                        }
                        for (old, new) in old.cases.iter().zip(&new.cases) {
                            self.analysis.edge(1)?;
                            if !self.equal(&old.name, &new.name)? {
                                return Ok(false);
                            }
                        }
                        Ok(true)
                    }
                    (TypeDefKind::Tuple(old), TypeDefKind::Tuple(new)) => {
                        if old.types.len() != new.types.len() {
                            return Ok(false);
                        }
                        for (old, new) in old.types.iter().zip(&new.types) {
                            if !self.ty(*old, *new, depth + 1)? {
                                return Ok(false);
                            }
                        }
                        Ok(true)
                    }
                    (TypeDefKind::List(old), TypeDefKind::List(new))
                    | (TypeDefKind::Option(old), TypeDefKind::Option(new)) => {
                        self.ty(*old, *new, depth + 1)
                    }
                    (TypeDefKind::Result(old), TypeDefKind::Result(new)) => {
                        Ok(self.optional(old.ok, new.ok, depth + 1)?
                            && self.optional(old.err, new.err, depth + 1)?)
                    }
                    _ => Ok(false),
                }
            }
            (left, right) => Ok(left == right),
        }
    }
    fn optional(
        &mut self,
        left: Option<Type>,
        right: Option<Type>,
        depth: usize,
    ) -> Result<bool, PlatformError> {
        match (left, right) {
            (None, None) => Ok(true),
            (Some(left), Some(right)) => self.ty(left, right, depth),
            _ => Ok(false),
        }
    }
}
fn owner_equal(
    left: &Resolve,
    old: TypeOwner,
    right: &Resolve,
    new: TypeOwner,
    a: &mut Analysis,
) -> Result<bool, PlatformError> {
    match (old, new) {
        (TypeOwner::None, TypeOwner::None) => Ok(true),
        (TypeOwner::Interface(old), TypeOwner::Interface(new)) => {
            let old = left
                .id_of(old)
                .ok_or_else(|| super::super::invalid("comparison-unqualified-type"))?;
            let new = right
                .id_of(new)
                .ok_or_else(|| super::super::invalid("comparison-unqualified-type"))?;
            a.text(&old)?;
            a.text(&new)?;
            Ok(old == new)
        }
        (TypeOwner::World(old), TypeOwner::World(new)) => {
            let old = &left.worlds[old];
            let new = &right.worlds[new];
            a.text(&old.name)?;
            a.text(&new.name)?;
            match (old.package, new.package) {
                (Some(lp), Some(rp)) => {
                    Ok(old.name == new.name && left.packages[lp].name == right.packages[rp].name)
                }
                _ => Ok(false),
            }
        }
        _ => Ok(false),
    }
}
