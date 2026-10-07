# Transactional pull input

The opt-in library path extends the existing `NatsTriggers` owner. The stateless configuration and acknowledgement policy remain supported. A transactional binding supplies a stable processing scope, an installed namespace/incarnation, a measured JetStream stream creation identity and finite state/intent budgets. The configured stream must retain accepted history for the existing seven-day command identity window, or disable age eviction while keeping its finite message and byte ceilings. Immediate child and outbound calls are refused.

The owner reserves the original node admission and input buffer before its bounded one-message pull. It checks authenticated server software and literal protected stream configuration before and after receiving the physical message. The durable input identity frames tenant, logical provider, stream creation, stable processing scope, namespace/incarnation and stream sequence. Consumer display names, configuration epochs, reusable credentials, redelivery counters and activation IDs do not select a new command. An exact digest binds the received payload; different bytes under the same trusted identity remain a conflict.

`InboxDelivery` has no public constructor. The installed host consumes this descriptive identity through `InboxAdmissionFactory`, retaining the same `InboundActivationReservation`. The provided `StateRuntime` implementation selects its actual signed operation, current publication and matching namespace/incarnation, and uses its existing command coordinator, original-source lookup, quotas, caller authority and canonical result codec. The inbox row is part of that same atomic state/command/result/outgoing-intent envelope. HTTP commands keep their inbox field absent.

Acknowledgement requires a sealed terminal transaction disposition whose original command and inbox linkage match the delivery. Original committed success and durable business rejection permit `+ACK`, including authorized duplicate recovery. Ordinary activation success, missing or uncertain disposition, technical abort and cleanup failure do not manufacture an acknowledgement or a retry fence. The owner rechecks stream history before acknowledging a completed transaction. Lost acknowledgements keep the existing uncertain transport result. Saturation and exhausted deliveries cannot silently terminate an unresolved transactional input or start a new command attempt.

Ordinary standalone configuration accepts the closed optional `transactionalTriggers` installation with `id`, `epoch`, a protected `configurationFile`, a protected `credentialDirectory` and at most eight tenant-scoped credential file references. The main node document retains its 64 KiB ceiling; the separate private trigger document retains the existing 512 KiB ceiling. Both paths are anchored to the configuration parent. Literal values or ambient credential sources are not accepted. The node requires protected Linux configuration, Phase4 accounting, installed State, audit, current capability policy and enforced supply-chain owners. The configured signed operations must match before the input owner starts.

The existing node ProviderRuntime supplies the single actual pool/broker and the separately retained incoming credential store, including an input-only configuration with no guest publisher binding. The node opens State first, prepares one caller-driven consumer task, and enables pulls after normal service readiness. Shutdown stops new pulls before its natural drain, joins the real input task under the original cutoff, then observes shared provider/state teardown. `transactional_trigger_status()` and the optional shutdown projection report actual fixed-owner counters; they supply no caller or broker authority.

The library and standalone configuration validation do not establish installed-node readiness against the live broker or the required crash and recreation races. Automatic poison disposition and approved technical retries require separate positive no-commit and physical-retirement evidence. Snapshot/restore, retention-edge clocks and authenticated incoming pause/drain controls remain qualification work.

## Entity admission

Installed command admission uses the shared finite entity table described in
[installed entity eligibility](installed-entity-eligibility.md). Transactional
inbox deliveries reuse that same command factory and its physical retirement
owners.

## Signed outgoing event requirements

The maintained Rust `transactional-aggregate` authoring recipe captures
`deferred-event-requirements.json` beside its transaction binding and packages
those exact bytes as a signed asset. It declares one `approved-event` intent
with an eight-byte `application/vnd.lsf.aggregate-v1` value and empty metadata.
The namespace, state-schema digest, companion digest and operation set must
match the captured binding. Packaging refuses a changed declaration.

An installed strict-command operation selects this asset with the closed
`deferredEvent` configuration: `requirementsDigest`, `topic`,
`stagingBinding`, `stagingPolicies`, `dispatchBinding` and `dispatchPolicies`.
The topic must already have an operator-qualified deferred mapping on the
node's existing NATS publisher. The runtime captures its actual configuration
digest and epoch, intersects current caller staging policy and derives the
independent dispatch service principal from the signed publication. A
declaration or configuration string never grants either permission.

The payload constraint narrows the original host count/byte ledgers. The
declaration reader retains the existing 8 KiB effect-requirements bound,
the default 32-intent cap and the existing application profile's 64 KiB
payload/16-attempt bounds. The actual NATS adapter adds its configured payload
limit and mandatory 16 KiB response buffers. Existing HTTP exact-digest
requirements and OrderDraft notification packaging keep their original
behavior.

Startup inspection reports these descriptive bindings in `deferredEvents`;
`deferredHttp` keeps its HTTP entries. Recovery resolves the same actual NATS
adapter profile. Event dispatch uses the existing EffectRuntime inspection,
pause/resume and prepared management-control ports under their current
authorization. It installs no extra publisher, broker, pool or consumer.

Compiler capture, payload-filter and decoder tests do not establish signed
ordinary-node execution or authenticated JetStream ACK/crash behavior. Those
campaigns must execute the installed factory, original ingress and actual
provider owners before issue completion.

The current shared-runtime union retains the original entity-lane table, physical command owners, current policy and namespace fences, and protected incoming owner. Local qualification of its separate source parents does not qualify this union. Real signed-node TLS JetStream delivery, ACK/recovery/retention schedules, six-language execution and authenticated shared-scope incoming management remain required.
