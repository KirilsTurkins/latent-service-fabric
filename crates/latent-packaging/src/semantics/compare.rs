mod types;
use super::{exhausted, incompatible, limits, SemanticLimits};
use latent_core::PlatformError;
use std::collections::BTreeMap;
use wit_parser::{FunctionKind, InterfaceId, Resolve, WorldId, WorldItem, WorldKey};

pub(super) struct WorldSurface {
    pub(super) imports: BTreeMap<String, InterfaceId>,
    pub(super) exports: BTreeMap<String, InterfaceId>,
}

pub(super) fn surface(
    resolve: &Resolve,
    world: WorldId,
    limits: SemanticLimits,
) -> Result<WorldSurface, PlatformError> {
    let world = &resolve.worlds[world];
    if world.imports.len() > limits.max_imports || world.exports.len() > limits.max_exports {
        return Err(exhausted("component-world-item-limit"));
    }
    let mut imports = BTreeMap::new();
    let mut exports = BTreeMap::new();
    for (items, output) in [
        (&world.imports, &mut imports),
        (&world.exports, &mut exports),
    ] {
        for (key, value) in items {
            let (WorldKey::Interface(named), WorldItem::Interface { id, .. }) = (key, value) else {
                return Err(incompatible("unsupported-world-item"));
            };
            if named != id {
                return Err(incompatible("aliased-world-interface"));
            }
            let name = resolve
                .id_of(*id)
                .ok_or_else(|| incompatible("unnamed-world-interface"))?;
            limits::name(&name, limits)?;
            if output.insert(name, *id).is_some() {
                return Err(incompatible("duplicate-world-interface"));
            }
        }
    }
    if exports.is_empty() {
        return Err(incompatible("component-has-no-export"));
    }
    if exports
        .values()
        .any(|id| resolve.interfaces[*id].functions.is_empty())
    {
        return Err(incompatible("component-export-has-no-function"));
    }
    Ok(WorldSurface { imports, exports })
}

pub(super) fn worlds(
    source: &Resolve,
    declared: &WorldSurface,
    actual: &Resolve,
    compiled: &WorldSurface,
    limits: SemanticLimits,
) -> Result<usize, PlatformError> {
    if !declared.exports.keys().eq(compiled.exports.keys()) {
        return Err(incompatible("component-world-identity-mismatch"));
    }
    let mut compare = Comparison::new(source, actual, limits);
    // Compilers may prune unused host interfaces or members. Every retained
    // import must still match the complete, independently pinned source world.
    for (name, actual) in &compiled.imports {
        let expected = declared
            .imports
            .get(name)
            .ok_or_else(|| incompatible("component-world-identity-mismatch"))?;
        compare.import_subset(*expected, *actual)?;
    }
    for (name, expected) in &declared.exports {
        compare.interface(*expected, compiled.exports[name])?;
    }
    Ok(compare.examined)
}

pub(super) struct Comparison<'a> {
    left: &'a Resolve,
    right: &'a Resolve,
    limits: SemanticLimits,
    examined: usize,
}

impl<'a> Comparison<'a> {
    pub(super) fn new(left: &'a Resolve, right: &'a Resolve, limits: SemanticLimits) -> Self {
        Self {
            left,
            right,
            limits,
            examined: 0,
        }
    }

    pub(super) fn interface(
        &mut self,
        left: InterfaceId,
        right: InterfaceId,
    ) -> Result<(), PlatformError> {
        let expected = &self.left.interfaces[left];
        let actual = &self.right.interfaces[right];
        if expected.functions.len() != actual.functions.len()
            || expected.types.len() != actual.types.len()
        {
            return Err(incompatible("component-interface-shape-mismatch"));
        }
        self.import_subset(left, right)
    }

    pub(super) fn import_subset(
        &mut self,
        left: InterfaceId,
        right: InterfaceId,
    ) -> Result<(), PlatformError> {
        let left = &self.left.interfaces[left];
        let right = &self.right.interfaces[right];
        self.node(1)?;
        for (name, actual) in &right.types {
            limits::name(name, self.limits)?;
            let expected = left
                .types
                .get(name)
                .ok_or_else(|| incompatible("component-named-type-mismatch"))?;
            self.ty(
                wit_parser::Type::Id(*expected),
                wit_parser::Type::Id(*actual),
                1,
            )?;
        }
        for (name, other) in &right.functions {
            limits::name(name, self.limits)?;
            let function = left
                .functions
                .get(name)
                .ok_or_else(|| incompatible("component-function-missing"))?;
            self.node(1)?;
            if !matches!(function.kind, FunctionKind::Freestanding)
                || !matches!(other.kind, FunctionKind::Freestanding)
                || function.params.len() != other.params.len()
                || function.params.len() > self.limits.max_parameters
            {
                return Err(incompatible("unsupported-component-function"));
            }
            for (parameter, actual) in function.params.iter().zip(&other.params) {
                if parameter.name != actual.name {
                    return Err(incompatible("component-parameter-name-mismatch"));
                }
                self.ty(parameter.ty, actual.ty, 1)?;
            }
            self.optional(function.result, other.result, 1)?;
        }
        Ok(())
    }

    fn node(&mut self, depth: usize) -> Result<(), PlatformError> {
        if depth > self.limits.max_type_depth {
            return Err(exhausted("component-type-depth-limit"));
        }
        limits::add(&mut self.examined, 1, self.limits.max_type_nodes)
    }
}
