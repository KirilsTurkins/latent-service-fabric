use super::http_support::*;
use base64::{
    engine::general_purpose::{STANDARD, URL_SAFE_NO_PAD},
    Engine,
};
use latent_core::transaction_contract::ExpectedVersion;
use latent_ingress::http::{
    transaction::{RouteMode, TransactionRoute},
    *,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};

fn configuration(mode: &str) -> BTreeMap<String, Value> {
    serde_json::from_value(json!({
        "profile":"transaction-http-v1", "scheme":"https", "host":"example.test",
        "path":"/commands", "pathMatch":"prefix", "method":if mode == "command" {"POST"} else {"GET"},
        "transactionMode":mode, "namespace":"orders", "incarnation":"1",
        "stateSchema":format!("sha256:{}", "1".repeat(64)),
        "companionDigest":format!("sha256:{}", "2".repeat(64)),
        "stateBinding":"orders-api", "resultPolicy":"orders-results", "entity":"customer-7"
    })).unwrap()
}
fn route(mode: &str) -> TransactionRoute {
    let mut fields = configuration(mode);
    if mode == "command" {
        fields.insert("preconditionKey".into(), json!(STANDARD.encode(b"count")));
    }
    TransactionRoute::from_configuration(&fields).unwrap()
}
fn map(
    mode: &str,
    method: &str,
    target: &str,
    body: &[u8],
    extra: &[HeaderView<'_>],
) -> Result<
    (
        Invocation,
        latent_ingress::http::transaction::TransactionRequest,
    ),
    HttpError,
> {
    let pool = pool();
    let mut headers = vec![HOST];
    let length = body.len().to_string();
    if method == "POST" {
        headers.push(HeaderView {
            name: "content-type",
            value: VALUE_MEDIA_TYPE.as_bytes(),
        });
        headers.push(HeaderView {
            name: "content-length",
            value: length.as_bytes(),
        });
    }
    headers.extend_from_slice(extra);
    let mut head = head(method, &headers);
    head.target = target;
    let mut collected = pool.begin(head, deadline())?;
    collected.append(body)?;
    collected.finish(context())?.into_transaction(&route(mode))
}
fn token(prefix: &[u8]) -> Vec<u8> {
    let mut token = prefix.to_vec();
    token.resize(67, 1);
    token
}
const ID: HeaderView<'static> = HeaderView {
    name: "idempotency-key",
    value: b"original-request",
};

#[test]
fn closed_route_scope_rejects_unknown_keys_missing_links_and_noncanonical_incarnation() {
    let base = configuration("command");
    for (key, value) in [
        ("unknown", json!("orders")),
        ("incarnation", json!("01")),
        ("incarnation", json!("0")),
        ("stateSchema", json!("not-a-digest")),
    ] {
        let mut fields = base.clone();
        fields.insert(key.into(), value);
        assert!(TransactionRoute::from_configuration(&fields).is_err());
    }
    let mut fields = base;
    fields.remove("host");
    fields.insert("preconditionKey".into(), json!(STANDARD.encode(b"count")));
    assert!(TransactionRoute::from_configuration(&fields).is_err());
    assert!(route("command").require_method(Method::Get).is_err());
    assert!(route("query").require_method(Method::Post).is_err());
    assert!(route("result").require_method(Method::Head).is_err());
}

#[test]
fn command_mapping_retains_original_key_path_precondition_with_credential_rotation() {
    let version = token(b"SV\x02");
    let expected = format!("\"{}\"", STANDARD.encode(&version));
    for credential in [b"Bearer old".as_slice(), b"Bearer rotated"] {
        let (invocation, facts) = map(
            "command",
            "POST",
            "/commands/customer-7",
            b"[3,false]",
            &[
                ID,
                HeaderView {
                    name: "authorization",
                    value: credential,
                },
                HeaderView {
                    name: "if-match",
                    value: expected.as_bytes(),
                },
            ],
        )
        .unwrap();
        assert_eq!(invocation.input(), b"[3,false]");
        assert_eq!(facts.client_key(), Some("original-request"));
        assert_eq!(facts.business_path(), "/commands/customer-7");
        assert_eq!(facts.business_query(), None);
        assert_eq!(facts.preconditions()[0].key, b"count");
        assert_eq!(
            facts.preconditions()[0].expected,
            ExpectedVersion::Present(version.clone())
        );
    }
}

