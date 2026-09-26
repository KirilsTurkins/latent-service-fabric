from __future__ import annotations

import asyncio
import json
import struct
import sys

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived, StreamEnded
from latent.control.v1 import capability_pb2, common_pb2, policy_pb2
from latent.invocation.v1 import invocation_pb2


TOKEN = "LSF-PUBLIC-C-PEER-TEST-ONLY"
MAXIMUM = 18446744073709551615
DIGEST = "sha256:" + "1" * 64
PUBLICATION = "publication:sha256:" + "2" * 64


class Peer:
    def __init__(self):
        self.activations = {}
        self.operations = {}
        self.policies = {}
        self.writers = set()
        self.connections = 0
        self.closed = 0
        self.requests = 0
        self.invocations = {}
        self.held = {}
        self.default_capability_pages = 0
        self.paired = {}

    async def connection(self, reader, writer):
        self.connections += 1
        self.writers.add(writer)
        connection = H2Connection(config=H2Configuration(client_side=False, header_encoding="utf-8"))
        connection.initiate_connection()
        writer.write(connection.data_to_send())
        streams = {}
        try:
            while data := await asyncio.wait_for(reader.read(16384), timeout=10):
                for event in connection.receive_data(data):
                    if isinstance(event, RequestReceived):
                        if len(streams) >= 32:
                            raise ValueError("peer stream bound")
                        streams[event.stream_id] = [dict(event.headers), bytearray()]
                    elif isinstance(event, DataReceived):
                        stream = streams[event.stream_id]
                        stream[1].extend(event.data)
                        if len(stream[1]) > 1048581:
                            raise ValueError("peer request bound")
                        connection.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        headers, body = streams.pop(event.stream_id)
                        self.dispatch(connection, writer, event.stream_id, headers, bytes(body))
                writer.write(connection.data_to_send())
                await writer.drain()
        except (ConnectionError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            self.paired.pop(writer, None)
            for identity, held in list(self.held.items()):
                if held[1] is writer:
                    del self.held[identity]
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.writers.discard(writer)
            self.closed += 1

    def reply(self, connection, stream, value=None, *, raw=None, status=0, metadata=()):
        headers = [(":status", "200"), ("content-type", "application/grpc+proto"), *metadata]
        if status:
            connection.send_headers(stream, [*headers, ("grpc-status", str(status))], end_stream=True)
            return
        connection.send_headers(stream, headers)
        encoded = raw if raw is not None else value.SerializeToString(deterministic=True)
        connection.send_data(stream, b"\0" + struct.pack(">I", len(encoded)) + encoded)
        connection.send_headers(stream, [("grpc-status", "0")], end_stream=True)

    def receipt(self, identity, mode, payload=b"opaque", media="application/octet-stream"):
        value = invocation_pb2.InvokeResponse(activation_id=identity, revision_id="revision-a", release_digest=DIGEST,
                                             publication_id=PUBLICATION, route_generation=MAXIMUM)
        value.consumption.cpu_fuel = MAXIMUM
        if mode == "declared":
            value.declared_error.CopyFrom(invocation_pb2.DeclaredError(code="typed-provider-error", payload=b"\0\xff", media_type=media))
        elif mode == "platform":
            value.platform_failure.code = "permission-denied"
            value.platform_failure.detail_items.add(kind="provider-observation", fields={"state": "revoked"})
        else:
            value.success.CopyFrom(invocation_pb2.Success(payload=payload, media_type=media, committed_state_version="",
                                                          effect_ids=["effect-a"], metadata={"nul\0key": "nul\0value"}))
        return value

    def terminal(self, identity, cancelled=False):
        value = invocation_pb2.ActivationStatus(activation_id=identity, phase="running", last_updated_unix_millis=MAXIMUM,
                                                terminal_state="cancelled" if cancelled else "completed", terminal_at_unix_millis=MAXIMUM)
        value.final_consumption.cpu_fuel = MAXIMUM
        if cancelled:
            value.platform_failure.code = "cancelled"
        else:
            value.succeeded.SetInParent()
        self.activations[identity] = value

    def dispatch(self, connection, writer, stream, headers, body):
        self.requests += 1
        if self.requests > 2048 or len(body) < 5 or body[0] != 0 or int.from_bytes(body[1:5], "big") != len(body) - 5:
            raise ValueError("peer request framing")
        if headers.get("authorization") != "Bearer " + TOKEN:
            self.reply(connection, stream, status=16)
            return
        timeout = headers.get("grpc-timeout", "")
        if not timeout.endswith("m") or not 0 < int(timeout[:-1]) <= 300000:
            raise ValueError("absolute deadline header")
        service, operation = headers[":path"].rsplit("/", 1)
        module = invocation_pb2 if operation in {"Invoke", "Cancel", "GetActivation"} else capability_pb2 if operation == "ListCapabilities" else policy_pb2
        expected = "/latent.invocation.v1.InvocationService" if module is invocation_pb2 else "/latent.control.v1.CapabilityService" if module is capability_pb2 else "/latent.control.v1.PolicyService"
        if service != expected:
            raise ValueError("authoritative RPC path")
        request = getattr(module, operation + "Request").FromString(body[5:])
        if operation == "Invoke":
            if request.target.tenant != "tests":
                self.reply(connection, stream, status=7)
                return
            identity = request.activation_id if request.HasField("activation_id") else "server-assigned"
            if not identity:
                self.reply(connection, stream, status=3)
                return
            self.invocations[identity] = self.invocations.get(identity, 0) + 1
            mode = request.payload.decode("utf-8", errors="replace")
            self.activations[identity] = invocation_pb2.ActivationStatus(activation_id=identity, phase="running")
            if mode in {"hold", "never-end"}:
                self.held[identity] = (connection, writer, stream)
                return
            self.terminal(identity)
            if mode == "paired":
                waiting = self.paired.setdefault(writer, [])
                waiting.append((stream, self.receipt(identity, mode, request.payload, request.media_type)))
                if len(waiting) == 2:
                    for selected, value in self.paired.pop(writer):
                        self.reply(connection, selected, value)
                return
            if mode == "drop":
                writer.close()
                return
            if mode == "refused":
                connection.reset_stream(stream, error_code=7)
                return
            if mode == "goaway":
                connection.close_connection(error_code=0, last_stream_id=0)
                return
            if mode == "rpc-detail":
                import base64
                detail = common_pb2.PlatformError(code="permission-denied", message="peer-private-text", retryable=True)
                detail.detail_items.add(kind="typed-detail", fields={"state": "bounded"})
                self.reply(connection, stream, status=7, metadata=[("grpc-status-details-bin", base64.b64encode(detail.SerializeToString()).decode())])
                return
            if mode == "rpc-future":
                self.reply(connection, stream, status=999)
                return
            if mode == "rpc-deadline":
                self.reply(connection, stream, status=4)
                return
            if mode == "oversize":
                connection.send_headers(stream, [(":status", "200"), ("content-type", "application/grpc")])
                connection.send_data(stream, b"\0\x7f\xff\xff\xff")
                return
            if mode == "header-flood":
                self.reply(connection, stream, self.receipt(identity, mode), metadata=[("long-header", "x" * 17000)])
                return
            value = self.receipt("different" if mode == "wrong-id" else identity, mode, request.payload, request.media_type)
            if mode == "future-platform":
                value.ClearField("success")
                value.platform_failure.code = "future-outcome"
            if mode == "empty-publication":
                value.publication_id = ""
            raw = value.SerializeToString(deterministic=True)
            if mode == "malformed":
                raw = b"\xff"
            elif mode == "contradictory":
                raw += b"\x4a\x0a\x0a\x08internal"
            elif mode == "unknown-field":
                raw += b"\x80\x20\x01"
            elif mode == "truncated":
                raw = b"\x0a\x08short"
            self.reply(connection, stream, raw=raw)
        elif operation == "GetActivation":
            value = self.activations.get(request.activation_id)
            if value is None:
                self.reply(connection, stream, status=5)
            elif request.activation_id == "future-phase":
                value.phase = "future-phase"
                self.reply(connection, stream, value)
            else:
                self.reply(connection, stream, value)
        elif operation == "Cancel":
            known = self.activations.get(request.activation_id)
            if request.activation_id == "future-cancel":
                self.reply(connection, stream, invocation_pb2.CancelResponse(disposition=-73))
            elif known is None:
                self.reply(connection, stream, invocation_pb2.CancelResponse(disposition=3))
            elif known.HasField("terminal_state"):
                self.reply(connection, stream, invocation_pb2.CancelResponse(disposition=2, terminal_state=known.terminal_state))
            else:
                self.terminal(request.activation_id, True)
                held = self.held.pop(request.activation_id, None)
                if held:
                    pending = self.receipt(request.activation_id, "platform")
                    pending.platform_failure.code = "cancelled"
                    self.reply(held[0], held[2], pending)
                    held[1].write(held[0].data_to_send())
                self.reply(connection, stream, invocation_pb2.CancelResponse(disposition=1))
        elif operation == "ListCapabilities":
            if request.HasField("page") and (request.page.page_size > 128 or len(request.page.page_token) > 160):
                self.reply(connection, stream, status=3)
                return
            if not request.HasField("page") or request.page.page_size == 0:
                self.default_capability_pages += 1
            value = capability_pb2.ListCapabilitiesResponse(state="current")
            value.page.SetInParent()
            value.revision.CopyFrom(capability_pb2.CapabilityInspectionRevision(deployment_id=request.deployment_id,
                revision_id="revision-a", component_digest=DIGEST, publication_id=PUBLICATION,
                route_generation=MAXIMUM, catalog_transaction=MAXIMUM))
            item = value.capabilities.add(id="http", contract="latent:http/client@0.2.0", provider="http", operations=["send"])
            item.inspection.provider_binding.CopyFrom(capability_pb2.CapabilityInspectionPolicy(id="provider-http", revision=MAXIMUM, digest=DIGEST))
            item.inspection.policies.add(id="policy-http", revision=MAXIMUM, digest=DIGEST)
            item.inspection.provider_configuration_epoch = MAXIMUM
            value.tenant_usage.scope = "tenant"
            value.tenant_usage.counters.update({"zero": 0, "maximum": MAXIMUM})
            value.tenant_usage.unavailable.append("dormant")
            self.reply(connection, stream, value)
        elif operation == "ListPolicies":
            if not request.HasField("page") or not 1 <= request.page.page_size <= 32 or len(request.page.page_token) > 117:
                self.reply(connection, stream, status=3)
                return
            value = policy_pb2.ListPoliciesResponse(catalog_generation=MAXIMUM)
            value.page.SetInParent()
            identity = "second" if request.page.HasField("page_token") else "first"
            value.policies.add(id=identity, generation=MAXIMUM, record_kind=request.record_kind, document="{}")
            if identity == "first":
                value.page.next_page_token = "opaque-page-token"
            self.reply(connection, stream, value)
        elif operation == "GetPolicy":
            value = policy_pb2.GetPolicyResponse()
            if request.id in self.policies:
                value.policy.CopyFrom(self.policies[request.id])
            elif request.id in {"provider-http", "policy-http"}:
                value.policy.CopyFrom(policy_pb2.Policy(id=request.id, generation=MAXIMUM, record_kind=request.record_kind, document="{}"))
            self.reply(connection, stream, value)
        elif operation == "ApplyPolicy":
            metadata = []
            if request.operation_id.startswith("audit-"):
                state = request.operation_id.removeprefix("audit-")
                metadata = [("latent-audit-status", state), ("latent-audit-attempt", str(MAXIMUM))]
            encoded = request.SerializeToString(deterministic=True)
            known = self.operations.get(request.operation_id)
            if known:
                if known[0] != encoded:
                    self.reply(connection, stream, status=9, metadata=metadata)
                    return
                self.reply(connection, stream, known[1], metadata=metadata)
                return
            current = self.policies.get(request.policy.id)
            if request.expected_generation != (current.generation if current else 0):
                self.reply(connection, stream, status=9)
                return
            value = policy_pb2.ApplyPolicyResponse()
            value.policy.CopyFrom(request.policy)
            value.policy.generation = 1
            value.policy.content_digest = DIGEST
            value.receipt.CopyFrom(policy_pb2.CapabilityPolicyOperation(operation_id=request.operation_id, tenant="tests",
                id=value.policy.id, record_kind=value.policy.record_kind, generation=1, content_digest=DIGEST))
            self.operations[request.operation_id] = (encoded, value)
            self.policies[value.policy.id] = value.policy
            if request.operation_id == "lost-policy":
                writer.close()
                return
            self.reply(connection, stream, value, metadata=metadata)
        elif operation == "GetPolicyOperation":
            if request.operation_id == "rpc-not-found":
                self.reply(connection, stream, status=5)
                return
            value = policy_pb2.GetPolicyOperationResponse()
            if request.operation_id in self.operations:
                value.receipt.CopyFrom(self.operations[request.operation_id][1].receipt)
            self.reply(connection, stream, value)


async def main():
    peer = Peer()
    server = await asyncio.start_server(peer.connection, "127.0.0.1", 0, limit=65536)
    print(json.dumps({"port": server.sockets[0].getsockname()[1]}), flush=True)
    command = await asyncio.to_thread(sys.stdin.readline)
    if command.strip() != "stop":
        raise ValueError("peer stop protocol")
    server.close()
    await server.wait_closed()
    for _attempt in range(100):
        if not peer.writers:
            break
        await asyncio.sleep(0.01)
    if peer.writers or peer.connections != peer.closed:
        raise ValueError("client left physical connections")
    if any(peer.invocations.get(name) != 1 for name in ("drop-id", "refused-id", "goaway-id")):
        raise ValueError("unexpected automatic invocation retry")
    print(json.dumps({"connections": peer.connections, "closed": peer.closed, "requests": peer.requests,
                      "defaultCapabilityPages": peer.default_capability_pages}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
