//! Authenticated bounded query projection over the node's single audit owner.
mod conversion;
mod enums;
mod lease;
mod legacy;
#[cfg(test)]
mod tests;
mod validation;

use latent_audit::{AuditFilter, AuditQueryRequest, AuditScope};
use tonic::{Request, Response, Status};

use super::{errors::platform_status, proto, ManagementOperation, ManagementServiceAdapter};
pub use lease::AuditResponseService;

pub(super) const MAX_REQUEST_BYTES: usize = 8192;
const MAX_RESPONSE_BYTES: usize = 64 * 1024;

#[tonic::async_trait]
impl proto::audit_service_server::AuditService for ManagementServiceAdapter {
    async fn query_phase2_audit(
        &self,
        mut request: Request<proto::QueryPhase2AuditRequest>,
    ) -> Result<Response<proto::QueryPhase2AuditResponse>, Status> {
        let deadline = validation::deadline(&request);
        let operation = if request
            .get_ref()
            .scope
            .as_ref()
            .is_some_and(|scope| scope.kind == proto::AuditScopeKind::Node as i32)
        {
            ManagementOperation::AuditNode
        } else {
            ManagementOperation::AuditTenant
        };
        let principal = self.authenticate(&mut request, operation)?;
        let scope = validation::typed(request.get_ref(), &principal, &self.limits)?;
        let request = request.into_inner();
        let filter = request.filter.map_or_else(
            || Ok(AuditFilter::default()),
            |filter| {
                Ok::<_, Status>(AuditFilter {
                    kind: filter.kind.map(enums::kind_from_proto).transpose()?,
                    actor: filter.actor_subject,
                    from_unix_millis: filter.from_unix_millis,
                    to_unix_millis: filter.to_unix_millis,
                })
            },
        )?;
        let query = self.audit_query(scope, filter, request.page)?;
        let maximum = query.maximum_bytes;
        let scope = query.scope.clone();
        let page = self
            .services
            .audit
            .as_ref()
            .expect("query checked audit owner")
            .query(query, deadline)
            .map_err(|error| platform_status(error, &self.limits))?
            .wait()
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        validation::completed(deadline)?;
        let (records, coverage, cursor, lease) = page.into_parts();
        conversion::scope(&records, &scope)?;
        let records = records
            .into_iter()
            .map(conversion::record)
            .collect::<Result<_, _>>()?;
        let value = proto::QueryPhase2AuditResponse {
            records,
            page: Some(proto::PageResponse {
                next_page_token: cursor.map(|value| value.0),
            }),
            coverage: Some(conversion::coverage(coverage)),
        };
        validation::encoded(&value, maximum)?;
        let mut response = self.response(value)?;
        response.extensions_mut().insert(lease);
        validation::completed(deadline)?;
        Ok(response)
    }

    async fn query_audit(
        &self,
        mut request: Request<proto::QueryAuditRequest>,
    ) -> Result<Response<proto::QueryAuditResponse>, Status> {
        let deadline = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::AuditTenant)?;
        let scope = validation::legacy(request.get_ref(), &principal, &self.limits)?;
        let request = request.into_inner();
        let filter = AuditFilter {
            kind: request
                .action
                .as_deref()
                .map(enums::kind_from_name)
                .transpose()?,
            actor: request.actor,
            from_unix_millis: request.from_unix_millis,
            to_unix_millis: request.to_unix_millis,
        };
        let query = self.audit_query(scope, filter, request.page)?;
        let maximum = query.maximum_bytes;
        let scope = query.scope.clone();
        let page = self
            .services
            .audit
            .as_ref()
            .expect("query checked audit owner")
            .query(query, deadline)
            .map_err(|error| platform_status(error, &self.limits))?
            .wait()
            .await
            .map_err(|error| platform_status(error, &self.limits))?;
        validation::completed(deadline)?;
        let (records, _, cursor, lease) = page.into_parts();
        conversion::scope(&records, &scope)?;
        let value = proto::QueryAuditResponse {
            events: records.into_iter().map(legacy::record).collect(),
            page: Some(proto::PageResponse {
                next_page_token: cursor.map(|value| value.0),
            }),
        };
        validation::encoded(&value, maximum)?;
        let mut response = self.response(value)?;
        response.extensions_mut().insert(lease);
        validation::completed(deadline)?;
        Ok(response)
    }
}

impl ManagementServiceAdapter {
    fn audit_query(
        &self,
        scope: AuditScope,
        filter: AuditFilter,
        page: Option<proto::PageRequest>,
    ) -> Result<AuditQueryRequest, Status> {
        let handle = self
            .services
            .audit
            .as_ref()
            .ok_or_else(|| Status::unimplemented("durable audit is not configured"))?;
        let limits = handle.limits();
        let page_size = page.as_ref().map_or(0, |value| value.page_size);
        let limit = if page_size == 0 {
            (self.limits.default_page_size as usize).min(limits.maximum_query_events)
        } else {
            page_size as usize
        };
        if limit == 0
            || limit > limits.maximum_query_events
            || limit > self.limits.max_page_size as usize
        {
            return Err(super::bounds::exhausted());
        }
        let maximum_bytes = MAX_RESPONSE_BYTES
            .min(self.limits.max_response_bytes)
            .min(limits.maximum_page_bytes);
        if maximum_bytes < 32 * 1024 {
            return Err(super::bounds::exhausted());
        }
        Ok(AuditQueryRequest {
            scope,
            filter,
            limit,
            maximum_bytes,
            cursor: page
                .and_then(|value| value.page_token)
                .map(latent_audit::AuditCursor),
        })
    }
}
