# Bounded TypeScript standard console

Declaring the exact `latent:log/log@0.1.0` WIT import selects the compiler-owned
`lsf-console-strict-v1` candidate. The normal SDK capture includes its global
declaration. This selects compatibility code; the package still needs its
existing LOG provider binding, operator grant and finite `logBytes` budget.
Undeclared worlds retain their existing compilation path. The compiler rejects
an altered LOG contract or an application attempt to override its backend.

`console.log`, `info`, `debug`, `warn` and `error` synchronously call typed
`write`. `log` maps to `info`; the other four preserve their severity. Accepted
writes return `undefined`. A false acknowledgement or a typed host failure
throws immediately. Only strict policy is implemented: there is no best-effort
drop mode, retry, worker, hidden buffer or flush/delivery acknowledgement.
An empty argument list performs no write. Host correlation and exact encoded
LogBytes accounting remain in the existing host implementation; the adapter
supplies no fields or caller-selected identity. Logging a string does not make
its contents public or automatically remove secrets from it.

The finite printer accepts strings, numbers, booleans, null and undefined,
with at most 16 arguments and 256 encoded UTF-8 bytes per message. Arguments
are joined with spaces. `%s`, `%d`/`%i` and `%f` use the
[Console Standard formatter](https://console.spec.whatwg.org/#formatter)
string, base-10 integer and floating conversion respectively; `%%` is an
explicit escaped-percent convenience. `%d` therefore uses `parseInt`, unlike
Node's numeric `%d` extension for fractional strings, booleans or null.
Isolated UTF-16 surrogates become the replacement character before the byte
bound is checked. Objects, functions, symbols, bigint, object/CSS formatting,
trace/timing/group/table/count and other unsupported console methods fail
explicitly. No object getter, custom stringifier or JSON serialization is used.

For this explicit profile, the compiler parses the actual bundled module and
defers its direct and transitive application initializers until the first
export call in the activation. Static typed imports and compiler globals are
installed before application initialization. No initializer writes a log in
Wizer or freezes a build-machine identity, log buffer or credential. Subsequent
calls in that module instance share its live application bindings and state;
an initializer failure is sticky and is not retried. Fresh instances start
uninitialized. Top-level await, re-exports, default/resource exports and other
unreviewed export shapes fail closed. Existing source-map locations are
translated through the generated wrapper.

The `--standard-console` authoring programme preserves the normal five
projects, SDK/guide checks and original authoring/fault/HTTP assertions. Its
owned greeting adds direct/transitive initializer logs, a pre-entry omitted-
grant denial and eight accepted formatting, Unicode, exact/over-limit,
object-refusal, strict budget and fresh-state cases. It requires actual
LogBytes, zero unrelated effects and existing provider-idle/physical cleanup
checks. It uses the existing native products and original job/node deadlines.

Local Node/Acorn/esbuild and data controls are source evidence. The new signed
programme has not yet passed; component initialization, host correlation and
strict accounting are not newly qualified by those local controls. This is a
partial TypeScript logging/initialization candidate for #681, not six-language
facility, asynchronous logging, publisher, release or whole-ticket completion.
