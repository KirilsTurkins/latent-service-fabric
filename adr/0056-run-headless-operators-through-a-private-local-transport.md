# ADR-0056: Run headless operators through a private local transport

Status: Accepted

## Context

Management remains authenticated literal-loopback HTTP. A CI worker in a
different network namespace cannot reach that endpoint through its own loopback.
An interrupted response also cannot establish whether a mutation committed.
The project owner excludes Azure resources and simulated cloud qualification.

## Decision

Support a Linux/WSL host operator using a fixed local Docker Unix socket and a
fixed, noninteractive receiver in the reviewed node image. The receiver runs as
UID/GID 10001 and invokes only the released native CLI. No shell, public control
listener, exported token or arbitrary command is part of the request protocol.
An exact container ID, image ID, start instant, data mount, node and tenant bind a
selection with a 15-minute expiry. Check the container before and after dispatch;
the receiver also authenticates the selected node and credential tenant.

Docker daemon access is host administration authority. This is an alternative
for a dedicated trusted Linux operator runner, not a cloud RBAC implementation
or a least-privilege boundary against that host administrator. Never give the
socket to an application or an untrusted CI job. Native LSF authorization remains
independent and mandatory. ACA remains unqualified.

Persist a private fsynced intent journal before mutation. It binds the exact
request, original operation ID, preconditions and selected instance. Hold one
kernel lock per host journal directory and one per node receiver; contention
fails immediately. A native child inherits the latter lock until completion.
Only publish, static GET/HEAD route apply and selected inspections are allowed.
Package and evidence inputs come from a separately reviewed read-only mount.

Every channel has finite input, output and time bounds. Signal cancellation
reaps the local transport and records an uncertain outcome. A disconnected
native mutation may still commit within its original deadline. Recovery only
queries the original operation; it never republishes or reapplies a trigger.
Missing/evicted receipts stay uncertain. A renewed transport lease may inspect
the same instance; a replaced instance requires explicit operator reconciliation.

## Consequences and validation

Retain private journals outside the ephemeral CI worker. Their contents can
contain deployment metadata even though credentials are never included. Revoke
native credentials and host daemon access separately. A historical receipt does
not prove a route is currently selected or a publication remains eligible.

The maintained GitHub-hosted CI drill runs an actual worker in a separate network
namespace against the authenticated release. It publishes signed sites, verifies
bytes and GET/HEAD routes, cuts a committed response, cancels a real worker,
evicts an actual receipt with 65 competing operations, and recovers without
replay. It also checks selection expiry, changed identity, native invocation-only
credentials and actual denied daemon access. Cloud execution is not inferred.
