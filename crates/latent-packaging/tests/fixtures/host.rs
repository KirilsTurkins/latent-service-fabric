//! Encode real, unexecuted Component Model imports from independently parsed WIT.
//! Shared with the runtime's generated-linker compatibility tests.
#![allow(dead_code)]

use std::collections::BTreeMap;
use wasm_encoder::{
    ComponentTypeRef, ComponentValType as Value, InstanceType, PrimitiveValType as P, TypeBounds,
};
use wit_parser::{FunctionKind, Resolve, Type, TypeDefKind, TypeId};

pub fn interface(source: &str, name: &str, asynchronous: Option<bool>) -> InstanceType {
    let mut resolve = Resolve::default();
    resolve.push_source("host.wit", source).unwrap();
    let (_, interface) = resolve
        .interfaces
        .iter()
        .find(|(id, _)| resolve.id_of(*id).as_deref() == Some(name))
        .unwrap();
    let mut encoder = Encoder {
        resolve: &resolve,
        host: InstanceType::new(),
        types: BTreeMap::new(),
    };
    for id in interface.types.values() {
        encoder.value(Type::Id(*id));
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

    fn defined(&mut self, id: TypeId) -> Value {
        if let Some(value) = self.types.get(&id) {
            return *value;
        }
        // This encoder only consumes small acyclic fixture sources. Production
        // parser, arena and comparison budgets are independently exercised.
        let def = &self.resolve.types[id];
        let index = match &def.kind {
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
        let value = if let Some(name) = &def.name {
            let alias = self.host.type_count();
            self.host
                .export(name.as_str(), ComponentTypeRef::Type(TypeBounds::Eq(index)));
            Value::Type(alias)
        } else {
            Value::Type(index)
        };
        self.types.insert(id, value);
        value
    }
}
