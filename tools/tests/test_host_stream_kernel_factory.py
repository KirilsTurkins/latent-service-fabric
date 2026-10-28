"""Authenticated outer ordering and unavailable prepaid-factory boundaries."""
import hashlib
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

from tools import host_stream_kernel_factory as factory
from tools import qualify_stream_kernel_owners as owners

ROOT = Path(__file__).resolve().parents[2]
OWNED = ROOT / "research/standard-outbound/linux-6.12-lineage"


class HostStreamKernelFactory(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(factory.FIXTURE.read_bytes())

    def test_all_five_whole_historical_preimages_and_eight_functions_are_bound(self):
        self.assertEqual(sum(row[0] for row in factory.SOURCE.values()), 265502)
        self.assertEqual(len(factory.SOURCE), 5)
        self.assertEqual(len(factory.PREFIXES), 8)
        self.assertEqual(set(self.fixture["source"]), set(factory.SOURCE))
        for name, (size, sha, blob) in factory.SOURCE.items():
            row = self.fixture["source"][name]
            self.assertEqual((row["bytes"], row["sha256"], row["gitBlob"]), (size, sha, blob))
            self.assertIn(self.fixture["upstreamCommit"], row["url"])
        for name, row in self.fixture["functions"].items():
            self.assertEqual(hashlib.sha256(row["text"].encode()).hexdigest(), row["sha256"])
            self.assertEqual(factory.function(row["text"], name), row["text"])
            self.assertIs(row["closureProven"], False)

    def test_unknown_membership_whole_preimages_and_partial_sources_refuse(self):
        with self.assertRaisesRegex(ValueError, "factory-source-membership"):
            factory.authenticate({})
        inputs = {name: b"\0" * row[0] for name, row in factory.SOURCE.items()}
        with self.assertRaisesRegex(ValueError, "factory-whole-preimage"):
            factory.authenticate(inputs)
        for name, row in self.fixture["functions"].items():
            for raw in (row["text"] * 2, row["text"].replace("\n", "\r\n"),
                        row["text"].replace("\n{\n", "\n{\n\t;\n")):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    factory.function(raw, name)

    def test_outer_security_and_vfs_precede_protocol_allocator(self):
        functions = self.fixture["functions"]
        create = functions["__sock_create"]["text"]
        self.assertLess(create.index("security_socket_create("), create.index("sock_alloc();"))
        self.assertLess(create.index("sock_alloc();"), create.index("pf->create("))
        self.assertIn("new_inode_pseudo(", functions["sock_alloc"]["text"])
        self.assertIn("alloc_inode_sb(", functions["sock_alloc_inode"]["text"])
        self.assertIn("alloc_file_pseudo(", functions["sock_alloc_file"]["text"])
        for name in ("inet_create", "inet6_create"):
            self.assertIn("sk_alloc(", functions[name]["text"])
        # Authentic old source counterexample to treating only sk_alloc as the
        # first physical allocation. No old Linux execution is claimed.
        self.assertNotIn("lsf_factory_context", create)

    def test_registration_and_open_refuse_before_any_backing_allocation(self):
        raw = (OWNED / "factory.c").read_text()
        selected = (OWNED / "factory-private.h").read_text()
        self.assertIn("lsf_factory_selected_consumer(void)\n{\n    return NULL;", selected)
        register = raw[raw.index("int lsf_factory_register(void)"):]
        self.assertLess(register.index("if (!lsf_factory_selected_consumer())"), register.index("misc_register("))
        opened = raw[raw.index("static int lsf_factory_open("):raw.index("static struct lsf_factory_context *")]
        self.assertLess(opened.index("if (!lsf_factory_selected_consumer())"), opened.index("alloc_pages("))
        self.assertNotIn("module_init(", raw)
        self.assertNotIn("EXPORT_SYMBOL", raw)

    def test_backing_uses_one_exact_order_without_general_allocator_fallback(self):
        raw = (OWNED / "factory.c").read_text()
        self.assertIn("PAGE_SIZE == 4096", raw)
        self.assertIn("sizeof(factory) + LSF_BACKING_BYTES < LSF_BOOTSTRAP_CEILING", raw)
        self.assertEqual(raw.count("factory.pages = alloc_pages("), 1)
        self.assertNotIn("__free_pages(", raw)
        self.assertNotIn("sock_create_kern(", raw)
        self.assertIn("spin_lock_irqsave(&pool_lock, flags)", raw)

    def test_protected_actor_and_fixed_create_only_wire_have_no_release_command(self):
        raw = (OWNED / "factory.c").read_text()
        for required in ("factory.mm == current->mm", "factory.tgid == task_tgid(current)",
                         "factory.cred == current_cred()", "file->f_cred == factory.cred",
                         "current->nsproxy->net_ns == factory.net", "CAP_SYS_ADMIN",
                         ".mode = 0600", "count != sizeof(request)", "factory.inflight"):
            self.assertIn(required, raw)
        wire = raw[raw.index("struct lsf_factory_create {"):raw.index("struct lsf_factory_reply")]
        for forbidden in ("pointer", "bytes", "proof", "free", "qualified", "layout"):
            self.assertNotIn(forbidden, wire)
        self.assertNotIn(".unlocked_ioctl", raw)
        self.assertNotIn(".mmap", raw)

    def test_context_exists_before_consumer_and_close_retains_backing(self):
        raw = (OWNED / "factory.c").read_text()
        self.assertLess(raw.index("lsf_prepaid_context_create("), raw.index("consumer->create("))
        closed = raw[raw.index("static int lsf_factory_release("):raw.index("static const struct file_operations")]
        self.assertIn("factory.pool.stopped = 1", closed)
        self.assertIn("WRITE_ONCE(factory.uncertain, 1)", closed)
        self.assertNotIn("lsf_prepaid_recycle(", closed)
        self.assertNotIn("__free_pages(", closed)

    def test_native_ownership_is_original_accepted_session_io_and_fixed_allowance(self):
        raw = (ROOT / "crates/latent-capabilities/src/broker/pools/protocol.rs").read_text()
        for item in ("io: IoLease", "_request: super::admission::RequestOwner", "Arc<StreamScope>",
                     "SessionCoreOwner::ptr_eq(&original.core, &accepted.core)", "65_536 | 98_304",
                     "io: self.io.lease()", "self.retain_stream_request()",
                     "scope.reserve_host_memory(bytes)?"):
            self.assertIn(item, raw)
        self.assertNotIn("Deserialize", raw)
        admission = (ROOT / "crates/latent-capabilities/src/broker/pools/admission.rs").read_text()
        self.assertIn("pub(in crate::broker) type RequestOwner = Shared<Request>;", admission)
        self.assertIn("use crate::broker::session::{PreparedShared, SessionCoreOwner, Shared, SharedWeak};", admission)
        self.assertIn("pub(super) fn retain_stream_request(&self) -> RequestOwner {\n        self.request.clone()\n    }", admission)
        backing = raw[raw.index("pub fn reserve_stream_kernel_backing("):]
        self.assertIn("self.reserve_protocol_metadata(1024 * 1024)?", backing)

    def test_actual_quarantine_selects_original_io_owner_without_double_reservation(self):
        raw = (ROOT / "crates/latent-streams/src/connection.rs").read_text()
        start = raw.index("impl SocketMemory {")
        reserve = raw[start:raw.index("\n}\n", start) + len("\n}\n")]
        self.assertIn("if mode.retains_unproved()", reserve)
        self.assertIn("call.reserve_stream_kernel_ownership(scope, bytes)", reserve)
        self.assertIn("scope.reserve_host_memory(bytes).map(Self::Logical)", reserve)
        self.assertIn(".map(Self::Kernel)", reserve)
        self.assertEqual(reserve.count("reserve_stream_kernel_ownership("), 1)
        self.assertEqual(reserve.count("reserve_host_memory("), 1)
        self.assertLess(reserve.index("if mode.retains_unproved()"),
                        reserve.index("call.reserve_stream_kernel_ownership(scope, bytes)"))
        self.assertLess(reserve.index("call.reserve_stream_kernel_ownership(scope, bytes)"),
                        reserve.index("} else {"))
        self.assertLess(reserve.index("} else {"), reserve.index("scope.reserve_host_memory(bytes)"))
        self.assertIn(".quarantine(value)", raw)
        self.assertIn("original.quarantine()", raw)

    def test_original_io_quiescence_owner_drops_after_all_original_accounting(self):
        raw = (ROOT / "crates/latent-capabilities/src/broker/pools/protocol.rs").read_text()
        fields = raw[raw.index("pub struct StreamKernelOwnership {"):raw.index("impl StreamKernelOwnership {")]
        self.assertLess(fields.index("memory:"), fields.index("_scope:"))
        self.assertLess(fields.index("_scope:"), fields.index("_request:"))
        self.assertLess(fields.index("_request:"), fields.index("io: IoLease"))

    def test_production_and_whole_accounting_gates_remain_unavailable(self):
        gate = (ROOT / "crates/latent-streams/src/kernel.rs").read_text()
        self.assertIn("Err(error(StreamErrorCode::Unsupported))", gate)
        for field in ("kernelBuilt", "trustedFactoryInstalled", "completeAllocationClosure", "productionInstallation"):
            self.assertIs(self.fixture[field], False)
        source = (OWNED / "prepaid.h").read_text()
        self.assertIn("records[LSF_ALLOCATION_SLOTS]", source)
        self.assertIn("contexts[LSF_OWNER_SLOTS]", source)
        self.assertIn("LSF_FACTORY_CONTEXTS 4u", source)

    def test_owner_reader_requires_exact_old_five_and_new_four_successes(self):
        self.assertEqual(len(owners.CASES), 9)
        text = "\n".join("test " + owners.PREFIX + name + " ... ok" for name in owners.CASES)
        text += "\ntest result: ok. 9 passed; 0 failed; 0 ignored; 171 filtered out; finished in 0.1s\n"
        owners.verify_tests(text.encode())
        for value in (text.replace("9 passed", "8 passed"), text.replace("0 ignored", "1 ignored"),
                      text.replace(" ... ok", " ... ignored", 1), text + text,
                      text.replace(owners.CASES[0], "unexpected")):
            with self.assertRaisesRegex(ValueError, "owner-test-identity-or-terminal-result"):
                owners.verify_tests(value.encode())

    def test_failed_owner_command_retains_both_bounded_streams_and_original_failure(self):
        from tools.owned_test_process import Result
        for category in ("infrastructure-timeout", "output-overflow", "unavailable-environment"):
            result = Result(None, b"bounded-out", stderr=b"bounded-compiler-error")
            failure = owners.ProcessFailure(category, "fixed-failure", result)
            with tempfile.TemporaryDirectory() as directory:
                out = Path(directory)
                with patch.object(owners, "run_owned", side_effect=failure), \
                        self.assertRaises(owners.ProcessFailure) as raised:
                    owners.capture(["cargo"], {}, 600, out, "broker-owners")
                self.assertIs(raised.exception, failure)
                self.assertEqual((out / "broker-owners.stdout").read_bytes(), result.output)
                self.assertEqual((out / "broker-owners.stderr").read_bytes(), result.stderr)
                self.assertIs(json.loads((out / "broker-owners-failure.json").read_bytes())["completed"], False)
                with patch.object(owners, "run_owned", side_effect=failure), \
                        patch.object(Path, "write_bytes", side_effect=OSError("storage-full")), \
                        self.assertRaises(owners.ProcessFailure) as original:
                    owners.capture(["cargo"], {}, 600, out, "broker-owners")
                self.assertIs(original.exception, failure)


class NodeBootstrapSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.abc
        import importlib.util
        source = OWNED / "node-bootstrap/projector.py"
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != "ff23bd22fd6043e9b46df14f0105a3cc6af55e59a140bb6851faf5256118354b":
            raise AssertionError("node-projector-captured-identity")
        path = str(source)
        class Captured(importlib.abc.SourceLoader):
            def get_filename(self, fullname):
                if fullname != "_lsf_node_bootstrap_projector":
                    raise ValueError("node-module-name")
                return path
            def get_data(self, requested):
                if requested != path:
                    raise ValueError("node-module-source-only")
                return raw
        loader = Captured()
        spec = importlib.util.spec_from_file_location("_lsf_node_bootstrap_projector", path, loader=loader)
        cls.module = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.module)
        cls.loader = loader
        cls.c_source = cls.module.materials(ROOT)[cls.module.MATERIAL_NAME]

    def test_material_reader_bounds_and_wrong_length_hash_short_circuit(self):
        module = self.module
        with patch.object(module.hashlib, "sha256", side_effect=AssertionError("must not hash")):
            self.assertFalse(module._bound(b"", module.MATERIAL_PIN))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / module.MATERIAL_PATH
            path.parent.mkdir(parents=True)
            path.write_bytes(self.c_source)
            self.assertEqual(module.materials(root)[module.MATERIAL_NAME], self.c_source)
            path.write_bytes(self.c_source[:-1])
            with patch.object(Path, "open", side_effect=AssertionError("no oversized/open read")):
                with self.assertRaisesRegex(ValueError, "node-material-kind-length"):
                    module.materials(root)
            path.write_bytes(bytes([self.c_source[0] ^ 1]) + self.c_source[1:])
            with self.assertRaisesRegex(ValueError, "node-material-identity"):
                module.materials(root)
            path.write_bytes(self.c_source)
            with patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaisesRegex(ValueError, "node-material-kind-length"):
                    module.materials(root)

    def test_compiled_fops_choice_has_exact_ordinary_inverse_and_no_runtime_selector(self):
        module = self.module
        old = b"/* unchanged ordinary body */\n" + module.ANCHOR + b'    .name = "lsf-stream-factory",\n' + module.OLD_FOPS + b"};\n"
        selected = module.edit_factory(old)
        self.assertEqual(module.inverse_factory(selected), old)
        self.assertTrue(selected.startswith(module.PREFIX))
        self.assertLess(selected.index(module.INCLUDE), selected.index(module.ANCHOR))
        self.assertEqual(selected.count(b".fops = &lsf_factory_node_operations"), 1)
        self.assertEqual(selected.count(b".fops = &lsf_factory_operations"), 1)
        with self.assertRaisesRegex(ValueError, "node-profile-before"):
            module.edit_factory(selected)
        with self.assertRaisesRegex(ValueError, "node-input-set"):
            module.transform({})
        with self.assertRaisesRegex(ValueError, "node-module-name"):
            self.loader.get_filename("alternate")
        with self.assertRaisesRegex(ValueError, "node-module-source-only"):
            self.loader.get_data(str(OWNED / "node-bootstrap/__pycache__/projector.pyc"))

    def test_actual_initial_header_precharge_and_unqualified_release_cuts(self):
        module = self.module
        module.node_body_obligations(self.c_source)
        for mutation in (
            self.c_source.replace(b"if (!lsf_factory_selected_consumer())", b"if (0)", 1),
            self.c_source.replace(b"error = lsf_cleanup_observers_prebank_enter();", b"error = 0;", 1),
            self.c_source.replace(b"error = -EIO;", b"error = 0;", 1),
            self.c_source.replace(b"*record = (struct lsf_prepaid_view)", b"/* unpaid header */", 1),
            self.c_source.replace(b"node->state = LSF_NODE_RETAINED;\n        spin_lock_irqsave",
                b"node->state = LSF_NODE_RETAINED;\n        __free_pages(factory.pages, LSF_BACKING_ORDER);\n        spin_lock_irqsave", 1),
        ):
            self.assertNotEqual(mutation, self.c_source)
            with self.assertRaises(ValueError):
                module.node_body_obligations(mutation)
        self.assertIn(b"sizeof(struct lsf_node_parent)", self.c_source)
        self.assertNotIn(b"lsf_factory_device_initialize(", self.c_source)
        self.assertNotIn(b"LSF_NODE_FUNDING_APPROVED", self.c_source)

    def test_actual_rust_entry_moves_one_escrow_and_old_ack_never_refunds_node(self):
        raw = (ROOT / "crates/latent-streams/src/kernel/native.rs").read_text()
        node = raw[raw.index("pub(crate) mod node_bootstrap {"):]
        production = node[:node.index("    #[cfg(test)]\n    mod controls")]
        start = production[production.index("    pub(crate) async fn start("):]
        self.assertLess(start.index("profile.check()?"), start.index("reserve_stream_kernel_node_backing("))
        self.assertEqual(production.count("reserve_stream_kernel_node_backing("), 1)
        self.assertNotIn("start_initialized_with(", production)
        self.assertNotIn("reserve_stream_kernel_backing(", production)
        self.assertLess(production.index("attempt.entered = true"), production.index("value.descriptor = Some(open()?)"))
        close = production[production.index("    fn close_retained("):production.index("    async fn enter_with")]
        self.assertNotIn("StreamKernelCloseObservation::KernelRootReturned", close)
        self.assertNotIn("partition_original_bank(", close)
        self.assertIn("value.phase = Phase::Retained", close)
        self.assertIn("connection.quarantine()", production)
        self.assertIn("No production constructor exists in this source slice", production)

if __name__ == "__main__":
    unittest.main()
