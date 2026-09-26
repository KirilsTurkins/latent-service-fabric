use super::super::{proto, RequestBudget};
use latent_capabilities::broker::diagnostics::InspectionPlan;
use latent_core::{InvocationPrincipal, PlatformError, PlatformErrorCode};
use sha2::{Digest, Sha256};
use std::ops::Range;
use tonic::Status;

pub(super) fn validate(
    page: Option<&proto::PageRequest>,
    budget: &mut RequestBudget,
) -> Result<(), Status> {
    if let Some(page) = page {
        if page.page_size > 128 {
            return Err(Status::invalid_argument("capability-inspection-page-size"));
        }
        if let Some(token) = &page.page_token {
            budget.string(token, 160)?;
        }
    }
    Ok(())
}
fn invalid() -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::InvalidArgument,
        message: "capability-inspection-cursor".into(),
        retryable: false,
        details: Vec::new(),
    }
}

pub(super) fn select(
    request: &proto::ListCapabilitiesRequest,
    principal: &InvocationPrincipal,
    selected: &InspectionPlan,
    count: usize,
) -> Result<(Range<usize>, Option<String>), PlatformError> {
    let mut hash = Sha256::new();
    hash.update(b"latent:capability-inspection:cursor:v1");
    for value in [
        principal.tenant.as_ref().map_or("", |t| t.0.as_str()),
        &principal.subject,
        &format!("{:?}", principal.kind),
        &request.deployment_id,
        request.contract_prefix.as_deref().unwrap_or(""),
        request.provider.as_deref().unwrap_or(""),
    ] {
        hash.update((value.len() as u64).to_le_bytes());
        hash.update(value.as_bytes());
    }
    let prefix = format!(
        "v1:{}:{}:{:x}:",
        selected.generation.0,
        selected.catalog_transaction,
        hash.finalize()
    );
    let offset = request
        .page
        .as_ref()
        .and_then(|p| p.page_token.as_ref())
        .map(|token| {
            let value = token.strip_prefix(&prefix).ok_or_else(invalid)?;
            let offset = value.parse::<usize>().map_err(|_| invalid())?;
            if offset.to_string() != value || offset == 0 || offset >= count {
                return Err(invalid());
            }
            Ok(offset)
        })
        .transpose()?
        .unwrap_or(0);
    let size = request.page.as_ref().map_or(128, |p| {
        if p.page_size == 0 {
            128
        } else {
            p.page_size as usize
        }
    });
    let end = count.min(offset.saturating_add(size));
    Ok((offset..end, (end < count).then(|| format!("{prefix}{end}"))))
}
#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{
        DeploymentId, Metadata, PrincipalKind, ReleaseDigest, RevisionId, RouteGeneration, TenantId,
    };

    #[test]
    fn cursor_pins_both_catalog_versions_scope_and_filters() {
        let mut selected = InspectionPlan {
            generation: RouteGeneration(9),
            catalog_transaction: 12,
            deployment: DeploymentId("d".into()),
            revision: RevisionId("r".into()),
            component: ReleaseDigest(format!("sha256:{}", "a".repeat(64))),
            publication: None,
            plan: None,
        };
        let mut principal = InvocationPrincipal {
            subject: "admin".into(),
            kind: PrincipalKind::Administrator,
            tenant: Some(TenantId("a".into())),
            service: None,
            claims: Metadata::new(),
        };
        let mut request = proto::ListCapabilitiesRequest {
            deployment_id: "d".into(),
            page: Some(proto::PageRequest {
                page_size: 1,
                page_token: None,
            }),
            ..Default::default()
        };
        let (range, token) = select(&request, &principal, &selected, 3).unwrap();
        assert_eq!(range, 0..1);
        request.page.as_mut().unwrap().page_token = token;
        assert_eq!(select(&request, &principal, &selected, 3).unwrap().0, 1..2);
        selected.catalog_transaction += 1;
        assert!(select(&request, &principal, &selected, 3).is_err());
        selected.catalog_transaction -= 1;
        selected.generation.0 += 1;
        assert!(select(&request, &principal, &selected, 3).is_err());
        selected.generation.0 -= 1;
        principal.tenant = Some(TenantId("b".into()));
        assert!(select(&request, &principal, &selected, 3).is_err());
        principal.tenant = Some(TenantId("a".into()));
        request.provider = Some("different".into());
        assert!(select(&request, &principal, &selected, 3).is_err());
    }
}
