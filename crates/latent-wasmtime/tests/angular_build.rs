//! Actual maintained build output, rendered in fresh cells before browser hydration.
#[path = "angular_renderer/mod.rs"]
#[allow(dead_code)]
mod angular_renderer;
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use angular_renderer::{artifact, config, html, request};
use latent_executor::{ExecutionBackend, GuestOutcome};
use latent_wasmtime::WasmtimeComponentEngineFactory;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the maintained Angular build and its owned browser test output"]
async fn actual_built_angular_application_renders_fresh_hydration_and_rejects_excess_data() {
    let artifact = artifact();
    let factory = WasmtimeComponentEngineFactory::new(config()).unwrap();
    let backend = factory.create_backend_instance();
    eprintln!("Angular build: preparing the actual produced component once");
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap();
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    for subject in ["Alice <unsafe>", "Bob", "Alice <unsafe>"] {
        let cancel = support::Cancellation::new(subject);
        let value = support::returned(
            support::run(&backend, request(&prepared, &cancel.id, "/"), &cancel)
                .await
                .unwrap(),
        );
        assert_eq!(value[0]["status"], 200);
        let document = html(&value);
        assert!(document.contains("ngh="));
        assert!(document.contains("/client/"));
        assert!(!document.contains("__LSF_CLIENT_ASSET__"));
        assert!(!document.contains("lsf-private-server-fixture-234"));
        if subject == "Bob" {
            assert!(document.contains("Hello Bob"));
            assert!(!document.contains("Alice"));
        } else {
            assert!(document.contains("Hello Alice &lt;unsafe&gt;"));
            assert!(!document.contains("Bob"));
            let path = std::env::var_os("LSF_ANGULAR_HTML").expect("owned browser test output");
            std::fs::write(path, &document).unwrap();
        }
        support::idle(&backend);
    }
    let cancel = support::Cancellation::new("hydration-limit");
    let outcome = support::run(
        &backend,
        request(&prepared, &cancel.id, "/large-hydration"),
        &cancel,
    )
    .await;
    assert!(!matches!(outcome, Ok(GuestOutcome::Returned { .. })));
    support::idle(&backend);
    let cancel = support::Cancellation::new("after-rejected-hydration");
    let recovered = support::returned(
        support::run(&backend, request(&prepared, &cancel.id, "/"), &cancel)
            .await
            .unwrap(),
    );
    assert!(html(&recovered).contains("Hello after-rejected-hydration"));
    support::idle(&backend);
}
