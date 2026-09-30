use crate::authority::AuthorityError;

pub(crate) fn parse(value: &str) -> Result<[u8; 32], AuthorityError> {
    if value.len() != 64 {
        return Err(AuthorityError::Invalid);
    }
    let mut identity = [0_u8; 32];
    for (target, pair) in identity.iter_mut().zip(value.as_bytes().chunks_exact(2)) {
        let nibble = |byte| match byte {
            b'0'..=b'9' => Ok(byte - b'0'),
            b'a'..=b'f' => Ok(byte - b'a' + 10),
            _ => Err(AuthorityError::Invalid),
        };
        *target = (nibble(pair[0])? << 4) | nibble(pair[1])?;
    }
    Ok(identity)
}

pub(crate) fn render(value: &[u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut text = String::with_capacity(64);
    for byte in value {
        text.push(char::from(HEX[usize::from(byte >> 4)]));
        text.push(char::from(HEX[usize::from(byte & 15)]));
    }
    text
}
