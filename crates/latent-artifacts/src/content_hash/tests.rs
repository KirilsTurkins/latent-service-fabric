use super::release_digest;

#[test]
fn canonical_digest_matches_fixed_padding_and_chunk_boundary_vectors() {
    // Independently computed SHA-256 vectors, including both SHA padding edges
    // and the repository reader's chunk boundary. Identity framing is unchanged.
    for (length, hexadecimal) in [
        (
            0,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),
        (
            55,
            "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318",
        ),
        (
            56,
            "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a",
        ),
        (
            63,
            "7d3e74a05d7db15bce4ad9ec0658ea98e3f06eeecf16b4c6fff2da457ddc2f34",
        ),
        (
            64,
            "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb",
        ),
        (
            65,
            "635361c48bb9eab14198e76ea8ab7f1a41685d6ad62aa9146d301d4f17eb0ae0",
        ),
        (
            127,
            "c57e9278af78fa3cab38667bef4ce29d783787a2f731d4e12200270f0c32320a",
        ),
        (
            128,
            "6836cf13bac400e9105071cd6af47084dfacad4e5e302c94bfed24e013afb73e",
        ),
        (
            129,
            "c12cb024a2e5551cca0e08fce8f1c5e314555cc3fef6329ee994a3db752166ae",
        ),
        (
            65535,
            "6e1bebca6a8229364a162a72ef064826c4cd7457bf54f190ef782bd9deff3e42",
        ),
        (
            65536,
            "bf718b6f653bebc184e1479f1935b8da974d701b893afcf49e701f3e2f9f9c5a",
        ),
        (
            65537,
            "008ffc88d3c96a9f307524eb361e47c5222a887fc45fa0c1fb8d429c5c23b430",
        ),
    ] {
        let bytes = vec![b'a'; length];
        assert_eq!(release_digest(&bytes).0, format!("sha256:{hexadecimal}"));
    }
    assert_eq!(
        release_digest(b"abc").0,
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    );
}
