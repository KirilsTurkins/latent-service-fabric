use latent_core::Metadata;

use super::{DispatchMode, InstanceAllocator, WasmtimeConfig, WASMTIME_VERSION};
use crate::WasmtimeEngineProfile;

impl WasmtimeConfig {
    #[cfg(test)]
    pub(crate) fn configuration_digest(&self, mode: DispatchMode) -> String {
        digest(&self.compatibility_fields(mode))
    }

    #[cfg(test)]
    pub(crate) fn profile(&self, mode: DispatchMode) -> WasmtimeEngineProfile {
        self.profile_with_runtime(mode, None)
    }

    pub(crate) fn profile_with_runtime(
        &self,
        mode: DispatchMode,
        runtime: Option<&latent_manifest::RuntimeCompatibilityProfile>,
    ) -> WasmtimeEngineProfile {
        let mut configuration = self.compatibility_fields(mode);
        if let Some(runtime) = runtime {
            let fingerprint = runtime
                .digest()
                .iter()
                .map(|byte| format!("{byte:02x}"))
                .collect::<String>();
            configuration.insert("runtime-compatibility-digest".into(), fingerprint);
        }
        configuration.insert("configuration-digest".to_owned(), digest(&configuration));
        WasmtimeEngineProfile {
            id: mode.backend_id().to_owned(),
            wasmtime_version: WASMTIME_VERSION.to_owned(),
            target_triple: self.target_triple.clone(),
            cpu_feature_set: self.cpu_feature_set.clone(),
            pooling_allocator: matches!(self.instance_allocator, InstanceAllocator::Pooling),
            copy_on_write_images: self.copy_on_write_images,
            async_support: true,
            fuel_enabled: true,
            epoch_interruption_enabled: true,
            configuration,
        }
    }

    fn compatibility_fields(&self, mode: DispatchMode) -> Metadata {
        let mut fields = Metadata::from([
            ("component-model".to_owned(), "enabled".to_owned()),
            ("component-model-async".to_owned(), "enabled".to_owned()),
            ("fuel".to_owned(), "enabled".to_owned()),
            ("epoch-interruption".to_owned(), "enabled".to_owned()),
            (
                "memory-accounting".to_owned(),
                "aggregate-linear-memory".to_owned(),
            ),
            ("ambient-wasi-authority".to_owned(), "none".to_owned()),
            (
                "cpu-feature-policy".to_owned(),
                "native-host-detection".to_owned(),
            ),
            ("dispatch-policy".to_owned(), mode.backend_id().to_owned()),
            ("target".to_owned(), self.target_triple.clone()),
            ("cpu".to_owned(), self.cpu_feature_set.clone()),
            (
                "instance-allocation-strategy".to_owned(),
                self.instance_allocator.name().to_owned(),
            ),
            (
                "copy-on-write-images".to_owned(),
                self.copy_on_write_images.to_string(),
            ),
            (
                "prepared-cache-enabled".to_owned(),
                self.prepared_cache_enabled.to_string(),
            ),
            (
                "hostcall-fuel".to_owned(),
                match mode {
                    DispatchMode::Generic => "configured-bounded-transfer-v1",
                    DispatchMode::Phase0 => "per-call-echo-world-max-transfer",
                }
                .to_owned(),
            ),
            ("value-codec".to_owned(), "canonical-json-v1".to_owned()),
        ]);
        self.include_resource_policy(&mut fields);
        self.include_engine_policy(&mut fields);
        if mode == DispatchMode::Generic {
            for (name, value) in [
                ("compiler-workers", self.effective_compiler_workers()),
                (
                    "maximum-preparation-waiters",
                    self.maximum_preparation_waiters,
                ),
                (
                    "maximum-waiters-per-preparation",
                    self.maximum_waiters_per_preparation,
                ),
                (
                    "maximum-ready-preparations",
                    self.maximum_ready_preparations,
                ),
                (
                    "maximum-preparation-document-bytes",
                    self.maximum_preparation_document_bytes,
                ),
            ] {
                fields.insert(name.to_owned(), value.to_string());
            }
        }
        self.include_value_policy(&mut fields);
        self.context_policy.append_profile_fields(&mut fields);
        fields
    }

