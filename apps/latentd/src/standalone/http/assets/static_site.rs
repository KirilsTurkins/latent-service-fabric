//! Resolution uses only the selected canonical path and checked public metadata.
use super::{
    negotiation::{self, Accept},
    request::single,
    Request,
};
use crate::standalone::http::head::Head;
use latent_artifacts::web::{
    StaticDirectoryIndexMode, StaticFallbackMode, WebApplicationManifest, WebAsset, WebRenderMode,
};
use latent_control_store::http_routes::{AcceptedHttpRoute, AcceptedHttpTarget};
use latent_ingress::http::{CanonicalTarget, MAX_HEADERS, MAX_TARGET_BYTES};

pub(in crate::standalone::http) fn select(
    head: &Head,
    accepted: &AcceptedHttpRoute,
    raw: &[u8],
) -> Result<Request, u16> {
    let AcceptedHttpTarget::StaticWeb {
        publication,
        selection,
        site_path,
        ..
    } = accepted.target()
    else {
        return Err(502);
    };
    if head.content_length != 0 {
        return Err(400);
    }
    let mut fields = [httparse::EMPTY_HEADER; MAX_HEADERS];
    let mut message = httparse::Request::new(&mut fields);
    if !matches!(message.parse(raw), Ok(httparse::Status::Complete(n)) if n == raw.len()) {
        return Err(400);
    }
    if !matches!(message.method, Some("GET" | "HEAD")) {
        return Err(405);
    }
    let accept = Accept::parse(single(message.headers, "accept")?)?;
    let navigation = negotiation::navigation(message.headers, &accept)?;
    let tenant = publication.scope.tenant().ok_or(403u16)?;
    // Validate bounded preconditions even on a genuine route miss. Assign the
    // public asset path only after resolving the captured checked manifest.
    let mut request = Request::parse_routed(raw, tenant, publication.clone(), String::new())?;
    let (asset, directory) = resolve(selection.layout().manifest(), site_path, navigation)?;
    if !accept.allows(&asset.media_type) {
        return Err(406);
    }
    request.path.clone_from(&asset.path);
    if directory && !head.collector.target().path().ends_with('/') {
        request.redirect = Some(location(head.collector.target())?);
    }
    Ok(request)
}

fn asset<'a>(manifest: &'a WebApplicationManifest, path: &str) -> Option<&'a WebAsset> {
    manifest
        .assets
        .binary_search_by(|asset| asset.path.as_str().cmp(path))
        .ok()
        .map(|i| &manifest.assets[i])
}
fn resolve<'a>(
    manifest: &'a WebApplicationManifest,
    path: &str,
    navigation: bool,
) -> Result<(&'a WebAsset, bool), u16> {
    let routing = manifest.static_routing.as_ref().ok_or(502u16)?;
    if let Some(route) = manifest.routes.iter().find(|route| route.path == path) {
        if route.mode == WebRenderMode::Server {
            return Err(502);
        }
        return asset(manifest, route.asset.as_deref().ok_or(502u16)?)
            .map(|a| (a, false))
            .ok_or(502);
    }
    if let Some(asset) = asset(manifest, path) {
        return Ok((asset, false));
    }
    if routing.directory_index == StaticDirectoryIndexMode::Redirect {
        // Stack-only derived lookup, at most the already checked public path bound.
        // It is metadata lookup, never a filesystem probe or a second URL decode.
        let prefix = path.trim_end_matches('/');
        let index = routing.directory_index_document.as_str();
        let mut candidate = [0u8; 240];
        if prefix.len() + index.len() <= candidate.len() {
            let end = prefix.len() + index.len();
            candidate[..prefix.len()].copy_from_slice(prefix.as_bytes());
            candidate[prefix.len()..end].copy_from_slice(index.as_bytes());
            let candidate = std::str::from_utf8(&candidate[..end]).map_err(|_| 502u16)?;
            if let Some(asset) = asset(manifest, candidate) {
                if asset.media_type != "text/html" {
                    return Err(502);
                }
                return Ok((asset, true));
            }
        }
    }
    if routing.fallback.mode == StaticFallbackMode::Spa && navigation {
        return asset(
            manifest,
            routing.fallback.document.as_deref().ok_or(502u16)?,
        )
        .filter(|a| a.media_type == "text/html")
        .map(|a| (a, false))
        .ok_or(502);
    }
    Err(404)
}

