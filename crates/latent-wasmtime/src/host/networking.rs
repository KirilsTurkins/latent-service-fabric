//! Exact stream resources. Accepted futures retain physical owners without a
//! Store borrow, and completion may publish only into its original generation.
use super::{
    service::{checkpoint, synchronize},
    HostState,
};
use latent_capabilities::broker::network::{
    OutboundStreamInvoker, StreamConnectRequest, StreamError, StreamErrorCode, StreamInterest,
    StreamObservation, StreamShutdown, StreamState, STREAM_CAPABILITY,
};
use latent_component_bindings::host::activation::latent::network::streams as wit;
use latent_policy::capability::{StreamEndpoint, StreamTransport};
use std::{sync::Arc, time::Instant};
use wasmtime::{
    component::{Linker, Resource, ResourceType},
    AsContextMut,
};
pub(super) mod table;
use table::{Kind, Value};

pub(crate) fn install(
    linker: &mut Linker<HostState>,
    invoker: Arc<dyn OutboundStreamInvoker>,
) -> wasmtime::Result<()> {
    let mut host = linker.instance(STREAM_CAPABILITY)?;
    host.resource(
        "connection",
        ResourceType::host::<wit::Connection>(),
        |mut store, rep| {
            store
                .data_mut()
                .capabilities
                .network
                .remove(rep, Kind::Connection)
                .map_err(trap)
        },
    )?;
    host.resource(
        "chunk",
        ResourceType::host::<wit::Chunk>(),
        |mut store, rep| {
            store
                .data_mut()
                .capabilities
                .network
                .remove(rep, Kind::Chunk)
                .map_err(trap)
        },
    )?;
    connect(&mut host, invoker)?;
    read(&mut host)?;
    write(&mut host)?;
    ready(&mut host)?;
    shutdown(&mut host)?;
    close(&mut host)?;
    host.func_wrap(
        "inspect",
        |mut store, (target,): (Resource<wit::Connection>,)| {
            checkpoint(&mut store)?;
            let observation = store
                .data_mut()
                .capabilities
                .network
                .connection(target.rep())
                .map_err(trap)?
                .inspect();
            synchronize(&mut store)?;
            Ok((convert_observation(observation),))
        },
    )?;
    host.func_wrap_concurrent(
        "chunk-bytes",
        |access, (chunk,): (Resource<wit::Chunk>,)| {
            Box::pin(async move {
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store
                        .data_mut()
                        .capabilities
                        .network
                        .chunk_bytes(chunk.rep());
                    synchronize(&mut store)?;
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}

fn connect(
    host: &mut wasmtime::component::LinkerInstance<'_, HostState>,
    invoker: Arc<dyn OutboundStreamInvoker>,
) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "connect",
        move |access, (request,): (wit::ConnectRequest,)| {
            let invoker = Arc::clone(&invoker);
            Box::pin(async move {
                let started = Instant::now();
                let opening = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let capabilities = &mut store.data_mut().capabilities;
                        let session = capabilities
                            .session
                            .as_ref()
                            .ok_or_else(|| StreamError::new(StreamErrorCode::Denied))?;
                        capabilities.network.initialize(session)?;
                        let rep = capabilities.network.reserve(Kind::Connection)?;
                        let request = StreamConnectRequest {
                            endpoint: StreamEndpoint {
                                host: request.host,
                                port: request.port,
                                transport: match request.transport {
                                    wit::Transport::Tcp => StreamTransport::Tcp,
                                    wit::Transport::HostTls => StreamTransport::HostTls,
                                },
                            },
                            timeout_millis: request.timeout_millis,
                        };
                        match invoker.start(session, request) {
                            Ok(future) => Ok((rep, future)),
                            Err(error) => {
                                capabilities.network.remove(rep, Kind::Connection)?;
                                Err(error)
                            }
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let completion = match opening {
                    Ok((rep, future)) => Ok((rep, future.await)),
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = completion.and_then(|(rep, result)| {
                        let table = &mut store.data_mut().capabilities.network;
                        match result {
                            Ok(connection) => {
                                table.put(rep, Kind::Connection, Value::Connection(connection))?;
                                Ok(Resource::<wit::Connection>::new_own(rep))
                            }
                            Err(error) => {
                                table.remove(rep, Kind::Connection)?;
                                Err(error)
                            }
                        }
                    });
                    synchronize(&mut store)?;
                    store.data_mut().record_host_call(started);
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}
fn read(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "read",
        |access, (source, maximum, timeout): (Resource<wit::Connection>, u32, Option<u32>)| {
            Box::pin(async move {
                let opening = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = (|| {
                        let table = &mut store.data_mut().capabilities.network;
                        let rep = table.reserve(Kind::Chunk)?;
                        match table
                            .connection(source.rep())
                            .and_then(|connection| connection.read(maximum as usize, timeout))
                        {
                            Ok(future) => Ok((rep, future)),
                            Err(error) => {
                                table.remove(rep, Kind::Chunk)?;
                                Err(error)
                            }
                        }
                    })();
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let completion = match opening {
                    Ok((rep, future)) => Ok((rep, future.await)),
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = completion.and_then(|(rep, result)| {
                        let table = &mut store.data_mut().capabilities.network;
                        match result {
                            Ok(Some(value)) => {
                                table.put(
                                    rep,
                                    Kind::Chunk,
                                    Value::Chunk {
                                        value,
                                        delivered: false,
                                    },
                                )?;
                                Ok(Some(Resource::<wit::Chunk>::new_own(rep)))
                            }
                            other => {
                                table.remove(rep, Kind::Chunk)?;
                                other.map(|_| None)
                            }
                        }
                    });
                    synchronize(&mut store)?;
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}
fn write(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "write",
        |access, (target, bytes, timeout): (Resource<wit::Connection>, Vec<u8>, Option<u32>)| {
            Box::pin(async move {
                let opening = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store
                        .data_mut()
                        .capabilities
                        .network
                        .connection(target.rep())
                        .and_then(|value| value.write(bytes, timeout));
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match opening {
                    Ok(future) => future.await,
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    synchronize(&mut store)?;
                    Ok((result.map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}
fn ready(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent("ready", |access, (target, interest, timeout): (Resource<wit::Connection>, wit::Interest, Option<u32>)| Box::pin(async move {
        let interest = match interest { wit::Interest::Readable => StreamInterest::Readable, wit::Interest::Writable => StreamInterest::Writable, wit::Interest::Either => StreamInterest::Either };
        let opening = access.with(|mut access| { let mut store = access.as_context_mut(); checkpoint(&mut store)?;
            let result = store.data_mut().capabilities.network.connection(target.rep()).and_then(|value| value.ready(interest, timeout));
            synchronize(&mut store)?; Ok::<_, wasmtime::Error>(result)
        })?;
        let result = match opening { Ok(future) => future.await, Err(error) => Err(error) };
        access.with(|mut access| { let mut store = access.as_context_mut(); checkpoint(&mut store)?; synchronize(&mut store)?;
            Ok((result.map(|value| wit::Readiness { readable: value.readable, writable: value.writable }).map_err(convert_error),))
        })
    }))?;
    Ok(())
}
fn shutdown(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "shutdown",
        |access, (target, how): (Resource<wit::Connection>, wit::ShutdownMode)| {
            Box::pin(async move {
                let how = match how {
                    wit::ShutdownMode::Send => StreamShutdown::Send,
                    wit::ShutdownMode::Receive => StreamShutdown::Receive,
                    wit::ShutdownMode::Both => StreamShutdown::Both,
                };
                let opening = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store
                        .data_mut()
                        .capabilities
                        .network
                        .connection(target.rep())
                        .and_then(|value| value.shutdown(how));
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match opening {
                    Ok(future) => future.await,
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    synchronize(&mut store)?;
                    Ok((result.map(convert_observation).map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}
fn close(host: &mut wasmtime::component::LinkerInstance<'_, HostState>) -> wasmtime::Result<()> {
    host.func_wrap_concurrent(
        "close",
        |access, (target,): (Resource<wit::Connection>,)| {
            Box::pin(async move {
                let opening = access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    let result = store
                        .data_mut()
                        .capabilities
                        .network
                        .take_connection(target.rep())
                        .map(|value| value.close());
                    synchronize(&mut store)?;
                    Ok::<_, wasmtime::Error>(result)
                })?;
                let result = match opening {
                    Ok(future) => future.await,
                    Err(error) => Err(error),
                };
                access.with(|mut access| {
                    let mut store = access.as_context_mut();
                    checkpoint(&mut store)?;
                    synchronize(&mut store)?;
                    Ok((result.map(convert_observation).map_err(convert_error),))
                })
            })
        },
    )?;
    Ok(())
}
fn trap(_: StreamError) -> wasmtime::Error {
    wasmtime::Error::msg("invalid outbound stream resource")
}
fn convert_observation(value: StreamObservation) -> wit::Observation {
    wit::Observation {
        state: match value.state {
            StreamState::Open => wit::State::Open,
            StreamState::ReadEof => wit::State::ReadEof,
            StreamState::WriteShut => wit::State::WriteShut,
            StreamState::ReadEofWriteShut => wit::State::ReadEofWriteShut,
            StreamState::Stopping => wit::State::Stopping,
            StreamState::Closed => wit::State::Closed,
            StreamState::Failed => wit::State::Failed,
        },
        accepted_write_bytes: value.accepted_write_bytes,
        delivered_read_bytes: value.delivered_read_bytes,
        application_write_attempted: value.application_write_attempted,
    }
}
fn convert_error(value: StreamError) -> wit::StreamError {
    wit::StreamError {
        code: match value.code {
            StreamErrorCode::InvalidInput => wit::ErrorCode::InvalidInput,
            StreamErrorCode::InvalidState => wit::ErrorCode::InvalidState,
            StreamErrorCode::Unsupported => wit::ErrorCode::Unsupported,
            StreamErrorCode::Denied => wit::ErrorCode::Denied,
            StreamErrorCode::Revoked => wit::ErrorCode::Revoked,
            StreamErrorCode::Exhausted => wit::ErrorCode::Exhausted,
            StreamErrorCode::DnsFailed => wit::ErrorCode::DnsFailed,
            StreamErrorCode::TlsFailed => wit::ErrorCode::TlsFailed,
            StreamErrorCode::ConnectFailed => wit::ErrorCode::ConnectFailed,
            StreamErrorCode::Timeout => wit::ErrorCode::Timeout,
            StreamErrorCode::Cancelled => wit::ErrorCode::Cancelled,
            StreamErrorCode::IoFailed => wit::ErrorCode::IoFailed,
            StreamErrorCode::Uncertain => wit::ErrorCode::Uncertain,
        },
        accepted_prefix_bytes: value.accepted_prefix_bytes,
        may_have_applied: value.may_have_applied,
    }
}
