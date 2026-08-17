# Security Policy

LSF assumes capsule code, capsule inputs, remote invocation payloads, and external provider responses are untrusted unless an explicit policy says otherwise.

Security-sensitive reports should not be opened as public issues. Until a private disclosure channel is established, document the issue locally and contact the repository maintainers through a private GitHub security advisory.

The initial trusted computing base is expected to include the node runtime, execution engine, artifact verifier, capability providers, policy engine, state commit coordinator, trusted compiler boundary, and host operating system.