fn location(target: &CanonicalTarget) -> Result<String, u16> {
    let size = target.path().len() + 1 + target.query().map_or(0, |q| q.len() + 1);
    if size > MAX_TARGET_BYTES {
        return Err(414);
    }
    // At most 8 KiB, covered by the existing 4 MiB exchange reservation. The
    // owner retains this buffer, selected route and catalog lease through output.
    let mut result = String::new();
    result.try_reserve_exact(size).map_err(|_| 503u16)?;
    result.push_str(target.path());
    result.push('/');
    if let Some(query) = target.query() {
        result.push('?');
        result.push_str(query);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_artifacts::web::*;
    use latent_ingress::http::Scheme;
    fn manifest() -> WebApplicationManifest {
        WebApplicationManifest {
            format_version: 1,
            profile: WEB_RELEASE_PROFILE.into(),
            assets_digest: String::new(),
            renderer: None,
            routes: vec![WebRoute {
                path: "/exact".into(),
                mode: WebRenderMode::Prerender,
                asset: Some("/index.html".into()),
            }],
            assets: ["/exact", "/guide/index.html", "/index.html", "/main.js"]
                .iter()
                .map(|p| WebAsset {
                    path: (*p).into(),
                    layer: format!("public{p}"),
                    digest: String::new(),
                    size: 1,
                    media_type: if *p == "/main.js" {
                        "text/javascript"
                    } else {
                        "text/html"
                    }
                    .into(),
                })
                .collect(),
            static_routing: Some(StaticWebRouting {
                profile: StaticWebRoutingProfile::StaticSiteV1,
                entry_document: "/index.html".into(),
                directory_index: StaticDirectoryIndexMode::Redirect,
                directory_index_document: "/index.html".into(),
                fallback: StaticWebFallback {
                    mode: StaticFallbackMode::Spa,
                    document: Some("/index.html".into()),
                },
            }),
        }
    }
    #[test]
    fn static_resolution_orders_signed_routes_assets_indexes_and_navigation_fallback() {
        let mut m = manifest();
        for (path, navigation, expected, redirect) in [
            ("/exact", false, "/index.html", false),
            ("/main.js", true, "/main.js", false),
            ("/guide", false, "/guide/index.html", true),
            ("/guide/", false, "/guide/index.html", true),
            ("/", false, "/index.html", true),
            ("/orders/42", true, "/index.html", false),
        ] {
            let (asset, actual) = resolve(&m, path, navigation).unwrap();
            assert_eq!((asset.path.as_str(), actual), (expected, redirect));
        }
        assert_eq!(resolve(&m, "/missing.js", false).unwrap_err(), 404);
        assert_eq!(resolve(&m, "/api/users", false).unwrap_err(), 404);
        m.static_routing.as_mut().unwrap().directory_index = StaticDirectoryIndexMode::Disabled;
        assert_eq!(resolve(&m, "/guide/", false).unwrap_err(), 404);
        m.static_routing.as_mut().unwrap().fallback.mode = StaticFallbackMode::None;
        assert_eq!(resolve(&m, "/orders/42", true).unwrap_err(), 404);
        m.routes[0].asset = Some("/absent.html".into());
        assert_eq!(resolve(&m, "/exact", true).unwrap_err(), 502);
    }
    #[test]
    fn static_redirect_preserves_canonical_mount_and_query_with_finite_scratch() {
        let target =
            CanonicalTarget::parse(Scheme::Http, "site.test", "/docs/guide?tab=history").unwrap();
        assert_eq!(location(&target).unwrap(), "/docs/guide/?tab=history");
        for path in [
            "//evil.test/guide",
            "/docs/../guide",
            "/docs%2fguide",
            "/docs\\guide",
        ] {
            assert!(CanonicalTarget::parse(Scheme::Http, "site.test", path).is_err());
        }
        let long = format!("/{}", "a".repeat(MAX_TARGET_BYTES - 1));
        let target = CanonicalTarget::parse(Scheme::Http, "site.test", &long).unwrap();
        assert_eq!(location(&target).unwrap_err(), 414);
        assert_eq!(resolve(&manifest(), &long, false).unwrap_err(), 404);
    }
}
