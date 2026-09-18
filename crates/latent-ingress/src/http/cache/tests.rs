use super::*;
use crate::http::{
    HeaderView, HttpPool, HttpVersion, Outcome, RawHead, TrustedContext,
    EXCHANGE_RESERVATION_BYTES, VALUE_MEDIA_TYPE,
};
use base64::Engine;
use latent_activation::TraceContext;
use latent_core::{
    IncomingDeadline, InvocationPrincipal, Metadata, PlatformErrorCode, SpanId, TenantId, TraceId,
};
use serde_json::json;

fn policy(tenant: &str) -> PublicCachePolicy {
    PublicCachePolicy {
        dependency_profile: DependencyProfile::ImmutablePublicV1,
        tenant: tenant.into(),
        publication: "publication-a".into(),
        release: "release-a".into(),
        renderer_profile: "buffered-v1".into(),
        authority: "example.test".into(),
        path: "/".into(),
        generation: 1,
        maximum_age_seconds: 30,
        vary: vec![VaryField {
            name: "accept-language".into(),
            values: vec!["en".into(), "de".into(), String::new()],
        }],
    }
}
fn cache() -> ResponseCache {
    ResponseCache::new(vec![policy("tenant-a"), policy("tenant-b")]).unwrap()
}
fn pool() -> HttpPool {
    HttpPool::new(8, 8 * EXCHANGE_RESERVATION_BYTES).unwrap()
}
fn scope(tenant: &str, generation: u64) -> CacheScope<'_> {
    CacheScope {
        tenant,
        publication: "publication-a",
        release: "release-a",
        revision: "revision-a",
        renderer_profile: "buffered-v1",
        trigger: "http-home",
        route_generation: generation,
        state_version: generation,
    }
}
fn make_request(
    pool: &HttpPool,
    tenant: &str,
    subject: &str,
    headers: &[HeaderView<'_>],
) -> Request {
    request_as(pool, tenant, subject, headers, PrincipalKind::Trigger)
}
fn request_as(
    pool: &HttpPool,
    tenant: &str,
    subject: &str,
    headers: &[HeaderView<'_>],
    kind: PrincipalKind,
) -> Request {
    let context = TrustedContext::new(
        InvocationPrincipal {
            subject: subject.into(),
            kind,
            tenant: Some(TenantId(tenant.into())),
            service: None,
            claims: Metadata::new(),
        },
        TraceContext {
            trace_id: TraceId("0123456789abcdef0123456789abcdef".into()),
            span_id: SpanId("0123456789abcdef".into()),
            trace_flags: 1,
            baggage: Metadata::new(),
        },
    )
    .unwrap();
    let mut fields = vec![HeaderView {
        name: "host",
        value: b"example.test",
    }];
    fields.extend_from_slice(headers);
    pool.begin(
        RawHead {
            version: HttpVersion::Http11,
            method: "GET",
            scheme: Scheme::Https,
            authority: "example.test",
            target: "/",
            headers: &fields,
        },
        IncomingDeadline::new(Instant::now() + Duration::from_secs(60), 2_000_000_000_000),
    )
    .unwrap()
    .finish(context)
    .unwrap()
}
fn ticket(cache: &ResponseCache, request: &Request, generation: u64) -> CacheRequest {
    let tenant = &request.context().principal().tenant.as_ref().unwrap().0;
    cache
        .request(request, &scope(tenant, generation))
        .unwrap()
        .bind_eligibility([1; 32])
}
fn wire(status: u16, body: &[u8], headers: &[(&str, &str)]) -> Vec<u8> {
    let headers: Vec<_> = headers
        .iter()
        .map(|(name, value)| json!({"name": name, "value": value.as_bytes()}))
        .collect();
    serde_json::to_vec(&json!([{
        "profile": "buffered-v1", "status": status, "headers": headers,
        "media-type": {"some": "text/html"}, "representation-length": {"none": null},
        "body-base64": base64::engine::general_purpose::STANDARD.encode(body)
    }]))
    .unwrap()
}
fn fill(request: Request, ticket: CacheRequest, body: &[u8], headers: &[(&str, &str)]) -> Delivery {
    let bytes = wire(200, body, headers);
    request
        .into_invocation()
        .unwrap()
        .complete_cached(
            Outcome::Returned {
                bytes: &bytes,
                media_type: VALUE_MEDIA_TYPE,
            },
            Some(ticket),
        )
        .unwrap()
}
fn finish(mut delivery: Delivery) {
    delivery.mark_headers_written().unwrap();
    let length = delivery.remaining_body().unwrap().len();
    delivery.advance(length).unwrap();
    delivery.finish().unwrap();
}
fn public() -> [(&'static str, &'static str); 1] {
    [("cache-control", "public, max-age=30")]
}
fn hit(ticket: CacheRequest) -> CacheHit {
    match ticket.lookup() {
        CacheLookup::Hit(hit) => hit,
        CacheLookup::Miss(_) => panic!("expected exact cache hit"),
    }
}

mod isolation;
mod ownership;
mod response;
