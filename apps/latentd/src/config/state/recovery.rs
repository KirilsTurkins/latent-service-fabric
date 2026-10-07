use latent_capabilities::namespace::RecoverySelection;
use latent_core::PlatformError;
use serde::Deserialize;

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RecoverySelectorConfig {
    pub selector: String,
    /// Management-only scope choice; selecting it grants no data/action access.
    pub selection: RecoverySelectionConfig,
}

#[derive(Clone, Debug)]
pub enum RecoverySelectionConfig {
    OriginalCaller,
    ServiceIntegration,
    Shared { name: String },
    Delegated { delegation: String, service: String },
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "kebab-case", deny_unknown_fields)]
enum SelectionWire {
    OriginalCaller {},
    ServiceIntegration {},
    Shared { name: String },
    Delegated { delegation: String, service: String },
}
impl<'de> Deserialize<'de> for RecoverySelectionConfig {
    fn deserialize<D: serde::Deserializer<'de>>(source: D) -> Result<Self, D::Error> {
        Ok(match SelectionWire::deserialize(source)? {
            SelectionWire::OriginalCaller {} => Self::OriginalCaller,
            SelectionWire::ServiceIntegration {} => Self::ServiceIntegration,
            SelectionWire::Shared { name } => Self::Shared { name },
            SelectionWire::Delegated {
                delegation,
                service,
            } => Self::Delegated {
                delegation,
                service,
            },
        })
    }
}

impl RecoverySelectorConfig {
    pub(crate) fn binding(&self) -> latent_wire::phase4::StateManagementRecoveryBinding {
        latent_wire::phase4::StateManagementRecoveryBinding {
            selector: self.selector.clone(),
            selection: match &self.selection {
                RecoverySelectionConfig::OriginalCaller => RecoverySelection::OriginalCaller,
                RecoverySelectionConfig::ServiceIntegration => {
                    RecoverySelection::ServiceIntegration
                }
                RecoverySelectionConfig::Shared { name } => {
                    RecoverySelection::Shared { name: name.clone() }
                }
                RecoverySelectionConfig::Delegated {
                    delegation,
                    service,
                } => RecoverySelection::Delegated {
                    delegation: delegation.clone(),
                    service: service.clone(),
                },
            },
        }
    }
}

pub(super) fn validate(values: &[RecoverySelectorConfig]) -> Result<(), PlatformError> {
    if values.len() > 128 {
        return Err(super::super::invalid("state.recoverySelections"));
    }
    for (index, value) in values.iter().enumerate() {
        super::checked_identity(&value.selector)?;
        if values[..index]
            .iter()
            .any(|prior| prior.selector == value.selector)
        {
            return Err(super::super::invalid("state.recoverySelections"));
        }
        match &value.selection {
            RecoverySelectionConfig::OriginalCaller
            | RecoverySelectionConfig::ServiceIntegration => {}
            RecoverySelectionConfig::Shared { name } => super::checked_identity(name)?,
            RecoverySelectionConfig::Delegated {
                delegation,
                service,
            } => {
                super::checked_identity(delegation)?;
                super::checked_identity(service)?;
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::StateConfig;

    fn input(rows: serde_json::Value) -> serde_json::Value {
        let mut value = super::super::tests::input();
        value["recoverySelections"] = rows;
        value
    }

    #[test]
    fn explicit_management_recovery_selections_derive_closed_data_without_changing_application_callers(
    ) {
        let raw = input(serde_json::json!([
            {"selector":"original", "selection":{"kind":"original-caller"}},
            {"selector":"service", "selection":{"kind":"service-integration"}},
            {"selector":"readers", "selection":{"kind":"shared", "name":"order-readers"}},
            {"selector":"delegation", "selection":{"kind":"delegated", "delegation":"operator-42", "service":"orders-worker"}}
        ]));
        let config: StateConfig = serde_json::from_value(raw).unwrap();
        let settings = super::super::derive(&config).unwrap();
        assert_eq!(settings.recovery_selections.len(), 4);
        assert!(matches!(
            settings.recovery_selections[0].binding().selection,
            RecoverySelection::OriginalCaller
        ));
        assert!(matches!(
            settings.recovery_selections[1].binding().selection,
            RecoverySelection::ServiceIntegration
        ));
        assert!(
            matches!(settings.recovery_selections[2].binding().selection, RecoverySelection::Shared {name} if name == "order-readers")
        );
        assert!(
            matches!(settings.recovery_selections[3].binding().selection, RecoverySelection::Delegated {delegation,service} if delegation == "operator-42" && service == "orders-worker")
        );
        assert_eq!(settings.operations[0].policies, ["state"]);
        let omitted: StateConfig = serde_json::from_value(super::super::tests::input()).unwrap();
        assert!(super::super::derive(&omitted)
            .unwrap()
            .recovery_selections
            .is_empty());
    }

    #[test]
    fn recovery_selector_configuration_rejects_duplicates_unknown_grants_and_unsafe_present_values()
    {
        for selection in [
            serde_json::json!({"kind":"shared","name":""}),
            serde_json::json!({"kind":"shared","name":"line\nfeed"}),
            serde_json::json!({"kind":"delegated","delegation":"a","service":""}),
        ] {
            let config: StateConfig = serde_json::from_value(input(
                serde_json::json!([{"selector":"named","selection":selection}]),
            ))
            .unwrap();
            assert!(super::super::derive(&config).is_err());
        }
        for selection in [
            serde_json::json!({"kind":"original-caller","grant":true}),
            serde_json::json!({"kind":"shared","name":"readers","principal":"alice"}),
            serde_json::json!({"kind":"delegated","delegation":"a","service":null}),
            serde_json::json!({"kind":"future"}),
            serde_json::Value::Null,
        ] {
            assert!(serde_json::from_value::<StateConfig>(input(
                serde_json::json!([{"selector":"named","selection":selection}])
            ))
            .is_err());
        }
        for selector in [String::new(), "x".repeat(257), "line\nfeed".into()] {
            let config: StateConfig = serde_json::from_value(input(serde_json::json!([
                {"selector":selector,"selection":{"kind":"original-caller"}}
            ])))
            .unwrap();
            assert!(super::super::derive(&config).is_err());
        }
        let row = serde_json::json!({"selector":"named","selection":{"kind":"original-caller"}});
        let duplicate: StateConfig =
            serde_json::from_value(input(serde_json::json!([row.clone(), row.clone()]))).unwrap();
        assert!(super::super::derive(&duplicate).is_err());
        let excessive: StateConfig = serde_json::from_value(input(serde_json::Value::Array((0..129).map(|i| serde_json::json!({"selector":format!("choice-{i}"),"selection":{"kind":"original-caller"}})).collect()))).unwrap();
        assert!(super::super::derive(&excessive).is_err());
        assert!(serde_json::from_value::<StateConfig>(input(serde_json::Value::Null)).is_err());
    }
}
