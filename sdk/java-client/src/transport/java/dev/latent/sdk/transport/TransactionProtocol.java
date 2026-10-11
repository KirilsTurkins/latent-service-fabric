package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import dev.latent.sdk.TransactionClient;
import dev.latent.sdk.Transactions;
import com.google.protobuf.CodedInputStream;
import com.google.protobuf.Descriptors;
import com.google.protobuf.Message;
import io.grpc.MethodDescriptor;
import io.grpc.protobuf.ProtoUtils;
import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/** Semantic checks for the authoritative DTOs, on the existing protobuf codec. */
final class TransactionProtocol {
    static final int WIRE_BYTES = 2 * 1024 * 1024;
    private static final int GRAPH_BYTES = 8 * 1024 * 1024;
    private TransactionProtocol() { }

    static Object part(Object value, String name) {
        Protocol.require(value != null && value.getClass().isRecord());
        try {
            Object field = value.getClass().getMethod(name).invoke(value);
            return field instanceof Optional<?> optional ? optional.orElse(null) : field;
        } catch (ReflectiveOperationException failure) { throw new Protocol.Invalid(); }
    }

    static String text(Object value, int maximum, boolean nonempty) {
        Protocol.require(value instanceof String);
        String text = (String) value;
        Protocol.require(text.length() <= maximum && text.getBytes(StandardCharsets.UTF_8).length <= maximum
                && (!nonempty || !text.isEmpty()) && text.codePoints().noneMatch(Character::isISOControl)
                && text.codePoints().noneMatch(point -> point >= 0xd800 && point <= 0xdfff));
        return text;
    }
    static String id(Object value) { return text(value, 256, true); }
    private static void optionalId(Object value) { if (value != null) id(value); }
    static long unsigned(Object value) { Protocol.require(value instanceof Long); return (Long) value; }
    private static void positive(Object value) { Protocol.require(unsigned(value) != 0); }
    private static int integer(Object value) { Protocol.require(value instanceof Integer); return (Integer) value; }
    private static int enumeration(Object value, int maximum, String field) {
        Protocol.require(value != null);
        int raw = integer(part(value, "value"));
        if (raw < 1 || raw > maximum) throw new Protocol.Invalid(field, Integer.toString(raw));
        return raw;
    }
    private static ByteBuffer bytes(Object value, int maximum, boolean nonempty) {
        Protocol.require(value instanceof ByteBuffer);
        ByteBuffer buffer = (ByteBuffer) value;
        Protocol.require(buffer.remaining() <= maximum && (!nonempty || buffer.hasRemaining()));
        return buffer;
    }
    private static List<?> list(Object value, int maximum) {
        Protocol.require(value instanceof List<?> && ((List<?>) value).size() <= maximum);
        return (List<?>) value;
    }
    private static void same(Object left, Object right) { Protocol.require(java.util.Objects.equals(left, right)); }
    private static void digest(Object value) { Protocol.require(id(value).matches("sha256:[0-9a-f]{64}")); }
    private static void media(Object value) { Protocol.require(text(value, 128, true).matches("[\\x20-\\x7e]+")); }

