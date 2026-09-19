use super::{
    peer::{identity, Peer},
    RegistryActions,
};
use crate::http::{
    auth::{cache::Token, token, ConfiguredBearer},
    RegistryCredentials,
};
use reqwest::header::{HeaderMap, HeaderValue, WWW_AUTHENTICATE};
use std::{
    sync::{atomic::Ordering, Arc},
    time::{Duration, SystemTime},
};
use tokio::time::Instant;

#[tokio::test]
async fn challenges_parse_quoted_action_lists_without_accepting_foreign_authority() {
    let peer = Peer::new().await;
    let bearer = ConfiguredBearer::new(&peer.config(RegistryActions::PullPush))
        .unwrap()
        .unwrap();
    for scope in ["pull", "push", "pull,push"] {
        let value = format!("Bearer realm=\"https://{}/token\",service=\"registry.test\",scope=\"repository:tenant/package:{scope}\"", peer.address);
        assert!(bearer.validate_challenge(&challenge(&value)).is_ok());
    }
    let realm = format!("https://{}/token", peer.address);
    for value in [
        format!("Bearer realm=\"{realm}\",service=\"other\",scope=\"repository:tenant/package:pull\""),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\",scope=\"repository:other/package:pull\""),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\",scope=\"repository:tenant/package:pull,push,delete\""),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\",scope=\"repository:tenant/package:pull repository:other:pull\""),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\",scope=\"repository:tenant/package:pull\",scope=\"repository:tenant/package:push\""),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\",extra=\"unapproved\""),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\","),
        format!("Bearer realm=\"{realm}\",service=\"registry.test\" scope=\"repository:tenant/package:pull\""),
    ] { assert!(bearer.validate_challenge(&challenge(&value)).is_err()); }
    let mut duplicate = challenge(&format!(
        "Bearer realm=\"{realm}\",service=\"registry.test\""
    ));
    duplicate.append(
        WWW_AUTHENTICATE,
        HeaderValue::from_static("Basic realm=\"other\""),
    );
    assert!(bearer.validate_challenge(&duplicate).is_err());
}

#[test]
fn token_expiry_aliases_offline_credentials_and_scope_are_closed_and_bounded() {
    let scope = "repository:tenant/package:pull";
    let wall: SystemTime = time::OffsetDateTime::parse(
        "2026-09-19T12:00:00Z",
        &time::format_description::well_known::Rfc3339,
    )
    .unwrap()
    .into();
    let started = Instant::now();
    for body in [
        r#"{"token":"opaque"}"#,
        r#"{"access_token":"opaque","expires_in":60}"#,
        r#"{"token":"opaque","access_token":"opaque","expires_in":3600}"#,
        r#"{"token":"opaque","access_token":"","expires_in":1800,"issued_at":"2026-09-19T12:00:00Z"}"#,
        r#"{"token":"","access_token":"opaque","expires_in":60}"#,
        r#"{"token":"opaque","issued_at":"2026-09-19T11:59:50Z","expires_in":60}"#,
    ] {
        let (header, expires) = token::parse(body.as_bytes(), scope, started, wall).unwrap();
        assert!(header.is_sensitive());
        assert!(expires <= started + Duration::from_secs(3595));
    }
    for body in [
        r#"{"token":"one","access_token":"two"}"#,
        r#"{"token":"","access_token":""}"#,
        r#"{"token":""}"#,
        "{}",
        r#"{"token":"opaque","expires_in":0}"#,
        r#"{"token":"opaque","expires_in":null}"#,
        r#"{"token":null,"access_token":"opaque"}"#,
        r#"{"token":"opaque","issued_at":null}"#,
        r#"{"token":"opaque","scope":null}"#,
        r#"{"token":"opaque","refresh_token":null}"#,
        r#"{"token":"opaque","expires_in":5}"#,
        r#"{"token":"opaque","expires_in":3601}"#,
        r#"{"token":"opaque","expires_in":-1}"#,
        r#"{"token":"opaque","expires_in":1.5}"#,
        r#"{"token":"opaque","expires_in":18446744073709551616}"#,
        r#"{"token":"opaque","scope":"repository:tenant/package:pull,push"}"#,
        r#"{"token":"opaque","scope":"repository:other/package:pull"}"#,
        r#"{"token":"opaque","refresh_token":"unapproved-offline-secret"}"#,
        r#"{"token":"opaque","issued_at":"2026-09-19T12:00:06Z"}"#,
        r#"{"token":"opaque","issued_at":"2026-09-19T11:58:00Z"}"#,
        r#"{"token":"opaque","issued_at":"not-a-timestamp"}"#,
        r#"{"token":"opaque","token":"duplicate"}"#,
        r#"{"token":"line\nbreak"}"#,
    ] {
        assert!(
            token::parse(body.as_bytes(), scope, started, wall).is_err(),
            "{body}"
        );
    }
    assert!(token::parse(&vec![b'x'; 16385], scope, started, wall).is_err());
    let oversized = format!("{{\"token\":\"{}\"}}", "x".repeat(8193));
    assert!(token::parse(oversized.as_bytes(), scope, started, wall).is_err());
    assert!(token::parse(
        b"{\"token\":\"expired\"}",
        scope,
        started - Duration::from_mins(1),
        wall
    )
    .is_err());
}

