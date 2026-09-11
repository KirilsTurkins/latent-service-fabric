# Actual catalog mutation protocol fixture

These are original bytes from `/workspace/project/target/issue108-dirty-normal-07`
in the owned Linux diagnostic container. The four successful candidate-side
collectors comprise distinct and shared catalogs, each with four publications
and an adjacent fresh-process reopen: 93 public commands, zero Invokes. They
exercise the neutral implementation, including the four explicitly counted
current pins. They are dirty debug diagnostics, not a paired benchmark or a
release qualification fixture.

The actual neutral counters record two encoder calls per mutation and a fresh
derivation for every remaining record: four normally, three after deletion.
`record_derivation_reuses` remains zero even when unchanged payloads are reused.
Empty initial opening records two encoder calls; reopening records one. These
are functional observations from the retained runs, not performance results.

The source baseline in the actual diagnostic identity is
`64467443c323064094ff75e48eb923fe3fdebbde`; the dirty source snapshot is
`f9c750b1764fd7999b2cf577aca3ab36632bffa9474b8ac516624cbd3d906165`.
The original debug binary was copied and had only its debug sections stripped.
Its executed identity remains in each original identity/process receipt:
115,456,152 bytes, SHA-256
`6bca7331e59a8d95e02fb6653e50c522e8290b252d940470f2f7ddabc2c9cfca`.
The original source and binary transformation receipts are retained; neither
the executable nor a reconstructed clean build receipt is included.

`manifest.json` binds 44 original files, 586,947 expanded bytes, to 74,530 bytes
of individual deterministic gzip files. It records every original path, length
and SHA-256 alongside each compressed file's length and SHA-256. Raw JSON is
not normalized or regenerated. The four raw SHA-256 values are:

| Shape / owner | Original raw SHA-256 |
| --- | --- |
| distinct / initial | `0859964af3f95331d327004ac8feeaf4be1e7202e76776688c26b720aa97a4d6` |
| distinct / reopen | `9ed65b5753d30d98f9ef8605677edb7d07625cca803740c5c6c79df113b37f01` |
| shared / initial | `5c887363e4f3af61bee208c82f04f846ff84da601369f44537187c865686263b` |
| shared / reopen | `df985e14d0515a0dc143dd9a81e834b7b4953f14b62879698df784684efe4e69` |

The subset includes the actual raw memory, CPU, observer and proof records;
plans and dirty identities; collector logs and process receipts; sampler data;
root markers, post-exit handoffs, reserve and cleanup receipts; and the original
Echo component, metadata and canonical source fixtures. The large executable
and derived `diagnostic-replay.json` are excluded. The suite retains its explicit
`qualifying: false` label and cannot satisfy the closed release suite schema.

The regression test restores only the declared files into a fresh temporary
directory, verifies both compressed and original hashes, and limits extraction
to 64 files, 1 MiB per file and 2 MiB in total. It calls the current raw parser,
event validator and persistence validator against the retained inputs. Negative
cases mutate in-memory copies; original fixture bytes remain unchanged.
