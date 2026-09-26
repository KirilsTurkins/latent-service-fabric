pub mod decode;
mod exchange;
#[cfg(test)]
mod tests;

use crate::{canonical, AddressPolicy, NetworkError};
use hickory_proto::{
    op::{Message, MessageType, OpCode, Query},
    rr::{Name, RecordType},
};
use std::{
    net::{IpAddr, SocketAddr},
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        Mutex,
    },
    time::Duration,
};
use tokio::{
    sync::Semaphore,
    time::{timeout_at, Instant},
};

#[derive(Clone, Copy, Debug, Default)]
pub struct Answers {
    addresses: [Option<IpAddr>; 8],
    count: usize,
}

impl Answers {
    pub fn iter(&self) -> impl Iterator<Item = IpAddr> + '_ {
        self.addresses[..self.count].iter().flatten().copied()
    }

    pub fn add(&mut self, address: IpAddr) -> Result<(), NetworkError> {
        let address = canonical(address);
        if self.iter().any(|value| value == address) {
            return Ok(());
        }
        if self.count == self.addresses.len() {
            return Err(NetworkError::DnsFailed);
        }
        self.addresses[self.count] = Some(address);
        self.count += 1;
        Ok(())
    }

    #[must_use]
    pub fn is_empty(self) -> bool {
        self.count == 0
    }
}

#[derive(Clone, Copy)]
struct Cached {
    answers: Answers,
    expires: Instant,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ResolverUsage {
    pub active: usize,
    pub waiting: usize,
    pub cached_answers: usize,
    pub reserved_bytes: usize,
    pub closed: bool,
}

pub struct Resolver {
    host: String,
    server: SocketAddr,
    maximum_ttl: u32,
    policy: AddressPolicy,
    cache: Mutex<Option<Cached>>,
    acquisition: tokio::sync::Mutex<()>,
    admission: Semaphore,
    active: AtomicUsize,
    waiting: AtomicUsize,
    closed: AtomicBool,
}

impl Resolver {
    pub fn new(
        host: String,
        server: SocketAddr,
        maximum_ttl: u32,
        policy: AddressPolicy,
        maximum_waiters: usize,
    ) -> Result<Self, NetworkError> {
        policy.validate()?;
        if host.is_empty()
            || host.len() > 253
            || !host.is_ascii()
            || host.parse::<IpAddr>().is_ok()
            || Name::from_ascii(&host).is_err()
            || server.port() == 0
            || server.ip().is_unspecified()
            || server.ip().is_multicast()
            || maximum_ttl == 0
            || maximum_ttl > 300
            || !(1..=32).contains(&maximum_waiters)
        {
            return Err(NetworkError::InvalidConfiguration);
        }
        Ok(Self {
            host,
            server,
            maximum_ttl,
            policy,
            cache: Mutex::new(None),
            acquisition: tokio::sync::Mutex::new(()),
            admission: Semaphore::new(maximum_waiters),
            active: AtomicUsize::new(0),
            waiting: AtomicUsize::new(0),
            closed: AtomicBool::new(false),
        })
    }

    pub async fn resolve(&self, deadline: Instant) -> Result<Answers, NetworkError> {
        self.check(deadline)?;
        if let Some(answers) = self.cached()? {
            return Ok(answers);
        }
        let _permit = self
            .admission
            .try_acquire()
            .map_err(|_| NetworkError::ResourceExhausted)?;
        let waiting = Count::new(&self.waiting);
        let _exclusive = timeout_at(deadline, self.acquisition.lock())
            .await
            .map_err(|_| NetworkError::DeadlineExceeded)?;
        drop(waiting);
        self.check(deadline)?;
        if let Some(answers) = self.cached()? {
            return Ok(answers);
        }
        let _active = Count::new(&self.active);
        let (answers, expires) = timeout_at(deadline, self.query())
            .await
            .map_err(|_| NetworkError::DeadlineExceeded)??;
        self.check(deadline)?;
        if expires > Instant::now() {
            let mut cache = self.cache.lock().map_err(|_| NetworkError::Closed)?;
            self.check(deadline)?;
            *cache = Some(Cached { answers, expires });
        }
        Ok(answers)
    }

    pub fn close(&self) -> Result<(), NetworkError> {
        self.closed.store(true, Ordering::Release);
        *self.cache.lock().map_err(|_| NetworkError::Closed)? = None;
        Ok(())
    }

    #[must_use]
    pub fn usage(&self) -> ResolverUsage {
        let cache = self
            .cache
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let active = self.active.load(Ordering::Acquire);
        ResolverUsage {
            active,
            waiting: self.waiting.load(Ordering::Acquire),
            cached_answers: cache.map_or(0, |cached| cached.answers.count),
            reserved_bytes: active * 65536 + std::mem::size_of::<Option<Cached>>(),
            closed: self.closed.load(Ordering::Acquire),
        }
    }

    fn check(&self, deadline: Instant) -> Result<(), NetworkError> {
        if self.closed.load(Ordering::Acquire) {
            return Err(NetworkError::Closed);
        }
        if Instant::now() >= deadline {
            return Err(NetworkError::DeadlineExceeded);
        }
        Ok(())
    }

    fn cached(&self) -> Result<Option<Answers>, NetworkError> {
        let mut cache = self.cache.lock().map_err(|_| NetworkError::Closed)?;
        if cache.is_some_and(|cached| cached.expires <= Instant::now()) {
            *cache = None;
        }
        Ok(cache.map(|cached| cached.answers))
    }

    async fn query(&self) -> Result<(Answers, Instant), NetworkError> {
        let name = Name::from_ascii(format!("{}.", self.host.trim_end_matches('.')))
            .map_err(|_| NetworkError::DnsFailed)?;
        let mut result = Answers::default();
        let mut expires = Instant::now() + Duration::from_secs(u64::from(self.maximum_ttl));
        for kind in [RecordType::A, RecordType::AAAA] {
            let mut current = name.clone();
            let mut visited = Vec::with_capacity(5);
            for depth in 0..5 {
                if visited.contains(&current) {
                    return Err(NetworkError::DnsFailed);
                }
                visited.push(current.clone());
                let mut nonce = [0; 2];
                getrandom::fill(&mut nonce).map_err(|_| NetworkError::DnsFailed)?;
                let identifier = u16::from_ne_bytes(nonce);
                let mut query = Message::new(identifier, MessageType::Query, OpCode::Query);
                query.metadata.recursion_desired = true;
                query.add_query(Query::query(current.clone(), kind));
                let packet = query.to_vec().map_err(|_| NetworkError::DnsFailed)?;
                let received = exchange::run(self.server, &packet).await?;
                let decoded =
                    decode::response(&received, identifier, &current, kind, &self.policy)?;
                expires = expires.min(Instant::now() + Duration::from_secs(u64::from(decoded.ttl)));
                for address in decoded.answers.iter() {
                    result.add(address)?;
                }
                match decoded.alias {
                    Some(alias) if depth < 4 => current = alias,
                    Some(_) => return Err(NetworkError::DnsFailed),
                    None => break,
                }
            }
        }
        if result.is_empty() {
            return Err(NetworkError::DnsFailed);
        }
        Ok((result, expires))
    }
}

struct Count<'a>(&'a AtomicUsize);

impl<'a> Count<'a> {
    fn new(counter: &'a AtomicUsize) -> Self {
        counter.fetch_add(1, Ordering::AcqRel);
        Self(counter)
    }
}

impl Drop for Count<'_> {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}
