//! Executes the selected Exchange source with explicit native host/owner doubles.
//! This is not a component, network, or original-ledger qualification.
#![allow(dead_code)]

mod latent {
    pub mod runtime {
        pub mod activation {
            #[derive(Debug)]
            pub struct Error;
            pub enum OwnerKind {
                Task,
            }
        }
    }
    pub mod http {
        pub mod streaming {
            use std::{cell::Cell, future::poll_fn, task::Poll};
            #[derive(Clone, Copy, Debug, Eq, PartialEq)]
            pub enum HttpError {
                InvalidState,
                RequestTooLarge,
                Uncertain,
                ResponseTooLarge,
                InvalidRequest,
                Cancelled,
            }
            pub struct Request {
                pub body_length: Option<u64>,
            }
            pub struct Upload;
            pub struct Body;
            pub struct Chunk;
            pub struct Header {
                pub name: String,
                pub value: String,
            }
            pub struct Response {
                pub status: u16,
                pub headers: Vec<Header>,
                pub body: Body,
            }
            thread_local! { static WRITE_READY: Cell<bool> = const { Cell::new(false) }; }
            pub fn set_write_ready(value: bool) {
                WRITE_READY.with(|ready| ready.set(value));
            }
            pub async fn open(_: Request) -> Result<Upload, HttpError> {
                Ok(Upload)
            }
            pub async fn write(_: &Upload, _: Vec<u8>) -> Result<(), HttpError> {
                poll_fn(|_| {
                    if WRITE_READY.with(Cell::get) {
                        Poll::Ready(Ok(()))
                    } else {
                        Poll::Pending
                    }
                })
                .await
            }
            pub async fn finish(_: Upload) -> Result<Response, HttpError> {
                std::future::pending().await
            }
            pub async fn read(_: &Body, _: u32) -> Result<Option<Chunk>, HttpError> {
                std::future::pending().await
            }
            pub async fn chunk_bytes(_: &Chunk) -> Result<Vec<u8>, HttpError> {
                std::future::pending().await
            }
            pub async fn trailers(_: &Body) -> Result<Vec<Header>, HttpError> {
                std::future::pending().await
            }
        }
    }
}
mod owner {
    use super::latent::runtime::activation;
    use std::cell::Cell;
    thread_local! { static LIVE: Cell<usize> = const { Cell::new(0) }; }
    pub struct Owner;
    impl Owner {
        pub fn new(_: activation::OwnerKind) -> Result<Self, activation::Error> {
            LIVE.with(|live| live.set(live.get() + 1));
            Ok(Self)
        }
    }
    impl Drop for Owner {
        fn drop(&mut self) {
            LIVE.with(|live| live.set(live.get().checked_sub(1).unwrap()));
        }
    }
    pub fn live() -> usize {
        LIVE.with(Cell::get)
    }
}
mod pump {
    use std::{cell::RefCell, rc::Rc, task::Context};
    pub trait Progress {
        fn pending(&self) -> bool;
        fn progress(&self, context: &mut Context<'_>);
    }
    pub struct Pump;
    thread_local! { static RETIRED: RefCell<Vec<Box<dyn FnOnce()>>> = RefCell::new(Vec::new()); }
    impl Pump {
        pub fn track(_: &Rc<dyn Progress>) {}
        pub fn current() -> Rc<Self> {
            Rc::new(Self)
        }
        pub fn step(&self) {}
        pub fn retire(action: impl FnOnce() + 'static) {
            RETIRED.with(|retired| retired.borrow_mut().push(Box::new(action)));
        }
    }
    pub fn retained() -> usize {
        RETIRED.with(|retired| retired.borrow().len())
    }
    pub fn drain() {
        while let Some(action) = RETIRED.with(|retired| retired.borrow_mut().pop()) {
            action();
        }
    }
}
#[path = "../../../sdk/wasi-http-runtime/fields.rs"]
mod fields;
#[path = "../../../sdk/wasi-http-runtime/limits.rs"]
mod limits;
#[path = "../../../sdk/dotnet-guest/runtime/http/quota.rs"]
mod quota;
#[path = "../../../sdk/wasi-http-runtime/retirement.rs"]
mod retirement;
#[path = "../../../sdk/wasi-http-runtime/state.rs"]
mod state;

#[cfg(test)]
mod tests {
    use super::{fields::Fields, latent::http::streaming as raw, owner, pump, state::Exchange};
    use std::{
        rc::Rc,
        task::{Context, Waker},
    };

    fn exchange(length: Option<u64>) -> Rc<Exchange> {
        let entries = length
            .map(|value| vec![("Content-Length".into(), value.to_string().into_bytes())])
            .unwrap_or_default();
        let headers = Fields::from_list(entries).unwrap().into_parent();
        let exchange = Exchange::new();
        exchange.body_requested.set(true);
        exchange.set_expected_length(headers.content_length().unwrap());
        exchange
    }
    fn advance(exchange: &Rc<Exchange>) {
        pump::Progress::progress(exchange.as_ref(), &mut Context::from_waker(Waker::noop()));
    }

    #[test]
    fn mismatch_before_handle_fails_without_admitting_work() {
        let exchange = exchange(Some(3));
        exchange.queue(vec![1, 2]).unwrap();
        assert_eq!(
            exchange.finish_output(false),
            Err(raw::HttpError::InvalidRequest)
        );
        assert!(!exchange.output_finished.get());
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }

