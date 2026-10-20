//! Encode real, unexecuted Component Model imports from independently parsed WIT.
//! Shared with the runtime's generated-linker compatibility tests.
#![allow(dead_code)]

use std::collections::{BTreeMap, BTreeSet};
use wasm_encoder::{
    Alias, ComponentOuterAliasKind, ComponentTypeRef, ComponentValType as Value, InstanceType,
    PrimitiveValType as P, TypeBounds,
};
use wit_parser::{FunctionKind, Resolve, Type, TypeDefKind, TypeId};

pub fn interface(source: &str, name: &str, asynchronous: Option<bool>) -> InstanceType {
    interface_with_dependencies(&[("host.wit", source)], name, asynchronous)
}

pub fn interface_with_dependencies(
    sources: &[(&str, &str)],
    name: &str,
    asynchronous: Option<bool>,
) -> InstanceType {
    let mut resolve = Resolve::default();
    for (path, source) in sources {
        resolve.push_source(path, source).unwrap();
    }
    encode_interface(&resolve, name, asynchronous)
}

/// Import the original named type closure without any operations or authority.
pub fn interface_types(source: &str, name: &str) -> InstanceType {
    let mut resolve = Resolve::default();
    resolve.push_source("host.wit", source).unwrap();
    encode_with_resources(&resolve, name, None, &[], false)
}

/// Share actual outer type identities instead of redefining foreign owners.
pub fn interface_with_type_aliases(
    sources: &[(&str, &str)],
    name: &str,
    asynchronous: Option<bool>,
    resources: &[(&str, &str, u32)],
) -> InstanceType {
    let mut resolve = Resolve::default();
    for (path, source) in sources {
        resolve.push_source(path, source).unwrap();
    }
    encode_with_resources(&resolve, name, asynchronous, resources, true)
}

/// Parse one exact committed package directory and its own declared WIT deps.
/// This is an unexecuted type fixture, not an installed WASI implementation.
pub fn interface_from_directory(
    directory: &std::path::Path,
    name: &str,
    asynchronous: Option<bool>,
) -> InstanceType {
    let mut resolve = Resolve::default();
    resolve.push_dir(directory).unwrap();
    encode_interface(&resolve, name, asynchronous)
}

fn encode_interface(resolve: &Resolve, name: &str, asynchronous: Option<bool>) -> InstanceType {
    encode_with_resources(resolve, name, asynchronous, &[], true)
}

fn encode_with_resources(
    resolve: &Resolve,
    name: &str,
    asynchronous: Option<bool>,
    resources: &[(&str, &str, u32)],
    include_functions: bool,
) -> InstanceType {
    let (_, interface) = resolve
        .interfaces
        .iter()
        .find(|(id, _)| resolve.id_of(*id).as_deref() == Some(name))
        .unwrap();
    let mut encoder = Encoder {
        resolve,
        host: InstanceType::new(),
        types: BTreeMap::new(),
        names: BTreeMap::new(),
        // Only the explicit shared-owner path restricts named exports. Imported
        // foreign definitions retain their original outer names and identities.
        exports: (!resources.is_empty()).then(|| interface.types.values().copied().collect()),
    };
    for (owner, name, outer) in resources {
        let (_, owner) = resolve
            .interfaces
            .iter()
            .find(|(id, _)| resolve.id_of(*id).as_deref() == Some(*owner))
            .unwrap();
        let resource = owner.types[*name];
        assert_eq!(resolve.types[resource].name.as_deref(), Some(*name));
        let index = encoder.host.type_count();
        encoder.host.alias(Alias::Outer {
            kind: ComponentOuterAliasKind::Type,
            count: 1,
            index: *outer,
        });
        assert!(encoder.types.insert(resource, Value::Type(index)).is_none());
    }
    for id in interface.types.values() {
        encoder.value(Type::Id(*id));
    }
    if !include_functions {
        return encoder.host;
    }
    for function in interface.functions.values() {
        let params: Vec<_> = function
            .params
            .iter()
            .map(|p| (p.name.as_str(), encoder.value(p.ty)))
            .collect();
        let result = function.result.map(|ty| encoder.value(ty));
        let index = encoder.host.type_count();
        encoder
            .host
            .ty()
            .function()
            .async_(asynchronous.unwrap_or(function.kind == FunctionKind::AsyncFreestanding))
            .params(params)
            .result(result);
        encoder
            .host
            .export(&function.name, ComponentTypeRef::Func(index));
    }
    encoder.host
}

struct Encoder<'a> {
    resolve: &'a Resolve,
    host: InstanceType,
    types: BTreeMap<TypeId, Value>,
    names: BTreeMap<String, Value>,
    exports: Option<BTreeSet<TypeId>>,
}

