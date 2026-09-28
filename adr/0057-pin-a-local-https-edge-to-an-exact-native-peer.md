# ADR-0057: Pin a local HTTPS edge to an exact native peer

Status: Accepted

## Context

The native trusted-proxy profile requires exact numeric peers and a fixed public
HTTPS scheme. Forwarded headers are not identity. The owner excludes Azure
resources and simulated cloud qualification; unknown managed ingress peers
cannot be added to the supported matrix on that basis.

## Decision

Qualify a local Linux alternative: one reviewed Node.js 24 TLS edge and one native
node in a protected shared network namespace. The edge connects from fixed
`127.0.0.2` to fixed `127.0.0.1` and the configured native port. Native ingress
allows that exact peer only. No DNS, redirects to other backends, credential
injection, route rewriting or public management is available in the edge.

The closed edge profile permits one exact authority and bodyless GET/HEAD. It
rejects incoming forwarding and platform-identity headers rather than translating
them into authority. Host, Origin and Fetch Metadata remain intact. Native
selection, publication eligibility, CSP and every browser response header remain
authoritative; the edge copies original response bytes and validators.

The edge is trusted deployment code, not a capsule or an authentication service.
Its private TLS volume contains no management credential. Protect the shared
namespace from unrelated processes; loopback source addresses are not a defense
against a host administrator. HTTP probes remain on the separate private adapter
port and cannot be reached through an edge route.

Bound the edge to 16 connections, eight exchanges, 32 headers, 8 KiB headers and
8 MiB responses. Stream with backpressure, use five-second total connection and
exchange lifetimes, two-second TLS/header/idle limits, and one request per socket.
There is no application queue, per-publication worker, content cache or retry.
An exchange owner survives until both directions close. Cancellation destroys
the upstream connection; the native node retains its own physical cleanup owner.
Run with 192 MiB memory, 128 MiB V8 old-space and 32 process/task slots.

## Evidence and limitations

The maintained drill uses independently authenticated released native binaries,
real signed publications and actual certificate-verified TLS requests. It checks
root and mounted paths, HEAD/304, redirects, HTTPS origins, HSTS, rejected foreign
origins/Fetch Metadata/forged authority, wrong certificates/names, direct untrusted
peers, disconnects, private readiness and clean shutdown. Recreating the edge and
probe after the node's network namespace changes preserves the exact peer and
published bytes. Receipts record native idle ownership and sampled edge overhead.

ACA peer lifecycle, Azure routing and Terraform resources remain unqualified.
No local observation claims otherwise. Operators needing those environments
must first qualify their real topology; the supported alternative here is a
controlled Linux host. Native direct TLS is also available when no edge is needed.
