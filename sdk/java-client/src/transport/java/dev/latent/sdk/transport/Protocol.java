package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import com.google.protobuf.CodedInputStream;
import com.google.protobuf.Descriptors;
import com.google.protobuf.Message;
import io.grpc.Metadata;
import io.grpc.MethodDescriptor;
import io.grpc.Status;
import io.grpc.protobuf.ProtoUtils;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

final class Protocol {
    static final Metadata.Key<String> AUDIT_STATUS = Metadata.Key.of("latent-audit-status", Metadata.ASCII_STRING_MARSHALLER);
    static final Metadata.Key<String> AUDIT_ATTEMPT = Metadata.Key.of("latent-audit-attempt", Metadata.ASCII_STRING_MARSHALLER);
    static final Metadata.Key<byte[]> DETAILS = Metadata.Key.of("grpc-status-details-bin", Metadata.BINARY_BYTE_MARSHALLER);
    static final Set<String> PHASES = Set.of("received", "resolved", "admitted", "queued", "materializing",
            "running", "suspended", "preparing_commit", "committed", "effects_pending");
    static final Set<String> TERMINALS = Set.of("completed", "rejected", "cancelled", "deadline_exceeded",
            "resource_exhausted", "guest_trap", "state_conflict", "dependency_failed", "platform_failed");
    static final Map<String, Integer> PLATFORM_CODES = Map.ofEntries(
            Map.entry("unavailable", 14), Map.entry("deadline-exceeded", 4), Map.entry("cancelled", 1),
            Map.entry("resource-exhausted", 8), Map.entry("permission-denied", 7), Map.entry("unauthenticated", 16),
            Map.entry("invalid-argument", 3), Map.entry("not-found", 5), Map.entry("already-exists", 6),
            Map.entry("incompatible-contract", 9), Map.entry("state-conflict", 10), Map.entry("dependency-failed", 9),
            Map.entry("guest-trap", 13), Map.entry("corrupt-artifact", 15), Map.entry("route-unavailable", 14),
            Map.entry("admission-rejected", 8), Map.entry("internal", 13));

    static final class Invalid extends RuntimeException {
        private static final long serialVersionUID = 1L;
        final transient Optional<Management.UnsupportedWireValue> unsupported;
        Invalid() { super("invalid bounded protocol value"); unsupported = Optional.empty(); }
        Invalid(String field, String value) {
            super("unsupported bounded protocol value");
            unsupported = value.length() <= 256 && value.getBytes(StandardCharsets.UTF_8).length <= 256
                    ? Optional.of(new Management.UnsupportedWireValue(field, value)) : Optional.empty();
        }
    }

    private Protocol() { }

    static boolean identity(String value) {
        return value != null && !value.isEmpty() && value.length() <= 256
                && value.getBytes(StandardCharsets.UTF_8).length <= 256
                && value.codePoints().noneMatch(character -> Character.isWhitespace(character) || Character.isISOControl(character));
    }

    static void require(boolean condition) { if (!condition) throw new Invalid(); }

    static void publication(Optional<String> value) {
        value.ifPresent(identity -> require(identity.matches("publication:sha256:[0-9a-f]{64}")));
    }

    static long sourceSize(Object value, long remaining, int depth) {
        if (value == null || remaining < 0 || depth > 24) throw new Invalid();
        long used = 8;
        if (value instanceof String text) {
            require(text.length() <= remaining);
            used += text.getBytes(StandardCharsets.UTF_8).length;
        } else if (value instanceof ByteBuffer bytes) {
            used += bytes.remaining();
        } else if (value instanceof Optional<?> optional) {
            if (optional.isPresent()) used += sourceSize(optional.get(), remaining - used, depth + 1);
        } else if (value instanceof Map<?, ?> values) {
            require(values.size() <= 128);
            for (var entry : values.entrySet()) {
                used += sourceSize(entry.getKey(), remaining - used, depth + 1);
                used += sourceSize(entry.getValue(), remaining - used, depth + 1);
            }
        } else if (value instanceof List<?> values) {
            require(values.size() <= 128);
            for (var item : values) used += sourceSize(item, remaining - used, depth + 1);
        } else if (value.getClass().isRecord()) {
            try {
                for (var component : value.getClass().getRecordComponents()) {
                    used += sourceSize(component.getAccessor().invoke(value), remaining - used, depth + 1);
                }
            } catch (ReflectiveOperationException failure) { throw new Invalid(); }
        } else {
            require(value instanceof Number || value instanceof Boolean);
        }
        require(used <= remaining);
        return used;
    }

