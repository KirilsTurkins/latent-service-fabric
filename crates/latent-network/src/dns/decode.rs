use super::Answers;
use crate::{AddressPolicy, NetworkError};
use hickory_proto::{
    op::{Message, MessageType, OpCode, ResponseCode},
    rr::{DNSClass, Name, RData, RecordType},
};
use std::net::IpAddr;

pub struct Decoded {
    pub answers: Answers,
    pub alias: Option<Name>,
    pub ttl: u32,
}

pub fn preflight(bytes: &[u8]) -> Result<(), NetworkError> {
    if !(12..=4096).contains(&bytes.len()) {
        return Err(NetworkError::DnsFailed);
    }
    let count = |offset| usize::from(u16::from_be_bytes([bytes[offset], bytes[offset + 1]]));
    if count(4) != 1 || count(6) > 16 || count(8) > 8 || count(10) > 8 {
        return Err(NetworkError::DnsFailed);
    }
    Ok(())
}

pub fn response(
    bytes: &[u8],
    identifier: u16,
    name: &Name,
    kind: RecordType,
    policy: &AddressPolicy,
) -> Result<Decoded, NetworkError> {
    preflight(bytes)?;
    let message = Message::from_vec(bytes).map_err(|_| NetworkError::DnsFailed)?;
    if message.metadata.id != identifier
        || message.metadata.message_type != MessageType::Response
        || message.metadata.op_code != OpCode::Query
        || message.metadata.truncation
        || message.metadata.response_code != ResponseCode::NoError
        || message.queries.len() != 1
        || message.queries[0].name() != name
        || message.queries[0].query_type() != kind
        || message.queries[0].query_class() != DNSClass::IN
    {
        return Err(NetworkError::DnsFailed);
    }
    let mut answers = Answers::default();
    let mut current = name.clone();
    let mut ttl = u32::MAX;
    let mut visited = Vec::with_capacity(5);
    for _ in 0..5 {
        if visited.contains(&current) {
            return Err(NetworkError::DnsFailed);
        }
        visited.push(current.clone());
        let mut alias = None;
        for record in &message.answers {
            if record.dns_class != DNSClass::IN {
                return Err(NetworkError::DnsFailed);
            }
            let address = match &record.data {
                RData::A(address) => Some(IpAddr::V4(address.0)),
                RData::AAAA(address) => Some(IpAddr::V6(address.0)),
                _ => None,
            };
            if address.is_some_and(|address| !policy.permits(address)) {
                return Err(NetworkError::PermissionDenied);
            }
            if record.name != current {
                continue;
            }
            ttl = ttl.min(record.ttl);
            match &record.data {
                RData::A(address) if kind == RecordType::A => answers.add(IpAddr::V4(address.0))?,
                RData::AAAA(address) if kind == RecordType::AAAA => {
                    answers.add(IpAddr::V6(address.0))?;
                }
                RData::CNAME(target) => {
                    if alias.is_some() || target.0.to_ascii().len() > 254 {
                        return Err(NetworkError::DnsFailed);
                    }
                    alias = Some(target.0.clone());
                }
                _ => (),
            }
        }
        if !answers.is_empty() {
            if alias.is_some() {
                return Err(NetworkError::DnsFailed);
            }
            return Ok(Decoded {
                answers,
                alias: None,
                ttl,
            });
        }
        match alias {
            Some(alias) => current = alias,
            None => {
                return Ok(Decoded {
                    answers,
                    alias: (current != *name).then_some(current),
                    ttl: ttl.min(300),
                });
            }
        }
    }
    Err(NetworkError::DnsFailed)
}
