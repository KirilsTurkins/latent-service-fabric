use super::{
    contract, invalid, Arc, AuthenticatedInvocationContext, Inner, PlatformError,
    StateManagementBinding,
};
use latent_audit::{AuditControlAction, AuditIdentities, AuditScope, AuditStateTarget};
use prost::Message;
use sha2::{Digest, Sha256};

pub(super) async fn begin(
    inner: &Arc<Inner>,
    context: &AuthenticatedInvocationContext,
    binding: &StateManagementBinding,
    request: &contract::Request,
) -> Result<super::super::audit::Pending, PlatformError> {
    let mut hash = Sha256::new();
    hash.update(b"lsf-command-result-read-v1\0");
    match request {
        contract::Request::LookupCommand(value) => {
            hash.update(b"command\0");
            hash.update(value.encode_to_vec());
        }
        contract::Request::LookupCommit(value) => {
            hash.update(b"commit\0");
            hash.update(value.encode_to_vec());
        }
        contract::Request::GetEffect(value) => {
            hash.update(b"effect\0");
            hash.update(value.encode_to_vec());
        }
        contract::Request::CancelCommand(value) => {
            hash.update(b"cancel\0");
            hash.update(value.encode_to_vec());
        }
        _ => return Err(invalid()),
    }
    super::super::audit::begin_operation(
        inner,
        context,
        super::super::audit::OperationAudit {
            scope: AuditScope::Tenant(context.principal().tenant.clone().ok_or_else(invalid)?),
            identities: AuditIdentities {
                state: Some(AuditStateTarget {
                    namespace: binding.namespace.0.clone(),
                    incarnation: binding.incarnation,
                    state_schema: binding.state_schema.parse().map_err(|_| invalid())?,
                }),
                publication: Some(binding.publication.id.clone()),
                component: Some(binding.component.clone()),
                ..Default::default()
            },
            operation_id: super::super::audit::read_operation_id(
                if matches!(request, contract::Request::CancelCommand(_)) {
                    "command-cancel"
                } else {
                    "command-result"
                },
            )?,
            action: if matches!(request, contract::Request::CancelCommand(_)) {
                AuditControlAction::CommandCancel
            } else {
                AuditControlAction::StateOperationRead
            },
            expected: None,
            request_digest: format!(
                "sha256:{:x}",
                latent_core::digest::HexDigest(hash.finalize())
            )
            .parse()
            .map_err(|_| invalid())?,
        },
    )
    .await
}
