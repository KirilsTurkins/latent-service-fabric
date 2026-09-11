# Validation receipts

These command receipts and nonempty captures retain their original bytes,
including Windows line endings and original local paths. The two failed setup
commands (`smoke-01` and `smoke-02`) produced empty stdout captures; their exit
receipts are published here, and their complete original failure, API and cleanup
evidence is retained under `attempts/` inside the raw archive. Empty wrapper
captures are not replaced with invented output.

`stage-01` records the rejected 5,014-file preflight before a staging directory
was created. `stage-02` records staging, and `stage-independent-01` records the
verified independent copies required by the archive's no-hard-links policy.
`package-linux.json` records complete Linux archive replay. Windows replay 01
failed on a validator path-separator assumption; replay 02 passed after that
validator correction, using the same archive bytes. None of these transport or
replay steps reran guest work.