    static void request(Object value, String tenant) {
        switch (value) {
            case Management.InvokeRequest request -> {
                require(request.target().isPresent());
                var target = request.target().get();
                require(identity(target.tenant()) && target.tenant().equals(tenant) && identity(target.service())
                        && identity(target.contract()) && identity(target.function()));
                target.route().ifPresent(route -> require(identity(route)));
                request.activationId().ifPresent(identity -> require(identity(identity)));
                request.rootActivationId().ifPresent(identity -> require(identity(identity)));
                request.parentActivationId().ifPresent(identity -> require(identity(identity)));
                require(request.parentActivationId().isEmpty() || request.rootActivationId().isPresent());
            }
            case Management.CancelRequest request -> require(identity(request.activationId()) && request.reason().length() <= 4096);
            case Management.GetActivationRequest request -> require(identity(request.activationId()));
            case Management.GetPolicyRequest request -> require(identity(request.id()));
            case Management.GetPolicyOperationRequest request -> require(identity(request.operationId()));
            case Management.ListPoliciesRequest request -> requestPage(request.page(), true);
            case Management.ListCapabilitiesRequest request -> {
                require(identity(request.deploymentId()));
                requestPage(request.page(), false);
                request.contractPrefix().ifPresent(Protocol::filter);
                request.provider().ifPresent(Protocol::filter);
            }
            case Management.ApplyPolicyRequest request -> {
                require(identity(request.operationId()) && request.expectedGeneration().isPresent() && request.policy().isPresent());
                var policy = request.policy().get();
                require(identity(policy.id()) && policy.metadata().isPresent());
                var metadata = policy.metadata().get();
                require(metadata.name().equals(policy.id()) && metadata.tenant().equals(Optional.of(tenant))
                        && metadata.namespace().isEmpty() && metadata.labels().isEmpty() && metadata.annotations().isEmpty()
                        && policy.generation() == 0 && policy.contentDigest().isEmpty() && !policy.revoked());
            }
            default -> throw new Invalid();
        }
    }

    static void filter(String value) {
        require(!value.isEmpty() && value.length() <= 128 && value.chars().allMatch(character -> character >= 33 && character <= 126));
    }

    static void requestPage(Optional<Management.PageRequest> page, boolean policy) {
        require(!policy || page.isPresent());
        page.ifPresent(value -> {
            long size = Integer.toUnsignedLong(value.pageSize());
            require(size <= (policy ? 32 : 128) && (!policy || size > 0));
            value.pageToken().ifPresent(token -> require(!token.isEmpty() && token.getBytes(StandardCharsets.UTF_8).length <= (policy ? 117 : 160)));
        });
    }

    static void platform(Management.PlatformError error) {
        require(error.code().length() <= 64 && error.message().length() <= 4096 && error.detailItems().size() <= 16);
        for (var detail : error.detailItems()) {
            require(detail.kind().length() <= 128 && detail.fields().size() <= 32);
            detail.fields().forEach((key, value) -> require(key.length() <= 128 && value.length() <= 1024));
        }
        if (!PLATFORM_CODES.containsKey(error.code())) throw new Invalid("platform_error.code", error.code());
    }

    static void terminal(String state) {
        if (!TERMINALS.contains(state)) throw new Invalid("activation.terminal_state", state);
    }

    static String terminalFor(String code) {
        return switch (code) {
            case "deadline-exceeded", "resource-exhausted", "guest-trap", "state-conflict" -> code.replace('-', '_');
            case "cancelled" -> "cancelled";
            case "dependency-failed", "unavailable", "route-unavailable" -> "dependency_failed";
            case "admission-rejected", "permission-denied", "unauthenticated", "invalid-argument", "not-found",
                    "already-exists", "incompatible-contract", "corrupt-artifact" -> "rejected";
            default -> "platform_failed";
        };
    }

    static void policy(Management.Policy policy, String tenant, Optional<String> expected, Management.CapabilityPolicyRecordKind kind) {
        require(identity(policy.id()) && expected.map(policy.id()::equals).orElse(true));
        policy.metadata().flatMap(Management.ObjectMetadata::tenant).ifPresent(scope -> require(scope.equals(tenant)));
        if (!policy.recordKind().equals(kind)) throw new Invalid("policy.record_kind", Integer.toString(policy.recordKind().value()));
    }

