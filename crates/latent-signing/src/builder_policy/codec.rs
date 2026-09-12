use crate::{provenance::json, SignatureFailure, SignatureResult};
use serde::{de::DeserializeOwned, Serialize};

pub(super) fn decode<T: DeserializeOwned>(
    bytes: &[u8],
    maximum: usize,
    failure: SignatureFailure,
) -> SignatureResult<T> {
    json::decode(bytes, maximum, 256).map_err(|error| {
        if error.reason() == SignatureFailure::ResourceLimit {
            error
        } else {
            failure.into()
        }
    })
}

pub(super) fn encode<T: Serialize>(value: &T, maximum: usize) -> SignatureResult<Vec<u8>> {
    json::encode(value, maximum)
}