    private static void namespace(Object value, String tenant) {
        same(id(part(value, "tenant")), tenant);
        id(part(value, "namespace"));
        String incarnation = text(part(value, "incarnation"), 20, true);
        try {
            long parsed = Long.parseUnsignedLong(incarnation);
            Protocol.require(parsed != 0 && Long.toUnsignedString(parsed).equals(incarnation));
        } catch (NumberFormatException failure) { throw new Protocol.Invalid(); }
    }
    private static void publication(Object value, String tenant) {
        same(part(value, "tenant"), tenant);
        Protocol.require(id(part(value, "id")).matches("publication:sha256:[0-9a-f]{64}"));
    }
    private static void profile(Object value) { same(value, Transactions.currentProfile()); }
    private static void commandSelector(Object value, String tenant) {
        namespace(part(value, "namespace"), tenant);
        id(part(value, "operation")); id(part(value, "clientKey"));
        optionalId(part(value, "entity")); optionalId(part(value, "sharedRecoveryScope"));
    }
    private static void inspect(Object value, String tenant) {
        profile(part(value, "profile")); namespace(part(value, "namespace"), tenant);
        publication(part(value, "authorizationPublication"), tenant);
    }
    private static void lookup(Object value, String tenant) {
        profile(part(value, "profile")); commandSelector(part(value, "command"), tenant);
        publication(part(value, "authorizationPublication"), tenant);
    }
    private static void effectVersion(Object value) {
        ByteBuffer data = bytes(value, 32, true); Protocol.require(data.remaining() == 32);
        boolean nonzero = false;
        for (int offset = data.position(); offset < data.limit(); offset++) nonzero |= data.get(offset) != 0;
        Protocol.require(nonzero);
    }
    private static void effectMutation(Object value, String tenant) {
        Object target = part(value, "effect"); lookup(target, tenant);
        Protocol.require(id(part(target, "effectId")).matches("[0-9a-f]{64}")); id(part(value, "operationId"));
        effectVersion(part(value, "expectedVersion")); digest(part(value, "expectedPolicyDigest")); text(part(value, "reason"), 1024, true);
        int action = enumeration(part(value, "mutation"), 5, "state.mutation"); long delay = unsigned(part(value, "retryDelayMillis"));
        Protocol.require(action == 1 && delay >= 1 && delay <= 60000 || (action == 2 || action == 5) && delay == 0);
    }
    private static void effectPlan(Object value, String tenant) {
        Object original = part(value, "original"); effectMutation(original, tenant); effectVersion(part(value, "planDigest"));
        int sequence = integer(part(value, "managementSequence")), attempt = integer(part(value, "dispatchAttempt"));
        long owner = unsigned(part(value, "ownerEpoch")), claim = unsigned(part(value, "claimGeneration"));
        long prepared = unsigned(part(value, "preparedAtUnixMillis")), expires = unsigned(part(value, "expiresAtUnixMillis"));
        boolean attempted = owner != 0 && claim != 0 && attempt != 0;
        Protocol.require(sequence >= 1 && sequence <= 128 && attempt >= 0 && attempt <= 128 &&
                (attempted || owner == 0 && claim == 0 && attempt == 0) && prepared != 0 &&
                Long.compareUnsigned(expires, prepared) > 0 && Long.compareUnsigned(expires - prepared, 30000) <= 0);
        int before = enumeration(part(value, "before"), 10, "effect.disposition"), safety = enumeration(part(value, "safety"), 4, "effect.plan.safety");
        int action = enumeration(part(original, "mutation"), 5, "state.mutation");
        Protocol.require(action == 1 && attempted && (safety == 1 && before == 4 || safety == 2 && (before == 4 || before == 5)) ||
                action == 5 && attempted && safety == 3 && (before == 4 || before == 5) ||
                action == 2 && safety == 4 && (before == 1 || before == 4 || before == 5 || before == 7 || before == 9));
        Object dedup = part(value, "dedupValidUntilUnixMillis"); Protocol.require((safety == 2) == (dedup != null));
        if (dedup != null) Protocol.require(Long.compareUnsigned(unsigned(dedup), expires) > 0);
        // Historical receipts use the original finite window, never the current clock.
    }
    private static void effectPlanAssociation(Object value, Object plan, String tenant, boolean recovery) {
        effectPlan(plan, tenant); Object original = part(plan, "original"), target = part(original, "effect"), current = part(value, "namespace");
        same(part(current, "namespace"), part(part(target, "command"), "namespace")); same(part(current, "profile"), part(target, "profile"));
        same(part(value, "operationId"), part(original, "operationId"));
        if (!recovery) {
            same(part(current, "authorizationPublication"), part(target, "authorizationPublication")); same(part(value, "recordId"), part(target, "effectId"));
            for (String field : List.of("mutation", "expectedVersion", "expectedPolicyDigest", "reason")) same(part(value, field), part(original, field));
        }
    }
    private static void effectPlanReceipt(Object value, Object expected, String tenant) {
        Object details = part(value, "effect"), plan = part(details, "originalPlan"), original = part(plan, "original");
        effectPlan(plan, tenant); same(plan, expected); same(part(details, "before"), part(plan, "before"));
        for (String field : List.of("operationId", "mutation")) same(part(value, field), part(original, field));
        same(part(value, "recordId"), part(part(original, "effect"), "effectId")); same(part(value, "beforeVersion"), part(original, "expectedVersion"));
        same(part(value, "policyDigest"), part(original, "expectedPolicyDigest")); effectVersion(part(value, "beforeVersion")); effectVersion(part(value, "afterVersion"));
        long completed = unsigned(part(value, "completedAtUnixMillis"));
        Protocol.require(enumeration(part(value, "disposition"), 5, "state.disposition") == 1 &&
                Long.compareUnsigned(completed, unsigned(part(plan, "preparedAtUnixMillis"))) >= 0 &&
                Long.compareUnsigned(completed, unsigned(part(plan, "expiresAtUnixMillis"))) < 0);
        int fact = enumeration(part(details, "fact"), 3, "effect.management.fact"), action = enumeration(part(original, "mutation"), 5, "state.mutation");
        int after = enumeration(part(details, "after"), 10, "effect.disposition");
        Protocol.require(fact == 1 && action == 1 && after == 9 || fact == 2 && action == 5 && after == 3 || fact == 3 && action == 2 && (after == 8 || after == 10));
        Object provider = part(details, "providerReceipt"), observed = part(details, "providerObservedAtUnixMillis");
        Protocol.require((fact == 2) == (provider != null) && (provider != null) == (observed != null)); optionalId(provider);
        if (observed != null) { positive(observed); Protocol.require(Long.compareUnsigned(unsigned(observed), completed) <= 0); }
    }
    private static void fence(Object value) {
        for (String name : List.of("commandId", "attemptId", "transactionId")) id(part(value, name));
        bytes(part(value, "ownerFence"), 256, true);
    }
    private static void page(Object value) {
        int limit = integer(part(value, "limit"));
        Protocol.require(limit > 0 && limit <= 128);
        if (part(value, "cursor") != null) bytes(part(value, "cursor"), 256, true);
    }
    private static void metadata(Object value, boolean caller) {
        Protocol.require(value instanceof Map<?, ?> && ((Map<?, ?>) value).size() <= 32);
        int total = 0;
        for (var entry : ((Map<?, ?>) value).entrySet()) {
            String key = id(entry.getKey()), member = text(entry.getValue(), 1024, false);
            Protocol.require(!caller || !key.toLowerCase(java.util.Locale.ROOT).matches("latent\\.(auth|principal)\\..*"));
            total += key.getBytes(StandardCharsets.UTF_8).length + member.getBytes(StandardCharsets.UTF_8).length;
        }
        Protocol.require(total <= 8192);
    }
    private static void invocation(Object value, String tenant) {
        Protocol.request(value, tenant);
        for (String name : List.of("activationId", "rootActivationId", "parentActivationId", "idempotencyKey")) optionalId(part(value, name));
        bytes(part(value, "payload"), 1024 * 1024, false); media(part(value, "mediaType"));
        metadata(part(value, "metadata"), true); Protocol.require(part(value, "budget") != null);
        Protocol.require(integer(part(value, "priority")) >= 0 && integer(part(value, "priority")) <= 255);
    }
    private static void quota(Object value) {
        for (String name : List.of("stateKeys", "resultRows", "effectRows", "stateBytes", "resultBytes", "effectBytes", "payloadBytes", "recoveryBytes")) {
            long number = unsigned(part(value, name));
            long maximum = name.endsWith("Keys") || name.endsWith("Rows") ? 1_000_000L : 1_073_741_824L;
            Protocol.require(number != 0 && Long.compareUnsigned(number, maximum) <= 0);
        }
        Protocol.require(Long.compareUnsigned(unsigned(part(value, "recoveryBytes")), unsigned(part(value, "resultBytes"))) <= 0);
    }
    private static void generation(Object value) { positive(part(value, "ownerEpoch")); positive(part(value, "revision")); }
    private static void control(Object value) {
        profile(part(value, "profile")); enumeration(part(value, "scope"), 1, "dispatcher.scope");
        id(part(value, "operationId")); enumeration(part(value, "action"), 2, "dispatcher.action");
        generation(part(value, "expectedGeneration"));
        Protocol.require(unsigned(part(part(value, "expectedGeneration"), "revision")) != -1L);
    }

