//! A single supervised upload initiator and cleanup owner per registry client.
//!
//! Each operation occupies one queued command or one reserved cleanup slot.
//! Reserving the slot before POST makes `Session::drop` infallibly enqueue DELETE;
//! the task never keeps a permanent Sender back to its own receiver.

use super::{transport::expect_status, Operation, Result, Transport};
use crate::error;
use latent_core::PlatformErrorCode;
use reqwest::{header::LOCATION, Method, StatusCode, Url};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use tokio::{
    runtime::Handle,
    sync::{mpsc, oneshot},
    task::JoinHandle,
    time::{timeout_at, Instant},
};

#[derive(Clone)]
pub(crate) struct UploadWorker {
    state: Arc<State>,
}

struct State {
    sender: Mutex<Option<mpsc::Sender<Command>>>,
    task: tokio::sync::Mutex<Option<JoinHandle<()>>>,
    cleanup_failed: Arc<AtomicBool>,
}

enum Command {
    Start {
        operation: Operation,
        cleanup_sender: mpsc::Sender<Self>,
        response: oneshot::Sender<Result<Session>>,
    },
    Delete {
        location: Url,
        operation: Operation,
    },
}

pub(super) struct Session {
    location: Url,
    operation: Option<Operation>,
    cleanup: Option<mpsc::OwnedPermit<Command>>,
}

impl Session {
    pub(super) fn location(&self) -> &Url {
        &self.location
    }

    pub(super) fn deadline(&self) -> Instant {
        self.operation
            .as_ref()
            .expect("live upload operation")
            .deadline
    }

    pub(super) fn complete(mut self) -> Operation {
        self.cleanup.take();
        self.operation.take().expect("live upload operation")
    }
}

impl Drop for Session {
    fn drop(&mut self) {
        if let (Some(cleanup), Some(operation)) = (self.cleanup.take(), self.operation.take()) {
            cleanup.send(Command::Delete {
                location: self.location.clone(),
                operation,
            });
        }
    }
}

impl UploadWorker {
    pub(crate) fn new(transport: Arc<Transport>, handle: &Handle) -> Self {
        let (sender, receiver) = mpsc::channel(transport.limits.max_in_flight);
        let cleanup_failed = Arc::new(AtomicBool::new(false));
        let task = handle.spawn(run(transport, receiver, cleanup_failed.clone()));
        Self {
            state: Arc::new(State {
                sender: Mutex::new(Some(sender)),
                task: tokio::sync::Mutex::new(Some(task)),
                cleanup_failed,
            }),
        }
    }

    pub(super) async fn start(&self, operation: Operation) -> Result<Session> {
        let deadline = operation.deadline;
        let sender = self
            .state
            .sender
            .lock()
            .map_err(|_| failure("oci-upload-worker-lock"))?
            .as_ref()
            .cloned()
            .ok_or_else(|| failure("oci-upload-worker-closed"))?;
        let (response, receiver) = oneshot::channel();
        // The acquired operation is not already queued or reserved. Therefore
        // its slot is free; no caller or Drop path waits for queue capacity.
        sender
            .try_send(Command::Start {
                operation,
                cleanup_sender: sender.clone(),
                response,
            })
            .map_err(|_| failure("oci-upload-worker-unavailable"))?;
        timeout_at(deadline, receiver)
            .await
            .map_err(|_| deadline_error())?
            .map_err(|_| failure("oci-upload-worker-unavailable"))?
    }

    pub(crate) async fn shutdown(&self, deadline: Instant) -> Result<()> {
        self.state
            .sender
            .lock()
            .map_err(|_| failure("oci-upload-worker-lock"))?
            .take();
        let mut task = timeout_at(deadline, self.state.task.lock())
            .await
            .map_err(|_| deadline_error())?;
        if let Some(handle) = task.as_mut() {
            let result = timeout_at(deadline, handle)
                .await
                .map_err(|_| deadline_error())?;
            task.take();
            if result.is_err() {
                self.state.cleanup_failed.store(true, Ordering::Release);
                return Err(failure("oci-upload-worker-failed"));
            }
        }
        if self.state.cleanup_failed.load(Ordering::Acquire) {
            return Err(failure("oci-upload-cleanup-failed"));
        }
        Ok(())
    }
}

async fn run(
    transport: Arc<Transport>,
    mut receiver: mpsc::Receiver<Command>,
    cleanup_failed: Arc<AtomicBool>,
) {
    while let Some(command) = receiver.recv().await {
        match command {
            Command::Start {
                operation,
                cleanup_sender,
                response,
            } => {
                if response.is_closed() {
                    continue;
                }
                let result = initiate(&transport, operation, cleanup_sender).await;
                // If cancellation wins the handoff, dropping the returned
                // Session queues DELETE and keeps its Operation lease alive.
                let _ = response.send(result);
            }
            Command::Delete {
                location,
                operation,
            } => {
                if cleanup(&transport, location).await.is_err() {
                    cleanup_failed.store(true, Ordering::Release);
                }
                drop(operation);
            }
        }
    }
}

async fn initiate(
    transport: &Transport,
    operation: Operation,
    cleanup_sender: mpsc::Sender<Command>,
) -> Result<Session> {
    let cleanup = timeout_at(operation.deadline, cleanup_sender.reserve_owned())
        .await
        .map_err(|_| deadline_error())?
        .map_err(|_| failure("oci-upload-worker-closed"))?;
    let response = transport
        .send(
            Method::POST,
            transport.endpoint.url("blobs/uploads/")?,
            Some(bytes::Bytes::new()),
            None,
            operation.deadline,
        )
        .await?;
    expect_status(&response, &[StatusCode::ACCEPTED])?;
    let raw = response
        .headers()
        .get(LOCATION)
        .and_then(|value| value.to_str().ok())
        .ok_or_else(|| failure("oci-upload-location-missing"))?;
    let prefix = format!("/v2/{}/blobs/uploads/", transport.endpoint.repository);
    let location = transport.endpoint.scoped_url(raw, &prefix)?;
    if location.path() == prefix {
        return Err(failure("oci-upload-location-invalid"));
    }
    let session = Session {
        location,
        operation: Some(operation),
        cleanup: Some(cleanup),
    };
    if session
        .location
        .query_pairs()
        .any(|(name, _)| name == "digest")
    {
        // The scoped session is safe to delete even though its upload query is
        // ambiguous. Keep cleanup ownership while rejecting the PUT target.
        return Err(failure("oci-upload-location-invalid"));
    }
    Ok(session)
}

async fn cleanup(transport: &Transport, location: Url) -> Result<()> {
    let response = transport
        .send(
            Method::DELETE,
            location,
            None,
            None,
            Instant::now() + transport.limits.cleanup_timeout,
        )
        .await?;
    expect_status(&response, &[StatusCode::NO_CONTENT, StatusCode::NOT_FOUND])
}

fn failure(reason: &'static str) -> latent_core::PlatformError {
    error(PlatformErrorCode::Unavailable, reason)
}

fn deadline_error() -> latent_core::PlatformError {
    error(PlatformErrorCode::DeadlineExceeded, "oci-upload-deadline")
}
