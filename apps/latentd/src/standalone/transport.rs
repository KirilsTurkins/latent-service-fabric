//! Node-owned transport admission and cleanup, separate from activation quotas.
mod auth;
mod config;
mod dispatch;
mod io;
mod owned;
mod signal;
mod state;
#[cfg(test)]
mod tests;

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use latent_core::{ActivationClock, PlatformError, PlatformErrorCode};
use latent_wire::invocation::{InvocationServiceAdapter, LocalInvocationRuntime};
use latent_wire::management::ManagementServiceAdapter;
use tokio::runtime::Handle;
use tokio::task::JoinHandle;

pub use config::{TransportConfig, TransportCredential};
pub use state::{TransportHandle, TransportSnapshot};

pub struct Transport {
    address: SocketAddr,
    handle: TransportHandle,
    serving: Option<JoinHandle<Result<(), tonic::transport::Error>>>,
}

impl Transport {
    /// Runtimes are owned by the synchronous composition root. Starts gated;
    /// call `start_accepting` only after installing final node readiness sources.
    pub async fn start(
        config: TransportConfig,
        invocation: InvocationServiceAdapter<LocalInvocationRuntime>,
        management: ManagementServiceAdapter,
        clock: Arc<dyn ActivationClock>,
        control_runtime: Handle,
    ) -> Result<Self, PlatformError> {
        let routes = tonic::service::Routes::new(invocation.into_server())
            .add_service(management.clone().release_server())
            .add_service(management.clone().deployment_server())
            .add_service(management.clone().route_server())
            .add_service(management.clone().audit_server())
            .add_service(management.node_server())
            .prepare();
        Self::start_routes(config, routes, clock, control_runtime).await
    }

    async fn start_routes(
        config: TransportConfig,
        routes: tonic::service::Routes,
        clock: Arc<dyn ActivationClock>,
        control_runtime: Handle,
    ) -> Result<Self, PlatformError> {
        config.validate()?;
        let listener = tokio::net::TcpListener::bind(config.bind)
            .await
            .map_err(|_| unavailable("standalone listener could not bind"))?;
        let address = listener
            .local_addr()
            .map_err(|_| unavailable("standalone listener address is unavailable"))?;
        let shared = state::Shared::new(config);
        let incoming = io::Incoming {
            listener,
            stopped: shared.stop.listen(),
            shared: Arc::clone(&shared),
        };
        let layer = dispatch::DispatchLayer {
            shared: Arc::clone(&shared),
            clock,
            control_runtime,
        };
        let server = tonic::transport::Server::builder()
            .timeout(shared.config.request_timeout)
            .max_concurrent_streams(Some(shared.config.maximum_streams_per_connection))
            .http2_max_header_list_size(Some(shared.config.maximum_header_bytes))
            .max_frame_size(Some(16_384))
            .initial_stream_window_size(Some(65_535))
            .initial_connection_window_size(Some(65_535))
            .http2_adaptive_window(Some(false))
            .http2_max_pending_accept_reset_streams(Some(
                shared.config.maximum_streams_per_connection as usize,
            ))
            .http2_max_local_error_reset_streams(Some(
                shared.config.maximum_streams_per_connection as usize,
            ))
            .layer(layer);
        let serving = tokio::spawn(server.serve_with_incoming_shutdown(
            routes,
            incoming,
            shared.stop.listen(),
        ));
        Ok(Self {
            address,
            handle: TransportHandle { shared },
            serving: Some(serving),
        })
    }

    #[must_use]
    pub const fn local_addr(&self) -> SocketAddr {
        self.address
    }
    #[must_use]
    pub fn handle(&self) -> TransportHandle {
        self.handle.clone()
    }
    #[must_use]
    pub fn is_finished(&self) -> bool {
        self.serving.as_ref().is_none_or(JoinHandle::is_finished)
    }

    pub async fn shutdown(mut self) -> Result<TransportSnapshot, PlatformError> {
        self.handle.cancel_active();
        let maximum = self.handle.shared.config.shutdown_timeout;
        let deadline = tokio::time::Instant::now() + maximum;
        let grace = (maximum / 2).min(Duration::from_secs(1));
        if tokio::time::timeout(grace, self.handle.shared.idle())
            .await
            .is_err()
        {
            self.handle.force_close();
        }
        // Reserve part of the same finite shutdown allowance for an abort join.
        // Keep the JoinHandle in self across every await: cancellation of this
        // shutdown future must still run Transport's conservative Drop.
        let join_deadline = deadline - maximum / 4;
        let result = tokio::time::timeout_at(join_deadline, async {
            self.handle.shared.idle().await;
            self.serving.as_mut().expect("owned server task").await
        })
        .await;
        if let Ok(Ok(Ok(()))) = result {
            self.serving.take();
            Ok(self.handle.snapshot())
        } else {
            self.handle.force_close();
            if result.is_err() {
                self.serving.as_ref().expect("owned server task").abort();
                if tokio::time::timeout_at(
                    deadline,
                    self.serving.as_mut().expect("owned server task"),
                )
                .await
                .is_ok()
                {
                    self.serving.take();
                }
            } else {
                // A completed error/panic is already joined; never poll it twice.
                self.serving.take();
            }
            Err(unavailable("standalone server did not stop cleanly"))
        }
    }
}

impl Drop for Transport {
    fn drop(&mut self) {
        if let Some(serving) = self.serving.take() {
            self.handle.force_close();
            serving.abort();
        }
    }
}

fn failure(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}
fn unavailable(message: &'static str) -> PlatformError {
    failure(PlatformErrorCode::Unavailable, message)
}
