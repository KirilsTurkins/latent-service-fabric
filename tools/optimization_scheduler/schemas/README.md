# Scheduler evidence shapes

These Draft 2020-12 schemas describe completed build receipts, collector inputs,
raw arm output, suite envelopes and aggregate envelopes. They are private
benchmark contracts, separate from application manifest schemas.

Run `tools/validate_optimization_scheduler.py` for semantic validation. Structural
schema validation alone does not prove exact population, timestamp ordering,
original deadlines, cleanup, source equality, process ownership, artifact hashes,
statistical summaries or selected allocation coverage. Nested shared process and
resource documents retain their existing semantic validators. Partial failed
build/collection receipts remain diagnostic evidence even when they do not satisfy
a completed document's structural schema.

The selector plan and suite plan encode fixed smoke/full populations. Integer
fields also undergo strict Python type checks during replay; JSON Schema's
mathematical integer semantics do not substitute for those checks.
