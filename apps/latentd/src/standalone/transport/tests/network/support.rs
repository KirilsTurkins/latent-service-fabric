use std::sync::atomic::{AtomicUsize, Ordering};

use latent_activation::ActivationStatus;
use latent_core::{
    ActivationPhase, BoxFuture, CancelDisposition, PlatformError, PlatformErrorCode,
};
pub(super) use latent_wire::invocation::proto;
use latent_wire::invocation::{
    CancellationCommand, InvocationCancellation, InvocationCommand, InvocationLimits,
    InvocationResponse, InvocationRuntime, InvocationServiceAdapter, StatusQuery,
};

use super::*;

pub(super) type Client =
    proto::invocation_service_client::InvocationServiceClient<tonic::transport::Channel>;

#[derive(Default)]
pub(super) struct Runtime {
    pub(super) started: AtomicUsize,
    pub(super) dropped: AtomicUsize,
    pub(super) finished: AtomicUsize,
    pub(super) cancelled: AtomicUsize,
    pub(super) release: Arc<signal::Signal>,
}

impl InvocationRuntime for Runtime {
    fn invoke(
        &self,
        _command: InvocationCommand,
        cancellation: InvocationCancellation,
    ) -> BoxFuture<'_, Result<InvocationResponse, PlatformError>> {
        self.started.fetch_add(1, Ordering::Release);
        Box::pin(async move {
            let _active = Active(self, cancellation);
            // The test owns this gate; there is no timer standing in for proof
            // that the handler was entered or its future was actually dropped.
            self.release.listen().await;
            self.finished.fetch_add(1, Ordering::Release);
            Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "controlled handler completed".to_owned(),
                retryable: false,
                details: Vec::new(),
            })
        })
    }

    fn cancel(
        &self,
        _command: CancellationCommand,
    ) -> BoxFuture<'_, Result<CancelDisposition, PlatformError>> {
        Box::pin(std::future::ready(Ok(CancelDisposition::NotFound)))
    }

    fn get_activation(
        &self,
        query: StatusQuery,
    ) -> BoxFuture<'_, Result<Option<ActivationStatus>, PlatformError>> {
        Box::pin(std::future::ready(Ok(Some(ActivationStatus {
            activation_id: query.activation_id,
            phase: ActivationPhase::Running,
            terminal_state: None,
            terminal_outcome: None,
            final_consumption: None,
            last_updated_unix_millis: 1,
            terminal_at_unix_millis: None,
            metadata: Metadata::new(),
        }))))
    }
}

struct Active<'a>(&'a Runtime, InvocationCancellation);
impl Drop for Active<'_> {
    fn drop(&mut self) {
        if self.1.cause().is_some() {
            self.0.cancelled.fetch_add(1, Ordering::Release);
        }
        self.0.dropped.fetch_add(1, Ordering::Release);
    }
}

pub(super) async fn start(config: TransportConfig, control: Handle) -> (Transport, Arc<Runtime>) {
    let runtime = Arc::new(Runtime::default());
    let adapter =
        InvocationServiceAdapter::new(Arc::clone(&runtime), InvocationLimits::default()).unwrap();
    let transport = Transport::start_routes(
        config,
        tonic::service::Routes::new(adapter.into_server()),
        Arc::new(SystemActivationClock),
        control,
    )
    .await
    .unwrap();
    transport.handle().start_accepting().unwrap();
    (transport, runtime)
}

pub(super) async fn client(transport: &Transport) -> Client {
    Client::connect(format!("http://{}", transport.local_addr()))
        .await
        .unwrap()
}

pub(super) fn authenticated<T>(message: T) -> tonic::Request<T> {
    let mut request = tonic::Request::new(message);
    request
        .metadata_mut()
        .insert("authorization", format!("Bearer {TOKEN}").parse().unwrap());
    request
}

pub(super) async fn status(client: &mut Client) -> Result<proto::ActivationStatus, tonic::Status> {
    client
        .get_activation(authenticated(proto::GetActivationRequest {
            activation_id: "observed".to_owned(),
        }))
        .await
        .map(tonic::Response::into_inner)
}

pub(super) fn invocation() -> tonic::Request<proto::InvokeRequest> {
    authenticated(proto::InvokeRequest {
        activation_id: Some("connection-owned".to_owned()),
        target: Some(proto::InvocationTarget {
            tenant: "acme".to_owned(),
            service: "echo".to_owned(),
            contract: "test:echo/api@1.0.0".to_owned(),
            function: "echo".to_owned(),
            route: None,
        }),
        budget: Some(proto::ResourceBudget {
            cpu_fuel: 1000,
            memory_bytes: 65_536,
            ..proto::ResourceBudget::default()
        }),
        payload: vec![1],
        media_type: "application/octet-stream".to_owned(),
        ..proto::InvokeRequest::default()
    })
}

pub(super) async fn until(mut predicate: impl FnMut() -> bool) {
    tokio::time::timeout(Duration::from_secs(3), async {
        while !predicate() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("bounded transport state transition");
}