    fn include_resource_policy(&self, fields: &mut Metadata) {
        macro_rules! include {
            ($name:literal, $value:expr) => {
                fields.insert($name.to_owned(), $value.to_string());
            };
        }
        include!("maximum-component-bytes", self.maximum_component_bytes);
        include!("maximum-memory-bytes", self.maximum_memory_bytes);
        include!("maximum-fuel", self.maximum_fuel);
        fields.insert(
            "fuel-async-yield-interval".to_owned(),
            self.fuel_async_yield_interval
                .map_or_else(|| "disabled".to_owned(), |interval| interval.to_string()),
        );
        include!("maximum-wasm-stack-bytes", self.maximum_wasm_stack_bytes);
        include!("async-stack-bytes", self.async_stack_bytes);
        include!(
            "prepared-cache-maximum-entries",
            self.prepared_cache_maximum_entries
        );
        include!(
            "prepared-cache-maximum-source-bytes",
            self.prepared_cache_maximum_source_bytes
        );
        include!(
            "prepared-cache-maximum-metadata-bytes",
            self.prepared_cache_maximum_metadata_bytes
        );
        include!(
            "prepared-cache-maximum-compiled-image-bytes",
            self.prepared_cache_maximum_compiled_image_bytes
        );
        include!(
            "maximum-artifact-metadata-bytes",
            self.maximum_artifact_metadata_bytes
        );
        include!(
            "maximum-concurrent-preparations",
            self.maximum_concurrent_preparations
        );
        include!("maximum-active-instances", self.maximum_active_instances);
        include!(
            "maximum-instances-per-store",
            self.maximum_instances_per_store
        );
        include!(
            "maximum-memories-per-store",
            self.maximum_memories_per_store
        );
        include!("maximum-tables-per-store", self.maximum_tables_per_store);
        include!("maximum-table-elements", self.maximum_table_elements);
        include!(
            "invocation-log-maximum-entries",
            self.invocation_log_maximum_entries
        );
        include!(
            "invocation-log-maximum-bytes",
            self.invocation_log_maximum_bytes
        );
        include!(
            "retained-log-maximum-entries",
            self.retained_log_maximum_entries
        );
        include!(
            "retained-log-maximum-bytes",
            self.retained_log_maximum_bytes
        );
        include!("epoch-ticks", self.epoch_deadline_ticks);
        include!(
            "epoch-tick-interval-millis",
            self.epoch_tick_interval_millis
        );
        include!("pooling-maximum-instances", self.pooling_maximum_instances);
        include!(
            "pooling-maximum-component-instance-bytes",
            self.pooling_maximum_component_instance_bytes
        );
        include!(
            "pooling-maximum-core-instance-bytes",
            self.pooling_maximum_core_instance_bytes
        );
        include!(
            "pooling-maximum-core-instances-per-component",
            self.pooling_maximum_core_instances_per_component
        );
        include!(
            "pooling-maximum-memories-per-component",
            self.pooling_maximum_memories_per_component
        );
        include!(
            "pooling-maximum-tables-per-component",
            self.pooling_maximum_tables_per_component
        );
        include!("hostcall-fuel-bytes", self.hostcall_fuel);
    }

    fn include_value_policy(&self, fields: &mut Metadata) {
        macro_rules! include {
            ($name:literal, $value:expr) => {
                fields.insert($name.to_owned(), $value.to_string());
            };
        }
        let values = self.value_codec_limits;
        include!("value-max-input-bytes", values.max_input_bytes);
        include!("value-max-output-bytes", values.max_output_bytes);
        include!("value-max-depth", values.max_depth);
        include!("value-max-nodes", values.max_nodes);
        include!("value-max-string-bytes", values.max_string_bytes);
        include!("value-max-collection-items", values.max_collection_items);
        include!("value-max-type-nodes", values.max_type_nodes);
        include!("value-max-type-name-bytes", values.max_type_name_bytes);
        include!("value-max-lifted-bytes", values.max_lifted_bytes);
        include!(
            "value-max-decoded-value-bytes",
            values.max_decoded_value_bytes
        );
    }
}

fn digest(fields: &Metadata) -> String {
    let mut digest = blake3::Hasher::new();
    digest.update(b"latent-wasmtime-policy-v1");
    for (name, value) in fields {
        // Length framing prevents labels containing separators from aliasing.
        digest.update(&(name.len() as u64).to_le_bytes());
        digest.update(name.as_bytes());
        digest.update(&(value.len() as u64).to_le_bytes());
        digest.update(value.as_bytes());
    }
    format!("blake3:{}", digest.finalize().to_hex())
}