    #[test]
    fn mismatch_after_dispatch_retains_the_original_owner_until_deferred_drain() {
        let exchange = exchange(Some(3));
        exchange.queue(vec![1, 2]).unwrap();
        exchange
            .admit(raw::Request {
                body_length: Some(3),
            })
            .unwrap();
        raw::set_write_ready(false);
        advance(&exchange);
        assert_eq!(owner::live(), 1);
        assert_eq!(
            exchange.finish_output(false),
            Err(raw::HttpError::Uncertain)
        );
        assert_eq!((owner::live(), pump::retained()), (1, 1));
        pump::drain();
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }

    #[test]
    fn accepted_bytes_include_completed_and_pending_writes_without_early_refund() {
        let exchange = exchange(Some(4));
        exchange.queue(vec![1, 2]).unwrap();
        exchange
            .admit(raw::Request {
                body_length: Some(4),
            })
            .unwrap();
        raw::set_write_ready(true);
        advance(&exchange);
        exchange.queue(vec![3, 4]).unwrap();
        raw::set_write_ready(false);
        advance(&exchange);
        assert_eq!(exchange.finish_output(false), Ok(()));
        assert!(exchange.output_finished.get());
        exchange.abort();
        assert_eq!((owner::live(), pump::retained()), (1, 1));
        pump::drain();
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }

    #[test]
    fn exact_pre_handle_and_unbounded_length_bodies_finish_normally() {
        for (length, bytes) in [(Some(0), vec![]), (Some(2), vec![1, 2]), (None, vec![1])] {
            let exchange = exchange(length);
            exchange.queue(bytes).unwrap();
            assert_eq!(exchange.finish_output(false), Ok(()));
            exchange
                .admit(raw::Request {
                    body_length: length,
                })
                .unwrap();
            assert!(exchange.output_finished.get());
            exchange.abort();
            pump::drain();
            assert_eq!((owner::live(), pump::retained()), (0, 0));
        }
    }

    #[test]
    fn pre_handle_overrun_fails_before_admission_and_remains_sticky() {
        let exchange = exchange(Some(1));
        assert_eq!(
            exchange.queue(vec![1, 2]),
            Err(raw::HttpError::RequestTooLarge)
        );
        assert_eq!(
            exchange.finish_output(false),
            Err(raw::HttpError::RequestTooLarge)
        );
        assert_eq!(
            exchange.finish_output(true),
            Err(raw::HttpError::RequestTooLarge)
        );
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }

    #[test]
    fn prequeued_bytes_cannot_finish_against_a_smaller_later_metadata_length() {
        // The real Request has immutable headers and normally detects this in
        // queue; this deliberately models a disagreeing later producer.
        let exchange = exchange(None);
        exchange.queue(vec![1, 2, 3]).unwrap();
        exchange
            .admit(raw::Request {
                body_length: Some(2),
            })
            .unwrap();
        assert_eq!(
            exchange.finish_output(false),
            Err(raw::HttpError::InvalidRequest)
        );
        assert_eq!((owner::live(), pump::retained()), (1, 1));
        pump::drain();
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }
}

// The owner supplies the exact method body extracted from types.rs. The
// canonical resource wrapper and host are explicit doubles, not a guest run.
#[cfg(lsf_exported_finish_control)]
mod exported_finish_wiring {
    use super::{latent::http::streaming as raw, owner, pump, state::Exchange};
    use std::{cell::Cell, rc::Rc};

    mod types {
        #[derive(Debug, PartialEq)]
        pub enum ErrorCode {
            Invalid,
            InternalError(Option<String>),
        }
        pub struct Trailers;
        pub struct OutgoingBody(pub super::OutgoingBody);
        impl OutgoingBody {
            pub fn into_inner<T: 'static>(self) -> T {
                *(Box::new(self.0) as Box<dyn std::any::Any>)
                    .downcast::<T>()
                    .ok()
                    .expect("outgoing body double")
            }
        }
    }
    fn error_code(_: raw::HttpError) -> types::ErrorCode {
        types::ErrorCode::Invalid
    }
    struct OutgoingBody {
        exchange: Rc<Exchange>,
        finished: Cell<bool>,
    }
    include!(env!("LSF_RUST_HTTP_FINISH_BODY"));
    impl Drop for OutgoingBody {
        fn drop(&mut self) {
            assert_eq!(self.exchange.output_views.get(), 0);
            if !self.finished.get() {
                self.exchange.abort();
            }
        }
    }
    #[test]
    fn exported_finish_refuses_short_body_and_keeps_the_owner() {
        let exchange = Exchange::new();
        exchange.body_requested.set(true);
        exchange.set_expected_length(Some(1));
        exchange
            .admit(raw::Request {
                body_length: Some(1),
            })
            .unwrap();
        let body = OutgoingBody {
            exchange: exchange.clone(),
            finished: Cell::new(false),
        };
        assert_eq!(
            OutgoingBody::finish(types::OutgoingBody(body), None),
            Err(types::ErrorCode::Invalid)
        );
        assert_eq!((owner::live(), pump::retained()), (1, 1));
        pump::drain();
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }
    #[test]
    fn exported_finish_accepts_exact_queued_body() {
        let exchange = Exchange::new();
        exchange.body_requested.set(true);
        exchange.set_expected_length(Some(1));
        exchange.queue(vec![7]).unwrap();
        exchange
            .admit(raw::Request {
                body_length: Some(1),
            })
            .unwrap();
        let body = OutgoingBody {
            exchange: exchange.clone(),
            finished: Cell::new(false),
        };
        assert_eq!(
            OutgoingBody::finish(types::OutgoingBody(body), None),
            Ok(())
        );
        assert!(exchange.output_finished.get());
        exchange.abort();
        pump::drain();
        assert_eq!((owner::live(), pump::retained()), (0, 0));
    }
}