    static void request(Object value, String tenant) {
        switch (value) {
            case Transactions.InvokeCommandRequest request -> {
                profile(part(value, "profile")); commandSelector(part(value, "command"), tenant);
                invocation(part(value, "invocation"), tenant); id(part(value, "inputFormat"));
                Set<ByteBuffer> keys = new HashSet<>();
                for (Object expected : list(part(value, "expectedVersions"), 128)) {
                    Protocol.require(keys.add(bytes(part(expected, "key"), 1024, false)));
                    Object absent = part(expected, "absent"), version = part(expected, "version");
                    Protocol.require((absent == null) != (version == null));
                    if (absent != null) same(absent, true); else bytes(version, 256, true);
                }
                Object retry = part(value, "retryAttempt");
                if (retry != null) { id(part(retry, "requestId")); fence(part(retry, "expectedAbort")); }
            }
            case Transactions.QueryRequest request -> {
                profile(part(value, "profile")); namespace(part(value, "namespace"), tenant);
                invocation(part(value, "invocation"), tenant); optionalId(part(value, "entity"));
                if (part(value, "minimumViewVersion") != null) bytes(part(value, "minimumViewVersion"), 256, true);
            }
            case Transactions.LookupCommandRequest request -> { lookup(value, tenant); optionalId(part(value, "attemptId")); }
            case Transactions.LookupCommitRequest request -> { lookup(value, tenant); id(part(value, "receiptId")); }
            case Transactions.GetEffectRequest request -> { lookup(value, tenant); id(part(value, "effectId")); }
            case Transactions.ListEffectHistoryRequest request -> {
                lookup(part(value, "effect"), tenant); id(part(part(value, "effect"), "effectId")); page(part(value, "page"));
            }
            case Transactions.CancelCommandRequest request -> {
                lookup(part(value, "command"), tenant); text(part(value, "reason"), 1024, true);
            }
            case Transactions.InspectNamespaceRequest request -> inspect(value, tenant);
            case Transactions.SelectEntityRequest request -> {
                inspect(part(value, "namespace"), tenant); page(part(value, "page"));
                if (part(value, "prefix") != null) bytes(part(value, "prefix"), 256, false);
            }
            case Transactions.GetStateOperationReceiptRequest request -> {
                inspect(part(value, "namespace"), tenant); id(part(value, "operationId"));
                if (part(value, "originalEffectPlan") != null) effectPlanAssociation(value, part(value, "originalEffectPlan"), tenant, true);
            }
            case Transactions.PlanEffectMutationRequest request -> effectMutation(value, tenant);
            case Transactions.MutateStateRequest request -> {
                inspect(part(value, "namespace"), tenant); id(part(value, "operationId"));
                bytes(part(value, "expectedVersion"), 256, true); digest(part(value, "expectedPolicyDigest")); text(part(value, "reason"), 1024, true);
                int mutation = enumeration(part(value, "mutation"), 5, "state.mutation");
                optionalId(part(value, "recordId")); Protocol.require((mutation == 4) == (part(value, "recordId") == null));
                if (mutation == 1 || mutation == 2 || mutation == 5) effectPlanAssociation(value, part(value, "effectPlan"), tenant, false);
                else Protocol.require(part(value, "effectPlan") == null);
            }
            case Transactions.MutateNamespaceRequest request -> {
                inspect(part(value, "namespace"), tenant); id(part(value, "operationId"));
                int mutation = enumeration(part(value, "mutation"), 5, "namespace.mutation");
                long expected = unsigned(part(value, "expectedGeneration"));
                Protocol.require((mutation == 1) == (expected == 0));
                if (mutation == 1) same(part(part(part(value, "namespace"), "namespace"), "incarnation"), "1");
                if (mutation == 1 || mutation == 5) {
                    id(part(part(value, "configuration"), "stateSchema")); quota(part(part(value, "configuration"), "quota"));
                } else Protocol.require(part(value, "configuration") == null);
            }
            case Transactions.InspectDispatcherRequest request -> { profile(part(value, "profile")); enumeration(part(value, "scope"), 1, "dispatcher.scope"); }
            case Transactions.ControlDispatcherRequest request -> control(value);
            case Transactions.GetDispatcherOperationRequest request -> control(part(value, "original"));
            default -> throw new Protocol.Invalid();
        }
    }

