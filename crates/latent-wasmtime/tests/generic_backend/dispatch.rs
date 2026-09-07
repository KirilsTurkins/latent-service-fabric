use latent_executor::{ExecutionBackend, GuestOutcome};
use serde_json::{json, Value};

use super::support::{
    budget, call, config, idle, prepared, request, returned, run, Cancellation, ALTERNATE, MEDIA,
    VALUES,
};

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn resolves_interface_and_function_names_and_multiple_parameters() {
    let (backend, prepared) = prepared(config()).await;
    for (contract, expected) in [(VALUES, 11), (ALTERNATE, 22)] {
        let cancellation = Cancellation::new(contract);
        let outcome = run(
            &backend,
            request(
                prepared.clone(),
                &cancellation.id,
                contract,
                "identify",
                b"[]",
                budget(),
            ),
            &cancellation,
        )
        .await
        .expect("identify");
        assert_eq!(returned(outcome), json!([expected]));
    }
    assert_eq!(
        returned(call(&backend, &prepared, "combine", b"[-7,12]").await),
        json!([5])
    );
    assert_eq!(backend.resource_snapshot().stores_created, 3);
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn lifts_and_lowers_every_supported_scalar_and_composite_family() {
    let (backend, prepared) = prepared(config()).await;
    let mut input = composite();
    let bytes = serde_json::to_vec(&json!([input.clone()])).expect("fixture JSON");
    let actual = returned(call(&backend, &prepared, "transform", &bytes).await);
    input["numbers"]["count"] = json!(42);
    input["bytes"] = json!([255, 2, 0]);
    input["access"] = json!(["read", "write"]);
    assert_eq!(actual, json!([input]));

    // A result inside a record is successful application data, even on err.
    let mut alternate = composite();
    alternate["maybe"] = json!({"none": null});
    alternate["nested"] = json!({"err": "nested-domain-data"});
    alternate["choice"] = json!({"case": "empty"});
    alternate["access"] = json!([]);
    let bytes = serde_json::to_vec(&json!([alternate.clone()])).expect("fixture JSON");
    let actual = returned(call(&backend, &prepared, "transform", &bytes).await);
    alternate["numbers"]["count"] = json!(42);
    alternate["bytes"] = json!([255, 2, 0]);
    assert_eq!(actual, json!([alternate]));
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn declared_errors_keep_the_complete_typed_result_and_generic_code() {
    let (backend, prepared) = prepared(config()).await;
    assert_eq!(
        returned(call(&backend, &prepared, "checked", b"[true]").await),
        json!([{"ok": "accepted"}])
    );
    match call(&backend, &prepared, "checked", b"[false]").await {
        GuestOutcome::DeclaredError { error, .. } => {
            assert_eq!(error.code, "declared-error");
            assert_eq!(error.media_type, MEDIA);
            assert_eq!(error.message, "component returned a declared error");
            assert_eq!(
                error.payload,
                br#"[{"err":{"case":"named","value":"denied"}}]"#
            );
        }
        other => panic!("expected declared error, got {other:?}"),
    }
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn preserves_zero_results_and_unit_result_branches() {
    let (backend, prepared) = prepared(config()).await;
    assert_eq!(
        returned(call(&backend, &prepared, "nothing", b"[]").await),
        json!([])
    );
    assert_eq!(
        returned(call(&backend, &prepared, "unit-result", b"[true]").await),
        json!([{"ok": null}])
    );
    match call(&backend, &prepared, "unit-result", b"[false]").await {
        GuestOutcome::DeclaredError { error, .. } => {
            assert_eq!(error.code, "declared-error");
            assert_eq!(error.media_type, MEDIA);
            assert_eq!(error.payload, br#"[{"err":null}]"#);
        }
        other => panic!("expected unit declared error, got {other:?}"),
    }
    idle(&backend);
}

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the generic component built by tools/validate_contracts.sh"]
async fn each_activation_starts_with_fresh_guest_memory_and_releases_its_store() {
    let (backend, prepared) = prepared(config()).await;
    for _ in 0..4 {
        assert_eq!(
            returned(call(&backend, &prepared, "bump", b"[]").await),
            json!([1])
        );
        idle(&backend);
    }
    assert_eq!(backend.resource_snapshot().stores_created, 4);
    assert_eq!(backend.cache_snapshot().entries, 1);
    backend
        .release(prepared)
        .await
        .expect("release prepared entry");
    assert_eq!(backend.cache_snapshot().entries, 0);
    idle(&backend);
}

pub fn composite() -> Value {
    json!({
        "numbers": {
            "boolean": true, "byte": 255, "short": 65_535, "count": 41,
            "wide": "18446744073709551615", "signed-byte": -128,
            "signed-short": -32_768, "signed-count": -2_147_483_648,
            "signed-wide": "-9223372036854775808", "single": "1.5", "double": "-0",
            "character": "λ", "text": "small typed fixture",
        },
        "bytes": [0, 2, 255], "pair": [-9, "tuple"], "maybe": {"some": "present"},
        "nested": {"ok": 7}, "choice": {"case": "named", "value": "choice"},
        "color": "blue", "access": ["write", "read"],
    })
}
