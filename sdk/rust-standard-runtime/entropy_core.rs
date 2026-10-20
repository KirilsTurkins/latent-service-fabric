// SPDX-License-Identifier: MIT OR Apache-2.0
// Compiler-owned synchronous canonical RANDOM scalar boundary. Both consumers
// are compiled from these exact bytes; this is neither a seed nor a fallback.
#[repr(C, align(8))]
struct ScalarResult {
    tag: u8,
    padding: [u8; 7],
    payload: u64,
}

const _: () = assert!(core::mem::size_of::<ScalarResult>() == 16);
const _: () = assert!(core::mem::align_of::<ScalarResult>() == 8);
const _: () = assert!(core::mem::offset_of!(ScalarResult, payload) == 8);

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "latent:random/random@0.1.0"))]
unsafe extern "C" {
    #[cfg_attr(target_arch = "wasm32", link_name = "u64-value")]
    fn lsf_entropy_scalar(result: *mut ScalarResult);
}

fn approved_fill(destination: &mut [u8]) -> Result<(), u8> {
    if destination.len() > 65_536 {
        return Err(0); // The existing typed invalid-length ordinal.
    }
    for chunk in destination.chunks_mut(8) {
        let mut result = ScalarResult { tag: 0, padding: [0; 7], payload: 0 };
        // SAFETY: canonical result<u64, random-error> has the exact asserted
        // layout. The private stack result remains live through actual lowering.
        unsafe { lsf_entropy_scalar(&mut result) };
        match result.tag {
            0 => chunk.copy_from_slice(&result.payload.to_le_bytes()[..chunk.len()]),
            1 if result.payload <= 2 => {
                destination.fill(0);
                return Err(result.payload as u8);
            }
            _ => panic!("invalid canonical RANDOM result"),
        }
    }
    Ok(())
}