    static void responsePage(Optional<Management.PageResponse> page, int count, Optional<Management.PageRequest> requested, boolean policy) {
        int maximum = requested.map(Management.PageRequest::pageSize).orElse(0);
        if (!policy && maximum == 0) maximum = 128;
        require(page.isPresent() && count <= maximum);
        page.flatMap(Management.PageResponse::nextPageToken).ifPresent(token -> require(!token.isEmpty()
                && token.getBytes(StandardCharsets.UTF_8).length <= (policy ? 117 : 160)));
    }

    static Optional<String> activation(Object value) {
        if (value instanceof Management.InvokeResponse response && identity(response.activationId())) return Optional.of(response.activationId());
        if (value instanceof Management.ActivationStatus response && identity(response.activationId())) return Optional.of(response.activationId());
        return Optional.empty();
    }

    static boolean response(Object value, Object request, String tenant, Management.RequestIdentity recovery) {
        activation(value).ifPresent(identity -> require(recovery.activationId().map(identity::equals).orElse(true)));
        switch (value) {
            case Management.InvokeResponse response -> {
                require(identity(response.activationId()) && response.consumption().isPresent());
                require((response.success().isPresent() ? 1 : 0) + (response.declaredError().isPresent() ? 1 : 0)
                        + (response.platformFailure().isPresent() ? 1 : 0) == 1);
                require((response.revisionId().isEmpty() && response.releaseDigest().isEmpty() && response.routeGeneration() == 0
                        && response.platformFailure().isPresent()) || (identity(response.revisionId()) && identity(response.releaseDigest())
                        && response.routeGeneration() != 0));
                response.platformFailure().ifPresent(Protocol::platform);
                publication(response.publicationId());
            }
            case Management.CancelResponse response -> {
                int disposition = response.disposition().value();
                if (disposition == 1 || disposition == 3) require(response.terminalState().isEmpty());
                if (disposition == 2) { require(response.terminalState().isPresent()); terminal(response.terminalState().get()); }
                require(disposition != 0);
            }
            case Management.ActivationStatus response -> {
                require(identity(response.activationId()));
                if (!PHASES.contains(response.phase())) throw new Invalid("activation.phase", response.phase());
                int count = (response.succeeded().isPresent() ? 1 : 0) + (response.declaredError().isPresent() ? 1 : 0)
                        + (response.platformFailure().isPresent() ? 1 : 0);
                if (response.terminalState().isEmpty()) {
                    require(count == 0 && response.finalConsumption().isEmpty() && response.terminalAtUnixMillis().isEmpty());
                } else {
                    require(count == 1 && response.finalConsumption().isPresent() && response.terminalAtUnixMillis().isPresent());
                    String state = response.terminalState().get();
                    terminal(state);
                    response.platformFailure().ifPresent(Protocol::platform);
                    require(state.equals(response.platformFailure().map(error -> terminalFor(error.code())).orElse("completed")));
                }
            }
            case Management.GetPolicyResponse response -> response.policy().ifPresent(policy ->
                    policy(policy, tenant, Optional.of(((Management.GetPolicyRequest) request).id()), ((Management.GetPolicyRequest) request).recordKind()));
            case Management.ListPoliciesResponse response -> {
                responsePage(response.page(), response.policies().size(), ((Management.ListPoliciesRequest) request).page(), true);
                response.policies().forEach(policy -> policy(policy, tenant, Optional.empty(), ((Management.ListPoliciesRequest) request).recordKind()));
            }
            case Management.ListCapabilitiesResponse response -> {
                var expected = (Management.ListCapabilitiesRequest) request;
                responsePage(response.page(), response.capabilities().size(), expected.page(), false);
                response.revision().ifPresent(revision -> {
                    require(revision.deploymentId().equals(expected.deploymentId()));
                    publication(revision.publicationId());
                });
            }
            case Management.ApplyPolicyResponse response -> {
                require(response.policy().isPresent() && response.receipt().isPresent());
                var document = response.policy().get();
                var receipt = response.receipt().get();
                var expected = (Management.ApplyPolicyRequest) request;
                policy(document, tenant, Optional.of(expected.policy().orElseThrow().id()), expected.policy().get().recordKind());
                require(receipt.operationId().equals(expected.operationId()) && receipt.tenant().equals(tenant)
                        && receipt.id().equals(document.id()) && receipt.generation() == document.generation()
                        && receipt.contentDigest().equals(document.contentDigest()) && receipt.recordKind().equals(document.recordKind())
                        && receipt.revoked() == document.revoked());
            }
            case Management.GetPolicyOperationResponse response -> {
                if (response.receipt().isEmpty()) return false;
                var receipt = response.receipt().get();
                require(receipt.operationId().equals(((Management.GetPolicyOperationRequest) request).operationId())
                        && receipt.tenant().equals(tenant) && identity(receipt.id()));
            }
            default -> throw new Invalid();
        }
        return true;
    }