    private static void source(Object value) {
        Protocol.require(id(part(value, "publicationId")).matches("publication:sha256:[0-9a-f]{64}"));
        for (String name : List.of("revisionId", "inputFormat", "resultFormat")) id(part(value, name));
        for (String name : List.of("releaseDigest", "componentDigest", "contractDigest", "stateSchema")) digest(part(value, name));
        positive(part(value, "routeGeneration"));
    }
    private static void retention(Object value) {
        id(part(value, "recordFormat")); Protocol.require(integer(part(value, "recordVersion")) != 0);
        for (Object identity : list(part(value, "requiredRecordIds"), 256)) id(identity);
    }
    private static void body(Object value, boolean rejection) {
        bytes(part(value, "payload"), 1024 * 1024, false); media(part(value, "mediaType")); metadata(part(value, "metadata"), false);
        if (rejection) { id(part(value, "code")); text(part(value, "message"), 4096, false); }
        else {
            optionalId(part(value, "committedStateVersion"));
            for (Object identity : list(part(value, "effectIds"), 128)) id(identity);
        }
    }
    private static void platform(Object value) {
        Management.PlatformError error = (Management.PlatformError) value;
        Protocol.platform(error);
        text(error.message(), 1024, false);
        Protocol.require(error.detailItems().size() <= 16);
        for (var detail : error.detailItems()) { id(detail.kind()); metadata(detail.fields(), false); }
    }
    private static Object command(Object value, Object selector, String tenant) {
        Object key = part(value, "key");
        namespace(part(key, "namespace"), tenant); id(part(key, "recoveryScope"));
        id(part(key, "operation")); id(part(key, "clientKey")); optionalId(part(key, "entity"));
        for (String name : List.of("namespace", "operation", "entity", "clientKey")) same(part(key, name), part(selector, name));
        int outcome = enumeration(part(value, "outcome"), 7, "command.outcome");
        boolean known = outcome != 5 && outcome != 6;
        for (String name : List.of("commandId", "attemptId")) {
            if (known || !"".equals(part(value, name))) id(part(value, name));
        }
        ByteBuffer fingerprint = bytes(part(value, "fingerprintSha256"), 32, known);
        if (known) Protocol.require(fingerprint.remaining() == 32);
        if (known || part(value, "source") != null) source(part(value, "source"));
        Object retained = part(value, "retention"); if (retained != null) retention(retained);
        Object success = part(value, "success"), rejection = part(value, "businessRejection"), technical = part(value, "technicalFailure");
        Protocol.require((success == null ? 0 : 1) + (rejection == null ? 0 : 1) + (technical == null ? 0 : 1) <= 1);
        if (success != null) body(success, false); if (rejection != null) body(rejection, true); if (technical != null) platform(technical);
        if (part(value, "cleanupFailure") != null) platform(part(value, "cleanupFailure"));
        Object commit = part(value, "commit"), abort = part(value, "provenAbort");
        if (commit != null) {
            for (String name : List.of("commandId", "attemptId", "transactionId", "receiptId")) id(part(commit, name));
            bytes(part(commit, "committedVersion"), 256, true); source(part(commit, "source"));
            var ids = list(part(commit, "effectIds"), 128); for (Object identity : ids) id(identity);
            Protocol.require(new HashSet<>(ids).size() == ids.size());
            for (String name : List.of("commandId", "attemptId", "source")) same(part(commit, name), part(value, name));
        }
        if (abort != null) {
            fence(abort); same(part(abort, "commandId"), part(value, "commandId")); same(part(abort, "attemptId"), part(value, "attemptId"));
        }
        boolean empty = success == null && rejection == null && technical == null;
        boolean omitted = empty && retained != null && Boolean.FALSE.equals(part(retained, "payloadAvailable"));
        boolean durable = Boolean.TRUE.equals(part(value, "metadataDurable")), committed = Boolean.TRUE.equals(part(value, "applicationStateCommitted"));
        switch (outcome) {
            case 2 -> Protocol.require(durable && committed && commit != null && abort == null && (success != null || omitted));
            case 3 -> Protocol.require(durable && !committed && commit == null && abort == null && (rejection != null || omitted));
            case 4 -> Protocol.require(durable && !committed && commit == null && abort != null && success == null && rejection == null);
            case 7 -> Protocol.require(durable && abort == null && empty && committed == (commit != null));
            default -> Protocol.require(!committed && commit == null && abort == null && empty);
        }
        return value;
    }
    private static void effect(Object value, Object expected) {
        for (String name : List.of("effectId", "commandId", "commandAttemptId", "providerProfile")) id(part(value, name));
        for (String name : List.of("providerReceipt", "failureCode", "managementOperationReceiptId")) optionalId(part(value, name));
        enumeration(part(value, "disposition"), 10, "effect.disposition"); same(part(value, "effectId"), expected);
        if (bytes(part(value, "recordVersion"), 32, false).hasRemaining()) effectVersion(part(value, "recordVersion"));
        Object owner = part(value, "ownerEpoch"), claim = part(value, "claimGeneration");
        Protocol.require((owner == null) == (claim == null));
        if (owner != null) { positive(owner); positive(claim); int attempt = integer(part(value, "dispatchAttempt")); Protocol.require(attempt >= 1 && attempt <= 128); }
        if (part(value, "retention") != null) retention(part(value, "retention"));
    }
    private static void boundedPage(Object value, Object requested, int count) {
        same(part(value, "returnedCount"), count); Protocol.require(count <= integer(part(requested, "limit")));
        Protocol.require(Long.compareUnsigned(unsigned(part(value, "encodedBytes")), 1024 * 1024) <= 0);
        Object cursor = part(value, "nextCursor");
        if (cursor != null) { bytes(cursor, 256, true); Protocol.require(!cursor.equals(part(requested, "cursor"))); }
    }
    private static void receipt(Object value, Object original, String tenant, boolean namespaceReceipt) {
        Object target = part(part(original, "namespace"), "namespace");
        namespace(part(value, "namespace"), tenant);
        for (String name : List.of("operationId", "receiptId", "authenticatedOperator")) id(part(value, name));
        same(part(value, "operationId"), part(original, "operationId"));
        int disposition = enumeration(part(value, "disposition"), 5, "state.disposition");
        if (namespaceReceipt) {
            same(part(part(value, "namespace"), "tenant"), part(target, "tenant"));
            same(part(part(value, "namespace"), "namespace"), part(target, "namespace"));
            id(part(value, "stateSchema")); enumeration(part(value, "status"), 4, "namespace.status");
            enumeration(part(value, "mutation"), 5, "namespace.mutation");
            if (disposition == 1) positive(part(value, "afterGeneration"));
        } else {
            same(part(value, "namespace"), target); bytes(part(value, "beforeVersion"), 256, true);
            bytes(part(value, "afterVersion"), 256, true); digest(part(value, "policyDigest"));
            enumeration(part(value, "mutation"), 5, "state.mutation"); optionalId(part(value, "recordId"));
        }
    }
    private static void view(Object value, Object target, String tenant) {
        namespace(part(value, "namespace"), tenant); same(part(value, "namespace"), target);
        bytes(part(value, "version"), 256, true); id(part(value, "stateSchema"));
    }
    private static void linkedInvocation(Object value, Object captured, String tenant, Object original) {
        source(captured);
        Protocol.response(value, original, tenant, new Management.RequestIdentity(
                ((Management.InvokeRequest) original).activationId(), Optional.empty()));
        for (String name : List.of("publicationId", "revisionId", "routeGeneration")) same(part(value, name), part(captured, name));
        same(part(value, "releaseDigest"), part(captured, "componentDigest"));
        if (part(value, "success") != null) body(part(value, "success"), false);
        if (part(value, "declaredError") != null) body(part(value, "declaredError"), true);
        if (part(value, "platformFailure") != null) platform(part(value, "platformFailure"));
    }
    private static void dispatcherReceipt(Object value, Object original) {
        for (String name : List.of("operationId", "receiptId", "authenticatedOperator", "actorTenant")) id(part(value, name));
        int action = enumeration(part(value, "action"), 2, "dispatcher.action");
        same(part(value, "operationId"), part(original, "operationId")); same(part(value, "action"), part(original, "action"));
        Object before = part(value, "beforeGeneration"), after = part(value, "afterGeneration");
        generation(before); generation(after); same(before, part(original, "expectedGeneration"));
        same(part(after, "ownerEpoch"), part(before, "ownerEpoch"));
        long revision = unsigned(part(before, "revision")); Protocol.require(revision != -1L);
        same(part(after, "revision"), revision + 1);
        Protocol.require(enumeration(part(value, "disposition"), 5, "dispatcher.disposition") == 1);
        if (action == 2) Protocol.require(Boolean.TRUE.equals(part(value, "clockContinuityProven")) && Boolean.FALSE.equals(part(value, "restoreReviewRequired")));
    }

