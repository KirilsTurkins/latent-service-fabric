use super::{
    Answers, DNSClass, HttpDestination, HttpError, IpAddr, Message, MessageType, Name, OpCode,
    RData, RecordType, ResponseCode,
};
pub(super) struct Decoded {
    pub answers: Answers,
    pub alias: Option<Name>,
    pub ttl: u32,
}
pub(super) fn preflight(bytes: &[u8]) -> Result<(), HttpError> {
    if !(12..=4096).contains(&bytes.len()) {
        return Err(HttpError::DnsFailed);
    }
    let count = |i| usize::from(u16::from_be_bytes([bytes[i], bytes[i + 1]]));
    if count(4) != 1 || count(6) > 16 || count(8) > 8 || count(10) > 8 {
        return Err(HttpError::DnsFailed);
    }
    Ok(())
}
pub(super) fn response(
    bytes: &[u8],
    id: u16,
    name: &Name,
    kind: RecordType,
    destination: &HttpDestination,
) -> Result<Decoded, HttpError> {
    preflight(bytes)?;
    let message = Message::from_vec(bytes).map_err(|_| HttpError::DnsFailed)?;
    if message.metadata.id != id
        || message.metadata.message_type != MessageType::Response
        || message.metadata.op_code != OpCode::Query
        || message.metadata.truncation
        || message.metadata.response_code != ResponseCode::NoError
        || message.queries.len() != 1
        || message.queries[0].name() != name
        || message.queries[0].query_type() != kind
        || message.queries[0].query_class() != DNSClass::IN
    {
        return Err(HttpError::DnsFailed);
    }
    let mut answers = Answers::empty();
    let mut current = name.clone();
    let mut ttl = u32::MAX;
    let mut visited = Vec::with_capacity(5);
    for _ in 0..5 {
        if visited.contains(&current) {
            return Err(HttpError::DnsFailed);
        }
        visited.push(current.clone());
        let mut alias = None;
        for record in &message.answers {
            if record.dns_class != DNSClass::IN {
                return Err(HttpError::DnsFailed);
            }
            // All returned address records must pass the configured address
            // boundary, even a mixed record the caller would otherwise ignore.
            let ip = match &record.data {
                RData::A(ip) => Some(IpAddr::V4(ip.0)),
                RData::AAAA(ip) => Some(IpAddr::V6(ip.0)),
                _ => None,
            };
            if ip.is_some_and(|ip| !destination.addresses.permits(ip)) {
                return Err(HttpError::PermissionDenied);
            }
            if record.name != current {
                continue;
            }
            ttl = ttl.min(record.ttl);
            match &record.data {
                RData::A(ip) if kind == RecordType::A => answers.add(IpAddr::V4(ip.0))?,
                RData::AAAA(ip) if kind == RecordType::AAAA => answers.add(IpAddr::V6(ip.0))?,
                RData::CNAME(target) => {
                    if alias.is_some() || target.0.to_ascii().len() > 254 {
                        return Err(HttpError::DnsFailed);
                    }
                    alias = Some(target.0.clone());
                }
                _ => (),
            }
        }
        if answers.count > 0 {
            if alias.is_some() {
                return Err(HttpError::DnsFailed);
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
                })
            }
        }
    }
    Err(HttpError::DnsFailed)
}
