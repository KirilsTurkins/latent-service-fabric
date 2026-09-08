use std::io::{self, Write};
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::Duration;

use latent_rpc::invocation::v1::invocation_service_server::InvocationServiceServer;
use tokio::net::{TcpListener, TcpStream};
use tonic::codegen::tokio_stream::Stream;

use super::command::{Args, MAXIMUM_MESSAGE_BYTES};
use super::service::NativeService;

struct Incoming(TcpListener);
impl Stream for Incoming {
    type Item = io::Result<TcpStream>;
    fn poll_next(self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        self.0.poll_accept(context).map(|result| {
            Some(result.and_then(|(stream, _)| {
                stream.set_nodelay(true)?;
                Ok(stream)
            }))
        })
    }
}

pub(super) async fn run(args: Args) -> Result<(), ()> {
    let listener = TcpListener::bind(args.listen).await.map_err(|_| ())?;
    let address = listener.local_addr().map_err(|_| ())?;
    #[cfg(unix)]
    let mut terminate = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
        .map_err(|_| ())?;
    let service = NativeService::new(&args);
    let (stop, stopped) = tokio::sync::oneshot::channel::<()>();
    let server = tonic::transport::Server::builder()
        .concurrency_limit_per_connection(args.concurrency)
        .max_concurrent_streams(Some(32))
        .http2_max_header_list_size(16 * 1024)
        .timeout(Duration::from_millis(args.timeout_ms))
        .add_service(
            InvocationServiceServer::new(service)
                .max_decoding_message_size(MAXIMUM_MESSAGE_BYTES)
                .max_encoding_message_size(MAXIMUM_MESSAGE_BYTES),
        )
        .serve_with_incoming_shutdown(Incoming(listener), async {
            let _ = stopped.await;
        });
    tokio::pin!(server);
    println!(
        "{}",
        serde_json::json!({"event":"ready","address":format!("http://{address}"),"implementation":"native-reference"})
    );
    io::stdout().flush().map_err(|_| ())?;
    #[cfg(unix)]
    let signal = async {
        tokio::select! {
            result = tokio::signal::ctrl_c() => result.map_err(|_| ()),
            received = terminate.recv() => received.ok_or(()),
        }
    };
    #[cfg(not(unix))]
    let signal = async { tokio::signal::ctrl_c().await.map_err(|_| ()) };
    tokio::pin!(signal);
    tokio::select! {
        result = &mut server => result.map_err(|_| ())?,
        result = &mut signal => {
            result?;
            let _ = stop.send(());
            tokio::time::timeout(Duration::from_secs(5), &mut server)
                .await.map_err(|_| ())?.map_err(|_| ())?;
        }
    }
    println!(
        "{}",
        serde_json::json!({"event":"stopped","clean":true,"implementation":"native-reference"})
    );
    io::stdout().flush().map_err(|_| ())
}
