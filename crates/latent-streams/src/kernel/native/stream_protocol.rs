//! Private operation framing for the prepaid factory, not a guest socket ABI.
//!
//! A complete selected kernel consumer and its actual original scope owner are
//! prerequisites. These bytes cannot qualify a kernel or release any owner.
//! Payloads travel in the caller's existing IoTransfer buffers, never here.

const MAGIC: u32 = 0x4c53_5354;
const VERSION: u32 = 1;
pub(super) const REQUEST_BYTES: usize = 160;
pub(super) const RESPONSE_BYTES: usize = 64;
const MAXIMUM_PAYLOAD: u32 = 16 * 1024;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub(super) enum Operation {
    Create = 1,
    Connect = 2,
    Read = 3,
    Write = 4,
    Ready = 5,
    ShutdownSend = 6,
    Close = 7,
    Retired = 8,
    FinishConnect = 9,
    DnsTcpFallback = 10,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub(super) enum Purpose {
    Tcp = 1,
    DnsUdp = 2,
    DnsTcp = 3,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub(super) enum Family {
    Ipv4 = 4,
    Ipv6 = 6,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) struct Identity {
    pub slot: u32,
    pub generation: u64,
    pub lease: u64,
}

/// No Debug/Serialize or public constructor: sealed original scope words must
/// stay private to the actual native owner, never become a receipt/grant.
pub(super) struct Scope(pub [u64; 8]);

pub(super) struct Request<'a> {
    pub operation: Operation,
    pub family: Family,
    pub identity: Identity,
    pub sequence: u64,
    pub expiry_nanos: u64,
    pub scope: &'a Scope,
    pub payload_bytes: u32,
    pub address: [u8; 16],
    pub port: u32,
    pub purpose: Purpose,
    pub interest: u32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Rejected {
    Identity,
    Shape,
    Operation,
    Bound,
}

impl Request<'_> {
    pub fn encode(&self) -> Result<[u8; REQUEST_BYTES], Rejected> {
        let create = self.operation == Operation::Create;
        if (create
            && (self.identity.slot != 4 || self.identity.generation != 0 || self.sequence != 1))
            || (!create && (self.identity.slot >= 4 || self.identity.generation == 0))
            || self.identity.lease == 0
            || self.sequence == 0
            || self.expiry_nanos == 0
            || self.scope.0.contains(&0)
        {
            return Err(Rejected::Identity);
        }
        if (create && self.purpose == Purpose::DnsTcp)
            || (self.operation == Operation::DnsTcpFallback && self.purpose != Purpose::DnsTcp)
        {
            return Err(Rejected::Operation);
        }
        let data = matches!(self.operation, Operation::Read | Operation::Write);
        if (data && !(1..=MAXIMUM_PAYLOAD).contains(&self.payload_bytes))
            || (!data && self.payload_bytes != 0)
            || (self.operation == Operation::Ready && !(1..=3).contains(&self.interest))
            || (self.operation != Operation::Ready && self.interest != 0)
        {
            return Err(Rejected::Bound);
        }
        // The original AddressPolicy normalizes mapped IPv6 to IPv4 before
        // this private boundary. Never introduce a second spelling/family.
        let mapped = self.address[..10] == [0; 10] && self.address[10..12] == [0xff, 0xff];
        if (self.family == Family::Ipv4 && self.address[4..].iter().any(|byte| *byte != 0))
            || (self.family == Family::Ipv6 && mapped)
            || self.port > u32::from(u16::MAX)
            || (self.operation == Operation::Connect && self.port == 0)
            || (self.operation != Operation::Connect
                && (self.port != 0 || self.address.iter().any(|byte| *byte != 0)))
        {
            return Err(Rejected::Shape);
        }
        let mut wire = [0; REQUEST_BYTES];
        put32(&mut wire, 0, MAGIC);
        put32(&mut wire, 4, VERSION);
        put32(&mut wire, 8, self.operation as u32);
        put32(&mut wire, 12, self.family as u32);
        put32(&mut wire, 16, self.identity.slot);
        put64(&mut wire, 24, self.identity.generation);
        put64(&mut wire, 32, self.identity.lease);
        put64(&mut wire, 40, self.sequence);
        put64(&mut wire, 48, self.expiry_nanos);
        put32(&mut wire, 56, self.payload_bytes);
        for (index, word) in self.scope.0.iter().enumerate() {
            put64(&mut wire, 64 + index * 8, *word);
        }
        wire[128..144].copy_from_slice(&self.address);
        put32(&mut wire, 144, self.port);
        put32(&mut wire, 148, self.purpose as u32);
        put32(&mut wire, 152, self.interest);
        Ok(wire)
    }

    pub fn response(&self, wire: &[u8; RESPONSE_BYTES]) -> Result<Response, Rejected> {
        if word(wire, 0) != MAGIC
            || word(wire, 4) != VERSION
            || word(wire, 8) != self.operation as u32
            || wide(wire, 32) != self.identity.lease
            || wide(wire, 40) != self.sequence
        {
            return Err(Rejected::Identity);
        }
        let status = match word(wire, 12) {
            0 => Status::Complete,
            1 => Status::Pending,
            2 => Status::Eof,
            3 => Status::Failed,
            _ => return Err(Rejected::Shape),
        };
        let errno = word(wire, 20);
        let count = word(wire, 48);
        let ready = word(wire, 52);
        let flags = word(wire, 56);
        let identity = Identity {
            slot: word(wire, 16),
            generation: wide(wire, 24),
            lease: wide(wire, 32),
        };
        if self.operation == Operation::Create {
            // Only the original kernel allocator selects a slot/generation.
            // A failed constructor may carry its actual cleanup-only identity,
            // never a usable connection. Missing birth remains the sentinel.
            if status == Status::Complete || identity != self.identity {
                let slot_matches = match self.purpose {
                    Purpose::Tcp => identity.slot < 2,
                    Purpose::DnsUdp | Purpose::DnsTcp => (2..4).contains(&identity.slot),
                };
                if !slot_matches || identity.generation == 0 {
                    return Err(Rejected::Identity);
                }
                if status != Status::Complete && status != Status::Failed {
                    return Err(Rejected::Shape);
                }
            } else if status != Status::Failed {
                return Err(Rejected::Identity);
            }
        } else if identity != self.identity {
            return Err(Rejected::Identity);
        }
        if word(wire, 60) != self.family as u32 || flags & !1 != 0 || ready & !31 != 0 {
            return Err(Rejected::Shape);
        }
        if errno > 4095
            || (status == Status::Failed) != (errno != 0)
            || (status == Status::Pending
                && !matches!(
                    self.operation,
                    Operation::Connect
                        | Operation::FinishConnect
                        | Operation::Read
                        | Operation::Write
                        | Operation::Ready
                        | Operation::Retired
                ))
            || (status == Status::Eof
                && (self.operation != Operation::Read || self.purpose == Purpose::DnsUdp))
            || (count != 0 && !matches!(self.operation, Operation::Read | Operation::Write))
            || count > self.payload_bytes
            || (status != Status::Complete && status != Status::Failed && count != 0)
            || (ready != 0 && self.operation != Operation::Ready)
            || (self.operation == Operation::Ready && status == Status::Complete && ready == 0)
            || (status != Status::Complete && ready != 0)
            || (flags != 0 && self.operation != Operation::Write)
            || (status == Status::Complete
                && matches!(self.operation, Operation::Read | Operation::Write)
                && count == 0)
        {
            return Err(Rejected::Operation);
        }
        Ok(Response {
            identity,
            status,
            errno,
            count,
            ready,
            may_have_applied: flags & 1 != 0,
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Status {
    Complete,
    Pending,
    Eof,
    Failed,
}

/// Native errno is retained privately and mapped through the closed stream
/// error model. Pending is neither successful zero I/O nor EOF. No response
/// can certify remote commit, context retirement or physical bank return.
pub(super) struct Response {
    pub identity: Identity,
    pub status: Status,
    pub errno: u32,
    pub count: u32,
    pub ready: u32,
    pub may_have_applied: bool,
}

fn put32<const N: usize>(wire: &mut [u8; N], at: usize, value: u32) {
    wire[at..at + 4].copy_from_slice(&value.to_le_bytes());
}
fn put64<const N: usize>(wire: &mut [u8; N], at: usize, value: u64) {
    wire[at..at + 8].copy_from_slice(&value.to_le_bytes());
}
fn word<const N: usize>(wire: &[u8; N], at: usize) -> u32 {
    u32::from_le_bytes(wire[at..at + 4].try_into().expect("fixed frame"))
}
fn wide<const N: usize>(wire: &[u8; N], at: usize) -> u64 {
    u64::from_le_bytes(wire[at..at + 8].try_into().expect("fixed frame"))
}
