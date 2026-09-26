//! Shared, explicitly supplied node host services.

use std::sync::Arc;

use latent_core::{ActivationClock, SystemActivationClock};

use crate::StructuredLogSink;

/// Host services are retained once by the factory and shared by active stores.
/// Preparing dormant components does not construct additional providers.
#[derive(Clone)]
pub struct WasmtimeHostServices {
    pub clock: Arc<dyn ActivationClock>,
    /// Explicit executor-neutral timer for pre-effect host-clock admission.
    /// None preserves immediate, nonblocking capability admission. This does
    /// not grant authority, refresh proofs, or change activation deadlines.
    pub currentness_read_wait: Option<Arc<dyn latent_executor::PreparationReadWait>>,
    pub log_sink: Option<Arc<dyn StructuredLogSink>>,
    /// Explicit managed capability mode; requires the exact catalog owner.
    pub capabilities: Option<Arc<latent_capabilities::broker::ActivationCapabilityRuntime>>,
}

impl Default for WasmtimeHostServices {
    fn default() -> Self {
        Self {
            clock: Arc::new(SystemActivationClock),
            currentness_read_wait: None,
            log_sink: None,
            capabilities: None,
        }
    }
}
