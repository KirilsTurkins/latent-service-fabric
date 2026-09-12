mod release;
mod rollout;
use super::{invalid_input, proto};
use crate::{
    args::audit::{AuditCommand, Scope},
    config::ResolvedConfig,
    error::Failure,
    operation::Operation,
};
pub(in crate::management) use release::release;
pub(in crate::management) use rollout::rollout;

pub(in crate::management) fn audit(
    command: &AuditCommand,
    config: &ResolvedConfig,
) -> Result<Operation, Failure> {
    let AuditCommand::Query(args) = command;
    let scope = match args.scope {
        Scope::Tenant => proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Tenant as i32,
            tenant: Some(config.tenant.clone()),
        },
        Scope::Node => proto::AuditQueryScope {
            kind: proto::AuditScopeKind::Node as i32,
            tenant: None,
        },
    };
    let kind = args
        .kind
        .as_ref()
        .map(|value| {
            let name = format!(
                "PHASE2_AUDIT_EVENT_KIND_{}",
                value.replace('-', "_").to_ascii_uppercase()
            );
            proto::Phase2AuditEventKind::from_str_name(&name)
                .map(|kind| kind as i32)
                .ok_or_else(invalid_input)
        })
        .transpose()?;
    Ok(Operation::QueryAudit(proto::QueryPhase2AuditRequest {
        scope: Some(scope),
        filter: Some(proto::Phase2AuditFilter {
            kind,
            actor_subject: args.actor.clone(),
            from_unix_millis: args.from_unix_millis,
            to_unix_millis: args.to_unix_millis,
        }),
        page: Some(super::super::prepare::page(
            args.page_size,
            args.page_token.as_deref(),
        )?),
    }))
}
