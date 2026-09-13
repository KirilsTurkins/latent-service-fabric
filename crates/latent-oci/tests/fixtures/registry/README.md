# Disposable registry credentials

The `htpasswd` file is a **public, test-only** bcrypt credential:
`lsf-test-only` / `lsf-test-only-password`. Never configure a deployed registry
with it. It was generated with Apache `htpasswd -nbB` and is created before
the pinned Zot minimal 2.1.18 registry starts.

[`tools/run_oci_registry_tests.py`](../../../../../tools/run_oci_registry_tests.py)
generates a fresh, short-lived test CA and a certificate for `127.0.0.1` using
OpenSSL. The test adapter explicitly trusts only that additional CA; certificate
and hostname verification stay enabled. Keys and certificates live in a temporary
directory and are removed after the owned container stops. No private production
credentials, registry data volume or success reports are retained.

The package-format corpus used by the integration test establishes exact byte
distribution for capsule, browser and SSR kinds. Its capsule bytes and detached
evidence are intentionally format fixtures, not executable or trusted releases.
