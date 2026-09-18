use super::*;

#[test]
fn alternate_tenants_public_principals_and_languages_never_cross_bytes() {
    let cache = cache();
    let pool = pool();
    // Six entries fit the byte reservation; look up each after interleaving fills.
    let cases = [
        ("tenant-a", "public-a", "en"), ("tenant-b", "public-a", "en"),
        ("tenant-a", "public-b", "en"), ("tenant-a", "public-a", "de"),
        ("tenant-b", "public-b", "de"), ("tenant-b", "public-a", "de"),
    ];
    for (tenant, subject, language) in cases {
        let headers = [HeaderView { name: "accept-language", value: language.as_bytes() }];
        let request = make_request(&pool, tenant, subject, &headers);
        let key = ticket(&cache, &request, 1);
        let body = format!("{tenant}/{subject}/{language}");
        finish(fill(request, key, body.as_bytes(), &public()));
    }
    for (tenant, subject, language) in cases.into_iter().rev() {
        let headers = [HeaderView { name: "accept-language", value: language.as_bytes() }];
        let request = make_request(&pool, tenant, subject, &headers);
        let read = hit(ticket(&cache, &request, 1));
        let delivery = request.into_invocation().unwrap().complete_cache_hit(read).unwrap();
        assert_eq!(delivery.remaining_body().unwrap(), format!("{tenant}/{subject}/{language}").as_bytes());
        assert!(delivery.headers().any(|h| h.name == "cache-control" && h.value == b"no-store"));
        assert!(delivery.headers().any(|h| h.name == "age"));
        finish(delivery);
    }
    cache.close();
    assert_eq!(cache.snapshot().reserved_bytes, 0);
    assert_eq!(pool.snapshot().active_exchanges, 0);
}

#[test]
fn credentials_cookies_unknown_headers_queries_and_user_principals_bypass() {
    let cache = cache();
    let pool = pool();
    for name in ["authorization", "proxy-authorization", "cookie", "cache-control", "range", "x-user"] {
        let headers = [HeaderView { name, value: b"private" }];
        let request = make_request(&pool, "tenant-a", "public", &headers);
        assert!(cache.request(&request, &scope("tenant-a", 1)).is_none(), "{name}");
    }
    let request = request_as(&pool, "tenant-a", "public", &[], PrincipalKind::User);
    assert!(cache.request(&request, &scope("tenant-a", 1)).is_none());
}

#[test]
fn non_public_context_and_non_get_inputs_bypass() {
    let cache = cache();
    let pool = pool();
    let mut request = make_request(&pool, "tenant-a", "public", &[]);
    request.data.query = crate::http::bounded::Optional::Some(String::new());
    assert!(cache.request(&request, &scope("tenant-a", 1)).is_none());
    request.data.query = crate::http::bounded::Optional::None(());
    request.data.method = Method::Head;
    assert!(cache.request(&request, &scope("tenant-a", 1)).is_none());
    request.data.method = Method::Get;
    assert!(cache.request(&request, &scope("tenant-b", 1)).is_none());
    let mut different = scope("tenant-a", 1);
    different.release = "release-b";
    assert!(cache.request(&request, &different).is_none());
    different.release = "release-a";
    different.renderer_profile = "other-runtime";
    assert!(cache.request(&request, &different).is_none());
}

#[test]
fn absent_empty_duplicate_and_unapproved_vary_values_are_distinct() {
    let cache = cache();
    let pool = pool();
    let absent = make_request(&pool, "tenant-a", "public", &[]);
    let key = ticket(&cache, &absent, 1);
    finish(fill(absent, key, b"absent", &public()));
    for values in [vec![""], vec!["fr"], vec!["en", "en"]] {
        let headers: Vec<_> = values.iter().map(|value| HeaderView {
            name: "accept-language", value: value.as_bytes(),
        }).collect();
        let request = make_request(&pool, "tenant-a", "public", &headers);
        let candidate = cache.request(&request, &scope("tenant-a", 1));
        if values == [""] {
            assert!(matches!(candidate.unwrap().bind_eligibility([1; 32]).lookup(), CacheLookup::Miss(_)));
        } else {
            assert!(candidate.is_none());
        }
    }
}

#[test]
fn policies_reject_unbounded_domains_unknown_profiles_and_ambiguous_routes() {
    let mut policy = policy("tenant-a");
    assert!(policy.validate());
    policy.vary[0].name = "cookie".into();
    assert!(!policy.validate());
    policy.vary[0].name = "accept-language".into();
    policy.vary[0].values = (0..17).map(|n| n.to_string()).collect();
    assert!(!policy.validate());
    policy.vary.clear();
    policy.maximum_age_seconds = MAX_AGE_SECONDS + 1;
    assert!(!policy.validate());
    policy.maximum_age_seconds = 1;
    policy.path = "/a/../b".into();
    assert!(!policy.validate());
    policy.path = "/".into();
    assert!(ResponseCache::new(vec![policy.clone(), policy]).is_err());
    assert!(serde_json::from_value::<DependencyProfile>(json!("secret-dependent-v1")).is_err());
}
