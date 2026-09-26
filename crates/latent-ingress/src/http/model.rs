use serde::{Deserialize, Serialize};

use super::bounded::{BoundedBytes, BoundedList, BoundedText, Decimal, Optional};
use super::{body::Body, HttpError, MAX_HEADERS, MAX_REQUEST_BODY, MAX_RESPONSE_BODY};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Method {
    Get,
    Head,
    Post,
    Put,
    Patch,
    Delete,
    Options,
}

impl Method {
    pub fn parse(value: &str) -> Result<Self, HttpError> {
        match value {
            "GET" => Ok(Self::Get),
            "HEAD" => Ok(Self::Head),
            "POST" => Ok(Self::Post),
            "PUT" => Ok(Self::Put),
            "PATCH" => Ok(Self::Patch),
            "DELETE" => Ok(Self::Delete),
            "OPTIONS" => Ok(Self::Options),
            _ => Err(HttpError::UnsupportedMethod),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Scheme {
    Http,
    Https,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HttpVersion {
    Http11,
    Http2,
}

/// Borrowed fields from an already bounded protocol parser. Header names and
/// values have not been combined. The adapter must reject folded/pseudo fields
/// and framing errors before creating this view.
#[derive(Clone, Copy)]
pub struct HeaderView<'a> {
    pub name: &'a str,
    pub value: &'a [u8],
}

#[derive(Clone, Copy)]
pub struct RawHead<'a> {
    pub version: HttpVersion,
    pub method: &'a str,
    /// The transport supplies the actual scheme, including its TLS policy.
    pub scheme: Scheme,
    pub authority: &'a str,
    pub target: &'a str,
    pub headers: &'a [HeaderView<'a>],
}

#[derive(Serialize, Deserialize)]
pub(super) enum Profile {
    #[serde(rename = "buffered-v1")]
    BufferedV1,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Header {
    pub name: BoundedText<64>,
    pub value: BoundedBytes<4096>,
}

impl Header {
    pub fn view(&self) -> HeaderView<'_> {
        HeaderView {
            name: &self.name.0,
            value: &self.value.0,
        }
    }
}

#[derive(Serialize)]
#[serde(rename_all = "kebab-case")]
pub(super) struct RequestData {
    pub profile: Profile,
    pub method: Method,
    pub scheme: Scheme,
    pub authority: String,
    pub path: String,
    pub query: Optional<String>,
    pub headers: Vec<Header>,
    pub media_type: Optional<String>,
    #[serde(rename = "body-base64")]
    pub body: Body<MAX_REQUEST_BODY>,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "kebab-case", deny_unknown_fields)]
pub(super) struct ResponseData {
    pub profile: Profile,
    pub status: u16,
    pub headers: BoundedList<Header, MAX_HEADERS>,
    pub media_type: Optional<BoundedText<256>>,
    pub representation_length: Optional<Decimal>,
    #[serde(rename = "body-base64")]
    pub body: Body<MAX_RESPONSE_BODY>,
}
