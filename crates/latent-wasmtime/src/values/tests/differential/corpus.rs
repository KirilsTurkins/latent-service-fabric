use super::*;

mod inputs;

const CASE_LIMIT: usize = 4096;
const BYTE_LIMIT: usize = 32 * 1024 * 1024;

#[derive(Default)]
struct Corpus {
    cases: usize,
    bytes: usize,
    accepted: usize,
}

impl Corpus {
    fn check(&mut self, signature: &[Type], bytes: &[u8], accepts: bool) {
        self.cases += 1;
        self.bytes = self
            .bytes
            .checked_add(bytes.len())
            .expect("corpus byte sum");
        assert!(self.cases <= CASE_LIMIT && self.bytes <= BYTE_LIMIT);
        assert!(bytes.len() <= 16 * 1024, "generated case input cap");
        let label = format!("fixed seed case {}", self.cases);
        let result = equivalent(&label, signature, bytes, ValueCodecLimits::default());
        assert_eq!(result.is_ok(), accepts, "{label}: independent validity");
        if accepts {
            self.accepted += 1;
        }
    }

    fn mutations(&mut self, signature: &[Type], bytes: &[u8]) {
        self.check(signature, bytes, true);
        let mut whitespace = b" \n\t".to_vec();
        whitespace.extend_from_slice(bytes);
        whitespace.extend_from_slice(b"\r\n ");
        self.check(signature, &whitespace, true);
        let mut suffix = bytes.to_vec();
        suffix.extend_from_slice(b" null");
        self.check(signature, &suffix, false);
        for end in [0, bytes.len() / 2, bytes.len() - 1] {
            self.check(signature, &bytes[..end], false);
        }
        let mut invalid_utf8 = bytes.to_vec();
        invalid_utf8[bytes.len() / 2] = 0xff;
        self.check(signature, &invalid_utf8, false);
    }
}

#[test]
fn fixed_seed_scalar_record_tagged_and_nested_corpus_has_an_exact_finite_population() {
    let mut random = inputs::Random::new();
    let mut corpus = Corpus::default();
    for _ in 0..128 {
        for family in 0..4 {
            let (signature, input) = inputs::case(&mut random, family);
            corpus.mutations(&signature, input.as_bytes());
        }
    }
    assert_eq!(corpus.cases, 3584);
    assert_eq!(corpus.accepted, 1024);
    assert!(corpus.bytes < BYTE_LIMIT);
}
