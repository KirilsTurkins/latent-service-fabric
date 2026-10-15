//! Real protected result reads across descriptive schema-history metadata.
//! Actual migration producer qualification remains a separate native control.
use super::fixture as effects_fixture;
use super::*;
mod fixture;
mod historical;
mod rejection;
use fixture::{backend, commit_request, inspection, request, rows, HistoryFixture};
use latent_core::TenantId;
use latent_rpc::transaction::v1 as t;
use std::sync::atomic::Ordering;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_original_result_and_commit_keep_old_schema_under_current_binding() {
    let mut fixture = HistoryFixture::new().await;
    let before = rows(&fixture.effect).await;
    fixture.advance().await;
    let result = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await;
    let commit = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            commit_request(&fixture).into(),
        )
        .await;
    let observed = result.as_ref().ok().map(|response| {
        response.owner.with_current(&mut || {}).unwrap();
        inspection(response).clone()
    });
    let receipt = commit.as_ref().ok().map(|response| {
        response.owner.with_current(&mut || {}).unwrap();
        inspection(response).clone()
    });
    let same_rows = rows(&fixture.effect).await == before;
    let original = fixture.original.clone();
    let old_schema = fixture.original_schema.clone();
    let current_schema = fixture.current_schema.clone();
    let failure = result.as_ref().err().map(|error| error.code.wire_code());
    drop((result, commit));
    fixture.finish().await;
    eprintln!(
        "original-result-schema-control: {}",
        serde_json::json!({
            "originalSchemaDiffers": old_schema != current_schema,
            "commandRowsUnchanged": same_rows, "failureCode": failure,
            "physicalRetirementCompleted": true, "descriptiveMetadataOnly": true,
        })
    );
    // The original-production baseline fails only after actual owner retirement.
    assert_eq!(observed.unwrap(), original);
    let mut expected_commit = original;
    expected_commit.retained_result = None;
    expected_commit
        .retention
        .as_mut()
        .unwrap()
        .payload_available = false;
    assert_eq!(receipt.unwrap(), expected_commit);
    assert!(same_rows);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_historical_attempt_keeps_original_abort_and_current_rejection_after_schema_change()
{
    let mut fixture = HistoryFixture::new().await;
    let command = historical::seed(&fixture).await;
    let mut prior = request(&fixture.effect);
    prior.command = Some(command.clone());
    prior.attempt_id = Some("1".into());
    let response = fixture
        .backend
        .execute_state(effects_fixture::reader("alice"), prior.clone().into())
        .await
        .unwrap();
    let original = inspection(&response).clone();
    assert_eq!(original.outcome, t::CommandOutcome::Aborted as i32);
    assert!(original.proven_abort.is_some());
    drop(response);
    let before = rows(&fixture.effect).await;
    fixture.advance().await;
    let response = fixture
        .backend
        .execute_state(effects_fixture::reader("alice"), prior.into())
        .await
        .unwrap();
    assert_eq!(inspection(&response), &original);
    response.owner.with_current(&mut || {}).unwrap();
    drop(response);
    let mut current = request(&fixture.effect);
    current.command = Some(command);
    let response = fixture
        .backend
        .execute_state(effects_fixture::reader("alice"), current.into())
        .await
        .unwrap();
    let rejected = inspection(&response);
    assert_eq!(rejected.attempt_id, "2");
    assert_eq!(rejected.outcome, t::CommandOutcome::Rejected as i32);
    assert_eq!(rejected.source, original.source);
    assert!(
        matches!(&rejected.retained_result, Some(t::command_inspection::RetainedResult::BusinessRejection(value)) if value.payload == b"second original decision")
    );
    drop(response);
    assert_eq!(rows(&fixture.effect).await, before);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_old_schema_result_keeps_caller_scope_and_all_selected_key_fields_closed() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    let before = rows(&fixture.effect).await;
    for (kind, expected) in [
        ("caller", PlatformErrorCode::NotFound),
        ("tenant", PlatformErrorCode::InvalidArgument),
        ("namespace", PlatformErrorCode::PermissionDenied),
        ("incarnation", PlatformErrorCode::PermissionDenied),
        ("operation", PlatformErrorCode::NotFound),
        ("entity", PlatformErrorCode::PermissionDenied),
        ("client-key", PlatformErrorCode::NotFound),
        ("shared-scope", PlatformErrorCode::PermissionDenied),
        ("publication", PlatformErrorCode::PermissionDenied),
    ] {
        let mut selected = request(&fixture.effect);
        let command = selected.command.as_mut().unwrap();
        let mut actor = effects_fixture::reader("alice");
        match kind {
            "caller" => actor = effects_fixture::reader("bob"),
            "tenant" => command.namespace.as_mut().unwrap().tenant = "foreign".into(),
            "namespace" => command.namespace.as_mut().unwrap().namespace = "foreign".into(),
            "incarnation" => command.namespace.as_mut().unwrap().incarnation = "2".into(),
            "operation" => command.operation = "foreign-operation".into(),
            "entity" => command.entity = Some("other-entity".into()),
            "client-key" => command.client_key = "other-client-key".into(),
            "shared-scope" => command.shared_recovery_scope = Some("uninstalled-scope".into()),
            "publication" => {
                selected.authorization_publication.as_mut().unwrap().id =
                    format!("publication:sha256:{}", "9".repeat(64));
            }
            _ => unreachable!(),
        }
        let error = fixture
            .backend
            .execute_state(actor, selected.into())
            .await
            .err()
            .unwrap();
        assert_eq!(error.code, expected, "{kind}: {}", error.code.wire_code());
        assert_eq!(rows(&fixture.effect).await, before);
    }
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_current_namespace_schema_and_original_result_policy_remain_mandatory() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    let before = rows(&fixture.effect).await;
    let old_binding = backend(&fixture.effect, &fixture.original_schema, "visibility-v1");
    let error = old_binding
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    drop(old_binding);
    let mut document = fixture.effect.fixture.document.clone();
    for rule in document["rules"].as_array_mut().unwrap() {
        if rule["id"] == "alice-effect-reader" {
            rule["resources"]["scopes"][0]["resultPolicy"] = "different-result-policy".into();
        }
    }
    fixture
        .effect
        .fixture
        .update(Some(&document), "different-current-result-policy");
    let other_policy = backend(
        &fixture.effect,
        &fixture.current_schema,
        "different-result-policy",
    );
    let error = other_policy
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    drop(other_policy);
    assert_eq!(rows(&fixture.effect).await, before);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_old_result_response_keeps_original_current_policy_after_revocation_and_regrant() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    let response = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .unwrap();
    response.owner.with_current(&mut || {}).unwrap();
    let original_policy = fixture.effect.fixture.document.clone();
    let mut revoked = original_policy.clone();
    revoked["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"] != "alice-effect-reader");
    fixture
        .effect
        .fixture
        .update(Some(&revoked), "revoke-original-result-read");
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    let error = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    fixture
        .effect
        .fixture
        .update(Some(&original_policy), "fresh-original-result-read");
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    let fresh = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .unwrap();
    assert_eq!(inspection(&fresh), &fixture.original);
    drop((response, fresh));
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_result_response_cannot_survive_a_later_namespace_lifecycle_change() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    let response = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .unwrap();
    // This actual lifecycle transition does not require drain: the held response
    // must retain its old pin and fail publication after the transition resolves.
    rejection::transition_while_held(&fixture).await;
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    drop(response);
    let error = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_original_schema_result_retains_distinct_body_identity_and_clock_floor_limits() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    let response = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .unwrap();
    let retention = fixture.original.retention.as_ref().unwrap();
    fixture.effect.time.store(
        retention.payload_expires_at_unix_millis.unwrap(),
        Ordering::SeqCst,
    );
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    drop(response);
    let metadata = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .unwrap();
    assert!(inspection(&metadata).retained_result.is_none());
    assert_eq!(inspection(&metadata).source, fixture.original.source);
    metadata.owner.with_current(&mut || {}).unwrap();
    fixture.effect.time.store(
        retention.identity_expires_at_unix_millis.unwrap(),
        Ordering::SeqCst,
    );
    assert_eq!(
        metadata.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::DeadlineExceeded
    );
    drop(metadata);
    let error = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::DeadlineExceeded);
    fixture.effect.time.store(100, Ordering::SeqCst);
    assert!(fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into()
        )
        .await
        .is_err());
    fixture.effect.time.store(102, Ordering::SeqCst);
    fixture.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_corrupt_original_result_link_never_becomes_readable_after_schema_change() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    rejection::damage_result(&fixture).await;
    let error = fixture
        .backend
        .execute_state(
            effects_fixture::reader("alice"),
            request(&fixture.effect).into(),
        )
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::Unavailable);
    rejection::finish_damaged(fixture).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn actual_effect_and_cancel_keep_original_schema_refusal_after_result_read_succeeds() {
    let mut fixture = HistoryFixture::new().await;
    fixture.advance().await;
    drop(
        fixture
            .backend
            .execute_state(
                effects_fixture::reader("alice"),
                request(&fixture.effect).into(),
            )
            .await
            .unwrap(),
    );
    let before = rows(&fixture.effect).await;
    let effect = t::GetEffectRequest {
        profile: Some(contract::current_profile()),
        command: Some(fixture.effect.command.clone()),
        effect_id: fixture.effect.effect.clone(),
        authorization_publication: fixture.effect.fixture.target().authorization_publication,
    };
    let mut original = request(&fixture.effect);
    original.attempt_id = Some("1".into());
    let cancel = t::CancelCommandRequest {
        command: Some(original),
        reason: "same original owner".into(),
    };
    for request in [
        contract::Request::from(effect),
        contract::Request::from(cancel),
    ] {
        let error = fixture
            .backend
            .execute_state(effects_fixture::reader("alice"), request)
            .await
            .err()
            .unwrap();
        assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    }
    assert_eq!(rows(&fixture.effect).await, before);
    fixture.finish().await;
}
