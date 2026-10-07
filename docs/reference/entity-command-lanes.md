# Entity command lanes

Strict commands that select an entity use one shared, finite eligibility table in
`TransactionAdmissionOwners`. The lane key comes from the validated, durably
claimed command: tenant, namespace incarnation and entity. Its canonical command
identity and attempt stay associated with the original caller and publication.
Existing commands replay through durable command admission before lane admission.
Commands without an entity keep their existing storage isolation behavior.

Eligibility is acquired before the native state view, code materialization and
guest cell. Each ready key has one round-robin position. Global, tenant and key
counts, queued commands, retained bytes and wait age have finite limits. A queued
command retains its original ingress reservation and deadline. The same bounded
activation future waits for a shared wake; no key owns a task or timer.

Dispatch checks current policy, publication, namespace lifecycle and command role.
The host then observes the current namespace generation with the original sealed
decision and its original authority deadline. Final commit additionally holds the
local lane generation fence through the existing short acceptance gates.

Actual native operation, read-view, writer and recovery keepers retain independent
clones of the same physical lane owner. Guest cancellation, waiter loss and elapsed
time cannot release those clones. The fixed completion owner drops its host clone
after the commit and cleanup path; independently accepted work releases eligibility
only when it physically retires. Empty lanes are removed immediately. Observation
fences and retained response bodies do not keep an otherwise retired entity live.

`TransactionAdmissionOwners::new_with_entity_limits` supplies the installed
runtime's finite limits. `entity_snapshot` reports live keys, queued/active/cleanup
owners and charged bytes without granting authority. The ordinary configured state
runtime must pass its limits to this same constructor and retain its one existing
factory. This common runtime change does not create another installation service.

The protected-engine tests exercise serialization, independent keys, backpressure,
queued cancellation, revocation, duplicate admission, explicit entity policy,
transactional child refusal, finite configuration and cold-key reclamation. A real
detached store worker verifies that dropping the original observation and cleaning
up the host cannot release its physical lane before the worker returns. The original
lane tests retain fairness, incarnation and stale-generation coverage. Installed
configuration, ordinary-node/component execution and full ticket qualification
remain separate integration and execution gates.
