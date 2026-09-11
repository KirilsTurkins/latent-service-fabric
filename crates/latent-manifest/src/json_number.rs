use std::cmp::Ordering;

use serde_json::Number;

/// Returns whether a JSON number is an integer in the mathematical sense used
/// by JSON Schema Draft 2020-12. Lexical forms such as `1.0`, `1e0`, and
/// `-0.0` are therefore integers.
pub(crate) fn is_mathematical_integer(number: &Number) -> bool {
    DecimalNumber::parse(number.as_str()).is_some_and(|value| value.is_integer())
}

/// Compares two finite JSON numbers without converting schema bounds through
/// binary floating point.
pub(crate) fn compare_numbers(left: &Number, right: &Number) -> Ordering {
    let left = DecimalNumber::parse(left.as_str())
        .expect("serde_json::Number always stores a valid finite JSON number");
    let right = DecimalNumber::parse(right.as_str())
        .expect("serde_json::Number always stores a valid finite JSON number");
    left.cmp(&right)
}

/// Produces a representation-independent key for JSON numeric equality.
pub(crate) fn canonical_number_key(number: &Number) -> String {
    DecimalNumber::parse(number.as_str())
        .expect("serde_json::Number always stores a valid finite JSON number")
        .canonical_key()
}

/// Canonicalizes any valid JSON-number token by mathematical value. The
/// historical function name is retained for the bounded codec call site: the
/// result covers non-integral and arbitrary-precision values as well as
/// representable integers.
pub(crate) fn representable_integer_lexeme(token: &[u8]) -> Option<Vec<u8>> {
    let token = std::str::from_utf8(token).ok()?;
    DecimalNumber::parse(token).map(|number| number.canonical_lexeme())
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct DecimalNumber {
    negative: bool,
    /// Significant decimal digits with no leading or trailing zeroes, except
    /// that zero is represented by one `0` digit.
    digits: Vec<u8>,
    /// Arbitrary-precision signed power of ten applied to `digits`.
    exponent: DecimalExponent,
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
                if bytes.get(index).is_some_and(|byte| byte.is_ascii_digit()) {
                    return None;
                }
            }
            b'1'..=b'9' => {
                index += 1;
                while bytes.get(index).is_some_and(|byte| byte.is_ascii_digit()) {
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
            while bytes.get(index).is_some_and(|byte| byte.is_ascii_digit()) {
                index += 1;
            }
            fraction_length = index - fraction_start;
            if fraction_length == 0 {
                return None;
            }
        }

        let mut explicit_exponent = DecimalExponent::zero();
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
            while bytes.get(index).is_some_and(|byte| byte.is_ascii_digit()) {
                index += 1;
            }
            if index == exponent_start {
                return None;
            }
            explicit_exponent =
                DecimalExponent::from_digits(exponent_negative, &bytes[exponent_start..index])?;
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
                exponent: DecimalExponent::zero(),
            });
        };
        digits = digits[first_nonzero..].to_vec();

        let trailing_zeroes = digits
            .iter()
            .rev()
            .take_while(|digit| **digit == b'0')
            .count();
        if trailing_zeroes > 0 {
            digits.truncate(digits.len() - trailing_zeroes);
        }

        let exponent = explicit_exponent
            .sub_usize(fraction_length)
            .add_usize(trailing_zeroes);

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
        self.is_zero() || self.exponent.is_nonnegative()
    }

    fn canonical_key(&self) -> String {
        let digits =
            std::str::from_utf8(&self.digits).expect("normalized decimal digits are always ASCII");
        format!(
            "{}{}e{}",
            if self.negative { "-" } else { "" },
            digits,
            self.exponent.canonical_string()
        )
    }

    fn canonical_lexeme(&self) -> Vec<u8> {
        if self.is_zero() {
            return vec![b'0'];
        }
        if let Some(integer) = self.representable_integer_lexeme() {
            return integer;
        }

        let decimal_point = self.exponent.add_usize(self.digits.len());
        if let Some(decimal_point) = decimal_point.small_i128() {
            if (-5..=21).contains(&decimal_point) {
                return self.plain_lexeme(decimal_point);
            }
        }

        self.scientific_lexeme()
    }

    fn plain_lexeme(&self, decimal_point: i128) -> Vec<u8> {
        let mut output = Vec::with_capacity(self.digits.len().saturating_add(24));
        if self.negative {
            output.push(b'-');
        }

        if decimal_point <= 0 {
            output.extend_from_slice(b"0.");
            let leading_zeroes = usize::try_from(-decimal_point)
                .expect("plain decimal notation inserts at most five leading zeroes");
            output.resize(output.len().saturating_add(leading_zeroes), b'0');
            output.extend_from_slice(&self.digits);
            return output;
        }

        let decimal_point = usize::try_from(decimal_point)
            .expect("plain decimal notation uses a small positive point position");
        if decimal_point >= self.digits.len() {
            output.extend_from_slice(&self.digits);
            output.resize(
                output
                    .len()
                    .saturating_add(decimal_point.saturating_sub(self.digits.len())),
                b'0',
            );
        } else {
            output.extend_from_slice(&self.digits[..decimal_point]);
            output.push(b'.');
            output.extend_from_slice(&self.digits[decimal_point..]);
        }
        output
    }

    fn scientific_lexeme(&self) -> Vec<u8> {
        let mut output = Vec::with_capacity(self.digits.len().saturating_add(48));
        if self.negative {
            output.push(b'-');
        }
        output.push(self.digits[0]);
        if self.digits.len() > 1 {
            output.push(b'.');
            output.extend_from_slice(&self.digits[1..]);
        }

        let scientific_exponent = self.exponent.add_usize(self.digits.len() - 1);
        output.push(b'e');
        scientific_exponent.append_canonical(&mut output, true);
        output
    }

    fn representable_integer_lexeme(&self) -> Option<Vec<u8>> {
        if !self.is_integer() {
            return None;
        }
        if self.is_zero() {
            return Some(vec![b'0']);
        }

        let appended_zeroes = self.exponent.as_usize()?;
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

        let left_order = self.exponent.add_usize(self.digits.len());
        let right_order = other.exponent.add_usize(other.digits.len());
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

#[derive(Debug, Clone, PartialEq, Eq)]
struct DecimalExponent {
    negative: bool,
    /// Canonical decimal magnitude: ASCII digits, no leading zeroes, and zero
    /// represented by one `0` digit.
    digits: Vec<u8>,
}

impl DecimalExponent {
    fn zero() -> Self {
        Self {
            negative: false,
            digits: vec![b'0'],
        }
    }

    fn from_digits(negative: bool, digits: &[u8]) -> Option<Self> {
        if digits.is_empty() || !digits.iter().all(|digit| digit.is_ascii_digit()) {
            return None;
        }

        let Some(first_nonzero) = digits.iter().position(|digit| *digit != b'0') else {
            return Some(Self::zero());
        };
        Some(Self {
            negative,
            digits: digits[first_nonzero..].to_vec(),
        })
    }

    fn from_usize(value: usize) -> Self {
        Self {
            negative: false,
            digits: value.to_string().into_bytes(),
        }
    }

    fn is_zero(&self) -> bool {
        self.digits.as_slice() == b"0"
    }

    fn is_nonnegative(&self) -> bool {
        !self.negative
    }

    fn add_usize(&self, value: usize) -> Self {
        self.add(&Self::from_usize(value))
    }

    fn sub_usize(&self, value: usize) -> Self {
        let mut operand = Self::from_usize(value);
        if !operand.is_zero() {
            operand.negative = true;
        }
        self.add(&operand)
    }

    fn add(&self, other: &Self) -> Self {
        if self.negative == other.negative {
            return Self::normalized(self.negative, add_magnitudes(&self.digits, &other.digits));
        }

        match compare_magnitudes(&self.digits, &other.digits) {
            Ordering::Greater => Self::normalized(
                self.negative,
                subtract_magnitudes(&self.digits, &other.digits),
            ),
            Ordering::Less => Self::normalized(
                other.negative,
                subtract_magnitudes(&other.digits, &self.digits),
            ),
            Ordering::Equal => Self::zero(),
        }
    }

    fn normalized(negative: bool, digits: Vec<u8>) -> Self {
        let first_nonzero = digits.iter().position(|digit| *digit != b'0');
        let Some(first_nonzero) = first_nonzero else {
            return Self::zero();
        };
        Self {
            negative,
            digits: digits[first_nonzero..].to_vec(),
        }
    }

    fn cmp(&self, other: &Self) -> Ordering {
        if self.negative != other.negative {
            return if self.negative {
                Ordering::Less
            } else {
                Ordering::Greater
            };
        }

        let magnitude = compare_magnitudes(&self.digits, &other.digits);
        if self.negative {
            magnitude.reverse()
        } else {
            magnitude
        }
    }

    fn small_i128(&self) -> Option<i128> {
        let mut magnitude = 0_i128;
        for digit in &self.digits {
            magnitude = magnitude
                .checked_mul(10)?
                .checked_add(i128::from(*digit - b'0'))?;
        }
        if self.negative {
            magnitude.checked_neg()
        } else {
            Some(magnitude)
        }
    }

    fn as_usize(&self) -> Option<usize> {
        if self.negative {
            return None;
        }
        let mut value = 0_usize;
        for digit in &self.digits {
            value = value
                .checked_mul(10)?
                .checked_add(usize::from(*digit - b'0'))?;
        }
        Some(value)
    }

    fn canonical_string(&self) -> String {
        let mut output = Vec::with_capacity(self.digits.len().saturating_add(1));
        self.append_canonical(&mut output, false);
        String::from_utf8(output).expect("canonical decimal exponents are ASCII")
    }

    fn append_canonical(&self, output: &mut Vec<u8>, explicit_positive_sign: bool) {
        if self.negative {
            output.push(b'-');
        } else if explicit_positive_sign {
            output.push(b'+');
        }
        output.extend_from_slice(&self.digits);
    }
}

fn compare_magnitudes(left: &[u8], right: &[u8]) -> Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

fn add_magnitudes(left: &[u8], right: &[u8]) -> Vec<u8> {
    let mut left_index = left.len();
    let mut right_index = right.len();
    let mut carry = 0_u8;
    let mut reversed = Vec::with_capacity(left.len().max(right.len()).saturating_add(1));

    while left_index > 0 || right_index > 0 || carry > 0 {
        let left_digit = if left_index > 0 {
            left_index -= 1;
            left[left_index] - b'0'
        } else {
            0
        };
        let right_digit = if right_index > 0 {
            right_index -= 1;
            right[right_index] - b'0'
        } else {
            0
        };
        let sum = left_digit + right_digit + carry;
        reversed.push(b'0' + sum % 10);
        carry = sum / 10;
    }

    reversed.reverse();
    reversed
}

fn subtract_magnitudes(left: &[u8], right: &[u8]) -> Vec<u8> {
    debug_assert!(compare_magnitudes(left, right) != Ordering::Less);

    let mut left_index = left.len();
    let mut right_index = right.len();
    let mut borrow = 0_i16;
    let mut reversed = Vec::with_capacity(left.len());

    while left_index > 0 {
        left_index -= 1;
        let mut digit = i16::from(left[left_index] - b'0') - borrow;
        let right_digit = if right_index > 0 {
            right_index -= 1;
            i16::from(right[right_index] - b'0')
        } else {
            0
        };
        if digit < right_digit {
            digit += 10;
            borrow = 1;
        } else {
            borrow = 0;
        }
        reversed.push(b'0' + u8::try_from(digit - right_digit).expect("decimal digit"));
    }

    while reversed.len() > 1 && reversed.last() == Some(&b'0') {
        reversed.pop();
    }
    reversed.reverse();
    reversed
}

#[cfg(test)]
mod tests {
    use super::*;

    const I128_MAX: &str = "170141183460469231731687303715884105727";
    const I128_MAX_PLUS_ONE: &str = "170141183460469231731687303715884105728";
    const I128_MAX_PLUS_TWO: &str = "170141183460469231731687303715884105729";

    #[test]
    fn canonicalizes_equivalent_non_integral_spellings() {
        for spelling in ["1.5", "1.50", "15e-1", "0.150e1", "1500e-3"] {
            assert_eq!(canonical(spelling), "1.5");
        }
        assert_eq!(canonical("-0.0"), "0");
        assert_eq!(canonical("10e399"), "1e+400");
        assert_eq!(canonical("10e-401"), "1e-400");
    }

    #[test]
    fn exponents_beyond_i128_are_exact_and_do_not_collapse() {
        let at_max = format!("1e{I128_MAX}");
        let ten_at_max = format!("10e{I128_MAX}");
        let above_max = format!("1e{I128_MAX_PLUS_ONE}");

        assert_eq!(canonical(&at_max), format!("1e+{I128_MAX}"));
        assert_eq!(canonical(&ten_at_max), format!("1e+{I128_MAX_PLUS_ONE}"));
        assert_eq!(canonical(&above_max), format!("1e+{I128_MAX_PLUS_ONE}"));
        assert_ne!(canonical(&at_max), canonical(&ten_at_max));

        let negative_boundary = format!("1e-{I128_MAX_PLUS_ONE}");
        let equivalent_negative = format!("10e-{I128_MAX_PLUS_TWO}");
        let distinct_negative = format!("10e-{I128_MAX_PLUS_ONE}");
        assert_eq!(
            canonical(&negative_boundary),
            canonical(&equivalent_negative)
        );
        assert_ne!(canonical(&negative_boundary), canonical(&distinct_negative));
    }

    #[test]
    fn equality_and_ordering_remain_exact_at_exponent_boundaries() {
        let at_max = number(&format!("1e{I128_MAX}"));
        let ten_at_max = number(&format!("10e{I128_MAX}"));
        let above_max = number(&format!("1e{I128_MAX_PLUS_ONE}"));
        assert_eq!(compare_numbers(&at_max, &ten_at_max), Ordering::Less);
        assert_eq!(compare_numbers(&ten_at_max, &above_max), Ordering::Equal);
        assert_eq!(
            canonical_number_key(&ten_at_max),
            canonical_number_key(&above_max)
        );

        let negative_boundary = number(&format!("1e-{I128_MAX_PLUS_ONE}"));
        let equivalent_negative = number(&format!("10e-{I128_MAX_PLUS_TWO}"));
        assert_eq!(
            compare_numbers(&negative_boundary, &equivalent_negative),
            Ordering::Equal
        );
        assert_eq!(
            canonical_number_key(&negative_boundary),
            canonical_number_key(&equivalent_negative)
        );
    }

    #[test]
    fn very_long_exponents_remain_compact_and_exact() {
        let exponent = "9".repeat(512);
        let token = format!("1e{exponent}");
        assert_eq!(canonical(&token), format!("1e+{exponent}"));

        let shifted = format!("10e{exponent}");
        let shifted_canonical = canonical(&shifted);
        assert!(shifted_canonical.starts_with("1e+1"));
        assert_eq!(shifted_canonical.len(), exponent.len() + 4);
        assert_ne!(canonical(&token), shifted_canonical);
    }

    fn canonical(text: &str) -> String {
        String::from_utf8(representable_integer_lexeme(text.as_bytes()).expect("valid JSON number"))
            .expect("canonical number is UTF-8")
    }

    fn number(text: &str) -> Number {
        serde_json::from_str(text).expect("valid arbitrary-precision JSON number")
    }
}
