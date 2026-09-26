//! A real bounded guest in the same parent process remains usable while an
//! independently owned compiler hangs and after that child is killed/reaped.
use super::{component, runtime};
use latent_executor::{ExecutionBackend, PreparedComponent};
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory};

pub(super) struct Guest {
    executor: tokio::runtime::Runtime,
    backend: WasmtimeBackend,
    prepared: PreparedComponent,
}

impl Guest {
    pub(super) fn new() -> Self {
        let executor = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let factory = WasmtimeComponentEngineFactory::new(runtime::config()).unwrap();
        let backend = factory.create_backend_instance();
        let artifact = runtime::artifact_bytes(component::bytes(), &[component::CONTRACT]);
        let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
        let prepared = executor.block_on(backend.prepare(&artifact, &key)).unwrap();
        Self {
            executor,
            backend,
            prepared,
        }
    }

    pub(super) fn invoke(&self) {
        let cancellation = runtime::Cancellation::new("unrelated-during-compiler-failure");
        let request = runtime::request(
            self.prepared.clone(),
            &cancellation.id,
            component::CONTRACT,
            "answer",
            b"[]",
            runtime::budget(),
        );
        let outcome = self.executor.block_on(async {
            tokio::time::timeout(
                runtime::WATCHDOG,
                self.backend.invoke(request, &cancellation),
            )
            .await
            .unwrap()
            .unwrap()
        });
        assert_eq!(runtime::returned(outcome), serde_json::json!([7]));
        runtime::idle(&self.backend);
    }
}
