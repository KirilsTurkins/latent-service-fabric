use super::fixture::{reader, setup_with_recovery_provider, FixtureEffect};
use super::*;
use latent_core::native_capacity::{NativeAdmissionClass, NativeReservationRequest};
use latent_effects::dispatch::Disposition;
use latent_rpc::transaction::v1::{self as t, transaction_service_server::TransactionService};
use std::sync::atomic::Ordering;

fn request(effect: &FixtureEffect) -> t::ListEffectHistoryRequest {
    t::ListEffectHistoryRequest {
        effect: Some(t::GetEffectRequest {
            profile: Some(contract::current_profile()),
            command: Some(effect.command.clone()),
            effect_id: effect.effect.clone(),
            authorization_publication: effect.fixture.target().authorization_publication,
        }),
        page: Some(t::PageRequest {
            limit: 1,
            cursor: None,
        }),
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn history_rpc_reads_original_receipt_with_bounded_current_authority() {
    let mut effect = setup_with_recovery_provider(Disposition::ProviderAcknowledged).await;
    effect.settle_original().await;
    let native = &effect.fixture.admission.native;
    let mut ordinary = Vec::new();
    while let Ok(reservation) = native.reserve(
        NativeAdmissionClass::Ordinary,
        NativeReservationRequest::default(),
        deadline(),
    ) {
        ordinary.push(reservation);
    }
    assert!(!ordinary.is_empty());
    let recovery_before = native.snapshot().unwrap().recovery;
    let adapter = crate::phase4::Phase4ServiceAdapter::with_services(
        Arc::new(effect.fixture.backend.clone()),
        crate::management::ManagementLimits::default(),
        crate::phase4::Phase4Services {
            principals: Arc::new(crate::invocation::LocalPrincipalPolicy),
            management: Arc::new(crate::management::LocalManagementPolicy),
            clock: Arc::new(latent_core::SystemActivationClock),
        },
    )
    .unwrap();
    let before = effect.rows().await;
    let response = adapter
        .list_effect_history(reader("alice").request(request(&effect)))
        .await
        .unwrap();
    let page = response.get_ref();
    assert_eq!(page.receipts.len(), 1);
    let receipt = &page.receipts[0];
    assert_eq!(receipt.effect_id, effect.effect);
    assert_eq!(
        receipt.disposition,
        t::EffectDisposition::ProviderAcknowledged as i32
    );
    assert_eq!(receipt.dispatch_attempt, 1);
    assert_eq!(
        receipt.provider_receipt.as_deref(),
        Some("controlled-positive-provider-receipt")
    );
    assert!(receipt.record_version.is_empty());
    assert_eq!(page.page.as_ref().unwrap().returned_count, 1);
    assert!(native.snapshot().unwrap().recovery.bytes > recovery_before.bytes);
    assert_eq!(effect.rows().await, before);
    drop(response);
    drop(adapter);
    assert_eq!(native.snapshot().unwrap().recovery, recovery_before);
    drop(ordinary);
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn history_refuses_foreign_effect_and_cursor_without_changing_rows() {
    let mut effect = setup_with_recovery_provider(Disposition::ProviderAcknowledged).await;
    effect.settle_original().await;
    let (_, foreign) = effect.related_command().await;
    let before = effect.rows().await;
    let mut wrong_effect = request(&effect);
    wrong_effect.effect.as_mut().unwrap().effect_id = foreign;
    let mut wrong_cursor = request(&effect);
    wrong_cursor.page.as_mut().unwrap().cursor = Some(vec![1, 2, 3]);
    for (value, expected) in [
        (wrong_effect, PlatformErrorCode::PermissionDenied),
        (wrong_cursor, PlatformErrorCode::InvalidArgument),
    ] {
        let error = effect
            .fixture
            .backend
            .execute_state(reader("alice"), value.into())
            .await
            .err()
            .unwrap();
        assert_eq!(error.code, expected);
    }
    let error = effect
        .fixture
        .backend
        .execute_state(reader("bob"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::NotFound);
    assert_eq!(effect.rows().await, before);
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn retained_history_page_cannot_outlive_revoked_original_read_authority() {
    let mut effect = setup_with_recovery_provider(Disposition::ProviderAcknowledged).await;
    effect.settle_original().await;
    let response = effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .unwrap();
    response.owner.with_current(&mut || {}).unwrap();
    let mut document = effect.fixture.document.clone();
    document["rules"]
        .as_array_mut()
        .unwrap()
        .retain(|rule| rule["id"] != "alice-effect-reader");
    effect
        .fixture
        .update(Some(&document), "revoke-history-read");
    assert_eq!(
        response.owner.with_current(&mut || {}).err().unwrap().code,
        PlatformErrorCode::PermissionDenied
    );
    let error = effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::PermissionDenied);
    drop(response);
    effect.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn history_pages_preserve_actual_uncertain_and_acknowledged_attempts() {
    let mut effect = setup_with_recovery_provider(Disposition::Uncertain).await;
    effect
        .provider
        .as_ref()
        .unwrap()
        .retry_once
        .store(true, Ordering::SeqCst);
    effect.dispatcher.resume().unwrap();
    tokio::time::timeout(Duration::from_secs(5), async {
        while effect.disposition().await != Disposition::RetryScheduled {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    effect.time.store(105, Ordering::SeqCst);
    tokio::time::timeout(Duration::from_secs(5), async {
        while effect.disposition().await != Disposition::ProviderAcknowledged {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    effect.dispatcher.pause();
    let first_response = effect
        .fixture
        .backend
        .execute_state(reader("alice"), request(&effect).into())
        .await
        .unwrap();
    let contract::Response::ListEffectHistory(first) = &first_response.response else {
        panic!("history page")
    };
    assert_eq!(first.receipts.len(), 1);
    assert_eq!(
        first.receipts[0].disposition,
        t::EffectDisposition::UncertainAfterDispatch as i32
    );
    assert_eq!(first.receipts[0].dispatch_attempt, 1);
    let cursor = first
        .page
        .as_ref()
        .unwrap()
        .next_cursor
        .clone()
        .expect("second page");
    let mut continuation = request(&effect);
    continuation.page.as_mut().unwrap().cursor = Some(cursor.clone());
    let second_response = effect
        .fixture
        .backend
        .execute_state(reader("alice"), continuation.into())
        .await
        .unwrap();
    let contract::Response::ListEffectHistory(second) = &second_response.response else {
        panic!("history page")
    };
    assert_eq!(second.receipts.len(), 1);
    assert_eq!(
        second.receipts[0].disposition,
        t::EffectDisposition::ProviderAcknowledged as i32
    );
    assert_eq!(second.receipts[0].dispatch_attempt, 2);
    assert!(second.page.as_ref().unwrap().next_cursor.is_none());
    drop(second_response);
    drop(first_response);
    let (other_command, other_effect) = effect.related_recovery_command().await;
    let mut foreign_cursor = request(&effect);
    let target = foreign_cursor.effect.as_mut().unwrap();
    target.command = Some(other_command);
    target.effect_id = other_effect;
    foreign_cursor.page.as_mut().unwrap().cursor = Some(cursor);
    let error = effect
        .fixture
        .backend
        .execute_state(reader("alice"), foreign_cursor.into())
        .await
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
    effect.finish().await;
}
