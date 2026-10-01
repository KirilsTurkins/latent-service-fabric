use super::{invalid, Guard, Kind, Measure, Result};
use std::collections::BTreeMap;
use wasmparser::{ComponentAlias, ComponentInstance, ComponentOuterAliasKind};

impl<'a> Guard<'a> {
    pub(super) fn alias(&mut self, alias: &ComponentAlias<'_>) -> Result<()> {
        match *alias {
            ComponentAlias::InstanceExport {
                kind,
                instance_index,
                name,
            } => {
                // An alias visits this named member, not every private or public
                // sibling in its instance. The member's full transitive measure
                // still spends the independent reference/depth limits.
                let instance = self.current()?.at(Kind::Instance, instance_index)?;
                let exports = instance
                    .exports
                    .and_then(|index| self.exports.get(index))
                    .ok_or_else(|| invalid("invalid-component-export-reference"))?;
                let (actual_kind, value) = exports
                    .get(name)
                    .copied()
                    .ok_or_else(|| invalid("invalid-component-export-reference"))?;
                if actual_kind != kind {
                    return Err(invalid("invalid-component-export-kind"));
                }
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

    pub(super) fn instance(&mut self, instance: &ComponentInstance<'a>) -> Result<()> {
        let mut result = Measure::LEAF;
        match instance {
            ComponentInstance::Instantiate {
                component_index,
                args,
            } => {
                let component = self.current()?.at(Kind::Component, *component_index)?;
                result.include(component, self.limits)?;
                result.exports = component.exports;
                for argument in args {
                    result.include(
                        self.current()?.at(argument.kind, argument.index)?,
                        self.limits,
                    )?;
                }
            }
            ComponentInstance::FromExports(exports) => {
                let mut members = BTreeMap::new();
                for export in exports {
                    let value = self.current()?.at(export.kind, export.index)?;
                    result.include(value, self.limits)?;
                    self.insert_export(&mut members, export.name.name, export.kind, value)?;
                }
                result.exports = Some(self.retain_exports(members)?);
            }
        }
        self.push(Kind::Instance, result)
    }
}