    static void response(Object value, Object original, String tenant) {
        graph(value);
        switch (value) {
            case Transactions.InvokeCommandResponse result -> {
                Object inspected = command(part(value, "command"), part(original, "command"), tenant);
                linkedInvocation(part(value, "invocation"), part(inspected, "source"), tenant, part(original, "invocation"));
                for (var pair : List.of(List.of("success", "success"), List.of("businessRejection", "declaredError"), List.of("technicalFailure", "platformFailure"))) {
                    if (part(inspected, pair.get(0)) != null) same(part(inspected, pair.get(0)), part(part(value, "invocation"), pair.get(1)));
                }
                Protocol.require(part(inspected, "success") != null || part(inspected, "businessRejection") != null || part(inspected, "technicalFailure") != null
                        || part(part(value, "invocation"), "platformFailure") != null);
            }
            case Transactions.LookupCommandResponse result -> {
                Object inspected = command(part(value, "command"), part(original, "command"), tenant);
                if (part(original, "attemptId") != null) same(part(inspected, "attemptId"), part(original, "attemptId"));
            }
            case Transactions.LookupCommitResponse result -> {
                Object inspected = command(part(value, "command"), part(original, "command"), tenant);
                same(part(part(inspected, "commit"), "receiptId"), part(original, "receiptId"));
            }
            case Transactions.GetEffectResponse result -> effect(part(value, "effect"), part(original, "effectId"));
            case Transactions.ListEffectHistoryResponse result -> {
                var entries = list(part(value, "receipts"), 128);
                for (Object entry : entries) effect(entry, part(part(original, "effect"), "effectId"));
                boundedPage(part(value, "page"), part(original, "page"), entries.size());
            }
            case Transactions.CancelCommandResponse result -> {
                int disposition = enumeration(part(value, "disposition"), 5, "command.cancel.disposition");
                Object inspected = part(value, "command");
                if (inspected != null) {
                    command(inspected, part(part(original, "command"), "command"), tenant);
                    if (disposition == 2) same(part(inspected, "outcome"), Transactions.CommandOutcome.COMMITTED);
                } else Protocol.require(disposition == 4);
            }
            case Transactions.QueryResponse result -> {
                view(part(value, "view"), part(original, "namespace"), tenant);
                linkedInvocation(part(value, "invocation"), part(value, "source"), tenant, part(original, "invocation"));
            }
            case Transactions.InspectNamespaceResponse result -> {
                Object inspected = part(value, "namespace"); view(part(inspected, "view"), part(original, "namespace"), tenant);
                enumeration(part(inspected, "status"), 4, "namespace.status"); positive(part(inspected, "generation"));
                quota(part(inspected, "quota")); id(part(inspected, "engineProfile")); digest(part(inspected, "engineProfileDigest"));
                for (Object format : list(part(inspected, "retainedFormats"), 128)) retention(format);
                if (!text(part(inspected, "namespacePolicyDigest"), 71, false).isEmpty()) digest(part(inspected, "namespacePolicyDigest"));
            }
            case Transactions.SelectEntityResponse result -> {
                var entries = list(part(value, "entities"), 128); Set<Object> names = new HashSet<>();
                for (Object entry : entries) {
                    Protocol.require(names.add(id(part(entry, "entity")))); bytes(part(entry, "version"), 256, true);
                }
                boundedPage(part(value, "page"), part(original, "page"), entries.size());
            }
            case Transactions.MutateStateResponse result -> {
                Object accepted = part(value, "receipt"); receipt(accepted, original, tenant, false);
                same(part(accepted, "mutation"), part(original, "mutation")); same(part(accepted, "recordId"), part(original, "recordId"));
                same(part(accepted, "beforeVersion"), part(original, "expectedVersion")); same(part(accepted, "policyDigest"), part(original, "expectedPolicyDigest"));
                Object plan = part(original, "effectPlan"); Protocol.require((part(accepted, "effect") != null) == (plan != null));
                if (plan != null) effectPlanReceipt(accepted, plan, tenant);
            }
            case Transactions.PlanEffectMutationResponse result -> { effectPlan(part(value, "plan"), tenant); same(part(part(value, "plan"), "original"), original); }
            case Transactions.MutateNamespaceResponse result -> {
                Object accepted = part(value, "receipt"); receipt(accepted, original, tenant, true);
                same(part(accepted, "mutation"), part(original, "mutation"));
                int mutation = enumeration(part(original, "mutation"), 5, "namespace.mutation");
                same(part(accepted, "beforeGeneration"), mutation == 1 ? null : part(original, "expectedGeneration"));
                if (Transactions.StateOperationDisposition.COMMITTED.equals(part(accepted, "disposition"))) {
                    long expected = unsigned(part(original, "expectedGeneration")); Protocol.require(expected != -1L);
                    same(part(accepted, "afterGeneration"), expected + 1);
                    long incarnation = Long.parseUnsignedLong((String) part(part(part(original, "namespace"), "namespace"), "incarnation"));
                    if (mutation == 5) { Protocol.require(incarnation != -1L); incarnation++; }
                    same(part(part(accepted, "namespace"), "incarnation"), Long.toUnsignedString(incarnation));
                    same(part(part(accepted, "status"), "value"), mutation == 1 || mutation == 5 ? 1 : mutation);
                    if (part(original, "configuration") != null) same(part(accepted, "stateSchema"), part(part(original, "configuration"), "stateSchema"));
                }
            }
            case Transactions.GetStateOperationReceiptResponse result -> {
                Object state = part(value, "receipt"), namespace = part(value, "namespaceReceipt");
                Protocol.require((state == null) != (namespace == null)); receipt(state == null ? namespace : state, original, tenant, state == null);
                Object plan = part(original, "originalEffectPlan");
                Protocol.require((state != null && part(state, "effect") != null) == (plan != null));
                if (plan != null) effectPlanReceipt(state, plan, tenant);
            }
            case Transactions.InspectDispatcherResponse result -> {
                Object snapshot = part(value, "dispatcher"); generation(part(snapshot, "generation")); enumeration(part(snapshot, "failure"), 7, "dispatcher.failure");
                if (Boolean.TRUE.equals(part(snapshot, "pendingControl")) || Boolean.TRUE.equals(part(snapshot, "restoreReviewRequired"))) same(part(snapshot, "paused"), true);
            }
            case Transactions.ControlDispatcherResponse result -> {
                dispatcherReceipt(part(value, "receipt"), original);
                Protocol.require(!(result.replayed() && result.published()));
                if (Transactions.DispatcherAction.PAUSE.equals(part(original, "action")) && result.published()) Protocol.require(result.paused());
            }
            case Transactions.GetDispatcherOperationResponse result -> dispatcherReceipt(part(value, "receipt"), part(original, "original"));
            default -> throw new Protocol.Invalid();
        }
    }

