use super::{state::Signal, HttpHandle, HttpServices, HttpSettings, Shared};
use std::{
    net::SocketAddr,
    sync::{atomic::Ordering, Arc},
};
use tokio::{
    net::TcpListener,
    task::{JoinHandle, JoinSet},
    time::Instant,
};

pub(crate) struct HttpOwner {
    task: Option<JoinHandle<()>>,
    handle: HttpHandle,
    address: SocketAddr,
}
impl HttpOwner {
    pub(crate) fn start(
        settings: HttpSettings,
        services: HttpServices,
    ) -> Result<Self, latent_core::PlatformError> {
        // Configure finite backlog as well as accepted owners. No authority is
        // granted by sitting in the OS backlog; pre-auth deadlines start on accept.
        let socket = if settings.bind.is_ipv4() {
            tokio::net::TcpSocket::new_v4()
        } else {
            tokio::net::TcpSocket::new_v6()
        }
        .map_err(|_| super::failure())?;
        // Set inherited buffers before listen/TCP window negotiation. Shrinking
        // an accepted socket can stall a body already sent against its previous
        // advertised receive window. Kernel rounding is a separate OS charge.
        socket
            .set_recv_buffer_size(64 * 1024)
            .map_err(|_| super::failure())?;
        socket
            .set_send_buffer_size(16 * 1024)
            .map_err(|_| super::failure())?;
        socket.bind(settings.bind).map_err(|_| super::failure())?;
        let listener = socket
            .listen(
                u32::try_from(settings.limits.maximum_connections).map_err(|_| super::failure())?,
            )
            .map_err(|_| super::failure())?;
        let address = listener.local_addr().map_err(|_| super::failure())?;
        let handle = HttpHandle::new(&settings)?;
        let shared = Arc::new(Shared {
            settings,
            services,
            handle: handle.clone(),
            traces: latent_wire::invocation::SystemInvocationTraceSource::default(),
        });
        // A constructed guard owns the socket even if the task is never polled.
        let driver = Driver {
            listener: Some(listener),
            tasks: JoinSet::new(),
            shared,
        };
        let task = tokio::spawn(driver.run());
        Ok(Self {
            task: Some(task),
            handle,
            address,
        })
    }
    pub(crate) fn local_addr(&self) -> SocketAddr {
        self.address
    }
    pub(crate) fn handle(&self) -> HttpHandle {
        self.handle.clone()
    }
    pub(crate) fn is_finished(&self) -> bool {
        self.task
            .as_ref()
            .is_none_or(tokio::task::JoinHandle::is_finished)
    }
    pub(crate) async fn shutdown(
        mut self,
        deadline: Instant,
    ) -> Result<(), latent_core::PlatformError> {
        self.handle.signal(Signal::Forced);
        let task = self.task.as_mut().expect("owned HTTP driver");
        if !matches!(
            tokio::time::timeout_at(deadline, &mut *task).await,
            Ok(Ok(()))
        ) {
            self.handle.0.failed.store(true, Ordering::Release);
            task.abort();
            let _ = task.await;
        }
        self.task.take();
        let assets_joined = match self.handle.0.assets.get() {
            Some(assets) => assets.shutdown(deadline).await,
            None => true,
        };
        if !assets_joined {
            self.handle.0.failed.store(true, Ordering::Release);
        }
        self.handle.0.joined.store(assets_joined, Ordering::Release);
        if self.handle.0.failed.load(Ordering::Acquire) {
            Err(super::failure())
        } else {
            Ok(())
        }
    }
}
impl Drop for HttpOwner {
    fn drop(&mut self) {
        if let Some(task) = self.task.take() {
            self.handle.signal(Signal::Forced);
            self.handle.0.failed.store(true, Ordering::Release);
            task.abort();
        }
    }
}
struct Driver {
    listener: Option<TcpListener>,
    tasks: JoinSet<()>,
    shared: Arc<Shared>,
}
impl Driver {
    async fn run(mut self) {
        loop {
            if *self.shared.handle.0.signal.borrow() >= Signal::Draining {
                self.listener.take();
                self.shared
                    .handle
                    .0
                    .listener_alive
                    .store(false, Ordering::Release);
            }
            if self.listener.is_none() && self.tasks.is_empty() {
                break;
            }
            tokio::select! {
                biased;
                joined = self.tasks.join_next(), if !self.tasks.is_empty() => {
                    if joined.is_some_and(|r| r.is_err()) {
                        self.shared.handle.0.failed.store(true, Ordering::Release);
                        self.shared.handle.signal(Signal::Forced);
                    }
                }
                () = self.shared.handle.stopped(Signal::Draining), if self.listener.is_some() => {}
                accepted = async { self.listener.as_ref().expect("live listener").accept().await }, if self.listener.is_some() => {
                    if let Ok((socket, peer)) = accepted {
                        if self.tasks.len() >= self.shared.settings.limits.maximum_connections { drop(socket); continue; }
                        let Some(permit) = self.shared.handle.reserve() else { drop(socket); continue; };
                        let shared = self.shared.clone();
                        self.tasks.spawn(super::connection::run(socket, peer, permit, shared));
                    } else {
                        self.shared.handle.0.failed.store(true, Ordering::Release);
                        self.shared.handle.signal(Signal::Forced);
                    }
                }
            }
        }
    }
}
impl Drop for Driver {
    fn drop(&mut self) {
        self.listener.take();
        self.shared
            .handle
            .0
            .listener_alive
            .store(false, Ordering::Release);
        self.shared
            .handle
            .0
            .owner_alive
            .store(false, Ordering::Release);
    }
}
