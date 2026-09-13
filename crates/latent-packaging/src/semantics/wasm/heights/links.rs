use super::{invalid, Guard, Kind, Measure, Result};
use wasmparser::{ComponentAlias, ComponentInstance, ComponentOuterAliasKind};

impl Guard {
    pub(super) fn alias(&mut self, alias: &ComponentAlias<'_>) -> Result<()> {
        match *alias {
            ComponentAlias::InstanceExport {
                kind,
                instance_index,
                ..
            } => {
                // A whole-instance maximum safely overestimates any named export.
                let value = self.current()?.at(Kind::Instance, instance_index)?;
                self.push(kind, value)
            }
            ComponentAlias::Outer { kind, count, index } => {
                let kind = match kind {
                    ComponentOuterAliasKind::Type => Kind::Type,
                    ComponentOuterAliasKind::Component => Kind::Component,
                    ComponentOuterAliasKind::CoreModule | ComponentOuterAliasKind::CoreType => {
                        return Ok(())
                    }
                };
                let level = self
                    .scopes
                    .len()
                    .checked_sub(count as usize + 1)
                    .ok_or_else(|| invalid("invalid-component-outer-reference"))?;
                let value = self.scopes[level].at(kind, index)?;
                self.push(kind, value)
            }
            ComponentAlias::CoreInstanceExport { .. } => Ok(()),
        }
    }

    pub(super) fn instance(&mut self, instance: &ComponentInstance<'_>) -> Result<()> {
        let mut result = Measure::LEAF;
        match instance {
            ComponentInstance::Instantiate {
                component_index,
                args,
            } => {
                result.include(
                    self.current()?.at(Kind::Component, *component_index)?,
                    self.limits,
                )?;
                for argument in args {
                    result.include(
                        self.current()?.at(argument.kind, argument.index)?,
                        self.limits,
                    )?;
                }
            }
            ComponentInstance::FromExports(exports) => {
                for export in exports {
                    result.include(self.current()?.at(export.kind, export.index)?, self.limits)?;
                }
            }
        }
        self.push(Kind::Instance, result)
    }
}
