"""Finite authenticated HTTP/2 peer for the actual maintained C owner."""
from __future__ import annotations

import asyncio
import json
import struct
import sys

from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import DataReceived, RequestReceived, StreamEnded, StreamReset
from latent.control.v1 import dispatcher_pb2, state_pb2
from latent.invocation.v1 import invocation_pb2
from latent.transaction.v1 import transaction_pb2 as tx

TOKEN = "LSF-PUBLIC-C-PEER-TEST-ONLY"
MAXIMUM = 18446744073709551615
DIGEST = "sha256:" + "1" * 64
PUBLICATION = "publication:" + DIGEST


def source():
    return tx.SourceIdentity(publication_id=PUBLICATION, revision_id="revision-a", release_digest=DIGEST,
        route_generation=MAXIMUM, contract_digest=DIGEST, state_schema=DIGEST,
        input_format="aggregate-input-v1", result_format="aggregate-result-v1", component_digest=DIGEST)


def command(selector, mode):
    value = tx.CommandInspection(command_id="command-a", attempt_id="attempt-a", fingerprint_sha256=b"f" * 32,
        outcome=2, metadata_durable=True, application_state_committed=True, source=source())
    value.key.namespace.CopyFrom(selector.namespace)
    value.key.recovery_scope = "caller:tests:operator-a"
    value.key.operation, value.key.client_key = selector.operation, selector.client_key
    if selector.HasField("entity"):
        value.key.entity = selector.entity
    value.success.CopyFrom(invocation_pb2.Success(payload=b"ok", media_type="application/octet-stream"))
    value.commit.CopyFrom(tx.CommitReceipt(command_id=value.command_id, attempt_id=value.attempt_id,
        transaction_id="transaction-a", committed_version=b"v1", committed_at_unix_millis=MAXIMUM,
        effect_ids=["effect-a"], receipt_id="receipt-a", source=source()))
    if mode == "paired":
        value.success.payload = b"p" * (750 * 1024)
    elif mode == "reject":
        value.ClearField("success"); value.ClearField("commit")
        value.outcome, value.application_state_committed = 3, False
        value.business_rejection.CopyFrom(invocation_pb2.DeclaredError(code="rejected", payload=b"no", media_type="application/octet-stream"))
    elif mode == "abort":
        value.ClearField("success"); value.ClearField("commit")
        value.outcome, value.application_state_committed = 4, False
        value.technical_failure.code = "cancelled"
        value.proven_abort.CopyFrom(tx.AbortFence(command_id=value.command_id, attempt_id=value.attempt_id,
            transaction_id="transaction-a", owner_fence=b"owner-a"))
    elif mode == "expired":
        value.ClearField("success")
        value.retention.CopyFrom(tx.LinkedRetention(record_format="command-v1", record_version=1, payload_available=False))
    elif mode in {"linked256", "linked257"}:
        value.retention.CopyFrom(tx.LinkedRetention(record_format="command-v1", record_version=1, payload_available=True,
            required_record_ids=["linked-" + str(i) for i in range(256 if mode == "linked256" else 257)]))
    elif mode == "unknown":
        value.ClearField("success"); value.ClearField("commit"); value.ClearField("source")
        value.outcome, value.metadata_durable, value.application_state_committed = 5, False, False
        value.command_id, value.attempt_id, value.fingerprint_sha256 = "", "", b""
    return value


def invoked(identity, cmd):
    value = invocation_pb2.InvokeResponse(activation_id=identity, revision_id="revision-a", release_digest=DIGEST,
        publication_id=PUBLICATION, route_generation=MAXIMUM)
    value.consumption.cpu_fuel = MAXIMUM
    if cmd.HasField("success"):
        value.success.CopyFrom(cmd.success)
    elif cmd.HasField("business_rejection"):
        value.declared_error.CopyFrom(cmd.business_rejection)
    else:
        value.platform_failure.CopyFrom(cmd.technical_failure)
    return value


def effect(identity):
    return tx.EffectReceipt(effect_id=identity, command_id="command-a", command_attempt_id="attempt-a",
        dispatch_attempt=1, disposition=1, occurred_at_unix_millis=MAXIMUM, provider_profile="event-v1")


