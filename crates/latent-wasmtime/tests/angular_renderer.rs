//! Required real Angular fixture gate; one immutable compilation, fresh Stores.
#[path = "angular_renderer/mod.rs"]
mod angular_renderer;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use angular_renderer::{artifact, config, request, success, WEB};
use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestInterruptionKind, GuestOutcome};
use latent_wasmtime::WasmtimeComponentEngineFactory;
use std::time::Duration;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires LSF_ANGULAR_COMPONENT built by the Angular renderer gate"]
#[expect(
    clippy::too_many_lines,
    reason = "one expensive compilation serves an ordered sequence of failures, recovery, cancellation and concurrent requests"
)]
async fn fresh_angular_cells_recover_from_failure_and_cancel_without_retaining_applications() {
    let artifact = artifact();
    let mut incompatible = config();
    incompatible.angular_renderer = false;
    let wrong = WasmtimeComponentEngineFactory::new(incompatible).unwrap();
    assert!(wrong
        .create_backend_instance()
        .prepare(
            &artifact,
            &wrong.preparation_key(artifact.descriptor.release_digest.clone())
        )
        .await
        .is_err());
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    eprintln!("Angular: preparing once through the generic backend");
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap();
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    for subject in ["Alice<private>", "Bob", "Alice<private>"] {
        success(&backend, &prepared, subject).await;
    }
    for path in [
        "/exception",
        "/invalid-result",
        "/allocate",
        "/delayed-timer",
        "/interval",
        "/timer-limit",
        "/microtask-limit",
        "/output-limit",
        "/frame-limit",
        "/ambient-fetch",
        "/replace-timer",
    ] {
        let cancel = support::Cancellation::new(path);
        let outcome = support::run(&backend, request(&prepared, &cancel.id, path), &cancel).await;
        assert!(
            !matches!(outcome, Ok(GuestOutcome::Returned { .. })),
            "{path}: {outcome:?}"
        );
        eprintln!("Angular bounded failure {path}: {outcome:?}");
        support::idle(&backend);
        success(&backend, &prepared, "recovered").await;
    }
    for path in ["/spin", "/promise-storm"] {
        let cancel = support::Cancellation::new(path);
        let mut call = request(&prepared, &cancel.id, path);
        call.budget.cpu_fuel = 10_000_000;
        call.activation.budget = call.budget.clone();
        let outcome = support::run(&backend, call, &cancel).await.unwrap();
        assert!(
            matches!(
                outcome,
                GuestOutcome::Interrupted {
                    kind: GuestInterruptionKind::FuelExhausted,
                    ..
                }
            ),
            "{outcome:?}"
        );
        support::idle(&backend);
        success(&backend, &prepared, "after-cpu").await;
    }
    let cancel = support::Cancellation::new("cancel-spin");
    let spin = backend.invoke_contained(request(&prepared, &cancel.id, "/spin"), &cancel);
    let controller = async {
        tokio::time::sleep(Duration::from_millis(30)).await;
        assert_eq!(backend.resource_snapshot().live_stores, 1);
        cancel.cancel();
    };
    let (report, ()) = tokio::time::timeout(Duration::from_secs(5), async {
        tokio::join!(spin, controller)
    })
    .await
    .unwrap();
    assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
    assert!(
        matches!(
            report.outcome,
            Ok(GuestOutcome::Interrupted {
                kind: GuestInterruptionKind::Cancelled,
                ..
            })
        ),
        "{:?}",
        report.outcome
    );
    support::idle(&backend);
    success(&backend, &prepared, "after-cancel").await;
    // Both requests make cooperative progress on the same Tokio worker. Each
    // assertion checks its own principal, cookie, lineage and hydration state.
    tokio::join!(
        success(&backend, &prepared, "concurrent-a"),
        success(&backend, &prepared, "concurrent-b")
    );
    support::idle(&backend);
    let cancel = support::Cancellation::new("maximum-html");
    let value = support::returned(
        support::run(
            &backend,
            request(&prepared, &cancel.id, "/maximum-document"),
            &cancel,
        )
        .await
        .unwrap(),
    );
    assert_eq!(angular_renderer::html(&value).len(), 128 * 1024);
    support::idle(&backend);
    assert_eq!(artifact.manifest.exports[0].contract.0, WEB);
}

#[test]
#[ignore = "requires LSF_ANGULAR_COMPONENT built by the Angular renderer gate"]
fn renderer_binary_profile_preserves_ordinary_and_public_wit_limits() {
    use latent_artifacts::web::WebRendererProfile::{AngularSsrComponentV1, WasmWebBufferedV1};
    use latent_packaging::{validate_web_renderer, SemanticLimits};
    let bytes = artifact().component_bytes;
    let limits = SemanticLimits::default();
    let checked = validate_web_renderer(&bytes, AngularSsrComponentV1, limits).unwrap();
    assert_eq!(checked.counts().exports, 1);
    assert_eq!(checked.counts().functions, 1);
    let private = std::fs::read(
        std::env::var_os("LSF_ANGULAR_PRIVATE_COMPONENT")
            .expect("required private composition fixture"),
    )
    .unwrap();
    assert!(
        validate_web_renderer(&private, AngularSsrComponentV1, limits).is_err(),
        "the private engine export cannot masquerade as the public async API"
    );
    assert!(validate_web_renderer(&bytes, WasmWebBufferedV1, limits).is_err());
    for limited in [
        SemanticLimits {
            max_renderer_operators: 2_000_000,
            ..limits
        },
        SemanticLimits {
            max_renderer_type_nodes: 128,
            ..limits
        },
        SemanticLimits {
            max_type_nodes: 16,
            ..limits
        },
    ] {
        assert!(
            validate_web_renderer(&bytes, AngularSsrComponentV1, limited).is_err(),
            "{limited:?}"
        );
    }
}
