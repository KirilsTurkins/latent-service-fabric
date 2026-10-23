//! The two variable result payloads retain the original allocation and guard.
//! Field tags and helper behavior match unmodified prost generation from the
//! authoritative invocation.proto (cross-checked against generation in tests).
use latent_core::ResultPayload;
use prost::{
    bytes::{Buf, BufMut},
    encoding::{self, DecodeContext, WireType},
    DecodeError, Message,
};
use std::collections::HashMap;

// Incoming transport storage is copied by the original prost Vec adapter. The
// original payload remains alive through the physical copy; opaque Bytes backing
// capacity is never presented as payload length or imported into ResultPayload.
fn merge_payload(
    wire: WireType,
    value: &mut ResultPayload,
    buf: &mut impl Buf,
    ctx: DecodeContext,
) -> Result<(), DecodeError> {
    let mut replacement = Vec::new();
    encoding::bytes::merge(wire, &mut replacement, buf, ctx)?;
    *value = replacement.into();
    Ok(())
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Success {
    pub payload: ResultPayload,
    pub media_type: String,
    pub committed_state_version: Option<String>,
    pub effect_ids: Vec<String>,
    pub metadata: HashMap<String, String>,
}
impl Message for Success {
    fn encode_raw(&self, buf: &mut impl BufMut) {
        if !self.payload.is_empty() {
            encoding::bytes::encode(1, &self.payload.shared_bytes(), buf);
        }
        if !self.media_type.is_empty() {
            encoding::string::encode(2, &self.media_type, buf);
        }
        if let Some(value) = &self.committed_state_version {
            encoding::string::encode(3, value, buf);
        }
        encoding::string::encode_repeated(4, &self.effect_ids, buf);
        encoding::hash_map::encode(
            encoding::string::encode,
            encoding::string::encoded_len,
            encoding::string::encode,
            encoding::string::encoded_len,
            5,
            &self.metadata,
            buf,
        );
    }
    fn merge_field(
        &mut self,
        tag: u32,
        wire: WireType,
        buf: &mut impl Buf,
        ctx: DecodeContext,
    ) -> Result<(), DecodeError> {
        let (field, result) = match tag {
            1 => ("payload", merge_payload(wire, &mut self.payload, buf, ctx)),
            2 => (
                "media_type",
                encoding::string::merge(wire, &mut self.media_type, buf, ctx),
            ),
            3 => (
                "committed_state_version",
                encoding::string::merge(
                    wire,
                    self.committed_state_version.get_or_insert_with(String::new),
                    buf,
                    ctx,
                ),
            ),
            4 => (
                "effect_ids",
                encoding::string::merge_repeated(wire, &mut self.effect_ids, buf, ctx),
            ),
            5 => (
                "metadata",
                encoding::hash_map::merge(
                    encoding::string::merge,
                    encoding::string::merge,
                    &mut self.metadata,
                    buf,
                    ctx,
                ),
            ),
            _ => return encoding::skip_field(wire, tag, buf, ctx),
        };
        result.map_err(|mut error| {
            error.push("Success", field);
            error
        })
    }
    fn encoded_len(&self) -> usize {
        0 + (if self.payload.is_empty() {
            0
        } else {
            encoding::bytes::encoded_len(1, &self.payload.shared_bytes())
        }) + (if self.media_type.is_empty() {
            0
        } else {
            encoding::string::encoded_len(2, &self.media_type)
        }) + (self
            .committed_state_version
            .as_ref()
            .map_or(0, |v| encoding::string::encoded_len(3, v)))
            + (encoding::string::encoded_len_repeated(4, &self.effect_ids))
            + (encoding::hash_map::encoded_len(
                encoding::string::encoded_len,
                encoding::string::encoded_len,
                5,
                &self.metadata,
            ))
    }
    fn clear(&mut self) {
        self.payload = ResultPayload::default();
        self.media_type.clear();
        self.committed_state_version = None;
        self.effect_ids.clear();
        self.metadata.clear();
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeclaredError {
    pub code: String,
    pub message: String,
    pub payload: ResultPayload,
    pub media_type: String,
    pub metadata: HashMap<String, String>,
}
impl Message for DeclaredError {
    fn encode_raw(&self, buf: &mut impl BufMut) {
        if !self.code.is_empty() {
            encoding::string::encode(1, &self.code, buf);
        }
        if !self.message.is_empty() {
            encoding::string::encode(2, &self.message, buf);
        }
        if !self.payload.is_empty() {
            encoding::bytes::encode(3, &self.payload.shared_bytes(), buf);
        }
        if !self.media_type.is_empty() {
            encoding::string::encode(4, &self.media_type, buf);
        }
        encoding::hash_map::encode(
            encoding::string::encode,
            encoding::string::encoded_len,
            encoding::string::encode,
            encoding::string::encoded_len,
            5,
            &self.metadata,
            buf,
        );
    }
    fn merge_field(
        &mut self,
        tag: u32,
        wire: WireType,
        buf: &mut impl Buf,
        ctx: DecodeContext,
    ) -> Result<(), DecodeError> {
        let (field, result) = match tag {
            1 => (
                "code",
                encoding::string::merge(wire, &mut self.code, buf, ctx),
            ),
            2 => (
                "message",
                encoding::string::merge(wire, &mut self.message, buf, ctx),
            ),
            3 => ("payload", merge_payload(wire, &mut self.payload, buf, ctx)),
            4 => (
                "media_type",
                encoding::string::merge(wire, &mut self.media_type, buf, ctx),
            ),
            5 => (
                "metadata",
                encoding::hash_map::merge(
                    encoding::string::merge,
                    encoding::string::merge,
                    &mut self.metadata,
                    buf,
                    ctx,
                ),
            ),
            _ => return encoding::skip_field(wire, tag, buf, ctx),
        };
        result.map_err(|mut error| {
            error.push("DeclaredError", field);
            error
        })
    }
    fn encoded_len(&self) -> usize {
        0 + (if self.code.is_empty() {
            0
        } else {
            encoding::string::encoded_len(1, &self.code)
        }) + (if self.message.is_empty() {
            0
        } else {
            encoding::string::encoded_len(2, &self.message)
        }) + (if self.payload.is_empty() {
            0
        } else {
            encoding::bytes::encoded_len(3, &self.payload.shared_bytes())
        }) + (if self.media_type.is_empty() {
            0
        } else {
            encoding::string::encoded_len(4, &self.media_type)
        }) + (encoding::hash_map::encoded_len(
            encoding::string::encoded_len,
            encoding::string::encoded_len,
            5,
            &self.metadata,
        ))
    }
    fn clear(&mut self) {
        self.code.clear();
        self.message.clear();
        self.payload = ResultPayload::default();
        self.media_type.clear();
        self.metadata.clear();
    }
}

#[cfg(test)]
mod tests;
