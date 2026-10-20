//! Immutable dispatch over separate installed providers, never credential aliases.
use std::sync::Arc;

use latent_capabilities::broker::{
    http::HttpError,
    streaming_http::{
        HttpPhaseError, PhaseHttpInvocation, StreamingHttpError, StreamingHttpInvocation,
        StreamingHttpInvoker, StreamingHttpRequest,
    },
    CapabilitySession,
};
use latent_core::{PlatformError, TenantId};
use latent_http::StreamingHttpProvider;

pub(crate) struct StreamingDispatcher {
    installations: Vec<(TenantId, StreamingHttpProvider)>,
}

impl StreamingDispatcher {
    pub(crate) fn compose(
        mut installations: Vec<(TenantId, StreamingHttpProvider)>,
    ) -> Result<Option<Arc<dyn StreamingHttpInvoker>>, PlatformError> {
        if installations.len() > 14 {
            return Err(super::super::unavailable());
        }
        // Keep the original single-installation runtime path unchanged.
        if installations.len() == 1 {
            return Ok(installations
                .pop()
                .map(|(_, provider)| Arc::new(provider) as Arc<dyn StreamingHttpInvoker>));
        }
        if installations.is_empty() {
            return Ok(None);
        }
        Ok(Some(Arc::new(Self { installations })))
    }

    fn selected(&self, session: &CapabilitySession) -> Result<&StreamingHttpProvider, HttpError> {
        session.check_liveness().map_err(HttpError::from)?;
        select_unique(&self.installations, session.tenant(), |provider| {
            session
                .uses_provider(&provider.reference())
                .map_err(Into::into)
        })
    }
}

fn select_unique<'a, Provider>(
    installations: &'a [(TenantId, Provider)],
    tenant: &TenantId,
    mut eligible: impl FnMut(&Provider) -> Result<bool, HttpError>,
) -> Result<&'a Provider, HttpError> {
    let mut selected = None;
    for (scope, provider) in installations {
        if scope == tenant && eligible(provider)? {
            if selected.is_some() {
                return Err(HttpError::PermissionDenied);
            }
            selected = Some(provider);
        }
    }
    selected.ok_or(HttpError::PermissionDenied)
}

impl StreamingHttpInvoker for StreamingDispatcher {
    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
    ) -> Result<StreamingHttpInvocation, StreamingHttpError> {
        // Concrete start repeats the original sealed-reference, credential,
        // grant, audit, epoch and per-provider/global admission checks.
        self.selected(session)?.start(session, request)
    }

    fn start_with_connect_timeout(
        &self,
        session: &CapabilitySession,
        request: StreamingHttpRequest,
        timeout_millis: Option<u32>,
    ) -> Result<PhaseHttpInvocation, HttpPhaseError> {
        self.selected(session)?
            .start_with_connect_timeout(session, request, timeout_millis)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selection_never_queries_foreign_providers_and_requires_one_sealed_match() {
        let tenant = TenantId("a".into());
        let installed = [
            (TenantId("b".into()), 0),
            (tenant.clone(), 1),
            (tenant.clone(), 2),
        ];
        let mut visited = Vec::new();
        assert_eq!(
            select_unique(&installed, &tenant, |id| {
                visited.push(*id);
                Ok(*id == 2)
            }),
            Ok(&2)
        );
        assert_eq!(visited, vec![1, 2]);
        for match_all in [false, true] {
            assert_eq!(
                select_unique(&installed, &tenant, |_| Ok(match_all)),
                Err(HttpError::PermissionDenied)
            );
        }
        assert_eq!(
            select_unique(&installed, &TenantId("absent".into()), |_| {
                panic!("foreign provider was queried")
            }),
            Err(HttpError::PermissionDenied)
        );
    }

    #[test]
    fn selection_preserves_liveness_errors_without_fallback_or_partial_dispatch() {
        let tenant = TenantId("a".into());
        let installed = [
            (tenant.clone(), 1),
            (tenant.clone(), 2),
            (tenant.clone(), 3),
        ];
        for error in [
            HttpError::Cancelled,
            HttpError::DeadlineExceeded,
            HttpError::BudgetExhausted,
        ] {
            let mut visited = Vec::new();
            assert_eq!(
                select_unique(&installed, &tenant, |id| {
                    visited.push(*id);
                    if *id == 2 {
                        Err(error)
                    } else {
                        Ok(true)
                    }
                }),
                Err(error)
            );
            assert_eq!(visited, vec![1, 2]);
        }
    }
}
