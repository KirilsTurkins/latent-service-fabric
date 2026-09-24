//! Explicit recursive resolver transport, finite records/aliases and fixed cache.
//! There is no system resolver, search suffix, DNS background task or retry loop.
use crate::{
    destination::canonical,
    network::{DnsConnection, DnsSocket, Network},
    HttpDestination, HttpError, HttpResolution,
};
#[cfg(test)]
use hickory_proto::rr::RData;
use hickory_proto::{
    op::{Message, MessageType, OpCode, Query},
    rr::{Name, RecordType},
};
use latent_capabilities::broker::pools::{PoolCall, ProviderClient, ProviderPools};
use std::{
    net::{IpAddr, SocketAddr},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpStream, UdpSocket},
};
mod decode;

#[derive(Clone, Copy)]
pub(crate) struct Answers {
    addresses: [Option<IpAddr>; 8],
    count: usize,
}
impl Answers {
    pub(crate) fn from_static(addresses: &[IpAddr]) -> Result<Self, HttpError> {
        let mut result = Self::empty();
        for address in addresses {
            result.add(*address)?;
        }
        Ok(result)
    }
    fn empty() -> Self {
        Self {
            addresses: [None; 8],
            count: 0,
        }
    }
    pub fn iter(&self) -> impl Iterator<Item = IpAddr> + '_ {
        self.addresses[..self.count].iter().flatten().copied()
    }
    pub fn contains(&self, ip: IpAddr) -> bool {
        self.iter().any(|value| value == canonical(ip))
    }
    fn add(&mut self, ip: IpAddr) -> Result<(), HttpError> {
        let ip = canonical(ip);
        if self.contains(ip) {
            return Ok(());
        }
        if self.count == self.addresses.len() {
            return Err(HttpError::DnsFailed);
        }
        self.addresses[self.count] = Some(ip);
        self.count += 1;
        Ok(())
    }
}
#[derive(Clone, Copy)]
struct Cached {
    answers: Answers,
    until: Instant,
}
pub(crate) struct Resolver {
    cache: [Mutex<Option<Cached>>; 8],
}
impl Resolver {
    pub fn new() -> Self {
        Self {
            cache: std::array::from_fn(|_| Mutex::new(None)),
        }
    }
    pub async fn resolve(
        &self,
        pools: &ProviderPools,
        client: &Arc<ProviderClient<Network>>,
        call: &PoolCall,
        destination: &HttpDestination,
        index: usize,
    ) -> Result<Answers, HttpError> {
        let HttpResolution::Dns {
            server,
            maximum_ttl_seconds,
        } = destination.resolution
        else {
            let HttpResolution::Static { addresses } = &destination.resolution else {
                unreachable!()
            };
            let mut result = Answers::empty();
            for ip in addresses {
                result.add(*ip)?;
            }
            return Ok(result);
        };
        let cached = *self.cache[index]
            .try_lock()
            .map_err(|_| HttpError::Unavailable)?;
        if let Some(cached) = cached.filter(|c| Instant::now() < c.until) {
            return Ok(cached.answers);
        }
        // Reserve before Name/Message parsing or any socket is allocated.
        let _parser = pools.reserve_protocol_metadata(32 * 1024)?;
        let name = Name::from_ascii(format!("{}.", destination.origin.host))
            .map_err(|_| HttpError::DnsFailed)?;
        let mut result = Answers::empty();
        let mut ttl = maximum_ttl_seconds;
        let mut valid_until = Instant::now() + Duration::from_secs(u64::from(maximum_ttl_seconds));
        for kind in [RecordType::A, RecordType::AAAA] {
            let mut current = name.clone();
            let mut visited = Vec::with_capacity(5);
            for depth in 0..5 {
                if visited.contains(&current) {
                    return Err(HttpError::DnsFailed);
                }
                visited.push(current.clone());
                let mut nonce = [0; 2];
                getrandom::fill(&mut nonce).map_err(|_| HttpError::DnsFailed)?;
                let id = u16::from_ne_bytes(nonce);
                let mut query = Message::new(id, MessageType::Query, OpCode::Query);
                query.metadata.recursion_desired = true;
                query.add_query(Query::query(current.clone(), kind));
                let packet = query.to_vec().map_err(|_| HttpError::DnsFailed)?;
                if packet.len() > 512 {
                    return Err(HttpError::DnsFailed);
                }
                let response = exchange(pools, client, call, server, &packet).await?;
                let decoded = decode::response(response.bytes(), id, &current, kind, destination)?;
                ttl = ttl.min(decoded.ttl);
                valid_until = valid_until.min(
                    Instant::now()
                        .checked_add(Duration::from_secs(u64::from(decoded.ttl)))
                        .ok_or(HttpError::DnsFailed)?,
                );
                for ip in decoded.answers.iter() {
                    result.add(ip)?;
                }
                match decoded.alias {
                    Some(alias) if depth < 4 => current = alias,
                    Some(_) => return Err(HttpError::DnsFailed),
                    None => break,
                }
            }
        }
        if result.count == 0 {
            return Err(HttpError::DnsFailed);
        }
        if ttl > 0 {
            if valid_until <= Instant::now() {
                return Err(HttpError::DnsFailed);
            }
            let until = valid_until;
            *self.cache[index]
                .try_lock()
                .map_err(|_| HttpError::Unavailable)? = Some(Cached {
                answers: result,
                until,
            });
        }
        Ok(result)
    }
}
async fn exchange(
    pools: &ProviderPools,
    client: &Arc<ProviderClient<Network>>,
    call: &PoolCall,
    server: SocketAddr,
    packet: &[u8],
) -> Result<latent_capabilities::broker::io::IoBuffer, HttpError> {
    let reservation = client.reserve_connection_wait(call).await?;
    let memory = pools.reserve_protocol_metadata(4096)?;
    let bind = if server.is_ipv4() {
        "0.0.0.0:0"
    } else {
        "[::]:0"
    };
    let socket = call
        .io()
        .wait_for(UdpSocket::bind(bind))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    call.io()
        .wait_for(socket.connect(server))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    let mut connection = reservation.connected(Network::Dns(DnsConnection {
        socket: DnsSocket::Udp(socket),
        _memory: memory,
    }))?;
    let Network::Dns(DnsConnection {
        socket: DnsSocket::Udp(socket),
        ..
    }) = connection.resource()
    else {
        unreachable!()
    };
    let n = call
        .io()
        .wait_for(socket.send(packet))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    if n != packet.len() {
        return Err(HttpError::DnsFailed);
    }
    let mut buffer = call.io().buffer(4097, 512)?;
    let n = call
        .io()
        .wait_for(socket.recv(buffer.spare_mut()?))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    buffer.advance_written(n)?;
    decode::preflight(buffer.bytes())?;
    if buffer.bytes()[..2] != packet[..2] || buffer.bytes()[2] & 0xf8 != 0x80 {
        return Err(HttpError::DnsFailed);
    }
    if buffer.bytes()[2] & 2 == 0 {
        return Ok(buffer);
    }
    // TC has no authority to grow the packet or contact another resolver.
    drop(connection);
    drop(buffer);
    tcp(pools, client, call, server, packet).await
}
async fn tcp(
    pools: &ProviderPools,
    client: &Arc<ProviderClient<Network>>,
    call: &PoolCall,
    server: SocketAddr,
    packet: &[u8],
) -> Result<latent_capabilities::broker::io::IoBuffer, HttpError> {
    let reservation = client.reserve_connection_wait(call).await?;
    let memory = pools.reserve_protocol_metadata(4096)?;
    let socket = call
        .io()
        .wait_for(TcpStream::connect(server))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    let mut connection = reservation.connected(Network::Dns(DnsConnection {
        socket: DnsSocket::Tcp(socket),
        _memory: memory,
    }))?;
    let Network::Dns(DnsConnection {
        socket: DnsSocket::Tcp(socket),
        ..
    }) = connection.resource()
    else {
        unreachable!()
    };
    let prefix = u16::try_from(packet.len())
        .map_err(|_| HttpError::DnsFailed)?
        .to_be_bytes();
    call.io()
        .wait_for(socket.write_all(&prefix))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    call.io()
        .wait_for(socket.write_all(packet))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    let mut size = [0; 2];
    call.io()
        .wait_for(socket.read_exact(&mut size))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    let length = usize::from(u16::from_be_bytes(size));
    if !(12..=4096).contains(&length) {
        return Err(HttpError::DnsFailed);
    }
    let mut buffer = call.io().buffer(length, 512)?;
    call.io()
        .wait_for(socket.read_exact(buffer.spare_mut()?))
        .await?
        .map_err(|_| HttpError::DnsFailed)?;
    buffer.advance_written(length)?;
    Ok(buffer)
}

#[cfg(test)]
mod tests;
