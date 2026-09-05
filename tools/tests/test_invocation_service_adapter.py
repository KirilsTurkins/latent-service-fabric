"""Structural guardrails for the Phase 1 invocation service boundary."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
WIRE = ROOT / "crates" / "latent-wire"


class InvocationServiceAdapterTests(unittest.TestCase):
    def test_generated_rpc_foundation_is_the_only_binding_source(self) -> None:
        cargo = (WIRE / "Cargo.toml").read_text(encoding="utf-8")
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((WIRE / "src").glob("invocation/**/*.rs"))
        ) + (WIRE / "src" / "invocation.rs").read_text(encoding="utf-8")

        self.assertIn("latent-rpc", cargo)
        self.assertIn("proto::invocation_service_server", source)
        self.assertIn("proto::invocation_service_client", source)
        self.assertIn("impl<R, C, P> InvocationService", source)
        self.assertFalse((WIRE / "build.rs").exists())
        self.assertFalse((WIRE / "src" / "invocation_proto.template.rs").exists())
        self.assertFalse((WIRE / "src" / "invocation" / "codec.rs").exists())

    def test_rpc_adapter_does_not_duplicate_lifecycle_ownership(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((WIRE / "src").glob("invocation/**/*.rs"))
        ) + (WIRE / "src" / "invocation.rs").read_text(encoding="utf-8")

        self.assertNotIn("InvocationIdSource", source)
        self.assertNotIn("MonotonicInvocationIdSource", source)
        self.assertNotIn("ActivationEnvelope {", source)
        self.assertNotIn("InMemoryInvocationStatusStore", source)
        self.assertIn("requested_activation_id", source)
        self.assertIn("InvocationRuntime", source)

    def test_cancel_and_status_receive_authenticated_principals_atomically(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((WIRE / "src").glob("invocation/**/*.rs"))
        ) + (WIRE / "src" / "invocation.rs").read_text(encoding="utf-8")
        tests = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((WIRE / "src" / "invocation").glob("tests/**/*.rs"))
        )

        self.assertIn("pub principal: InvocationPrincipal", source)
        self.assertIn("fn cancel<'a>", source)
        self.assertIn("fn get_activation<'a>", source)
        self.assertIn("cancellation_is_fail_closed_before_status_publication", tests)
        self.assertIn("dropped_transport_cancels_only_its_own_activation", tests)
        self.assertIn("grpc_timeout_is_propagated", tests)


if __name__ == "__main__":
    unittest.main()
