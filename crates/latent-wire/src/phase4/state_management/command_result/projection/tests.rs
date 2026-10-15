use super::*;
use crate::phase4::retained_abort_fixture as original;
use latent_commit::atomic;
use prost::Message;

fn projected(fixture: &original::StoredAbort) -> t::CommandInspection {
    let contract::Response::LookupCommand(response) =
        response(&original::lookup(), &fixture.command, Some(&fixture.result)).unwrap()
    else {
        panic!("original command lookup absent");
    };
    let decoded = t::LookupCommandResponse::decode(response.encode_to_vec().as_slice()).unwrap();
    assert_eq!(decoded, *response);
    let command = decoded.command.unwrap();
    assert_eq!(command.outcome, t::CommandOutcome::Aborted as i32);
    assert_eq!(command.command_id, fixture.command.id().hex());
    assert!(command.metadata_durable && !command.application_state_committed);
    assert!(command.commit.is_none());
    let proof = command.proven_abort.as_ref().unwrap();
    assert_eq!(proof.command_id, command.command_id);
    assert_eq!(proof.transaction_id, fixture.command.transaction_id().hex());
    assert_eq!(
        proof.owner_fence,
        fixture.command.abort_proof().unwrap().bytes()
    );
    command
}
fn failure(command: &t::CommandInspection) -> &i::PlatformError {
    let Some(t::command_inspection::RetainedResult::TechnicalFailure(failure)) =
        command.retained_result.as_ref()
    else {
        panic!("original retained technical failure absent");
    };
    assert!(!failure.retryable);
    assert!(failure.detail_items.is_empty());
    assert_eq!(failure.message, "transaction result unavailable");
    failure
}
#[test]
fn actual_retired_abort_lookup_preserves_known_platform_codes() {
    for code in original::KNOWN {
        let fixture = original::aborted(code.wire_code());
        let command = projected(&fixture);
        assert_eq!(failure(&command).code, code.wire_code());
    }
}
#[test]
fn actual_retired_abort_lookup_keeps_unknown_codes_unavailable() {
    for code in original::UNKNOWN {
        let fixture = original::aborted(code);
        let command = projected(&fixture);
        assert_eq!(failure(&command).code, "unavailable");
        assert_eq!(fixture.result.code(), Some(code));
    }
}
#[test]
fn actual_pending_and_expired_abort_lookup_cannot_manufacture_a_retained_failure() {
    let pending = original::pending();
    let (record, result) = atomic::inspect(
        &pending.store.snapshot().unwrap(),
        &pending.key,
        original::time(101),
        |_, _| Ok(()),
    )
    .unwrap();
    assert!(result.is_none());
    let contract::Response::LookupCommand(value) =
        response(&original::lookup(), &record, result.as_ref()).unwrap()
    else {
        panic!("pending lookup absent");
    };
    let command = value.command.unwrap();
    assert_eq!(command.outcome, t::CommandOutcome::RecoveryRequired as i32);
    assert!(!command.metadata_durable && !command.application_state_committed);
    assert!(command.proven_abort.is_none() && command.commit.is_none());
    assert!(command.retained_result.is_none());
    let retirement = pending.claim.retirement();
    drop(pending.claim);
    assert!(retirement.proven_noncommit().is_ok());

    let fixture = original::aborted("guest-trap");
    let (record, result) = atomic::inspect(
        &fixture.store.snapshot().unwrap(),
        &fixture.key,
        original::time(fixture.command.result_expires()),
        |_, _| Ok(()),
    )
    .unwrap();
    assert!(result.is_none());
    let contract::Response::LookupCommand(value) =
        response(&original::lookup(), &record, result.as_ref()).unwrap()
    else {
        panic!("expired retained lookup absent");
    };
    let command = value.command.unwrap();
    assert_eq!(command.outcome, t::CommandOutcome::Aborted as i32);
    assert!(command.metadata_durable && !command.application_state_committed);
    assert!(command.retained_result.is_none());
    assert_eq!(command.proven_abort, projected(&fixture).proven_abort);
    assert!(command.commit.is_none());
}
