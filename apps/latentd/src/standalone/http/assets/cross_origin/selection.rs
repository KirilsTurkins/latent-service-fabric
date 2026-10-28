//! One shared-router selection, retained through preflight/error output or read.
use super::super::{request, Request};
use super::metadata::Candidate;
use crate::standalone::http::{head::Head, Shared};
use latent_artifacts::{web::WebSelection, PublicationRef};
use latent_control_store::http_routes::{AcceptedHttpRoute, AcceptedHttpTarget};
use latent_ingress::http::MAX_HEADERS;
use latent_wire::invocation::{LocalPrincipalPolicy, PrincipalPolicy};

pub(super) enum Selection {
    Routed(AcceptedHttpRoute),
    Immutable { selection: WebSelection, path: String },
}

impl Selection {
    pub(super) fn capture(
        shared: &Shared,
        head: &Head,
        candidate: &Candidate,
        raw: &[u8],
    ) -> Result<Self, u16> {
        LocalPrincipalPolicy
            .authenticate(&head.principal)
            .map_err(|error| super::super::status(&error))?;
        let tenant = head.principal.tenant.as_ref().ok_or(403u16)?;
        LocalPrincipalPolicy
            .authorize_target(&head.principal, &tenant.0)
            .map_err(|error| super::super::status(&error))?;
        let target = head.collector.target();
        if target.path().starts_with(latent_artifacts::web::IMMUTABLE_ASSET_PREFIX) {
            let mut fields = [httparse::EMPTY_HEADER; MAX_HEADERS];
            let mut message = httparse::Request::new(&mut fields);
            if !matches!(message.parse(raw), Ok(httparse::Status::Complete(n)) if n == raw.len()) {
                return Err(400);
            }
            let (reference, path) = request::locator(message.path.ok_or(400u16)?, tenant)?;
            let store = shared.handle.0.assets.get().ok_or(503u16)?;
            let selection = store
                .repository
                .select_web_publication(&reference)
                .map_err(|error| denial(super::super::status(&error)))?;
            return Ok(Self::Immutable { selection, path });
        }
        if target.path() == "/_lsf" || target.path().starts_with("/_lsf/") {
            return Err(403);
        }
        // OPTIONS selects exactly its requested GET/HEAD route. It cannot select
        // an OPTIONS handler or fall back to a different method/application.
        let route = shared
            .services
            .deployments
            .select_http(target, candidate.method)
            .map_err(|error| denial(super::super::status(&error)))?;
        let AcceptedHttpTarget::StaticWeb { publication, .. } = route.target() else {
            return Err(403);
        };
        let selected_tenant = publication.scope.tenant().ok_or(403u16)?;
        LocalPrincipalPolicy
            .authorize_target(&head.principal, &selected_tenant.0)
            .map_err(|error| super::super::status(&error))?;
        Ok(Self::Routed(route))
    }

    pub(super) fn web(&self) -> &WebSelection {
        match self {
            Self::Routed(route) => route.target().web_selection().expect("static-only selection"),
            Self::Immutable { selection, .. } => selection,
        }
    }

    pub(super) fn reference(&self) -> &PublicationRef {
        self.web().publication()
    }

    pub(super) fn current(&self) -> Result<(), u16> {
        let tenant = self.reference().scope.tenant().ok_or(403u16)?;
        self.web()
            .with_current(tenant, &mut |current| current.check())
            .map_err(|error| denial(super::super::status(&error)))
    }

    pub(super) fn asset_path(&self) -> Result<String, u16> {
        let layout = self.web().layout();
        let path = match self {
            Self::Immutable { path, .. } => path.as_str(),
            Self::Routed(route) => {
                let AcceptedHttpTarget::StaticWeb { site_path, .. } = route.target() else {
                    return Err(403);
                };
                // Respect signed exact-route precedence, but never directory
                // indexes, SPA fallback, error documents or renderer routes.
                match layout.manifest().routes.iter().find(|route| route.path == *site_path) {
                    Some(route) => {
                        if route.mode == latent_artifacts::web::WebRenderMode::Server {
                            return Err(403);
                        }
                        route.asset.as_deref().ok_or(403u16)?
                    }
                    None => site_path.as_str(),
                }
            }
        };
        let asset = layout.asset(path).ok_or(404u16)?;
        if matches!(asset.media_type.as_str(), "text/html" | "application/xhtml+xml") {
            return Err(403);
        }
        Ok(asset.path.clone())
    }

    pub(super) fn request(&self, raw: &[u8], path: String) -> Result<Request, u16> {
        let reference = self.reference();
        Request::parse_routed(raw, reference.scope.tenant().ok_or(403u16)?, reference.clone(), path)
    }

    pub(super) fn retain(self, mut request: Request) -> Request {
        if let Self::Routed(route) = self {
            request.route = Some(route);
        }
        // Immutable reads reselect this exact reference in Store::prepare and
        // recheck it at output. Do not hold two publication read owners at once.
        request
    }
}

fn denial(status: u16) -> u16 {
    if matches!(status, 400 | 401 | 403 | 404) {
        403
    } else {
        status
    }
}
