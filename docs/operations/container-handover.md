# Replace a standalone container safely

One node owns a durable installation at a time. A replica limit does not establish
ownership during a replacement: some orchestrators start the next revision while
the previous one still serves. This guide uses an explicit stop-before-start
sequence on the [local container profile](container-runtime.md). Expect downtime.
Azure revision behavior is not qualified by this local procedure.

## Prepare the replacement

Keep the old container, its approved image ID, protected configuration and a
[complete stopped backup](local-storage-recovery.md) available for recovery.
Prepare the next container **without starting it**, using the same coupled data
and cache roots, reviewed configuration, non-root user and runtime restrictions.
Keep management private. Run the candidate image's bounded `check` against the
reviewed mounts before planning a cutover.

The container entrypoint acquires a process-lifetime lock in the shared data
root. A second container with an independent network namespace is rejected at
that fence, before native catalog access or admission. Existing catalog locks
remain in force. Do not delete lock files: ownership is released when the actual
owner exits. A per-container private data root would not protect shared state.

## Stop, verify exit, then start

Run these commands in an administrative session on the Docker host. `Current`
and `Next` identify the prepared exact containers, not an unreviewed moving image
tag. Remove the old instance from the edge's ready backend set first:

```sh
docker stop --time 10 "$Current"
docker inspect --format '{{.State.Running}} {{.State.ExitCode}}' "$Current"
```

Require `false 0` for an orderly handover. If the response is interrupted, inspect
the **same** container before doing anything else. Do not assume that a lost
response means it remains running, or that a timeout means it stopped. Keep the
old definition and all state. Wait for the configured persisted supply-chain
clock lease; the maintained test uses a five-second lease and a six-second wait.
Then start only the prepared replacement:

```sh
docker start "$Next"
docker exec "$Next" /opt/lsf/release/bin/latent --config /etc/lsf/client.json --output json node get "$NodeId"
```

Require the expected authenticated node identity, known outcome, available
pressure and `data.inventory.health.ready: true`. Verify actual static content,
GET/HEAD route targets and original publication receipts before returning the
backend to traffic. An open port or a successful `docker start` is not readiness.
The entrypoint's nonblocking fence also protects against a mistaken concurrent
start; that refusal does not itself complete deployment.

## Recover an interrupted replacement

If the old owner is still running, leave the replacement stopped. If it exited
and the replacement is ready, finish read-only verification of the replacement.
If neither is ready, preserve the diagnostics and state, establish that neither
process owns the installation, and choose an explicitly eligible recovery image.
After SIGKILL, the operating system releases the dead owner's descriptor; the
next node reopens its native state and enforces the clock floor. Never force
recovery by removing a lock, intent, receipt or format marker.

The maintained rollback pair is two container revisions of the **same
authenticated runtime image and state format**. It kills the replacement, waits
for the lease, starts the retained original container and verifies both sites and
their publication receipts. This establishes recovery of an interrupted container
replacement. It does not authorize downgrading to an earlier LSF binary. A binary
upgrade or downgrade must have an explicit compatible native release pair and
its own [installation/upgrade qualification](../installation.md); otherwise keep
it out of this container procedure. Restoring a complete compatible stopped
backup into a separate installation is the recovery alternative.

## Measured behavior and limits

The CI receipt records clean cutover and forced-termination recovery duration,
including its explicit clock-lease wait. Use the measured receipt for your
actual host and reserve downtime; do not advertise zero-downtime replacement of
a single durable owner. The real drill verifies overlap refusal across separate
containers, continued service from the old owner, clean replacement, SIGKILL,
abandoned-owner recovery and the eligible same-image rollback. It runs together
with the two-site update and full backup/restore drill on the chosen local mount.

Content publication updates use the existing node and
[route-set reconciliation](static-route-sets.md). They do not replace a runtime
container. No ACA revision, remote mount, distributed fence, host power failure
or different-version runtime rollback is claimed by these results.
