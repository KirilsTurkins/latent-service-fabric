use super::{denied, PlatformError, StateRequest};
use crate::standalone::state::InstalledTransactionOperation;
use latent_core::transaction_contract::{AbortFence, ExpectedVersion, Precondition};
use latent_manifest::TransactionOperationMode;
use latent_wire::{
    invocation::proto as i,
    phase4::{contract, transaction as t},
};

pub(super) struct Selected {
    pub invocation: i::InvokeRequest,
    pub request: StateRequest,
    pub query: bool,
    pub original_command: Option<t::CommandSelector>,
    namespace: t::NamespaceSelector,
    entity: Option<String>,
    operation: String,
}
impl Selected {
    pub fn check(&self, installed: &InstalledTransactionOperation) -> Result<(), PlatformError> {
        if installed.target().tenant.0 != self.namespace.tenant
            || installed.namespace() != self.namespace.namespace
            || installed.incarnation().to_string() != self.namespace.incarnation
            || installed.entity() != self.entity.as_deref()
            || installed.target().function.0 != self.operation
            || installed.mode()
                != if self.query {
                    TransactionOperationMode::FreshQuery
                } else {
                    TransactionOperationMode::StrictCommand
                }
        {
            return Err(denied());
        }
        Ok(())
    }
}
pub(super) fn select(message: contract::Request) -> Result<Selected, PlatformError> {
    match message {
        contract::Request::InvokeCommand(value) => {
            if value.input_format != "lsf-wit-values-v1" {
                return Err(denied());
            }
            let command = value.command.ok_or_else(denied)?;
            // This installed application slice still requires the original
            // caller. Management-only selectors cannot invent application scope.
            if command.shared_recovery_scope.is_some() {
                return Err(denied());
            }
            let original_command = Some(command.clone());
            let namespace = command.namespace.ok_or_else(denied)?;
            let invocation = value.invocation.ok_or_else(denied)?;
            if invocation.media_type != "application/vnd.latent.wit-values.v1+json" {
                return Err(denied());
            }
            let conditions = value
                .expected_versions
                .into_iter()
                .map(|row| {
                    let expected = match row.expectation {
                        Some(t::expected_version::Expectation::Absent(true)) => {
                            ExpectedVersion::Absent
                        }
                        Some(t::expected_version::Expectation::Version(bytes)) => {
                            ExpectedVersion::Present(bytes)
                        }
                        _ => return Err(denied()),
                    };
                    Ok(Precondition {
                        key: row.key,
                        expected,
                    })
                })
                .collect::<Result<Vec<_>, PlatformError>>()?;
            let retry = value
                .retry_attempt
                .map(|value| {
                    let proof = value.expected_abort.ok_or_else(denied)?;
                    latent_node::transaction_runtime::command_completion::CommandRetry::new(
                        value.request_id,
                        AbortFence {
                            command_id: proof.command_id,
                            attempt_id: proof.attempt_id,
                            transaction_id: proof.transaction_id,
                            owner_fence: proof.owner_fence,
                        },
                    )
                })
                .transpose()?;
            Ok(Selected {
                invocation,
                request: StateRequest::command(command.client_key, conditions, vec![], retry)?,
                query: false,
                original_command,
                namespace,
                entity: command.entity,
                operation: command.operation,
            })
        }
        contract::Request::Query(value) => {
            let invocation = value.invocation.ok_or_else(denied)?;
            if invocation.media_type != "application/vnd.latent.wit-values.v1+json" {
                return Err(denied());
            }
            let operation = invocation
                .target
                .as_ref()
                .ok_or_else(denied)?
                .function
                .clone();
            Ok(Selected {
                invocation,
                request: StateRequest::query(value.minimum_view_version)?,
                query: true,
                original_command: None,
                namespace: value.namespace.ok_or_else(denied)?,
                entity: value.entity,
                operation,
            })
        }
        _ => Err(denied()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn command() -> t::InvokeCommandRequest {
        t::InvokeCommandRequest {
            profile: Some(contract::current_profile()),
            invocation: Some(i::InvokeRequest {
                target: Some(i::InvocationTarget {
                    tenant: "a".into(),
                    service: "a/aggregate".into(),
                    contract: "a:aggregate/api@1.0.0".into(),
                    function: "update".into(),
                    route: None,
                }),
                payload: b"{\"params\":[]}".to_vec(),
                media_type: "application/vnd.latent.wit-values.v1+json".into(),
                budget: Some(i::ResourceBudget {
                    cpu_fuel: 100,
                    memory_bytes: 4096,
                    wall_time_limit_millis: Some(500),
                    ..Default::default()
                }),
                ..Default::default()
            }),
            command: Some(t::CommandSelector {
                namespace: Some(t::NamespaceSelector {
                    tenant: "a".into(),
                    namespace: "orders".into(),
                    incarnation: "1".into(),
                }),
                operation: "update".into(),
                entity: None,
                client_key: "original-key".into(),
                shared_recovery_scope: None,
            }),
            input_format: "lsf-wit-values-v1".into(),
            expected_versions: vec![t::ExpectedVersion {
                key: b"counter".to_vec(),
                expectation: Some(t::expected_version::Expectation::Version(vec![4, 5, 6])),
            }],
            retry_attempt: None,
        }
    }
    #[test]
    fn command_rpc_selection_preserves_original_preconditions_and_refuses_scope_authority_from_metadata(
    ) {
        let selected = select(command().into()).unwrap();
        let crate::standalone::state::request::RequestKind::Command {
            client_id,
            conditions,
            retry,
            ..
        } = selected.request.kind
        else {
            panic!("command selection");
        };
        assert_eq!(client_id, "original-key");
        assert!(retry.is_none());
        assert_eq!(conditions[0].key, b"counter");
        assert_eq!(
            conditions[0].expected,
            ExpectedVersion::Present(vec![4, 5, 6])
        );
        let mut changed = command();
        changed.command.as_mut().unwrap().shared_recovery_scope =
            Some("known-management-selector".into());
        assert!(select(changed.into()).is_err());
        let mut changed = command();
        changed.input_format = "arbitrary-json".into();
        assert!(select(changed.into()).is_err());
        let mut changed = command();
        changed.invocation.as_mut().unwrap().media_type = "application/json".into();
        assert!(select(changed.into()).is_err());
        let mut changed = command();
        changed.expected_versions[0].expectation =
            Some(t::expected_version::Expectation::Absent(false));
        assert!(select(changed.into()).is_err());
    }
}
