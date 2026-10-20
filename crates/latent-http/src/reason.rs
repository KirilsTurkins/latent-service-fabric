//! Explicit-profile raw HTTP/1 metadata, before httparse discards obs-text.
use crate::HttpError;
use latent_capabilities::broker::{http::MAXIMUM_HTTP_REASON_BYTES, io::IoBuffer};
use std::sync::{Arc, Mutex};

pub(crate) type Capture = Arc<Mutex<Option<Reason>>>;

pub(crate) fn supports_version(version: http::Version) -> bool {
    matches!(version, http::Version::HTTP_10 | http::Version::HTTP_11)
}

pub(crate) struct Reason {
    buffer: IoBuffer,
    parser: Parser,
    failure: Option<HttpError>,
}
impl Reason {
    pub fn new(buffer: IoBuffer) -> Self {
        Self {
            buffer,
            parser: Parser::default(),
            failure: None,
        }
    }
    pub fn observe(&mut self, bytes: &[u8]) {
        if self.failure.is_none() {
            self.failure = self
                .buffer
                .spare_mut()
                .map_err(HttpError::from)
                .and_then(|target| self.parser.observe(bytes, target))
                .err();
        }
    }
    pub fn finish(mut self, status: u16) -> Result<IoBuffer, HttpError> {
        if let Some(error) = self.failure {
            return Err(error);
        }
        if self.parser.state != State::Done || self.parser.status != status {
            return Err(HttpError::ConnectionFailed);
        }
        self.buffer.advance_written(self.parser.length)?;
        Ok(self.buffer)
    }
}

#[derive(Clone, Copy, Default, PartialEq, Eq)]
enum State {
    #[default]
    Start,
    StartLf,
    Prefix,
    Separator,
    Reason,
    ReasonLf,
    Headers,
    HeaderLf,
    Done,
}

