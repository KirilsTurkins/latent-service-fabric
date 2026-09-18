use super::*;

#[test]
fn no_store_private_cookies_unknown_vary_and_ttl_extensions_never_publish() {
    let cache = cache();
    let pool = pool();
    let cases = [
        vec![("cache-control", "public, no-store, max-age=30")],
        vec![("cache-control", "private, max-age=30")],
        vec![("cache-control", "public, max-age=0")],
        vec![("cache-control", "public, max-age=30, s-maxage=0")],
        vec![("cache-control", "public, max-age=30, stale-if-error=60")],
        vec![("cache-control", "public, max-age=30, max-age=60")],
        vec![("cache-control", "public, max-age=\"30\"")],
        vec![("cache-control", "public, max-age=30"), ("cache-control", "public")],
        vec![("cache-control", "public, max-age=30"), ("set-cookie", "session=a")],
        vec![("cache-control", "public, max-age=30"), ("vary", "*")],
        vec![("cache-control", "public, max-age=30"), ("vary", "cookie")],
        vec![("cache-control", "public, max-age=30"), ("vary", "accept-language, accept-language")],
        vec![("cache-control", "public, max-age=30"), ("age", "10")],
        vec![],
    ];
    for headers in cases {
        let request = make_request(&pool, "tenant-a", "public", &[]);
        let key = ticket(&cache, &request, 1);
        finish(fill(request, key, b"private", &headers));
        assert_eq!(cache.snapshot().entries, 0, "{headers:?}");
        assert_eq!(cache.snapshot().owners, 0);
    }
}

#[test]
fn only_application_200_can_publish_and_failures_are_no_store() {
    let cache = cache();
    let pool = pool();
    for status in [201, 204, 301, 304, 400, 404, 500, 503] {
        let request = make_request(&pool, "tenant-a", "public", &[]);
        let key = ticket(&cache, &request, 1);
        let bytes = wire(status, b"", &public());
        let delivery = request.into_invocation().unwrap().complete_cached(
            Outcome::Returned { bytes: &bytes, media_type: VALUE_MEDIA_TYPE }, Some(key),
        ).unwrap();
        finish(delivery);
        assert_eq!(cache.snapshot().entries, 0);
    }
    for outcome in [Outcome::DeclaredError, Outcome::Platform(PlatformErrorCode::GuestTrap),
        Outcome::Returned { bytes: b"broken", media_type: VALUE_MEDIA_TYPE }] {
        let request = make_request(&pool, "tenant-a", "public", &[]);
        let key = ticket(&cache, &request, 1);
        let delivery = request.into_invocation().unwrap().complete_cached(outcome, Some(key)).unwrap();
        assert!(delivery.headers().any(|h| h.name == "cache-control" && h.value == b"no-store"));
        finish(delivery);
        assert_eq!(cache.snapshot().reserved_bytes, 0);
    }
}

#[test]
fn ttl_is_the_minimum_and_approved_vary_is_accepted() {
    let cache = cache();
    let pool = pool();
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let key = ticket(&cache, &request, 1);
    finish(fill(request, key, b"short lifetime", &[
        ("cache-control", "PUBLIC, max-age=300, s-maxage=20"),
        ("vary", "Accept-Language"),
    ]));
    let state = cache.0.state.lock().unwrap();
    assert_eq!(state.entries.len(), 1);
    assert_eq!(state.entries[0].expires.duration_since(state.entries[0].created), Duration::from_secs(20));
}
