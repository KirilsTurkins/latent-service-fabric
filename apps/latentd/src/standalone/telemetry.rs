//! One exporter owner transfers from provider bootstrap to the running node.
use std::sync::Arc;

use latent_core::PlatformError;
use latent_telemetry::{
    LocalSinkConfig, StructuredLocalSink, TelemetryHandle, TelemetryPipelineConfig,
    TelemetryRuntime,
};

use crate::config::NodeSettings;

pub(super) struct TelemetryOwner {
    pub handle: TelemetryHandle,
    pub sink: Arc<StructuredLocalSink>,
    pub runtime: TelemetryRuntime,
    pipeline: TelemetryPipelineConfig,
    local: LocalSinkConfig,
}

impl TelemetryOwner {
    pub fn start(settings: &NodeSettings) -> Result<Box<Self>, PlatformError> {
        let sink = Arc::new(StructuredLocalSink::new(settings.local_sink)?);
        let (handle, runtime) = TelemetryRuntime::spawn(settings.telemetry, sink.clone())?;
        Ok(Box::new(Self {
            handle,
            sink,
            runtime,
            pipeline: settings.telemetry,
            local: settings.local_sink,
        }))
    }

    pub fn matches(&self, settings: &NodeSettings) -> bool {
        self.pipeline == settings.telemetry && self.local == settings.local_sink
    }
}