#[derive(Default)]
struct Parser {
    state: State,
    prefix: [u8; 12],
    prefix_length: usize,
    status: u16,
    length: usize,
    observed: usize,
    header_empty: bool,
}
impl Parser {
    fn next_status(&mut self) {
        self.state = State::Start;
        self.prefix_length = 0;
        self.status = 0;
        self.length = 0;
    }
    fn line_complete(&mut self) {
        self.state = if (100..200).contains(&self.status) && self.status != 101 {
            self.header_empty = true;
            State::Headers
        } else {
            State::Done
        };
    }
    fn header_complete(&mut self) {
        if self.header_empty {
            self.next_status();
        } else {
            self.header_empty = true;
            self.state = State::Headers;
        }
    }
    // Storage is fixed before contact. Only status metadata is retained; even
    // informational headers share Hyper's existing 32 KiB prefix ceiling.
    #[expect(
        clippy::too_many_lines,
        reason = "one finite status/header state machine"
    )]
    fn observe(&mut self, bytes: &[u8], target: &mut [u8]) -> Result<(), HttpError> {
        for &byte in bytes {
            if self.state == State::Done {
                break;
            }
            self.observed += 1;
            if self.observed > 32768 {
                return Err(HttpError::ResponseTooLarge);
            }
            match self.state {
                State::Start => match byte {
                    b'\n' => {}
                    b'\r' => self.state = State::StartLf,
                    b'H' => {
                        self.prefix[0] = byte;
                        self.prefix_length = 1;
                        self.state = State::Prefix;
                    }
                    _ => return Err(HttpError::ConnectionFailed),
                },
                State::StartLf => {
                    if byte != b'\n' {
                        return Err(HttpError::ConnectionFailed);
                    }
                    self.state = State::Start;
                }
                State::Prefix => {
                    self.prefix[self.prefix_length] = byte;
                    self.prefix_length += 1;
                    if self.prefix_length == self.prefix.len() {
                        if !matches!(&self.prefix[..9], b"HTTP/1.0 " | b"HTTP/1.1 ")
                            || !self.prefix[9..].iter().all(u8::is_ascii_digit)
                        {
                            return Err(HttpError::ConnectionFailed);
                        }
                        self.status = self.prefix[9..]
                            .iter()
                            .fold(0, |value, digit| value * 10 + u16::from(*digit - b'0'));
                        self.state = State::Separator;
                    }
                }
                State::Separator => match byte {
                    b' ' => self.state = State::Reason,
                    b'\r' => self.state = State::ReasonLf,
                    b'\n' => self.line_complete(),
                    _ => return Err(HttpError::ConnectionFailed),
                },
                State::Reason => match byte {
                    b'\r' => self.state = State::ReasonLf,
                    b'\n' => self.line_complete(),
                    b'\t' | b' '..=b'~' | 0x80..=0xff => {
                        if self.length == MAXIMUM_HTTP_REASON_BYTES || self.length == target.len() {
                            return Err(HttpError::ResponseTooLarge);
                        }
                        target[self.length] = byte;
                        self.length += 1;
                    }
                    _ => return Err(HttpError::ConnectionFailed),
                },
                State::ReasonLf => {
                    if byte != b'\n' {
                        return Err(HttpError::ConnectionFailed);
                    }
                    self.line_complete();
                }
                State::Headers => match byte {
                    b'\r' => self.state = State::HeaderLf,
                    b'\n' => self.header_complete(),
                    _ => self.header_empty = false,
                },
                State::HeaderLf => {
                    if byte != b'\n' {
                        return Err(HttpError::ConnectionFailed);
                    }
                    self.header_complete();
                }
                State::Done => unreachable!("completed capture stops before body bytes"),
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fragmented_informational_and_raw_final_reason_do_not_capture_body_or_stale_bytes() {
        let mut parser = Parser::default();
        let mut target = [0; MAXIMUM_HTTP_REASON_BYTES];
        for byte in b"\r\nHTTP/1.1 103 Early hints\r\nX-Test: ignored\r\n\r\nHTTP/1.0 200 Caf\xe9\r\nContent-Length: 4\r\n\r\nbody" {
            parser.observe(&[*byte], &mut target).unwrap();
        }
        assert!(parser.state == State::Done);
        assert_eq!(parser.status, 200);
        assert_eq!(&target[..parser.length], b"Caf\xe9");
        let before = (parser.observed, target);
        parser.observe(b"more body data", &mut target).unwrap();
        assert_eq!((parser.observed, target), before);
    }

    #[test]
    fn malformed_status_and_bounded_prefix_or_reason_refuse_without_growing_storage() {
        for wire in [
            &b"HTTP/2.0 200 OK\r\n"[..],
            &b"HTTP/1.1 20x Bad\r\n"[..],
            &b"HTTP/1.1 200 forbidden\0value\r\n"[..],
            &b"HTTP/1.1 200 invalid\rX"[..],
        ] {
            let mut parser = Parser::default();
            assert!(matches!(
                parser.observe(wire, &mut [0; MAXIMUM_HTTP_REASON_BYTES]),
                Err(HttpError::ConnectionFailed)
            ));
        }
        let mut target = [0; MAXIMUM_HTTP_REASON_BYTES];
        let mut parser = Parser::default();
        parser.observe(b"HTTP/1.1 200 ", &mut target).unwrap();
        parser
            .observe(&[b'x'; MAXIMUM_HTTP_REASON_BYTES], &mut target)
            .unwrap();
        assert!(matches!(
            parser.observe(b"x", &mut target),
            Err(HttpError::ResponseTooLarge)
        ));
        let mut parser = Parser::default();
        parser
            .observe(b"HTTP/1.1 103 Early\r\nX: ", &mut target)
            .unwrap();
        assert!(matches!(
            parser.observe(&[b'x'; 32768], &mut target),
            Err(HttpError::ResponseTooLarge)
        ));
    }
}
