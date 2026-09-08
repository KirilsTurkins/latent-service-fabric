mod support;

use std::sync::atomic::Ordering;
use std::time::Instant;

use latent_core::{ActivationClock, ClockSample};
use latent_wire::invocation::{
    proto, InvocationLimits, InvocationServiceAdapter, InvocationServiceServices,
};

use super::*;
use support::{Clock, DelayedChannel, Runtime};

#[test]
fn delayed_unary_body_keeps_arrival_deadline_and_expiry_drop_cause() {
    run(|control| async move {
        for already_expired in [false, true] {
            let arrival = Instant::now();
            let clock = Arc::new(Clock(std::sync::Mutex::new(ClockSample::new(
                10_000, arrival,
            ))));
            let runtime = Arc::new(Runtime::default());
            let adapter = InvocationServiceAdapter::with_services(
                Arc::clone(&runtime),
                InvocationLimits::default(),
                InvocationServiceServices {
                    clock: clock.clone(),
                    ..InvocationServiceServices::default()
                },
            )
            .unwrap();
            let routes = tonic::service::Routes::new(adapter.into_server());
            let transport =
                Transport::start_routes(configuration(), routes, clock.clone(), control.clone())
                    .await
                    .unwrap();
            transport.handle().start_accepting().unwrap();
            let gate = Arc::new(signal::Signal::default());
            let channel = tonic::transport::Endpoint::from_shared(format!(
                "http://{}",
                transport.local_addr()
            ))
            .unwrap()
            .connect()
            .await
            .unwrap();
            let mut client =
                proto::invocation_service_client::InvocationServiceClient::new(DelayedChannel {
                    channel,
                    gate: Arc::clone(&gate),
                });
            let mut request = tonic::Request::new(message());
            request
                .metadata_mut()
                .insert("authorization", format!("Bearer {TOKEN}").parse().unwrap());
            request.set_timeout(Duration::from_millis(500));
            let mut invocation = Box::pin(client.invoke(request));
            std::future::poll_fn(|cx| {
                assert!(invocation.as_mut().poll(cx).is_pending());
                std::task::Poll::Ready(())
            })
            .await;
            while transport.handle().snapshot().active_rpcs != 1 {
                tokio::task::yield_now().await;
            }
            assert_eq!(runtime.started.load(Ordering::Acquire), 0);
            // A real delayed DATA body makes an incorrectly restarted relative
            // timer strictly later than Tonic's header timer, beyond tick rounding.
            tokio::time::sleep(Duration::from_millis(20)).await;
            let elapsed = if already_expired {
                Duration::from_millis(500)
            } else {
                Duration::from_millis(499)
            };
            *clock.0.lock().unwrap() = ClockSample::new(1000, arrival + elapsed);
            gate.trigger();
            assert_eq!(
                invocation.as_mut().await.unwrap_err().code(),
                tonic::Code::DeadlineExceeded
            );
            drop(invocation);
            assert_eq!(
                runtime.started.load(Ordering::Acquire),
                usize::from(!already_expired)
            );
            assert_eq!(
                runtime.dropped.load(Ordering::Acquire),
                if already_expired { 0 } else { 2 }
            );
            assert_eq!(clock.sample().unix_millis(), 1000);
            drop(client);
            let snapshot = transport.shutdown().await.unwrap();
            assert_eq!(snapshot.active_rpcs, 0);
        }
    });
}

fn message() -> proto::InvokeRequest {
    proto::InvokeRequest {
        activation_id: Some("deadline-owned".to_owned()),
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
    }
}