#[tokio::test]
async fn retired_tokens_remain_charged_and_cannot_manufacture_cache_capacity() {
    let peer = Peer::new().await;
    let bearer = ConfiguredBearer::new(&peer.config(RegistryActions::Pull))
        .unwrap()
        .unwrap();
    let header = crate::http::transport::client::bearer_authorization(&"x".repeat(8192)).unwrap();
    let mut retained = Vec::new();
    for _ in 0..10 {
        retained.push(
            Token::new(
                header.clone(),
                1,
                Instant::now() + Duration::from_mins(1),
                &bearer.accounting,
            )
            .unwrap(),
        );
    }
    assert!(Token::new(header.clone(), 1, Instant::now(), &bearer.accounting).is_err());
    bearer.cache.lock().unwrap().cached = Some(Arc::clone(&retained[0]));
    bearer
        .rotate(identity(2), "public-test-user", "rotated-public-secret")
        .unwrap();
    assert_eq!(bearer.usage().cached_tokens, 0);
    assert_eq!(
        bearer.usage().retained_token_bytes,
        bearer.usage().maximum_token_bytes
    );
    retained.pop();
    let after_drop = bearer.usage().retained_token_bytes;
    let replacement = Token::new(
        header,
        2,
        Instant::now() + Duration::from_mins(1),
        &bearer.accounting,
    )
    .unwrap();
    bearer.cache.lock().unwrap().cached = Some(replacement);
    bearer.close().unwrap();
    assert_eq!(bearer.usage().retained_token_bytes, after_drop);
    drop(retained);
    assert_eq!(bearer.accounting.bytes.load(Ordering::Acquire), 0);
}

#[tokio::test]
async fn expired_cache_entries_are_reclaimed_on_demand_without_timers() {
    let peer = Peer::new().await;
    let bearer = ConfiguredBearer::new(&peer.config(RegistryActions::Pull))
        .unwrap()
        .unwrap();
    bearer.cache.lock().unwrap().cached = Some(
        Token::new(
            HeaderValue::from_static("Bearer expired"),
            1,
            Instant::now() - Duration::from_secs(1),
            &bearer.accounting,
        )
        .unwrap(),
    );
    assert!(bearer.cached(1).unwrap().is_none());
    assert_eq!(bearer.usage().retained_token_bytes, 0);
    let mut config = peer.config(RegistryActions::Pull);
    if let RegistryCredentials::BearerChallenge { identity, .. } = &mut config.credentials {
        identity.credential_epoch = 0;
    }
    assert!(ConfiguredBearer::new(&config).is_err());
}

fn challenge(value: &str) -> HeaderMap {
    let mut headers = HeaderMap::new();
    headers.insert(WWW_AUTHENTICATE, HeaderValue::from_str(value).unwrap());
    headers
}
