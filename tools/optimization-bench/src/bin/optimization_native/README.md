# Native comparison reference

`optimization-native` serves the existing invocation protobuf on one loopback
HTTP/2 listener. It uses the shared `latent-optimization-workloads` functions and
canonical JSON framing. The caller supplies a bearer token, tenant and explicit
service allowlist. Defaults are two Tokio runtime workers, four concurrent calls,
32 HTTP/2 streams per connection, 16 KiB headers and TCP_NODELAY. These transport
settings do not give the native reference LSF's global connection or queue gates.

This reference has no component compiler, Wasm store, fuel meter, guest-memory
limiter, admission scheduler, artifact catalog, telemetry pipeline or activation
journal. Its nonqueueing semaphore limits executing handlers. Each deterministic
workload has a finite input/work bound; synchronous native execution is not
preempted. The handler intersects the configured ceiling, caller wall budget,
absolute deadline and received gRPC timeout, then checks the original monotonic
deadline before and after work. Tonic also applies transport timeouts. A deadline
may therefore be observed as either a typed response or transport failure.

Successful and typed-failure responses preserve the activation ID and carry the
fixed `native-reference-v1` revision and release labels, with route generation 1.
Those labels identify this reference contract; they are not a component hash.
The parent receipt records the actual native binary hash. Wall consumption is
measured from handler entry. Other consumption fields are unavailable: their
protobuf zero values must never be interpreted as evidence of zero CPU, memory
or log cost. Cancellation and status return authenticated `Unimplemented`.

SIGINT and Linux SIGTERM stop acceptance and allow at most five seconds for the
server to finish. The parent runner retains an independent process watchdog.
Readiness and clean-stop records contain no token or request payload.
