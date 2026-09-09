use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll};
use std::time::Duration;

use http_body::{Body as HttpBody, Frame, SizeHint};
use latent_core::{DeadlineDiagnosticObservation, DeadlineDiagnosticObserver};
use latent_wire::invocation::InvocationServiceClient;
use serde_json::{json, Value};
use tokio::sync::oneshot;
use tonic::body::Body;
use tonic::codegen::{
    http::{Request, Response},
    Bytes,
};
use tonic::transport::Channel;
use tower::Service;

use super::{call, cold::call::Clock, Result};

pub(super) async fn invoke(
    channel: Channel,
    clock: Clock,
    offer: call::Offer,
    observer: &DeadlineDiagnosticObserver,
) -> Result<Value> {
    let before = observer.snapshot().identities.len();
    let (request, row) = call::request(&offer, clock)?;
    let (release, ready) = oneshot::channel();
    let service = DelayedChannel {
        channel,
        ready: Arc::new(Mutex::new(Some(ready))),
    };
    let mut client = InvocationServiceClient::new(service);
    let future = client.invoke(request);
    tokio::pin!(future);
    // Poll the real request while waiting for the authenticated ingress witness.
    let ingress = async {
        for _ in 0..128 {
            let snapshot = observer.snapshot();
            if let Some(identity) = snapshot.identities.get(before) {
                let record = snapshot
                    .records
                    .iter()
                    .find(|record| {
                        record.token == identity.token
                            && matches!(
                                record.observation,
                                DeadlineDiagnosticObservation::Ingress { .. }
                            )
                    })
                    .ok_or("missing ingress record")?;
                if let DeadlineDiagnosticObservation::Ingress {
                    expires_at: Some(expiry),
                    ..
                } = record.observation
                {
                    return Ok::<_, Box<dyn std::error::Error + Send + Sync>>((
                        identity.token,
                        expiry,
                    ));
                }
                return Err("missing ingress expiry".into());
            }
            tokio::time::sleep(Duration::from_millis(1)).await;
        }
        Err("delayed body never reached authenticated ingress".into())
    };
    tokio::pin!(ingress);
    let mut early = None;
    let mut row = Some(row);
    let (token, expiry) = tokio::select! {
        result = &mut ingress => result?,
        result = &mut future => { early = Some(call::response(&offer,clock,row.take().expect("one response"),result)); ingress.await? }
    };
    let intended = expiry
        .checked_add(Duration::from_millis(1))
        .ok_or("body release instant overflow")?;
    let gate_time = tokio::time::sleep_until(tokio::time::Instant::from_std(intended));
    tokio::pin!(gate_time);
    if early.is_none() {
        // Keep observing the real RPC while the body is held. Otherwise a
        // transport timeout could arrive early but be recorded only at release.
        tokio::select! {
            biased;
            result = &mut future => {
                early = Some(call::response(&offer,clock,row.take().expect("one response"),result));
                gate_time.await;
            }
            () = &mut gate_time => {}
        }
    } else {
        gate_time.await;
    }
    let released = clock.elapsed();
    let delivered = release.send(()).is_ok();
    let completed_before_release = early.is_some();
    let mut row = match early {
        Some(row) => row,
        None => call::response(
            &offer,
            clock,
            row.take().expect("one response"),
            future.await,
        ),
    };
    row["diagnostic_token"] = json!(token.id().to_string());
    row["body_gate"] = json!({"ingress_token":token.id().to_string(),
        "intended_release_nanos":intended.checked_duration_since(clock.origin).ok_or("body release before origin")?.as_nanos().to_string(),
        "released_nanos":released.to_string(),"release_delivered":delivered,"response_before_release":completed_before_release});
    Ok(row)
}

#[derive(Clone)]
struct DelayedChannel {
    channel: Channel,
    ready: Arc<Mutex<Option<oneshot::Receiver<()>>>>,
}
impl Service<Request<Body>> for DelayedChannel {
    type Response = Response<Body>;
    type Error = tonic::transport::Error;
    type Future = <Channel as Service<Request<Body>>>::Future;
    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<std::result::Result<(), Self::Error>> {
        self.channel.poll_ready(cx)
    }
    fn call(&mut self, request: Request<Body>) -> Self::Future {
        let ready = self
            .ready
            .lock()
            .expect("body gate mutex")
            .take()
            .expect("one body request");
        self.channel.call(request.map(|body| {
            Body::new(DelayedBody {
                inner: Box::pin(body),
                ready: Some(ready),
            })
        }))
    }
}
struct DelayedBody {
    inner: Pin<Box<Body>>,
    ready: Option<oneshot::Receiver<()>>,
}
impl HttpBody for DelayedBody {
    type Data = Bytes;
    type Error = tonic::Status;
    fn poll_frame(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Option<std::result::Result<Frame<Bytes>, Self::Error>>> {
        if let Some(ready) = &mut self.ready {
            match Pin::new(ready).poll(cx) {
                Poll::Pending => return Poll::Pending,
                Poll::Ready(Err(_)) => {
                    return Poll::Ready(Some(Err(tonic::Status::cancelled(
                        "diagnostic body gate dropped",
                    ))))
                }
                Poll::Ready(Ok(())) => self.ready = None,
            }
        }
        self.inner.as_mut().poll_frame(cx)
    }
    fn size_hint(&self) -> SizeHint {
        self.inner.size_hint()
    }
}
