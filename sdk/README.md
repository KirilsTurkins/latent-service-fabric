# SDK surfaces

The SDK directories contain interface-only client and guest programming models. They do not contain transports, serializers, retry logic, code generation, or runtime integration.

WIT remains authoritative for typed capsule contracts. Language SDKs are convenience surfaces and must preserve deadlines, cancellation, platform errors, domain errors, resource budgets, identity, and idempotency semantics.
