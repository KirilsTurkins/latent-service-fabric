# Optimization comparison workloads

This package supplies identical pure Rust logic to the native reference and the
`lsf:optimization/service@0.1.0` component. Both export the
`lsf:optimization/workloads@0.1.0` interface:

- `echo(message: string) -> string` preserves the UTF-8 message, including empty input.
- `compute(seed: u32, rounds: u32) -> u32` uses the documented wrapping recurrence in `compute`; zero rounds returns the seed.
- `transform(value: record { label: string, bytes: list<u8>, values: list<u32> }) -> same record` preserves the label, reverses bytes, and applies wrapping multiply/add/rotate to each integer using its original index.

Argument and result frames are LSF WIT-value JSON arrays. For example, echo uses
`["hello"]` in both directions. Transform output fields are always ordered
`label`, `bytes`, `values`; u8/u32 are JSON integers, not decimal strings.

Limits are 1 MiB per frame and text value, 4,096 elements per collection
and 1,000,000 compute rounds. The native helper rejects values beyond those bounds
without clamping. The component calls the same functions and traps on a rejected
value because its requested WIT signatures have no declared-error result. Native
invalid-input errors and guest traps are distinct failure mechanisms, outside the
accepted-input performance comparison. Plans must pass the shared helper before
dispatch. This package supplies no fabric isolation or resource-budget enforcement.