class Peer:
    def __init__(self):
        self.writers = set()
        self.connections = self.closed = self.requests = 0
        self.methods, self.invocations = {}, {}
        self.lost = None

    def reply(self, connection, pending, stream, value=None, *, raw=None, status=0, metadata=()):
        headers = [(":status", "200"), ("content-type", "application/grpc+proto"), *metadata]
        if status:
            connection.send_headers(stream, [*headers, ("grpc-status", str(status))], end_stream=True)
            return
        encoded = raw if raw is not None else value.SerializeToString(deterministic=True)
        if len(encoded) > 3 * 1024**2 or len(pending) >= 8:
            raise ValueError("finite peer response bound")
        connection.send_headers(stream, headers)
        pending[stream] = b"\0" + struct.pack(">I", len(encoded)) + encoded

    def flush(self, connection, pending):
        for stream in list(pending):
            while pending[stream]:
                window = connection.local_flow_control_window(stream)
                size = min(window, connection.max_outbound_frame_size, len(pending[stream]))
                if size == 0:
                    break
                connection.send_data(stream, pending[stream][:size])
                pending[stream] = pending[stream][size:]
            if not pending[stream]:
                connection.send_headers(stream, [("grpc-status", "0")], end_stream=True)
                del pending[stream]

    async def connection(self, reader, writer):
        self.connections += 1; self.writers.add(writer)
        connection = H2Connection(config=H2Configuration(client_side=False, header_encoding="utf-8"))
        connection.initiate_connection(); writer.write(connection.data_to_send())
        streams, pending = {}, {}
        try:
            while data := await asyncio.wait_for(reader.read(65536), timeout=10):
                for event in connection.receive_data(data):
                    if isinstance(event, RequestReceived):
                        if len(streams) >= 8: raise ValueError("finite peer stream bound")
                        streams[event.stream_id] = [dict(event.headers), bytearray()]
                    elif isinstance(event, DataReceived):
                        stream = streams[event.stream_id]; stream[1].extend(event.data)
                        if len(stream[1]) > 2 * 1024**2 + 5: raise ValueError("finite peer request bound")
                        connection.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, StreamEnded):
                        headers, body = streams.pop(event.stream_id)
                        self.dispatch(connection, pending, writer, event.stream_id, headers, bytes(body))
                    elif isinstance(event, StreamReset):
                        streams.pop(event.stream_id, None); pending.pop(event.stream_id, None)
                self.flush(connection, pending)
                writer.write(connection.data_to_send()); await writer.drain()
        except (ConnectionError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except ConnectionError: pass
            self.writers.discard(writer); self.closed += 1

    def dispatch(self, connection, pending, writer, stream, headers, body):
        self.requests += 1
        if self.requests > 256 or len(body) < 5 or body[0] != 0 or int.from_bytes(body[1:5], "big") != len(body) - 5:
            raise ValueError("request framing")
        if headers.get("authorization") != "Bearer " + TOKEN: raise ValueError("missing authentication")
        timeout = headers.get("grpc-timeout", "")
        if not timeout.endswith("m") or not 0 < int(timeout[:-1]) <= 300000: raise ValueError("deadline missing")
        service, method = headers[":path"].rsplit("/", 1)
        module = dispatcher_pb2 if "DispatcherService" in service else state_pb2 if "StateService" in service else tx
        expected = "/latent.control.v1.DispatcherService" if module is dispatcher_pb2 else "/latent.control.v1.StateService" if module is state_pb2 else "/latent.transaction.v1.TransactionService"
        if service != expected: raise ValueError("exact RPC path")
        request = getattr(module, method + "Request").FromString(body[5:])
        self.methods[method] = self.methods.get(method, 0) + 1
        if method == "InvokeCommand":
            key = request.command.client_key
            self.invocations[key] = self.invocations.get(key, 0) + 1
            if len(request.expected_versions) != 1 or request.expected_versions[0].version != b"\xaa": raise ValueError("original caller precondition changed")
            if request.invocation.payload != b"input-a": raise ValueError("request payload was not snapshotted")
            if key == "held": return
            if key == "aborted-status": self.reply(connection, pending, stream, status=10); return
            cmd = command(request.command, key)
            if key == "lost": self.lost = cmd; writer.close(); return
            value = tx.InvokeCommandResponse(command=cmd, invocation=invoked(request.invocation.activation_id, cmd))
            if key == "substitution": value.invocation.activation_id = "different-activation"
            self.reply(connection, pending, stream, value)
        elif method in {"LookupCommand", "LookupCommit"}:
            key = request.command.client_key
            cmd = self.lost if key == "lost" and self.lost is not None else command(request.command, key)
            value = getattr(tx, method + "Response")(command=cmd)
            encoded = value.SerializeToString(deterministic=True)
            raw = encoded + encoded if key == "duplicate" else encoded.replace(b"tests", b"\xff" * 5, 1) if key == "invalid-utf8" else b"x" * (2 * 1024**2 + 1) if key == "oversized-wire" else None
            self.reply(connection, pending, stream, value, raw=raw)
        elif method == "Query":
            if request.invocation.target.function == "held-query":
                return
            cmd = command(tx.CommandSelector(namespace=request.namespace, operation="query", client_key="query"), "query")
            self.reply(connection, pending, stream, tx.QueryResponse(invocation=invoked(request.invocation.activation_id, cmd),
                source=source(), view=tx.ViewIdentity(namespace=request.namespace, version=b"view-v1", state_schema=DIGEST)))
        elif method == "GetEffect":
            row = effect(request.effect_id)
            if request.effect_id == "future": row.disposition = 91
            self.reply(connection, pending, stream, tx.GetEffectResponse(effect=row))
        elif method == "ListEffectHistory":
            count = 129 if request.effect.effect_id == "oversized-page" else 1
            value = tx.ListEffectHistoryResponse(receipts=[effect(request.effect.effect_id) for _ in range(count)])
            value.page.returned_count, value.page.encoded_bytes = count, 256
            self.reply(connection, pending, stream, value)
        elif method == "CancelCommand":
            self.reply(connection, pending, stream, tx.CancelCommandResponse(disposition=2, command=command(request.command.command, "ok")))
        elif method == "InspectNamespace":
            value = state_pb2.InspectNamespaceResponse()
            value.namespace.view.CopyFrom(tx.ViewIdentity(namespace=request.namespace, version=b"v1", state_schema=DIGEST))
            value.namespace.engine_profile, value.namespace.engine_profile_digest = "redb-v1", DIGEST
            value.namespace.status, value.namespace.generation = 1, MAXIMUM
            for name in ("state_keys", "result_rows", "effect_rows"): setattr(value.namespace.quota, name, 1000)
            for name in ("state_bytes", "result_bytes", "effect_bytes", "payload_bytes", "recovery_bytes"): setattr(value.namespace.quota, name, 60000)
            self.reply(connection, pending, stream, value)
        elif method == "SelectEntity":
            value = state_pb2.SelectEntityResponse(entities=[state_pb2.EntityInspection(entity="entity-a", version=b"v1")])
            value.page.returned_count, value.page.encoded_bytes = 1, 32
            self.reply(connection, pending, stream, value)
        elif method == "MutateNamespace":
            row = state_pb2.NamespaceOperationReceipt(operation_id=request.operation_id, receipt_id="namespace-receipt",
                mutation=request.mutation, namespace=request.namespace.namespace, authenticated_operator="operator-a",
                before_generation=request.expected_generation, after_generation=request.expected_generation + 1,
                status=2, state_schema=DIGEST, disposition=1)
            self.reply(connection, pending, stream, state_pb2.MutateNamespaceResponse(receipt=row))
        elif method in {"MutateState", "GetStateOperationReceipt"}:
            row = state_pb2.StateOperationReceipt(operation_id=request.operation_id, receipt_id="state-receipt", mutation=2,
                namespace=request.namespace.namespace, authenticated_operator="operator-a", before_version=b"v1", after_version=b"v2",
                record_id="effect-a", policy_digest=DIGEST, disposition=1)
            self.reply(connection, pending, stream, getattr(state_pb2, method + "Response")(receipt=row))
        elif method == "InspectDispatcher":
            value = dispatcher_pb2.InspectDispatcherResponse()
            value.dispatcher.generation.owner_epoch, value.dispatcher.generation.revision = MAXIMUM, MAXIMUM
            value.dispatcher.failure, value.dispatcher.clock_continuity_proven = 1, True
            value.dispatcher.retained_attempt_bytes = MAXIMUM
            self.reply(connection, pending, stream, value)
        elif method in {"ControlDispatcher", "GetDispatcherOperation"}:
            original = request.original if method == "GetDispatcherOperation" else request
            row = dispatcher_pb2.DispatcherOperationReceipt(operation_id=original.operation_id, receipt_id="dispatcher-receipt", action=original.action,
                authenticated_operator="operator-a", actor_tenant="tests", before_generation=original.expected_generation,
                after_generation=dispatcher_pb2.DispatcherGeneration(owner_epoch=original.expected_generation.owner_epoch,
                    revision=original.expected_generation.revision + 1), disposition=1, clock_continuity_proven=True)
            value = getattr(dispatcher_pb2, method + "Response")(receipt=row)
            if method == "ControlDispatcher": value.published, value.paused = True, True
            if original.operation_id == "audit-body": value.audit_ack.status = 91
            metadata = (("latent-audit-status", "durable"), ("latent-audit-attempt", "wrong")) if original.operation_id == "audit-header" else ()
            if original.operation_id == "wrong-cas": value.receipt.before_generation.revision -= 1
            self.reply(connection, pending, stream, value, metadata=metadata)


async def main():
    peer = Peer()
    server = await asyncio.start_server(peer.connection, "127.0.0.1", 0, limit=65536)
    print(json.dumps({"port": server.sockets[0].getsockname()[1]}), flush=True)
    if (await asyncio.to_thread(sys.stdin.readline)).strip() != "stop": raise ValueError("peer stop protocol")
    server.close(); await server.wait_closed()
    for _ in range(100):
        if not peer.writers: break
        await asyncio.sleep(0.01)
    if peer.writers or peer.connections != peer.closed: raise ValueError("client left physical owners")
    if len(peer.methods) != 15: raise ValueError("not all fifteen RPCs executed")
    if any(count != 1 for count in peer.invocations.values()): raise ValueError("mutation automatically retried")
    print(json.dumps({"connections": peer.connections, "closed": peer.closed, "requests": peer.requests,
        "methods": len(peer.methods), "invocations": peer.invocations}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
