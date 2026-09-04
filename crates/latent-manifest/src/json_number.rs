use std::cmp::Ordering;

use serde_json::Number;

/// Returns whether a JSON number is an integer in the mathematical sense used
/// by JSON Schema Draft 2020-12. Lexical forms such as `1.0`, `1e0`, and
/// `-0.0` are therefore integers.
pub(crate) fn is_mathematical_integer(number: &Number) -> bool {
    DecimalNumber::parse(&number.to_string()).is_some_and(|value| value.is_integer())
}

/// Compares two finite JSON numbers without converting schema bounds through
/// binary floating point.
pub(crate) fn compare_numbers(left: &Number, right: &Number) -> Ordering {
    let left = DecimalNumber::parse(&left.to_string())
        .expect("serde_json::Number always renders as a valid finite JSON number");
    let right = DecimalNumber::parse(&right.to_string())
        .expect("serde_json::Number always renders as a valid finite JSON number");
    left.cmp(&right)
}

/// Produces a representation-independent key for JSON numeric equality.
pub(crate) fn canonical_number_key(number: &Number) -> String {
    DecimalNumber::parse(&number.to_string())
        .expect("serde_json::Number always renders as a valid finite JSON number")
        .canonical_key()
}

/// Converts an integral JSON-number token to a canonical integer token when
/// the result can be represented losslessly by serde_json's integer storage.
/// Non-integral and wider-than-supported tokens are left untouched by callers.
pub(crate) fn representable_integer_lexeme(token: &[u8]) -> Option<Vec<u8>> {
    let token = std::str::from_utf8(token).ok()?;
    DecimalNumber::parse(token)?.representable_integer_lexeme()
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DecimalNumber {
    negative: bool,
    /// Significant decimal digits with no leading or trailing zeroes, except
    /// that zero is represented by one `0` digit.
    digits: Vec<u8>,
    /// Power of ten applied to `digits`.
    exponent: i128,
}

impl DecimalNumber {
    fn parse(text: &str) -> Option<Self> {
        let bytes = text.as_bytes();
        if bytes.is_empty() {
            return None;
        }

        let mut index = 0_usize;
        let negative = bytes.get(index) == Some(&b'-');
        if negative {
            index += 1;
        }
        if index >= bytes.len() {
            return None;
        }

        let integer_start = index;
        match bytes[index] {
            b'0' => {
                index += 1;
                if bytes
                    .get(index)
                    .is_some_and(|byte| byte.is_ascii_digit())
                {
                    return None;
                }
            }
            b'1'..=b'9' => {
                index += 1;
                while bytes
                    .get(index)
                    .is_some_and(|byte| byte.is_ascii_digit())
                {
                    index += 1;
                }
            }
            _ => return None,
        }
        let integer_end = index;

        let mut fraction_start = index;
        let mut fraction_length = 0_usize;
        if bytes.get(index) == Some(&b'.') {
            index += 1;
            fraction_start = index;
            while bytes
                .get(index)
                .is_some_and(|byte| byte.is_ascii_digit())
            {
                index += 1;
            }
            fraction_length = index.saturating_sub(fraction_start);
            if fraction_length == 0 {
                return None;
            }
        }

        let mut explicit_exponent = 0_i128;
        if bytes
            .get(index)
            .is_some_and(|byte| matches!(*byte, b'e' | b'E'))
        {
            index += 1;
            let exponent_negative = bytes.get(index) == Some(&b'-');
            if exponent_negative || bytes.get(index) == Some(&b'+') {
                index += 1;
            }
            let exponent_start = index;
            while bytes
                .get(index)
                .is_some_and(|byte| byte.is_ascii_digit())
            {
                explicit_exponent = explicit_exponent
                    .saturating_mul(10)
                    .saturating_add(i128::from(bytes[index] - b'0'));
                index += 1;
            }
            if index == exponent_start {
                return None;
            }
            if exponent_negative {
                explicit_exponent = -explicit_exponent;
            }
        }

        if index != bytes.len() {
            return None;
        }

        let mut digits = Vec::with_capacity(
            integer_end
                .saturating_sub(integer_start)
                .saturating_add(fraction_length),
        );
        digits.extend_from_slice(&bytes[integer_start..integer_end]);
        if fraction_length > 0 {
            digits.extend_from_slice(&bytes[fraction_start..fraction_start + fraction_length]);
        }

        let Some(first_nonzero) = digits.iter().position(|digit| *digit != b'0') else {
            return Some(Self {
                negative: false,
                digits: vec![b'0'],
                exponent: 0,
            });
        };
        digits = digits[first_nonzero..].to_vec();

        let fraction_length = i128::try_from(fraction_length).unwrap_or(i128::MAX);
        let mut exponent = explicit_exponent.saturating_sub(fraction_length);
        while digits.len() > 1 && digits.last() == Some(&b'0') {
            digits.pop();
            exponent = exponent.saturating_add(1);
        }

        Some(Self {
            negative,
            digits,
            exponent,
        })
    }

    fn is_zero(&self) -> bool {
        self.digits.as_slice() == b"0"
    }

    fn is_integer(&self) -> bool {
        self.is_zero() || self.exponent >= 0
    }

    fn canonical_key(&self) -> String {
        let digits = std::str::from_utf8(&self.digits)
            .expect("normalized decimal digits are always ASCII");
        format!(
            "{}{}e{}",
            if self.negative { "-" } else { "" },
            digits,
            self.exponent
        )
    }

    fn representable_integer_lexeme(&self) -> Option<Vec<u8>> {
        if !self.is_integer() {
            return None;
        }
        if self.is_zero() {
            return Some(vec![b'0']);
        }

        let appended_zeroes = usize::try_from(self.exponent).ok()?;
        let total_digits = self.digits.len().checked_add(appended_zeroes)?;
        let maximum: &[u8] = if self.negative {
            &b"9223372036854775808"[..]
        } else {
            &b"18446744073709551615"[..]
        };
        if total_digits > maximum.len() {
            return None;
        }

        let mut magnitude = Vec::with_capacity(total_digits);
        magnitude.extend_from_slice(&self.digits);
        magnitude.resize(total_digits, b'0');
        if magnitude.len() == maximum.len() && magnitude.as_slice() > maximum {
            return None;
        }

        let sign_bytes = if self.negative { 1 } else { 0 };
        let mut output = Vec::with_capacity(total_digits + sign_bytes);
        if self.negative {
            output.push(b'-');
        }
        output.extend_from_slice(&magnitude);
        Some(output)
    }

    fn cmp(&self, other: &Self) -> Ordering {
        if self.negative != other.negative {
            return if self.negative {
                Ordering::Less
            } else {
                Ordering::Greater
            };
        }

        let magnitude = self.cmp_magnitude(other);
        if self.negative {
            magnitude.reverse()
        } else {
            magnitude
        }
    }

    fn cmp_magnitude(&self, other: &Self) -> Ordering {
        match (self.is_zero(), other.is_zero()) {
            (true, true) => return Ordering::Equal,
            (true, false) => return Ordering::Less,
            (false, true) => return Ordering::Greater,
            (false, false) => {}
        }

        let left_order = i128::try_from(self.digits.len())
            .unwrap_or(i128::MAX)
            .saturating_add(self.exponent);
        let right_order = i128::try_from(other.digits.len())
            .unwrap_or(i128::MAX)
            .saturating_add(other.exponent);
        match left_order.cmp(&right_order) {
            Ordering::Equal => {}
            comparison => return comparison,
        }

        let comparison_length = self.digits.len().max(other.digits.len());
        for index in 0..comparison_length {
            let left = self.digits.get(index).copied().unwrap_or(b'0');
            let right = other.digits.get(index).copied().unwrap_or(b'0');
            match left.cmp(&right) {
                Ordering::Equal => {}
                comparison => return comparison,
            }
        }
        Ordering::Equal
    }
}
