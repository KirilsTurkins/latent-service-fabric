use super::{HeaderView, MAX_COOKIES, MAX_COOKIE_BYTES};

fn pair(value: &[u8]) -> Option<&[u8]> {
    let separator = value.iter().position(|byte| *byte == b'=')?;
    let (name, value) = (&value[..separator], &value[separator + 1..]);
    (!name.is_empty()
        && name.len() <= 64
        && name.iter().copied().all(super::super::headers::token)
        && value.len() <= 1024
        && value.iter().all(
            |byte| matches!(*byte, 0x21 | 0x23..=0x2b | 0x2d..=0x3a | 0x3c..=0x5b | 0x5d..=0x7e),
        ))
    .then_some(name)
}

pub(super) fn request(headers: &[HeaderView<'_>]) -> Result<(), u16> {
    let mut names: [&[u8]; MAX_COOKIES] = [b""; MAX_COOKIES];
    let mut count = 0;
    let mut bytes = 0;
    for header in headers
        .iter()
        .filter(|header| header.name.eq_ignore_ascii_case("cookie"))
    {
        bytes += header.value.len();
        if bytes > MAX_COOKIE_BYTES {
            return Err(431);
        }
        for entry in header.value.split(|byte| *byte == b';') {
            let entry = entry.strip_prefix(b" ").unwrap_or(entry);
            if count == names.len() {
                return Err(431);
            }
            let name = pair(entry).ok_or(400u16)?;
            if names[..count].contains(&name) {
                return Err(400);
            }
            names[count] = name;
            count += 1;
        }
    }
    Ok(())
}

pub(super) fn response<'value>(value: &'value [u8], names: &mut Vec<&'value [u8]>) -> bool {
    let mut fields = value.split(|byte| *byte == b';');
    let Some(name) = fields.next().and_then(pair) else {
        return false;
    };
    if !name.starts_with(b"__Host-")
        || name.len() == 7
        || names.contains(&name)
        || names.len() == MAX_COOKIES
    {
        return false;
    }
    let mut attributes = 0u8;
    for field in fields {
        let field = field.strip_prefix(b" ").unwrap_or(field);
        let mask = match field {
            b"Secure" => 1,
            b"HttpOnly" => 2,
            b"SameSite=Strict" => 4,
            b"Path=/" => 8,
            b"Max-Age=0" => 16,
            _ => return false,
        };
        if attributes & mask != 0 {
            return false;
        }
        attributes |= mask;
    }
    if attributes & 15 != 15 {
        return false;
    }
    names.push(name);
    true
}
