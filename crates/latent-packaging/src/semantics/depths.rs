//! Exact transitive heights for every WIT arena type, including unused types.
//!
//! The parser represents flat alias chains by IDs. Bound those chains before
//! handing an unresolved arena to Resolve, and again after foreign references
//! have been linked. Retain only borrowed definitions and one state per type.

use latent_core::PlatformError;
use wit_parser::{Handle, Type, TypeDef, TypeDefKind, TypeId};

use super::{exhausted, SemanticLimits};

#[derive(Clone, Copy)]
enum State {
    Unseen,
    Visiting,
    Height(usize),
}

struct Node<'a> {
    id: TypeId,
    definition: &'a TypeDef,
    state: State,
}

struct Guard<'a> {
    nodes: Vec<Node<'a>>,
    work: usize,
    limits: SemanticLimits,
}

pub(super) fn validate<'a>(
    types: impl Iterator<Item = (TypeId, &'a TypeDef)>,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    let mut guard = Guard {
        nodes: Vec::new(),
        work: 0,
        limits,
    };
    for (id, definition) in types {
        if guard.nodes.len() >= limits.max_type_nodes {
            return Err(exhausted("wit-type-graph-node-limit"));
        }
        // Arena iteration is contiguous and ordered. Checking the ID later also
        // prevents a foreign arena's same-numbered ID from becoming an edge.
        if id.index() != guard.nodes.len() {
            return Err(invalid("invalid-wit-type-index"));
        }
        guard.nodes.push(Node {
            id,
            definition,
            state: State::Unseen,
        });
    }
    for index in 0..guard.nodes.len() {
        guard.height(guard.nodes[index].id, 1)?;
    }
    Ok(())
}

impl Guard<'_> {
    fn charge(&mut self, depth: usize) -> Result<(), PlatformError> {
        if depth > self.limits.max_type_depth {
            return Err(exhausted("wit-type-reference-depth-limit"));
        }
        self.work = self
            .work
            .checked_add(1)
            .filter(|value| *value <= self.limits.max_type_nodes)
            .ok_or_else(|| exhausted("wit-type-graph-work-limit"))?;
        Ok(())
    }

    fn ty(&mut self, ty: Type, depth: usize) -> Result<usize, PlatformError> {
        if let Type::Id(id) = ty {
            self.height(id, depth)
        } else {
            self.charge(depth)?;
            Ok(1)
        }
    }

    fn height(&mut self, id: TypeId, depth: usize) -> Result<usize, PlatformError> {
        self.charge(depth)?;
        let node = self
            .nodes
            .get(id.index())
            .filter(|node| node.id == id)
            .ok_or_else(|| invalid("invalid-wit-type-reference"))?;
        match node.state {
            State::Height(height) => {
                if depth
                    .checked_sub(1)
                    .and_then(|value| value.checked_add(height))
                    .is_none_or(|value| value > self.limits.max_type_depth)
                {
                    return Err(exhausted("wit-type-reference-depth-limit"));
                }
                return Ok(height);
            }
            State::Visiting => return Err(invalid("cyclic-wit-type-reference")),
            State::Unseen => (),
        }
        let definition = node.definition;
        self.nodes[id.index()].state = State::Visiting;
        let mut height = 1;
        let mut include = |ty| -> Result<(), PlatformError> {
            let child = self.ty(ty, depth + 1)?;
            height = height.max(child + 1);
            Ok(())
        };
        match &definition.kind {
            TypeDefKind::Record(record) => {
                for field in &record.fields {
                    include(field.ty)?;
                }
            }
            TypeDefKind::Variant(variant) => {
                for case in &variant.cases {
                    if let Some(ty) = case.ty {
                        include(ty)?;
                    }
                }
            }
            TypeDefKind::Tuple(tuple) => {
                for ty in &tuple.types {
                    include(*ty)?;
                }
            }
            TypeDefKind::List(ty)
            | TypeDefKind::Option(ty)
            | TypeDefKind::FixedLengthList(ty, _)
            | TypeDefKind::Type(ty) => include(*ty)?,
            TypeDefKind::Map(key, value) => {
                include(*key)?;
                include(*value)?;
            }
            TypeDefKind::Result(result) => {
                for ty in result.ok.iter().chain(&result.err) {
                    include(*ty)?;
                }
            }
            TypeDefKind::Future(ty) | TypeDefKind::Stream(ty) => {
                if let Some(ty) = ty {
                    include(*ty)?;
                }
            }
            TypeDefKind::Handle(Handle::Own(id) | Handle::Borrow(id)) => include(Type::Id(*id))?,
            // Unknown is a foreign placeholder only in unresolved input. The
            // second pass checks the linked graph; this grants no type support.
            TypeDefKind::Resource
            | TypeDefKind::Flags(_)
            | TypeDefKind::Enum(_)
            | TypeDefKind::Unknown => (),
        }
        self.nodes[id.index()].state = State::Height(height);
        Ok(height)
    }
}

