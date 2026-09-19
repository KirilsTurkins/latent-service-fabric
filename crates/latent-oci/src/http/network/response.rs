use super::owned::{Driver, Lease};
use bytes::Bytes;
use http_body::{Body, Frame, SizeHint};
use hyper::body::Incoming;
use std::{
    future::Future,
    pin::Pin,
    task::{Context, Poll},
};
use tokio::time::{sleep_until, Instant, Sleep};

pub(super) struct OwnedBody {
    incoming: Incoming,
    driver: Option<Driver>,
    deadline: Pin<Box<Sleep>>,
    _lease: Lease,
    finished: bool,
    frames: usize,
}

#[derive(Debug)]
pub(super) enum BodyFailure {
    Deadline,
    Connection,
    Frames,
}

impl std::fmt::Display for BodyFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(match self {
            Self::Deadline => "oci-body-deadline",
            Self::Connection => "oci-body-connection-failed",
            Self::Frames => "oci-body-frame-limit",
        })
    }
}

impl std::error::Error for BodyFailure {}

impl OwnedBody {
    pub(super) fn new(incoming: Incoming, driver: Driver, lease: Lease, deadline: Instant) -> Self {
        Self {
            incoming,
            driver: Some(driver),
            deadline: Box::pin(sleep_until(deadline)),
            _lease: lease,
            finished: false,
            frames: 0,
        }
    }
}

impl Body for OwnedBody {
    type Data = Bytes;
    type Error = BodyFailure;

    fn poll_frame(
        self: Pin<&mut Self>,
        context: &mut Context<'_>,
    ) -> Poll<Option<std::result::Result<Frame<Bytes>, Self::Error>>> {
        let body = self.get_mut();
        if body.finished {
            return Poll::Ready(None);
        }
        if body.deadline.as_mut().poll(context).is_ready() {
            body.finished = true;
            body.driver = None;
            return Poll::Ready(Some(Err(BodyFailure::Deadline)));
        }
        let mut frame = Pin::new(&mut body.incoming).poll_frame(context);
        if frame.is_pending() {
            if let Some(driver) = &mut body.driver {
                if Pin::new(driver).poll(context).is_ready() {
                    body.driver = None;
                }
            }
            frame = Pin::new(&mut body.incoming).poll_frame(context);
            if frame.is_pending() && body.driver.is_none() {
                body.finished = true;
                return Poll::Ready(Some(Err(BodyFailure::Connection)));
            }
        }
        match frame {
            Poll::Ready(Some(Ok(frame))) => {
                body.frames += 1;
                if body.frames > 65536 || frame.is_trailers() {
                    body.finished = true;
                    body.driver = None;
                    Poll::Ready(Some(Err(BodyFailure::Frames)))
                } else {
                    Poll::Ready(Some(Ok(frame)))
                }
            }
            Poll::Ready(Some(Err(_))) => {
                body.finished = true;
                body.driver = None;
                Poll::Ready(Some(Err(BodyFailure::Connection)))
            }
            Poll::Ready(None) => {
                body.finished = true;
                body.driver = None;
                Poll::Ready(None)
            }
            Poll::Pending => Poll::Pending,
        }
    }

    fn is_end_stream(&self) -> bool {
        self.finished
    }

    fn size_hint(&self) -> SizeHint {
        self.incoming.size_hint()
    }
}
