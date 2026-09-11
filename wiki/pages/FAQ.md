<!-- LSF-WIKI-MANAGED -->
# Frequently asked questions

## Is LSF still a scaffold?

The single-node runtime, catalogs, CLI and supported RPCs are implemented; Phase 1 is complete. Later-phase subsystems retain interfaces/designs. The alpha release does not claim production readiness.

## Is each service a process or container?

Dormant services are metadata and artifacts. Invocations lease generic capacity and own temporary guest state. Fixed execution topology does not imply constant catalog RSS.

## Is it faster than Docker or Kubernetes?

Native handlers were faster in every headline warm pair. LSF reduced dense-cohort leaf memory and startup costs; single-service memory favored native. See [performance and infrastructure](Performance-and-Infrastructure).

## Can I rely on a 1 or 2 ms deadline?

There is no universal guarantee. Historical resident Echo achieved 99.7857% useful success at 2 ms and zero at 1 ms. Later one-second-budget infrastructure percentiles do not retest that deadline target. Cold preparation, queues, transport and cleanup require headroom.

## Does accepted cancel mean cleanup is finished?

No. Accepted cancellation, terminal status, disconnect and native reclamation differ. Keep a known activation ID and inspect explicit status/cancel responses; do not automatically retry unknown outcomes.

## Are SDKs ready-made network clients?

They are interface models with executable fixtures, without transports/serializers/retries. The current CLI has an actual generated gRPC implementation.

## Does the Kubernetes benchmark deliver LSF clustering?

No. It deploys standalone LSF and native comparators on actual local Kubernetes. Clustered control, HA and multi-zone placement remain later work.

## What comes next?

Phase 2 packaging/supply chain: OCI, signatures/provenance/SBOM, trusted AOT distribution and rollout orchestration. See [Roadmap](Roadmap).