#[test]
fn duplicates_and_ambiguous_preconditions_fail_before_invocation() {
    assert!(map("command", "POST", "/commands", b"[]", &[ID, ID]).is_err());
    assert!(map("command", "POST", "/commands?namespace=other", b"[]", &[ID]).is_err());
    for value in [
        b"*".as_slice(),
        b"W/\"absent\"",
        b"\"absent\",\"absent\"",
        b"\"AA==\"",
    ] {
        assert!(map(
            "command",
            "POST",
            "/commands",
            b"[]",
            &[
                ID,
                HeaderView {
                    name: "if-match",
                    value
                }
            ]
        )
        .is_err());
    }
    let (_, facts) = map(
        "command",
        "POST",
        "/commands",
        b"[]",
        &[
            ID,
            HeaderView {
                name: "if-match",
                value: b"\"absent\"",
            },
        ],
    )
    .unwrap();
    assert_eq!(facts.preconditions()[0].expected, ExpectedVersion::Absent);
}

#[test]
fn queries_ignore_valid_command_keys_and_require_full_original_minimum_view() {
    let view = token(b"NV\x02");
    let encoded = STANDARD.encode(&view);
    let target = format!(
        "/commands?input={}",
        URL_SAFE_NO_PAD.encode(b"[\"prefix\",10]")
    );
    let (invocation, facts) = map(
        "query",
        "GET",
        &target,
        b"",
        &[
            ID,
            HeaderView {
                name: "if-state-view",
                value: encoded.as_bytes(),
            },
        ],
    )
    .unwrap();
    assert_eq!(invocation.input(), b"[\"prefix\",10]");
    assert_eq!(facts.client_key(), None);
    assert!(facts.preconditions().is_empty());
    assert_eq!(facts.minimum_view(), Some(view.as_slice()));
    for target in [
        "/commands?input=W10=",
        "/commands?input=W10&namespace=other",
        "/commands?input=W10%3D",
    ] {
        assert!(map("query", "GET", target, b"", &[ID]).is_err());
    }
    assert!(map(
        "query",
        "GET",
        "/commands",
        b"",
        &[
            ID,
            HeaderView {
                name: "if-state-view",
                value: b"AA=="
            }
        ]
    )
    .is_err());
    assert_eq!(route("query").mode(), RouteMode::Query);
}

#[test]
fn result_requests_cannot_select_guest_inputs_or_preconditions() {
    assert!(map("result", "GET", "/commands", b"", &[]).is_err());
    assert!(map("result", "GET", "/commands?input=W10", b"", &[ID]).is_err());
    assert!(map(
        "result",
        "GET",
        "/commands",
        b"",
        &[
            ID,
            HeaderView {
                name: "if-match",
                value: b"\"absent\""
            }
        ]
    )
    .is_err());
    let (_, facts) = map("result", "GET", "/commands", b"", &[ID]).unwrap();
    assert_eq!(facts.client_key(), Some("original-request"));
    assert_eq!(route("result").mode(), RouteMode::Result);
}

#[test]
fn transaction_mapping_retains_exchange_until_actual_delivery_or_drop() {
    let pool = pool();
    let request = pool
        .begin(head("GET", &[HOST, ID]), deadline())
        .unwrap()
        .finish(context())
        .unwrap();
    let (invocation, _) = request.into_transaction(&route("query")).unwrap();
    let cancellation = invocation.cancellation();
    assert_eq!(pool.snapshot().reserved_bytes, EXCHANGE_RESERVATION_BYTES);
    drop(invocation);
    assert_eq!(pool.snapshot().reserved_bytes, EXCHANGE_RESERVATION_BYTES);
    drop(cancellation);
    assert_eq!(pool.snapshot().reserved_bytes, 0);
}

struct CurrentDelivery(AtomicBool);
impl DeliveryFence for CurrentDelivery {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), HttpError>,
    ) -> Result<(), HttpError> {
        if !self.0.load(Ordering::Acquire) {
            return Err(HttpError::Forbidden);
        }
        action()
    }
}

