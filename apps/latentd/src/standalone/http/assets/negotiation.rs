//! Closed, bounded negotiation for static documents. No substring matching.
use super::request::{qvalue, single};

#[derive(Clone, Copy)]
struct Range<'a> {
    kind: &'a str,
    subtype: &'a str,
    quality: u16,
}

pub(super) struct Accept<'a> {
    ranges: [Option<Range<'a>>; 16],
    present: bool,
}
impl<'a> Accept<'a> {
    pub(super) fn parse(value: Option<&'a str>) -> Result<Self, u16> {
        let mut result = Self {
            ranges: [None; 16],
            present: value.is_some(),
        };
        let Some(value) = value else {
            return Ok(result);
        };
        if value.len() > 2048 {
            return Err(431);
        }
        for (index, entry) in value.split(',').enumerate() {
            if index >= result.ranges.len() {
                return Err(431);
            }
            let mut parts = entry.trim().split(';');
            let (kind, subtype) = parts
                .next()
                .ok_or(400u16)?
                .trim()
                .split_once('/')
                .ok_or(400u16)?;
            let token = |value: &str| {
                !value.is_empty()
                    && value
                        .bytes()
                        .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
            };
            if !token(kind)
                || !token(subtype)
                || (kind == "*" && subtype != "*")
                || (kind.contains('*') && kind != "*")
                || (subtype.contains('*') && subtype != "*")
            {
                return Err(400);
            }
            let quality = match parts.next() {
                None => 1000,
                Some(parameter) => {
                    let (key, value) = parameter.trim().split_once('=').ok_or(400u16)?;
                    if !key.eq_ignore_ascii_case("q") {
                        return Err(400);
                    }
                    qvalue(value.trim())?
                }
            };
            if parts.next().is_some()
                || result.ranges[..index].iter().flatten().any(|r| {
                    r.kind.eq_ignore_ascii_case(kind) && r.subtype.eq_ignore_ascii_case(subtype)
                })
            {
                return Err(400);
            }
            result.ranges[index] = Some(Range {
                kind,
                subtype,
                quality,
            });
        }
        Ok(result)
    }
    pub(super) fn allows(&self, media: &str) -> bool {
        if !self.present {
            return true;
        }
        let Some((kind, subtype)) = media.split_once('/') else {
            return false;
        };
        self.ranges
            .iter()
            .flatten()
            .filter_map(|r| {
                let specificity = if r.kind.eq_ignore_ascii_case(kind)
                    && r.subtype.eq_ignore_ascii_case(subtype)
                {
                    2
                } else if r.kind.eq_ignore_ascii_case(kind) && r.subtype == "*" {
                    1
                } else if r.kind == "*" && r.subtype == "*" {
                    0
                } else {
                    return None;
                };
                Some((specificity, r.quality))
            })
            .max_by_key(|(specificity, _)| *specificity)
            .is_some_and(|(_, q)| q != 0)
    }
    fn explicit_html(&self) -> bool {
        self.ranges.iter().flatten().any(|r| {
            r.kind.eq_ignore_ascii_case("text")
                && r.subtype.eq_ignore_ascii_case("html")
                && r.quality != 0
        })
    }
}

pub(super) fn navigation(
    headers: &[httparse::Header<'_>],
    accept: &Accept<'_>,
) -> Result<bool, u16> {
    let mode = single(headers, "sec-fetch-mode")?;
    let destination = single(headers, "sec-fetch-dest")?;
    let metadata = headers.iter().any(|h| {
        h.name
            .get(..10)
            .is_some_and(|n| n.eq_ignore_ascii_case("sec-fetch-"))
    });
    Ok(if metadata {
        mode == Some("navigate") && destination == Some("document")
    } else {
        accept.explicit_html()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn accept_uses_specific_quality_and_bounded_unambiguous_ranges() {
        let accepted = Accept::parse(Some("text/html;q=0, text/*;q=0.5, */*;q=1")).unwrap();
        assert!(!accepted.allows("text/html"));
        assert!(accepted.allows("text/css"));
        assert!(accepted.allows("application/json"));
        for invalid in [
            "",
            "html",
            "text/html;q=1.001",
            "text/html;q=-1",
            "text/html;q=0.1234",
            "text/html;q=0;q=1",
            "text/html,text/HTML",
            "text/html; charset=utf-8",
            "*/html",
            "text/ht*ml",
        ] {
            assert!(Accept::parse(Some(invalid)).is_err(), "{invalid}");
        }
        assert!(Accept::parse(Some(&"text/html,".repeat(17))).is_err());
        assert!(Accept::parse(Some(&"x".repeat(2049))).is_err());
    }
    #[test]
    fn navigation_requires_complete_fetch_metadata_or_explicit_html() {
        let html = Accept::parse(Some("text/html;q=0.7,application/json")).unwrap();
        let wildcard = Accept::parse(Some("*/*")).unwrap();
        assert!(navigation(&[], &html).unwrap());
        assert!(!navigation(&[], &wildcard).unwrap());
        assert!(!navigation(&[], &Accept::parse(Some("application/json")).unwrap()).unwrap());
        for (mode, destination, expected) in [
            ("navigate", "document", true),
            ("cors", "script", false),
            ("navigate", "image", false),
            ("same-origin", "empty", false),
        ] {
            let headers = [
                httparse::Header {
                    name: "Sec-Fetch-Mode",
                    value: mode.as_bytes(),
                },
                httparse::Header {
                    name: "Sec-Fetch-Dest",
                    value: destination.as_bytes(),
                },
            ];
            assert_eq!(navigation(&headers, &html).unwrap(), expected);
        }
        assert!(!navigation(
            &[httparse::Header {
                name: "Sec-Fetch-Site",
                value: b"same-origin"
            }],
            &html
        )
        .unwrap());
        assert!(navigation(
            &[
                httparse::Header {
                    name: "Sec-Fetch-Dest",
                    value: b"document"
                },
                httparse::Header {
                    name: "sec-fetch-dest",
                    value: b"script"
                }
            ],
            &html
        )
        .is_err());
    }
}
