#![allow(dead_code)]
use latent_activation::TraceContext;
use latent_core::{
    IncomingDeadline, InvocationPrincipal, Metadata, PrincipalKind, SpanId, TenantId, TraceId,
};
use latent_ingress::http::*;
use std::time::{Duration, Instant};

pub const RESPONSE: &str = include_str!("../fixtures/http-response-v1.json");
pub fn pool() -> HttpPool {
    HttpPool::new(1, EXCHANGE_RESERVATION_BYTES).unwrap()
}
pub fn deadline() -> IncomingDeadline {
    IncomingDeadline::new(Instant::now() + Duration::from_mins(1), 2_000_000_000_000)
}
pub fn head<'a>(method: &'a str, headers: &'a [HeaderView<'a>]) -> RawHead<'a> {
    RawHead {
        version: HttpVersion::Http11,
        method,
        scheme: Scheme::Https,
        authority: "example.test",
        target: "/",
        headers,
    }
}
pub const HOST: HeaderView<'static> = HeaderView {
    name: "host",
    value: b"example.test",
};
pub fn context() -> TrustedContext {
    TrustedContext::new(
        InvocationPrincipal {
            subject: "user-a".into(),
            kind: PrincipalKind::User,
            tenant: Some(TenantId("tenant-a".into())),
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
    .unwrap()
}
pub fn invocation(pool: &HttpPool, method: &str) -> Invocation {
    pool.begin(head(method, &[HOST]), deadline())
        .unwrap()
        .finish(context())
        .unwrap()
        .into_invocation()
        .unwrap()
}
pub fn deliver(pool: &HttpPool, method: &str, bytes: &[u8]) -> Delivery {
    invocation(pool, method)
        .complete(Outcome::Returned {
            bytes,
            media_type: VALUE_MEDIA_TYPE,
        })
        .unwrap()
}
pub fn response() -> serde_json::Value {
    serde_json::from_str(RESPONSE).unwrap()
}