impl Encoder<'_> {
    fn value(&mut self, ty: Type) -> Value {
        let primitive = match ty {
            Type::Bool => P::Bool,
            Type::U8 => P::U8,
            Type::S8 => P::S8,
            Type::U16 => P::U16,
            Type::S16 => P::S16,
            Type::U32 => P::U32,
            Type::S32 => P::S32,
            Type::U64 => P::U64,
            Type::S64 => P::S64,
            Type::F32 => P::F32,
            Type::F64 => P::F64,
            Type::Char => P::Char,
            Type::String => P::String,
            Type::Id(id) => return self.defined(id),
            Type::ErrorContext => panic!("unsupported fixture type"),
        };
        primitive.into()
    }

    fn handle(&mut self, handle: &wit_parser::Handle) -> u32 {
        let (id, own) = match handle {
            wit_parser::Handle::Own(id) => (*id, true),
            wit_parser::Handle::Borrow(id) => (*id, false),
        };
        let Value::Type(resource) = self.value(Type::Id(id)) else {
            panic!("named fixture resource")
        };
        let index = self.host.type_count();
        if own {
            self.host.ty().defined_type().own(resource);
        } else {
            self.host.ty().defined_type().borrow(resource);
        }
        index
    }

    fn defined(&mut self, id: TypeId) -> Value {
        if let Some(value) = self.types.get(&id) {
            return *value;
        }
        // This encoder only consumes small acyclic fixture sources. Production
        // parser, arena and comparison budgets are independently exercised.
        let def = &self.resolve.types[id];
        if matches!(def.kind, TypeDefKind::Resource) {
            assert!(
                self.exports.as_ref().is_none_or(|ids| ids.contains(&id)),
                "foreign fixture resources require their outer owner aliases"
            );
            let index = self.host.type_count();
            self.host.export(
                def.name.as_deref().expect("named fixture resource"),
                ComponentTypeRef::Type(TypeBounds::SubResource),
            );
            let value = Value::Type(index);
            assert!(self
                .names
                .insert(def.name.clone().unwrap(), value)
                .is_none());
            self.types.insert(id, value);
            return value;
        }
        let index = match &def.kind {
            TypeDefKind::Handle(handle) => self.handle(handle),
            TypeDefKind::Type(ty) => {
                let value = self.value(*ty);
                match value {
                    Value::Type(index) => index,
                    Value::Primitive(p) => {
                        let index = self.host.type_count();
                        self.host.ty().defined_type().primitive(p);
                        index
                    }
                }
            }
            TypeDefKind::Record(record) => {
                let fields: Vec<_> = record
                    .fields
                    .iter()
                    .map(|f| (f.name.as_str(), self.value(f.ty)))
                    .collect();
                let index = self.host.type_count();
                self.host.ty().defined_type().record(fields);
                index
            }
            TypeDefKind::Variant(variant) => {
                let cases: Vec<_> = variant
                    .cases
                    .iter()
                    .map(|c| (c.name.as_str(), c.ty.map(|t| self.value(t))))
                    .collect();
                let index = self.host.type_count();
                self.host.ty().defined_type().variant(cases);
                index
            }
            TypeDefKind::Enum(value) => {
                let index = self.host.type_count();
                self.host
                    .ty()
                    .defined_type()
                    .enum_type(value.cases.iter().map(|c| c.name.as_str()));
                index
            }
            TypeDefKind::Tuple(tuple) => {
                let items: Vec<_> = tuple.types.iter().map(|t| self.value(*t)).collect();
                let index = self.host.type_count();
                self.host.ty().defined_type().tuple(items);
                index
            }
            TypeDefKind::List(ty) | TypeDefKind::Option(ty) => {
                let value = self.value(*ty);
                let index = self.host.type_count();
                let encoder = self.host.ty().defined_type();
                if matches!(def.kind, TypeDefKind::List(_)) {
                    encoder.list(value);
                } else {
                    encoder.option(value);
                }
                index
            }
            TypeDefKind::Result(result) => {
                let ok = result.ok.map(|t| self.value(t));
                let err = result.err.map(|t| self.value(t));
                let index = self.host.type_count();
                self.host.ty().defined_type().result(ok, err);
                index
            }
            _ => panic!("unsupported fixture shape"),
        };
        let visible = self.exports.as_ref().is_none_or(|ids| ids.contains(&id));
        let value = if let Some(name) = def.name.as_ref().filter(|_| visible) {
            if let Some(existing) = self.names.get(name) {
                // WIT `use` aliases can reuse the original exported spelling.
                // Preserve that one type identity, not a second resource.
                assert_eq!(*existing, Value::Type(index));
                *existing
            } else {
                let alias = self.host.type_count();
                self.host
                    .export(name.as_str(), ComponentTypeRef::Type(TypeBounds::Eq(index)));
                let value = Value::Type(alias);
                self.names.insert(name.clone(), value);
                value
            }
        } else {
            Value::Type(index)
        };
        self.types.insert(id, value);
        value
    }
}
