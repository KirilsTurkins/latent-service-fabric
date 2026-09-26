//! Finite pull parsing of the selected S3 XML subset; no DTD or external entities.
use super::{BlobError, Result, XML_BYTES};
use quick_xml::{events::Event, Reader};

pub(super) struct Document {
    pub root: String,
    pub fields: Vec<(String, String)>,
}
impl Document {
    pub fn parse(bytes: &[u8]) -> Result<Self> {
        if bytes.is_empty() || bytes.len() > XML_BYTES || std::str::from_utf8(bytes).is_err() {
            return Err(BlobError::Unavailable);
        }
        let mut reader = Reader::from_reader(bytes);
        reader.config_mut().expand_empty_elements = true;
        let mut stack = Vec::<String>::new();
        let mut texts = Vec::<String>::new();
        let mut root = String::new();
        let mut fields = Vec::new();
        let mut events = 0;
        loop {
            events += 1;
            if events > 2048 {
                return Err(BlobError::BudgetExhausted);
            }
            match reader.read_event().map_err(|_| BlobError::Unavailable)? {
                Event::Start(start) => {
                    let name = start.name().as_ref().to_owned();
                    if !super::text(&name, 64)
                        || !name.bytes().all(|b| b.is_ascii_alphanumeric())
                        || stack.len() >= 8
                    {
                        return Err(BlobError::Unavailable);
                    }
                    for attribute in start.attributes() {
                        let attribute = attribute.map_err(|_| BlobError::Unavailable)?;
                        if !stack.is_empty()
                            || attribute.key.as_ref() != "xmlns"
                            || attribute.value.as_ref() != "http://s3.amazonaws.com/doc/2006-03-01/"
                        {
                            return Err(BlobError::Unavailable);
                        }
                    }
                    if stack.is_empty() {
                        if !root.is_empty() {
                            return Err(BlobError::Unavailable);
                        }
                        root.clone_from(&name);
                    }
                    stack.push(name);
                    texts.push(String::new());
                }
                Event::End(_) => {
                    let value = texts.pop().ok_or(BlobError::Unavailable)?;
                    if !value.trim().is_empty() {
                        if fields.len() == 256 || value.len() > 4096 {
                            return Err(BlobError::BudgetExhausted);
                        }
                        fields.push((
                            stack.iter().skip(1).cloned().collect::<Vec<_>>().join("/"),
                            value,
                        ));
                    }
                    stack.pop().ok_or(BlobError::Unavailable)?;
                }
                Event::Text(text) => {
                    let value = text.xml10_content();
                    if let Some(target) = texts.last_mut() {
                        if target.len() + value.len() > 4096 {
                            return Err(BlobError::BudgetExhausted);
                        }
                        target.push_str(&value);
                    } else if !value.trim().is_empty() {
                        return Err(BlobError::Unavailable);
                    }
                }
                Event::GeneralRef(reference) => {
                    let name = reference.as_ref();
                    let escaped = format!("&{name};");
                    let decoded = quick_xml::escape::unescape(&escaped)
                        .map_err(|_| BlobError::Unavailable)?;
                    let target = texts.last_mut().ok_or(BlobError::Unavailable)?;
                    if target.len() + decoded.len() > 4096 {
                        return Err(BlobError::BudgetExhausted);
                    }
                    target.push_str(&decoded);
                }
                Event::Decl(_) if root.is_empty() => (),
                Event::Eof => break,
                _ => return Err(BlobError::Unavailable),
            }
        }
        if !stack.is_empty() || root.is_empty() {
            return Err(BlobError::Unavailable);
        }
        Ok(Self { root, fields })
    }
    pub fn field(&self, name: &str) -> Result<&str> {
        let mut values = self.fields.iter().filter(|v| v.0 == name);
        let value = values.next().ok_or(BlobError::Unavailable)?;
        if values.next().is_some() {
            return Err(BlobError::Unavailable);
        }
        Ok(&value.1)
    }
    pub fn expect(&self, root: &str) -> Result<()> {
        if self.root == root {
            Ok(())
        } else {
            Err(BlobError::Uncertain)
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fields_entities_and_fail_closed_xml() {
        let doc = Document::parse(b"<Result><ETag>&quot;a&amp;b&quot;</ETag></Result>").unwrap();
        assert_eq!(doc.field("ETag").unwrap(), "\"a&b\"");
        for value in [
            "<!DOCTYPE x [<!ENTITY y SYSTEM 'file:///etc/passwd'>]><x>&y;</x>",
            "<x><a>1</a>",
            "<x/><y/>",
            "<x><?work y?></x>",
        ] {
            assert!(Document::parse(value.as_bytes()).is_err());
        }
        let duplicate = Document::parse(b"<x><a>1</a><a>2</a></x>").unwrap();
        assert!(duplicate.field("a").is_err());
        let error = Document::parse(b"<Error><Code>InternalError</Code></Error>").unwrap();
        assert_eq!(
            error.expect("CompleteMultipartUploadResult"),
            Err(BlobError::Uncertain)
        );
    }
}