    static <Value> Optional<Value> single(Metadata metadata, Metadata.Key<Value> key) {
        Iterable<Value> values = metadata.getAll(key);
        if (values == null) return Optional.empty();
        var iterator = values.iterator();
        if (!iterator.hasNext()) return Optional.empty();
        Value value = iterator.next();
        require(!iterator.hasNext());
        return Optional.of(value);
    }

    record Audit(Optional<Management.AuditAck> ack, Optional<String> status, Optional<Long> attempt) { }

    static Audit audit(Metadata metadata) {
        Optional<String> raw = single(metadata, AUDIT_STATUS);
        Optional<String> sequence = single(metadata, AUDIT_ATTEMPT);
        Optional<Long> attempt = sequence.map(value -> {
            try { long parsed = Management.parseU64Decimal(value); require(parsed != 0); return parsed; }
            catch (NumberFormatException failure) { throw new Invalid(); }
        });
        require(raw.isPresent() || sequence.isEmpty());
        if (raw.isEmpty()) return new Audit(Optional.empty(), raw, attempt);
        String status = raw.get();
        if (status.isEmpty() || status.length() > 64 || !status.chars().allMatch(character -> character >= 33 && character <= 126)) {
            throw new Invalid("audit.status", status);
        }
        Management.AuditAckStatus known = switch (status) {
            case "durable" -> Management.AuditAckStatus.DURABLE;
            case "outcome-unknown" -> Management.AuditAckStatus.OUTCOME_UNKNOWN;
            case "audit-unavailable" -> Management.AuditAckStatus.AUDIT_UNAVAILABLE;
            case "disabled" -> Management.AuditAckStatus.DISABLED;
            default -> null;
        };
        require(!Set.of("durable", "outcome-unknown").contains(status) || attempt.isPresent());
        return new Audit(Optional.ofNullable(known).map(value -> new Management.AuditAck(value, attempt)), raw, attempt);
    }

    static Optional<Management.PlatformError> details(Metadata metadata, int code) {
        return single(metadata, DETAILS).map(bytes -> {
            require(bytes.length <= 8192);
            try {
                var value = Wire.fromWire(latent.control.v1.Common.PlatformError.parseFrom(bytes));
                platform(value);
                require(PLATFORM_CODES.get(value.code()) == code);
                return value;
            } catch (com.google.protobuf.InvalidProtocolBufferException failure) { throw new Invalid(); }
        });
    }

    static <Value extends Message> MethodDescriptor.Marshaller<Value> marshaller(Value prototype, int limit) {
        var delegate = ProtoUtils.marshaller(prototype);
        return new MethodDescriptor.Marshaller<>() {
            @Override public InputStream stream(Value value) { return delegate.stream(value); }
            @Override public Value parse(InputStream input) {
                try {
                    byte[] bytes = input.readNBytes(limit + 1);
                    require(bytes.length <= limit);
                    validateWire(CodedInputStream.newInstance(bytes), prototype.getDescriptorForType(), 0);
                    return delegate.parse(new ByteArrayInputStream(bytes));
                } catch (Invalid failure) { throw failure; }
                catch (java.io.IOException | RuntimeException failure) { throw new Invalid(); }
            }
        };
    }

    static void validateWire(CodedInputStream input, Descriptors.Descriptor descriptor, int depth) throws java.io.IOException {
        require(depth <= 32);
        Set<Integer> seen = new HashSet<>();
        Set<Descriptors.OneofDescriptor> groups = new HashSet<>();
        int entries = 0;
        while (!input.isAtEnd()) {
            require(++entries <= 65536);
            int tag = input.readTag();
            var field = descriptor.findFieldByNumber(tag >>> 3);
            if (field != null) {
                require(field.isRepeated() || seen.add(field.getNumber()));
                if (field.getContainingOneof() != null) require(groups.add(field.getContainingOneof()));
                if (field.getJavaType() == Descriptors.FieldDescriptor.JavaType.MESSAGE) {
                    require((tag & 7) == 2);
                    int size = input.readRawVarint32();
                    int previous = input.pushLimit(size);
                    validateWire(input, field.getMessageType(), depth + 1);
                    input.popLimit(previous);
                    continue;
                }
            }
            require(input.skipField(tag));
        }
    }
}
