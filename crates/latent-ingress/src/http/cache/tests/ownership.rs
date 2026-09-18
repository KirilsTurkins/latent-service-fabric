use super::*;

#[test]
fn partial_delivery_disconnect_and_drop_never_publish() {
    let cache = cache();
    let pool = pool();
    for mode in 0..3 {
        let request = make_request(&pool, "tenant-a", "public", &[]);
        let key = ticket(&cache, &request, 1);
        let mut delivery = fill(request, key, b"complete body", &public());
        assert_eq!(cache.snapshot().entries, 1); // charged but not visible
        let probe = make_request(&pool, "tenant-a", "public", &[]);
        assert!(matches!(ticket(&cache, &probe, 1).lookup(), CacheLookup::Miss(_)));
        drop(probe);
        if mode == 0 {
            drop(delivery);
        } else {
            delivery.mark_headers_written().unwrap();
            delivery.advance(1).unwrap();
            if mode == 2 {
                delivery.cancellation().disconnect();
            }
            assert!(delivery.finish().is_err());
        }
        assert_eq!(cache.snapshot().reserved_bytes, 0);
        assert_eq!(pool.snapshot().active_exchanges, 0);
    }
}

#[test]
fn rollout_and_eligibility_generations_invalidate_future_use_not_read_ownership() {
    let cache = cache();
    let pool = pool();
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let key = ticket(&cache, &request, 1);
    finish(fill(request, key, b"old", &public()));
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let old_read = hit(ticket(&cache, &request, 1));
    let different = cache.request(&request, &scope("tenant-a", 1)).unwrap().bind_eligibility([2; 32]);
    assert!(matches!(different.lookup(), CacheLookup::Miss(_)));
    assert!(cache.observe_generation(2));
    assert!(!cache.observe_generation(1));
    assert!(cache.request(&request, &scope("tenant-a", 1)).is_none());
    assert!(matches!(ticket(&cache, &request, 2).lookup(), CacheLookup::Miss(_)));
    assert_eq!(cache.snapshot().entries, 1); // retired read still charged
    assert!(old_read.wire().windows(4).any(|bytes| bytes == b"b2xk"));
    cache.close();
    assert!(cache.snapshot().reserved_bytes > 0);
    drop(old_read);
    assert_eq!(cache.snapshot().reserved_bytes, 0);
}

#[test]
fn late_fill_cannot_repopulate_new_generation() {
    let cache = cache();
    let pool = pool();
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let key = ticket(&cache, &request, 1);
    let delivery = fill(request, key, b"old", &public());
    assert!(cache.observe_generation(2));
    finish(delivery);
    assert_eq!(cache.snapshot().reserved_bytes, 0);
}

#[test]
fn monotonic_expiry_includes_render_delivery_delay_and_never_renews_on_hit() {
    let cache = cache();
    let pool = pool();
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let mut key = ticket(&cache, &request, 1);
    key.created = Instant::now() - Duration::from_secs(31);
    finish(fill(request, key, b"too late", &public()));
    assert_eq!(cache.snapshot().entries, 0);
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let key = ticket(&cache, &request, 1);
    finish(fill(request, key, b"fresh", &public()));
    {
        let mut state = cache.0.state.lock().unwrap();
        Arc::get_mut(&mut state.entries[0]).unwrap().expires = Instant::now();
    }
    let request = make_request(&pool, "tenant-a", "public", &[]);
    assert!(matches!(ticket(&cache, &request, 1).lookup(), CacheLookup::Miss(_)));
    assert_eq!(cache.snapshot().entries, 0);
}

#[test]
fn owner_key_body_and_churn_bounds_return_to_zero() {
    let cache = cache();
    let pool = pool();
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let owners: Vec<_> = (0..MAX_OWNERS).map(|_| ticket(&cache, &request, 1)).collect();
    assert!(cache.request(&request, &scope("tenant-a", 1)).is_none());
    assert_eq!(cache.snapshot().owners, MAX_OWNERS);
    drop(owners);
    let huge = "x".repeat(MAX_KEY_BYTES);
    let mut oversize = scope("tenant-a", 1);
    oversize.trigger = &huge;
    assert!(cache.request(&request, &oversize).is_none());
    assert_eq!(cache.snapshot().owners, 0);
    drop(request);
    for generation in 2..130 {
        let request = make_request(&pool, "tenant-a", "public", &[]);
        let key = ticket(&cache, &request, generation);
        finish(fill(request, key, b"bounded", &public()));
        assert!(cache.snapshot().entries <= MAX_ENTRIES);
        assert!(cache.snapshot().reserved_bytes <= MAX_CACHE_BYTES);
    }
    let request = make_request(&pool, "tenant-a", "public", &[]);
    let key = ticket(&cache, &request, 130);
    finish(fill(request, key, &vec![b'x'; crate::http::MAX_RESPONSE_BODY + 1], &public()));
    assert_eq!(cache.snapshot().entries, 0);
    cache.close();
    assert_eq!(cache.snapshot().reserved_bytes, 0);
}

#[test]
fn pinned_read_eviction_cannot_refund_capacity_or_admit_an_unbounded_fill() {
    let cache = cache();
    let pool = pool();
    let mut reads = Vec::new();
    for index in 0..MAX_CACHE_BYTES / MAX_ENTRY_BYTES {
        let subject = format!("public-{index}");
        let request = make_request(&pool, "tenant-a", &subject, &[]);
        let key = ticket(&cache, &request, 1);
        finish(fill(request, key, subject.as_bytes(), &public()));
        let request = make_request(&pool, "tenant-a", &subject, &[]);
        reads.push(hit(ticket(&cache, &request, 1)));
    }
    let before = cache.snapshot();
    let request = make_request(&pool, "tenant-a", "new", &[]);
    let key = ticket(&cache, &request, 1);
    finish(fill(request, key, b"bypass", &public()));
    assert_eq!(cache.snapshot().entries, before.entries);
    assert_eq!(cache.snapshot().reserved_bytes, before.reserved_bytes);
    assert!(cache.0.state.lock().unwrap().entries.is_empty());
    for read in &reads {
        assert!(!read.wire().is_empty());
    }
    drop(reads);
    assert_eq!(cache.snapshot().reserved_bytes, 0);
    assert_eq!(pool.snapshot().active_exchanges, 0);
}