fn invalid(reason: &'static str) -> PlatformError {
    super::super::invalid(reason)
}

#[cfg(test)]
mod tests {
    use std::fmt::Write;

    use super::*;
    use wit_parser::{Resolve, UnresolvedPackageGroup};

    fn source(chain: usize) -> String {
        let mut text = "package tests:depth@1.0.0; interface unused { type t0 = u32;".to_owned();
        for index in 1..chain {
            write!(text, "type t{index} = t{};", index - 1).unwrap();
        }
        text.push_str("} interface api { call: func(); } world service { export api; }");
        text
    }

    #[test]
    fn unused_flat_aliases_check_cached_transitive_heights_before_and_after_resolution() {
        let limits = SemanticLimits {
            max_type_depth: 8,
            ..SemanticLimits::default()
        };
        for (chain, valid) in [(7, true), (8, false), (80, false)] {
            let text = source(chain);
            let unresolved = UnresolvedPackageGroup::parse("fixture.wit", &text).unwrap();
            let before = validate(unresolved.main.types.iter(), limits);
            assert_eq!(before.is_ok(), valid, "unresolved chain {chain}");
            let mut resolved = Resolve::default();
            resolved.push_group(unresolved).unwrap();
            let after = validate(resolved.types.iter(), limits);
            assert_eq!(after.is_ok(), valid, "resolved chain {chain}");
            if !valid {
                assert_eq!(
                    before.unwrap_err().message,
                    "wit-type-reference-depth-limit"
                );
                assert_eq!(after.unwrap_err().message, "wit-type-reference-depth-limit");
            }
        }
    }

    #[test]
    fn cycles_and_foreign_ids_do_not_acquire_cached_heights() {
        let mut resolved = Resolve::default();
        resolved.push_str("fixture.wit", &source(1)).unwrap();
        let id = resolved.types.iter().next().unwrap().0;
        resolved.types[id].kind = TypeDefKind::Type(Type::Id(id));
        assert_eq!(
            validate(resolved.types.iter(), SemanticLimits::default())
                .unwrap_err()
                .message,
            "cyclic-wit-type-reference"
        );
        let mut other = Resolve::default();
        other.push_str("other.wit", &source(1)).unwrap();
        let foreign = other.types.iter().next().unwrap().0;
        resolved.types[id].kind = TypeDefKind::Type(Type::Id(foreign));
        assert_eq!(
            validate(resolved.types.iter(), SemanticLimits::default())
                .unwrap_err()
                .message,
            "invalid-wit-type-reference"
        );
    }

    #[test]
    fn type_arena_and_edge_work_are_independently_bounded() {
        let unresolved = UnresolvedPackageGroup::parse("fixture.wit", &source(2)).unwrap();
        let limits = SemanticLimits {
            max_type_nodes: 1,
            ..SemanticLimits::default()
        };
        assert_eq!(
            validate(unresolved.main.types.iter(), limits)
                .unwrap_err()
                .message,
            "wit-type-graph-node-limit"
        );
        let limits = SemanticLimits {
            max_type_nodes: 2,
            ..SemanticLimits::default()
        };
        assert_eq!(
            validate(unresolved.main.types.iter(), limits)
                .unwrap_err()
                .message,
            "wit-type-graph-work-limit"
        );
    }
}