    static void independentAudit(Object value) {
        Object audit = switch (value) {
            case Transactions.MutateStateResponse result -> result.auditAck().orElse(null);
            case Transactions.PlanEffectMutationResponse result -> result.auditAck().orElse(null);
            case Transactions.GetStateOperationReceiptResponse result -> result.auditAck().orElse(null);
            case Transactions.MutateNamespaceResponse result -> result.auditAck().orElse(null);
            case Transactions.InspectDispatcherResponse result -> result.auditAck().orElse(null);
            case Transactions.ControlDispatcherResponse result -> result.auditAck().orElse(null);
            case Transactions.GetDispatcherOperationResponse result -> result.auditAck().orElse(null);
            default -> null;
        };
        if (audit != null) enumeration(part(audit, "status"), 4, "audit.status");
    }

    static void graph(Object value) { graph(value, new long[]{GRAPH_BYTES, 4096}, 0, 128); }
    private static void graph(Object value, long[] budget, int depth, int listLimit) {
        Protocol.require(value != null && depth <= 32 && --budget[1] >= 0);
        budget[0] -= 32;
        if (value instanceof String text) {
            Protocol.require(text.length() <= budget[0]); budget[0] -= text.getBytes(StandardCharsets.UTF_8).length;
            Protocol.require(text.codePoints().noneMatch(point -> point >= 0xd800 && point <= 0xdfff));
        } else if (value instanceof ByteBuffer bytes) budget[0] -= bytes.remaining();
        else if (value instanceof Optional<?> optional) { if (optional.isPresent()) graph(optional.get(), budget, depth + 1, listLimit); }
        else if (value instanceof Map<?, ?> entries) {
            Protocol.require(entries.size() <= 32);
            for (var entry : entries.entrySet()) { graph(entry.getKey(), budget, depth + 1, 128); graph(entry.getValue(), budget, depth + 1, 128); }
        } else if (value instanceof List<?> entries) {
            Protocol.require(entries.size() <= listLimit);
            for (Object entry : entries) graph(entry, budget, depth + 1, 128);
        } else if (value.getClass().isRecord()) {
            try {
                for (var field : value.getClass().getRecordComponents()) {
                    int limit = value instanceof Transactions.LinkedRetention && field.getName().equals("requiredRecordIds") ? 256 : 128;
                    graph(field.getAccessor().invoke(value), budget, depth + 1, limit);
                }
            } catch (ReflectiveOperationException failure) { throw new Protocol.Invalid(); }
        } else Protocol.require(value instanceof Number || value instanceof Boolean);
        Protocol.require(budget[0] >= 0);
    }

