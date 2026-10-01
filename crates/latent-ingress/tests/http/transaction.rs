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