#[test]
fn revoked_delivery_refuses_to_poll_an_already_pending_write_again() {
    let pool = pool();
    let fence = Arc::new(CurrentDelivery(AtomicBool::new(true)));
    let delivery = invocation(&pool, "POST")
        .complete_transaction(200, b"{}".to_vec(), fence.clone())
        .unwrap();
    let mut polls = 0;
    assert_eq!(
        delivery.with_current(|| {
            polls += 1;
            std::task::Poll::<()>::Pending
        }),
        Ok(std::task::Poll::Pending)
    );
    fence.0.store(false, Ordering::Release);
    assert_eq!(
        delivery.with_current(|| {
            polls += 1;
            std::task::Poll::Ready(())
        }),
        Err(HttpError::Forbidden)
    );
    assert_eq!(polls, 1);
    assert_eq!(delivery.remaining_body(), Err(HttpError::Forbidden));
    assert_eq!(pool.snapshot().reserved_bytes, EXCHANGE_RESERVATION_BYTES);
    drop(delivery);
    assert_eq!(pool.snapshot().reserved_bytes, 0);
}

#[test]
fn transaction_delivery_owns_fixed_media_head_length_and_no_historical_headers() {
    let pool = pool();
    let fence = Arc::new(CurrentDelivery(AtomicBool::new(true)));
    let mut delivery = invocation(&pool, "HEAD")
        .complete_transaction(200, b"{\"result\":null}".to_vec(), fence.clone())
        .unwrap();
    delivery.enforce_browser_profile(Scheme::Https).unwrap();
    assert_eq!(delivery.content_length(), Some(15));
    assert_eq!(delivery.remaining_body().unwrap(), b"");
    assert_eq!(
        delivery.media_type(),
        Some("application/vnd.latent.transaction-http.v1+json")
    );
    let headers: Vec<_> = delivery.headers().collect();
    assert_eq!(headers.len(), 1);
    assert_eq!(headers[0].name, "cache-control");
    assert_eq!(headers[0].value, b"no-store");
    delivery.mark_headers_written().unwrap();
    assert_eq!(delivery.finish().unwrap().body_bytes, 0);
    assert_eq!(pool.snapshot().reserved_bytes, 0);
    assert!(matches!(
        invocation(&pool, "POST").complete_transaction(200, vec![0; MAX_RESPONSE_BODY + 1], fence),
        Err(HttpError::InvalidResponse)
    ));
}

#[test]
fn retry_requires_explicit_complete_original_fence_and_separate_request_identity() {
    let wire = json!({
        "command-id": "a".repeat(64),
        "attempt-id": "b".repeat(64),
        "transaction-id": "c".repeat(64),
        "owner-fence": STANDARD.encode([7;32])
    });
    let encoded = STANDARD.encode(serde_json::to_vec(&wire).unwrap());
    let retry = HeaderView {
        name: "command-retry-key",
        value: b"retry-request-1",
    };
    let fence = HeaderView {
        name: "command-abort-fence",
        value: encoded.as_bytes(),
    };
    let (_, facts) = map(
        "command",
        "POST",
        "/commands",
        b"[3,false]",
        &[ID, retry, fence],
    )
    .unwrap();
    assert_eq!(facts.client_key(), Some("original-request"));
    assert_eq!(facts.retry().unwrap().request_id(), "retry-request-1");
    assert_eq!(facts.retry().unwrap().fence().owner_fence, [7; 32]);
    for headers in [
        vec![ID, retry],
        vec![ID, fence],
        vec![ID, retry, fence, fence],
    ] {
        assert!(map("command", "POST", "/commands", b"[]", &headers).is_err());
    }
    assert!(map("query", "GET", "/commands", b"", &[retry, fence]).is_err());
    assert!(map("result", "GET", "/commands", b"", &[ID, retry, fence]).is_err());
    for replacement in [json!("a".repeat(63)), json!("A".repeat(64))] {
        let mut changed = wire.clone();
        changed["command-id"] = replacement;
        let encoded = STANDARD.encode(serde_json::to_vec(&changed).unwrap());
        assert!(map(
            "command",
            "POST",
            "/commands",
            b"[]",
            &[
                ID,
                retry,
                HeaderView {
                    name: "command-abort-fence",
                    value: encoded.as_bytes()
                }
            ]
        )
        .is_err());
    }
    let mut unknown = wire;
    unknown["permitted"] = json!(true);
    let encoded = STANDARD.encode(serde_json::to_vec(&unknown).unwrap());
    assert!(map(
        "command",
        "POST",
        "/commands",
        b"[]",
        &[
            ID,
            retry,
            HeaderView {
                name: "command-abort-fence",
                value: encoded.as_bytes()
            }
        ]
    )
    .is_err());
}
