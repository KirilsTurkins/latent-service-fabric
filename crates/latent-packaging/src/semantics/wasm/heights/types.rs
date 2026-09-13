use super::{Guard, Kind, Measure, Result};
use wasmparser::{
    ComponentDefinedType, ComponentType, ComponentTypeDeclaration, ComponentValType,
    InstanceTypeDeclaration,
};

impl Guard {
    pub(super) fn ty(&mut self, ty: &ComponentType<'_>) -> Result<()> {
        let value = match ty {
            ComponentType::Resource { .. } => Measure::LEAF,
            ComponentType::Defined(ty) => self.defined(ty)?,
            ComponentType::Func(function) => {
                let mut result = Measure::LEAF;
                for (_, value) in &function.params {
                    result.include(self.value(*value)?, self.limits)?;
                }
                if let Some(value) = function.result {
                    result.include(self.value(value)?, self.limits)?;
                }
                result
            }
            ComponentType::Component(declarations) => {
                self.enter()?;
                for declaration in declarations {
                    match declaration {
                        ComponentTypeDeclaration::Type(value) => self.ty(value)?,
                        ComponentTypeDeclaration::Alias(value) => self.alias(value)?,
                        ComponentTypeDeclaration::Import(value) => self.reference(value.ty)?,
                        ComponentTypeDeclaration::Export { ty, .. } => self.reference(*ty)?,
                        ComponentTypeDeclaration::CoreType(_) => (),
                    }
                }
                self.leave()?
            }
            ComponentType::Instance(declarations) => {
                self.enter()?;
                for declaration in declarations {
                    match declaration {
                        InstanceTypeDeclaration::Type(value) => self.ty(value)?,
                        InstanceTypeDeclaration::Alias(value) => self.alias(value)?,
                        InstanceTypeDeclaration::Export { ty, .. } => self.reference(*ty)?,
                        InstanceTypeDeclaration::CoreType(_) => (),
                    }
                }
                self.leave()?
            }
        };
        self.push(Kind::Type, value)
    }

    fn defined(&self, ty: &ComponentDefinedType<'_>) -> Result<Measure> {
        let mut result = Measure::LEAF;
        let mut include = |value| result.include(self.value(value)?, self.limits);
        match ty {
            ComponentDefinedType::Primitive(_)
            | ComponentDefinedType::Flags(_)
            | ComponentDefinedType::Enum(_) => (),
            ComponentDefinedType::Record(fields) => {
                for (_, value) in fields {
                    include(*value)?;
                }
            }
            ComponentDefinedType::Variant(cases) => {
                for case in cases {
                    if let Some(value) = case.ty {
                        include(value)?;
                    }
                }
            }
            ComponentDefinedType::Tuple(values) => {
                for value in values {
                    include(*value)?;
                }
            }
            ComponentDefinedType::List(value)
            | ComponentDefinedType::Option(value)
            | ComponentDefinedType::FixedLengthList(value, _) => include(*value)?,
            ComponentDefinedType::Map(key, value) => {
                include(*key)?;
                include(*value)?;
            }
            ComponentDefinedType::Result { ok, err } => {
                for value in ok.iter().chain(err) {
                    include(*value)?;
                }
            }
            ComponentDefinedType::Future(value) | ComponentDefinedType::Stream(value) => {
                if let Some(value) = value {
                    include(*value)?;
                }
            }
            ComponentDefinedType::Own(index) | ComponentDefinedType::Borrow(index) => {
                include(ComponentValType::Type(*index))?;
            }
        }
        Ok(result)
    }
}
