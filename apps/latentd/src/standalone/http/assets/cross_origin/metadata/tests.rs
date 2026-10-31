use super::*;

fn grants() -> Vec<CrossOriginAssetGrant> {
    vec![CrossOriginAssetGrant {
        authority: "assets.example.test".into(),
        tenant: "tests".into(),
        publication: format!("publication:sha256:{}", "ab".repeat(32)),
        origins: vec!["https://portal.example.test".into()],
        credentials: CrossOriginCredentials::Omit,
    }]
}
fn headers() -> Vec<HeaderView<'static>> {
    vec![
        HeaderView {
            name: "origin",
            value: b"https://portal.example.test",
        },
        HeaderView {
            name: "sec-fetch-site",
            value: b"cross-site",
        },
        HeaderView {
            name: "sec-fetch-mode",
            value: b"cors",
        },
        HeaderView {
            name: "sec-fetch-dest",
            value: b"empty",
        },
    ]
}
fn candidate(method: Method, headers: &[HeaderView<'_>]) -> Result<Option<Candidate>, u16> {
    admit(
        &grants(),
        &CanonicalTarget::parse(Scheme::Https, "assets.example.test", "/app.js").unwrap(),
        "tests",
        method,
        headers,
    )
}

#[test]
fn cross_origin_provisional_admission_preserves_defaults_and_allows_only_subresources() {
    let target = CanonicalTarget::parse(Scheme::Https, "assets.example.test", "/app.js").unwrap();
    assert!(admit(&[], &target, "tests", Method::Get, &headers())
        .unwrap()
        .is_none());
    assert!(candidate(Method::Get, &[]).unwrap().is_none());
    let mut same = headers();
    same[0].value = b"https://assets.example.test";
    assert!(candidate(Method::Get, &same).unwrap().is_none());
    for method in [Method::Get, Method::Head] {
        for destination in ["empty", "script", "style", "font", "image", "manifest"] {
            let mut fields = headers();
            fields[3].value = destination.as_bytes();
            assert!(candidate(method, &fields).unwrap().is_some());
        }
    }
    for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"] {
        assert!(candidate(Method::parse(method).unwrap(), &headers()).is_err());
    }
    for missing in 1..4 {
        let mut fields = headers();
        fields.remove(missing);
        assert_eq!(candidate(Method::Get, &fields).unwrap_err(), 403);
    }
}

#[test]
fn cross_origin_metadata_rejects_opaque_origins_navigation_no_cors_and_duplicates() {
    for origin in [
        "null",
        "https://unrelated.example.test",
        "https://portal.example.test:443",
        "https://portal.example.test, https://other.test",
        "https://PORTAL.example.test",
    ] {
        let mut fields = headers();
        fields[0].value = origin.as_bytes();
        assert_eq!(candidate(Method::Get, &fields).unwrap_err(), 403);
    }
    for (index, value) in [
        (1, "same-origin"),
        (1, "none"),
        (2, "no-cors"),
        (2, "navigate"),
        (3, "document"),
        (3, "iframe"),
    ] {
        let mut fields = headers();
        fields[index].value = value.as_bytes();
        assert_eq!(candidate(Method::Get, &fields).unwrap_err(), 403);
    }
    for index in 0..4 {
        let mut fields = headers();
        fields.push(HeaderView {
            name: fields[index].name,
            value: fields[index].value,
        });
        assert_eq!(candidate(Method::Get, &fields).unwrap_err(), 400);
    }
    for name in [
        "sec-fetch-user",
        "authorization",
        "proxy-authorization",
        "x-tenant",
        "x-lsf-tenant",
    ] {
        let mut fields = headers();
        fields.push(HeaderView {
            name,
            value: b"forbidden",
        });
        assert_eq!(candidate(Method::Get, &fields).unwrap_err(), 403);
    }
}

#[test]
fn cross_origin_final_grant_requires_exact_publication_tenant_authority_and_credentials() {
    let mut grants = grants();
    let mut approved = candidate(Method::Get, &headers()).unwrap().unwrap();
    let publication = grants[0].publication.clone();
    assert!(approved
        .grant(&grants, "assets.example.test", "tests", &publication)
        .is_ok());
    assert!(approved
        .grant(&grants, "other.example.test", "tests", &publication)
        .is_err());
    assert!(approved
        .grant(&grants, "assets.example.test", "foreign", &publication)
        .is_err());
    assert!(approved
        .grant(&grants, "assets.example.test", "tests", "new-publication")
        .is_err());
    assert!(approved
        .grant(&[], "assets.example.test", "tests", &publication)
        .is_err());
    approved.cookie = true;
    assert!(approved
        .grant(&grants, "assets.example.test", "tests", &publication)
        .is_err());
    grants[0].credentials = CrossOriginCredentials::Include;
    assert!(approved
        .grant(&grants, "assets.example.test", "tests", &publication)
        .is_ok());
}

#[test]
fn cross_origin_preflight_is_bounded_conditional_only_and_never_credentialed() {
    for method in ["GET", "HEAD"] {
        let mut fields = headers();
        fields.push(HeaderView {
            name: "access-control-request-method",
            value: method.as_bytes(),
        });
        let admitted = candidate(Method::Options, &fields).unwrap().unwrap();
        assert_eq!(admitted.method, Method::parse(method).unwrap());
        assert_eq!(admitted.preflight.as_deref(), Some(""));
        fields.push(HeaderView {
            name: "access-control-request-headers",
            value: b"if-modified-since, if-none-match",
        });
        assert_eq!(
            candidate(Method::Options, &fields)
                .unwrap()
                .unwrap()
                .preflight
                .as_deref(),
            Some("if-none-match, if-modified-since")
        );
        assert!(candidate(Method::Get, &fields).is_err());
        fields.push(HeaderView {
            name: "cookie",
            value: b"__Host-test=value",
        });
        assert!(candidate(Method::Options, &fields).is_err());
    }
    for value in [
        "",
        "authorization",
        "proxy-authorization",
        "x-tenant",
        "range",
        "if-match",
        "If-None-Match",
        "if-none-match,if-none-match",
        "if-none-match,",
        "if-none-match,if-modified-since,x-extra",
    ] {
        assert!(
            conditional_headers(Some(value.as_bytes())).is_err(),
            "{value}"
        );
    }
    assert!(conditional_headers(Some(&[b' '; 65])).is_err());
    for method in ["POST", "PUT", "DELETE", "get"] {
        let mut fields = headers();
        fields.push(HeaderView {
            name: "access-control-request-method",
            value: method.as_bytes(),
        });
        assert!(candidate(Method::Options, &fields).is_err());
    }
}
