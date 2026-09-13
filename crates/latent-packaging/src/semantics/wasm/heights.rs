//! Conservative index-graph bounds before the validator can recurse through types.
//!
//! The preceding borrowed scan bounds every AST allocation. This pass keeps only
//! depth/work summaries, including aliases and nested scopes; no validator runs here.
mod links;
mod types;
use super::{charge, exhausted, invalid, read, Result, SemanticLimits};
use wasmparser::{
    CanonicalFunction, ComponentExternalKind as Kind, ComponentTypeRef, ComponentValType, Encoding,
    Parser, Payload, TypeBounds,
};

#[derive(Clone, Copy)]
struct Measure {
    depth: usize,
    work: usize,
}

impl Measure {
    const LEAF: Self = Self { depth: 1, work: 1 };

    fn include(&mut self, child: Self, limits: SemanticLimits) -> Result<()> {
        self.depth = self.depth.max(child.depth.saturating_add(1));
        charge(&mut self.work, child.work, limits.max_type_nodes)?;
        if self.depth > limits.max_type_depth {
            return Err(exhausted("component-reference-depth-limit"));
        }
        Ok(())
    }
}

#[derive(Default)]
struct Scope {
    types: Vec<Measure>,
    functions: Vec<Measure>,
    instances: Vec<Measure>,
    components: Vec<Measure>,
    values: Vec<Measure>,
    depth: usize,
    work: usize,
}

impl Scope {
    fn items(&self, kind: Kind) -> &[Measure] {
        match kind {
            Kind::Type => &self.types,
            Kind::Func => &self.functions,
            Kind::Instance => &self.instances,
            Kind::Component => &self.components,
            Kind::Value => &self.values,
            Kind::Module => &[],
        }
    }

    fn at(&self, kind: Kind, index: u32) -> Result<Measure> {
        if kind == Kind::Module {
            return Ok(Measure::LEAF);
        }
        self.items(kind)
            .get(index as usize)
            .copied()
            .ok_or_else(|| invalid("invalid-component-reference"))
    }
}

struct Guard {
    scopes: Vec<Scope>,
    work: usize,
    limits: SemanticLimits,
}

pub(super) fn validate(bytes: &[u8], limits: SemanticLimits) -> Result<()> {
    let mut guard = Guard {
        scopes: Vec::new(),
        work: 0,
        limits,
    };
    let mut encodings = Vec::new();
    for payload in Parser::new(0).parse_all(bytes) {
        match read(payload)? {
            Payload::Version { encoding, .. } => {
                encodings.push(encoding);
                if encoding == Encoding::Component {
                    guard.enter()?;
                }
            }
            Payload::End(_) => {
                if encodings.pop() == Some(Encoding::Component) {
                    let value = guard.leave()?;
                    if !guard.scopes.is_empty() {
                        guard.push(Kind::Component, value)?;
                    }
                }
            }
            Payload::ComponentTypeSection(values) => {
                for value in values {
                    guard.ty(&read(value)?)?;
                }
            }
            Payload::ComponentImportSection(values) => {
                for value in values {
                    guard.reference(read(value)?.ty)?;
                }
            }
            Payload::ComponentExportSection(values) => {
                for value in values {
                    let value = read(value)?;
                    let actual = guard.current()?.at(value.kind, value.index)?;
                    if let Some(ty) = value.ty {
                        guard.record(actual)?;
                        guard.reference(ty)?;
                    } else {
                        guard.push(value.kind, actual)?;
                    }
                }
            }
            Payload::ComponentAliasSection(values) => {
                for value in values {
                    guard.alias(&read(value)?)?;
                }
            }
            Payload::ComponentInstanceSection(values) => {
                for value in values {
                    guard.instance(&read(value)?)?;
                }
            }
            Payload::ComponentCanonicalSection(values) => {
                for value in values {
                    if let CanonicalFunction::Lift { type_index, .. } = read(value)? {
                        let value = guard.current()?.at(Kind::Type, type_index)?;
                        guard.push(Kind::Func, value)?;
                    }
                }
            }
            Payload::ComponentStartSection { start, .. } => {
                let value = guard.current()?.at(Kind::Func, start.func_index)?;
                for _ in 0..start.results {
                    guard.push(Kind::Value, value)?;
                }
            }
            _ => (),
        }
    }
    Ok(())
}

impl Guard {
    fn current(&self) -> Result<&Scope> {
        self.scopes
            .last()
            .ok_or_else(|| invalid("missing-component-scope"))
    }

    fn enter(&mut self) -> Result<()> {
        if self.scopes.len() >= self.limits.max_type_depth {
            return Err(exhausted("component-reference-depth-limit"));
        }
        self.scopes.push(Scope::default());
        Ok(())
    }

    fn leave(&mut self) -> Result<Measure> {
        let scope = self
            .scopes
            .pop()
            .ok_or_else(|| invalid("missing-component-scope"))?;
        let mut result = Measure::LEAF;
        result.include(
            Measure {
                depth: scope.depth,
                work: scope.work,
            },
            self.limits,
        )?;
        Ok(result)
    }

    fn record(&mut self, value: Measure) -> Result<()> {
        charge(&mut self.work, value.work, self.limits.max_type_nodes)?;
        let scope = self
            .scopes
            .last_mut()
            .ok_or_else(|| invalid("missing-component-scope"))?;
        scope.depth = scope.depth.max(value.depth);
        charge(&mut scope.work, value.work, self.limits.max_type_nodes)
    }

    fn push(&mut self, kind: Kind, value: Measure) -> Result<()> {
        self.record(value)?;
        let scope = self
            .scopes
            .last_mut()
            .ok_or_else(|| invalid("missing-component-scope"))?;
        match kind {
            Kind::Type => scope.types.push(value),
            Kind::Func => scope.functions.push(value),
            Kind::Instance => scope.instances.push(value),
            Kind::Component => scope.components.push(value),
            Kind::Value => scope.values.push(value),
            Kind::Module => (),
        }
        Ok(())
    }

    fn value(&self, value: ComponentValType) -> Result<Measure> {
        match value {
            ComponentValType::Primitive(_) => Ok(Measure::LEAF),
            ComponentValType::Type(index) => self.current()?.at(Kind::Type, index),
        }
    }

    fn reference(&mut self, reference: ComponentTypeRef) -> Result<()> {
        let (kind, value) = match reference {
            ComponentTypeRef::Module(_) => (Kind::Module, Measure::LEAF),
            ComponentTypeRef::Func(index) => (Kind::Func, self.current()?.at(Kind::Type, index)?),
            ComponentTypeRef::Instance(index) => {
                (Kind::Instance, self.current()?.at(Kind::Type, index)?)
            }
            ComponentTypeRef::Component(index) => {
                (Kind::Component, self.current()?.at(Kind::Type, index)?)
            }
            ComponentTypeRef::Type(TypeBounds::Eq(index)) => {
                (Kind::Type, self.current()?.at(Kind::Type, index)?)
            }
            ComponentTypeRef::Type(TypeBounds::SubResource) => (Kind::Type, Measure::LEAF),
            ComponentTypeRef::Value(value) => (Kind::Value, self.value(value)?),
        };
        self.push(kind, value)
    }
}
