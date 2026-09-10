These bounded original bytes come from the third dirty-source catalog diagnostic,
snapshot `2abef5f89c22a86a292eadad4ef8f01231a5f4cffc8dbc3ad254d5dd322d5381`.
The original JSON explicitly declares `qualifying: false` and a dirty debug source.
The fixture retains the 604-operation initial graph, its 7-operation reopen,
one 98-operation allocation-mode functional graph, source sampler rows and the
unchanged Echo inputs. No Heaptrack profile, release build or full suite is asserted.

Tests replay the actual operation/resource protocol and semantic negatives. They
do not promote the diagnostic identity or its pretty-printed data marker into a
qualified build/suite. `manifest.json` binds every original uncompressed byte stream;
the three raw graphs use deterministic gzip solely to bound repository storage.
