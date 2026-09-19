use super::{Answers, HttpDestination, HttpError, Name, RecordType};
use latent_network::{dns::decode, NetworkError};

pub(super) struct Decoded {
    pub answers: Answers,
    pub alias: Option<Name>,
    pub ttl: u32,
}

pub(super) fn preflight(bytes: &[u8]) -> Result<(), HttpError> {
    decode::preflight(bytes).map_err(error)
}

pub(super) fn response(
    bytes: &[u8],
    identifier: u16,
    name: &Name,
    kind: RecordType,
    destination: &HttpDestination,
) -> Result<Decoded, HttpError> {
    let decoded =
        decode::response(bytes, identifier, name, kind, &destination.addresses).map_err(error)?;
    let mut answers = Answers::empty();
    for address in decoded.answers.iter() {
        answers.add(address)?;
    }
    Ok(Decoded {
        answers,
        alias: decoded.alias,
        ttl: decoded.ttl,
    })
}

fn error(error: NetworkError) -> HttpError {
    if error == NetworkError::PermissionDenied {
        HttpError::PermissionDenied
    } else {
        HttpError::DnsFailed
    }
}