    static <Value extends Message> MethodDescriptor.Marshaller<Value> marshaller(Value prototype, int limit) {
        var delegate = ProtoUtils.marshaller(prototype);
        return new MethodDescriptor.Marshaller<>() {
            @Override public InputStream stream(Value value) { return delegate.stream(value); }
            @Override public Value parse(InputStream input) {
                try {
                    byte[] bytes = input.readNBytes(limit + 1); Protocol.require(bytes.length <= limit);
                    wire(CodedInputStream.newInstance(bytes), prototype.getDescriptorForType(), new int[]{4096}, 0);
                    return delegate.parse(new ByteArrayInputStream(bytes));
                } catch (Protocol.Invalid failure) { throw failure; }
                catch (java.io.IOException | RuntimeException failure) { throw new Protocol.Invalid(); }
            }
        };
    }

    private static void wire(CodedInputStream input, Descriptors.Descriptor descriptor, int[] nodes, int depth) throws java.io.IOException {
        Protocol.require(depth <= 32 && --nodes[0] >= 0);
        Set<Integer> seen = new HashSet<>(); Set<Descriptors.OneofDescriptor> groups = new HashSet<>();
        Map<Integer, Integer> counts = new HashMap<>(); Map<Integer, Set<Object>> keys = new HashMap<>();
        while (!input.isAtEnd()) {
            Protocol.require(--nodes[0] >= 0);
            int tag = input.readTag(), kind = tag & 7; Protocol.require(kind == 0 || kind == 1 || kind == 2 || kind == 5);
            var field = descriptor.findFieldByNumber(tag >>> 3);
            if (field == null) { Protocol.require(input.skipField(tag)); continue; }
            Protocol.require(field.isRepeated() || seen.add(field.getNumber()));
            if (field.getContainingOneof() != null) Protocol.require(groups.add(field.getContainingOneof()));
            if (field.isRepeated()) {
                int maximum = field.isMapField() ? 32 : descriptor.getFullName().equals("latent.transaction.v1.LinkedRetention") && field.getName().equals("required_record_ids") ? 256 : 128;
                Protocol.require(counts.merge(field.getNumber(), 1, Integer::sum) <= maximum);
            }
            switch (field.getJavaType()) {
                case MESSAGE -> {
                    Protocol.require(kind == 2); int size = input.readRawVarint32(), previous = input.pushLimit(size);
                    if (field.isMapField()) {
                        byte[] entry = input.readRawBytes(size);
                        Protocol.require(keys.computeIfAbsent(field.getNumber(), ignored -> new HashSet<>()).add(mapKey(entry)));
                        wire(CodedInputStream.newInstance(entry), field.getMessageType(), nodes, depth + 1);
                    } else wire(input, field.getMessageType(), nodes, depth + 1);
                    input.popLimit(previous);
                }
                case STRING -> { Protocol.require(kind == 2); input.readStringRequireUtf8(); }
                case BYTE_STRING -> { Protocol.require(kind == 2); input.readBytes(); }
                case BOOLEAN -> { Protocol.require(kind == 0); long value = varint(input); Protocol.require(value == 0 || value == 1); }
                case LONG, INT, ENUM -> {
                    Protocol.require(kind == 0); long value = varint(input);
                    if (field.getType() == Descriptors.FieldDescriptor.Type.UINT32) Protocol.require(Long.compareUnsigned(value, 0xffff_ffffL) <= 0);
                    if (field.getJavaType() == Descriptors.FieldDescriptor.JavaType.ENUM || field.getType() == Descriptors.FieldDescriptor.Type.INT32)
                        Protocol.require(value == (long) (int) value || Long.compareUnsigned(value, 0xffff_ffffL) <= 0);
                }
                default -> throw new Protocol.Invalid();
            }
        }
    }

    private static long varint(CodedInputStream input) throws java.io.IOException {
        long result = 0;
        for (int index = 0; index < 10; index++) {
            int value = Byte.toUnsignedInt(input.readRawByte());
            Protocol.require(index != 9 || value <= 1);
            result |= (long) (value & 127) << (7 * index);
            if ((value & 128) == 0) return result;
        }
        throw new Protocol.Invalid();
    }

    private static String mapKey(byte[] entry) throws java.io.IOException {
        CodedInputStream input = CodedInputStream.newInstance(entry);
        String key = "";
        while (!input.isAtEnd()) {
            int tag = input.readTag();
            if (tag >>> 3 == 1) { Protocol.require((tag & 7) == 2); key = input.readStringRequireUtf8(); }
            else Protocol.require(input.skipField(tag));
        }
        return key;
    }
}
