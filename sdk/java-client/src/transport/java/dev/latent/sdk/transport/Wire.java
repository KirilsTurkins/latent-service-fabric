package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import com.google.protobuf.ByteString;
import java.util.Map;
import java.util.Optional;

public final class Wire {
    private Wire() { }

    public static latent.control.v1.Common.ResourceBudget toWire(Management.ResourceBudget value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.ResourceBudget toWire(Management.ResourceBudget value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.ResourceBudget.newBuilder();
        result.setCpuFuel(budget.scalar(value.cpuFuel()));
        result.setMemoryBytes(budget.scalar(value.memoryBytes()));
        result.setChildCalls(budget.scalar(value.childCalls()));
        result.setOutboundRequests(budget.scalar(value.outboundRequests()));
        result.setStateReadBytes(budget.scalar(value.stateReadBytes()));
        result.setStateWriteBytes(budget.scalar(value.stateWriteBytes()));
        result.setBlobReadBytes(budget.scalar(value.blobReadBytes()));
        result.setBlobWriteBytes(budget.scalar(value.blobWriteBytes()));
        result.setLogBytes(budget.scalar(value.logBytes()));
        result.setEffectCount(budget.scalar(value.effectCount()));
        if (value.wallTimeLimitMillis().isPresent()) result.setWallTimeLimitMillis(budget.scalar(value.wallTimeLimitMillis().get()));
        return result.build();
    }

    public static Management.ResourceBudget fromWire(latent.control.v1.Common.ResourceBudget value) {
        return new Management.ResourceBudget(
                value.getCpuFuel(),
                value.getMemoryBytes(),
                value.getChildCalls(),
                value.getOutboundRequests(),
                value.getStateReadBytes(),
                value.getStateWriteBytes(),
                value.getBlobReadBytes(),
                value.getBlobWriteBytes(),
                value.getLogBytes(),
                value.getEffectCount(),
                value.hasWallTimeLimitMillis() ? Optional.of(value.getWallTimeLimitMillis()) : Optional.empty());
    }

    public static latent.control.v1.Common.ErrorDetail toWire(Management.ErrorDetail value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.ErrorDetail toWire(Management.ErrorDetail value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.ErrorDetail.newBuilder();
        result.setKind(budget.text(value.kind()));
        result.putAllFields(budget.map(value.fields()));
        return result.build();
    }

    public static Management.ErrorDetail fromWire(latent.control.v1.Common.ErrorDetail value) {
        return new Management.ErrorDetail(
                value.getKind(),
                Map.copyOf(value.getFieldsMap()));
    }

    public static latent.control.v1.Common.PlatformError toWire(Management.PlatformError value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.PlatformError toWire(Management.PlatformError value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.PlatformError.newBuilder();
        result.setCode(budget.text(value.code()));
        result.setMessage(budget.text(value.message()));
        result.setRetryable(budget.scalar(value.retryable()));
        for (var item : budget.list(value.detailItems(), 128)) result.addDetailItems(toWire(item, budget, depth + 1));
        return result.build();
    }

    public static Management.PlatformError fromWire(latent.control.v1.Common.PlatformError value) {
        return new Management.PlatformError(
                value.getCode(),
                value.getMessage(),
                value.getRetryable(),
                value.getDetailItemsList().stream().map(item -> fromWire(item)).toList());
    }

    public static latent.control.v1.Common.ObjectMetadata toWire(Management.ObjectMetadata value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.ObjectMetadata toWire(Management.ObjectMetadata value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.ObjectMetadata.newBuilder();
        result.setName(budget.text(value.name()));
        if (value.tenant().isPresent()) result.setTenant(budget.text(value.tenant().get()));
        if (value.namespace().isPresent()) result.setNamespace(budget.text(value.namespace().get()));
        result.putAllLabels(budget.map(value.labels()));
        result.putAllAnnotations(budget.map(value.annotations()));
        return result.build();
    }

    public static Management.ObjectMetadata fromWire(latent.control.v1.Common.ObjectMetadata value) {
        return new Management.ObjectMetadata(
                value.getName(),
                value.hasTenant() ? Optional.of(value.getTenant()) : Optional.empty(),
                value.hasNamespace() ? Optional.of(value.getNamespace()) : Optional.empty(),
                Map.copyOf(value.getLabelsMap()),
                Map.copyOf(value.getAnnotationsMap()));
    }

    public static latent.control.v1.Common.PageRequest toWire(Management.PageRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.PageRequest toWire(Management.PageRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.PageRequest.newBuilder();
        result.setPageSize(budget.scalar(value.pageSize()));
        if (value.pageToken().isPresent()) result.setPageToken(budget.text(value.pageToken().get()));
        return result.build();
    }

    public static Management.PageRequest fromWire(latent.control.v1.Common.PageRequest value) {
        return new Management.PageRequest(
                value.getPageSize(),
                value.hasPageToken() ? Optional.of(value.getPageToken()) : Optional.empty());
    }

    public static latent.control.v1.Common.PageResponse toWire(Management.PageResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.PageResponse toWire(Management.PageResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.PageResponse.newBuilder();
        if (value.nextPageToken().isPresent()) result.setNextPageToken(budget.text(value.nextPageToken().get()));
        return result.build();
    }

    public static Management.PageResponse fromWire(latent.control.v1.Common.PageResponse value) {
        return new Management.PageResponse(
                value.hasNextPageToken() ? Optional.of(value.getNextPageToken()) : Optional.empty());
    }

    public static latent.control.v1.Common.AuditAck toWire(Management.AuditAck value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Common.AuditAck toWire(Management.AuditAck value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Common.AuditAck.newBuilder();
        result.setStatusValue(budget.scalar(value.status().value()));
        if (value.attemptSequence().isPresent()) result.setAttemptSequence(budget.scalar(value.attemptSequence().get()));
        return result.build();
    }

    public static Management.AuditAck fromWire(latent.control.v1.Common.AuditAck value) {
        return new Management.AuditAck(
                new Management.AuditAckStatus(value.getStatusValue()),
                value.hasAttemptSequence() ? Optional.of(value.getAttemptSequence()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.InvocationTarget toWire(Management.InvocationTarget value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.InvocationTarget toWire(Management.InvocationTarget value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.InvocationTarget.newBuilder();
        result.setTenant(budget.text(value.tenant()));
        result.setService(budget.text(value.service()));
        result.setContract(budget.text(value.contract()));
        result.setFunction(budget.text(value.function()));
        if (value.route().isPresent()) result.setRoute(budget.text(value.route().get()));
        return result.build();
    }

    public static Management.InvocationTarget fromWire(latent.invocation.v1.Invocation.InvocationTarget value) {
        return new Management.InvocationTarget(
                value.getTenant(),
                value.getService(),
                value.getContract(),
                value.getFunction(),
                value.hasRoute() ? Optional.of(value.getRoute()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.InvokeRequest toWire(Management.InvokeRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.InvokeRequest toWire(Management.InvokeRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.InvokeRequest.newBuilder();
        if (value.activationId().isPresent()) result.setActivationId(budget.text(value.activationId().get()));
        if (value.parentActivationId().isPresent()) result.setParentActivationId(budget.text(value.parentActivationId().get()));
        if (value.rootActivationId().isPresent()) result.setRootActivationId(budget.text(value.rootActivationId().get()));
        if (value.target().isPresent()) result.setTarget(toWire(value.target().get(), budget, depth + 1));
        result.setPayload(budget.bytes(value.payload()));
        result.setMediaType(budget.text(value.mediaType()));
        if (value.deadlineUnixMillis().isPresent()) result.setDeadlineUnixMillis(budget.scalar(value.deadlineUnixMillis().get()));
        result.setPriority(budget.scalar(value.priority()));
        if (value.idempotencyKey().isPresent()) result.setIdempotencyKey(budget.text(value.idempotencyKey().get()));
        if (value.budget().isPresent()) result.setBudget(toInvocationResourceBudget(value.budget().get(), budget, depth + 1));
        result.putAllMetadata(budget.map(value.metadata()));
        return result.build();
    }

    public static Management.InvokeRequest fromWire(latent.invocation.v1.Invocation.InvokeRequest value) {
        return new Management.InvokeRequest(
                value.hasActivationId() ? Optional.of(value.getActivationId()) : Optional.empty(),
                value.hasParentActivationId() ? Optional.of(value.getParentActivationId()) : Optional.empty(),
                value.hasRootActivationId() ? Optional.of(value.getRootActivationId()) : Optional.empty(),
                value.hasTarget() ? Optional.of(fromWire(value.getTarget())) : Optional.empty(),
                value.getPayload().asReadOnlyByteBuffer(),
                value.getMediaType(),
                value.hasDeadlineUnixMillis() ? Optional.of(value.getDeadlineUnixMillis()) : Optional.empty(),
                value.getPriority(),
                value.hasIdempotencyKey() ? Optional.of(value.getIdempotencyKey()) : Optional.empty(),
                value.hasBudget() ? Optional.of(fromWire(value.getBudget())) : Optional.empty(),
                Map.copyOf(value.getMetadataMap()));
    }

    public static latent.invocation.v1.Invocation.BudgetConsumption toWire(Management.BudgetConsumption value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.BudgetConsumption toWire(Management.BudgetConsumption value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.BudgetConsumption.newBuilder();
        result.setCpuFuel(budget.scalar(value.cpuFuel()));
        result.setPeakMemoryBytes(budget.scalar(value.peakMemoryBytes()));
        result.setWallTimeMicros(budget.scalar(value.wallTimeMicros()));
        result.setChildCalls(budget.scalar(value.childCalls()));
        result.setOutboundRequests(budget.scalar(value.outboundRequests()));
        result.setStateReadBytes(budget.scalar(value.stateReadBytes()));
        result.setStateWriteBytes(budget.scalar(value.stateWriteBytes()));
        result.setBlobReadBytes(budget.scalar(value.blobReadBytes()));
        result.setBlobWriteBytes(budget.scalar(value.blobWriteBytes()));
        result.setLogBytes(budget.scalar(value.logBytes()));
        result.setEffectCount(budget.scalar(value.effectCount()));
        return result.build();
    }

    public static Management.BudgetConsumption fromWire(latent.invocation.v1.Invocation.BudgetConsumption value) {
        return new Management.BudgetConsumption(
                value.getCpuFuel(),
                value.getPeakMemoryBytes(),
                value.getWallTimeMicros(),
                value.getChildCalls(),
                value.getOutboundRequests(),
                value.getStateReadBytes(),
                value.getStateWriteBytes(),
                value.getBlobReadBytes(),
                value.getBlobWriteBytes(),
                value.getLogBytes(),
                value.getEffectCount());
    }

    public static latent.invocation.v1.Invocation.InvokeResponse toWire(Management.InvokeResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.InvokeResponse toWire(Management.InvokeResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.InvokeResponse.newBuilder();
        if ((value.success().isPresent() ? 1 : 0) + (value.declaredError().isPresent() ? 1 : 0) + (value.platformFailure().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        result.setActivationId(budget.text(value.activationId()));
        result.setRevisionId(budget.text(value.revisionId()));
        result.setReleaseDigest(budget.text(value.releaseDigest()));
        result.setRouteGeneration(budget.scalar(value.routeGeneration()));
        if (value.success().isPresent()) result.setSuccess(toWire(value.success().get(), budget, depth + 1));
        if (value.declaredError().isPresent()) result.setDeclaredError(toWire(value.declaredError().get(), budget, depth + 1));
        if (value.platformFailure().isPresent()) result.setPlatformFailure(toInvocationPlatformError(value.platformFailure().get(), budget, depth + 1));
        if (value.consumption().isPresent()) result.setConsumption(toWire(value.consumption().get(), budget, depth + 1));
        if (value.publicationId().isPresent()) result.setPublicationId(budget.text(value.publicationId().get()));
        return result.build();
    }

    public static Management.InvokeResponse fromWire(latent.invocation.v1.Invocation.InvokeResponse value) {
        return new Management.InvokeResponse(
                value.getActivationId(),
                value.getRevisionId(),
                value.getReleaseDigest(),
                value.getRouteGeneration(),
                value.hasSuccess() ? Optional.of(fromWire(value.getSuccess())) : Optional.empty(),
                value.hasDeclaredError() ? Optional.of(fromWire(value.getDeclaredError())) : Optional.empty(),
                value.hasPlatformFailure() ? Optional.of(fromWire(value.getPlatformFailure())) : Optional.empty(),
                value.hasConsumption() ? Optional.of(fromWire(value.getConsumption())) : Optional.empty(),
                value.hasPublicationId() ? Optional.of(value.getPublicationId()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.Success toWire(Management.Success value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.Success toWire(Management.Success value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.Success.newBuilder();
        result.setPayload(budget.bytes(value.payload()));
        result.setMediaType(budget.text(value.mediaType()));
        if (value.committedStateVersion().isPresent()) result.setCommittedStateVersion(budget.text(value.committedStateVersion().get()));
        for (var item : budget.list(value.effectIds(), 128)) result.addEffectIds(budget.text(item));
        result.putAllMetadata(budget.map(value.metadata()));
        return result.build();
    }

    public static Management.Success fromWire(latent.invocation.v1.Invocation.Success value) {
        return new Management.Success(
                value.getPayload().asReadOnlyByteBuffer(),
                value.getMediaType(),
                value.hasCommittedStateVersion() ? Optional.of(value.getCommittedStateVersion()) : Optional.empty(),
                value.getEffectIdsList().stream().map(item -> item).toList(),
                Map.copyOf(value.getMetadataMap()));
    }

    public static latent.invocation.v1.Invocation.DeclaredError toWire(Management.DeclaredError value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.DeclaredError toWire(Management.DeclaredError value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.DeclaredError.newBuilder();
        result.setCode(budget.text(value.code()));
        result.setMessage(budget.text(value.message()));
        result.setPayload(budget.bytes(value.payload()));
        result.setMediaType(budget.text(value.mediaType()));
        result.putAllMetadata(budget.map(value.metadata()));
        return result.build();
    }

    public static Management.DeclaredError fromWire(latent.invocation.v1.Invocation.DeclaredError value) {
        return new Management.DeclaredError(
                value.getCode(),
                value.getMessage(),
                value.getPayload().asReadOnlyByteBuffer(),
                value.getMediaType(),
                Map.copyOf(value.getMetadataMap()));
    }

    public static latent.invocation.v1.Invocation.CancelRequest toWire(Management.CancelRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.CancelRequest toWire(Management.CancelRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.CancelRequest.newBuilder();
        result.setActivationId(budget.text(value.activationId()));
        result.setReason(budget.text(value.reason()));
        return result.build();
    }

    public static Management.CancelRequest fromWire(latent.invocation.v1.Invocation.CancelRequest value) {
        return new Management.CancelRequest(
                value.getActivationId(),
                value.getReason());
    }

    public static latent.invocation.v1.Invocation.CancelResponse toWire(Management.CancelResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.CancelResponse toWire(Management.CancelResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.CancelResponse.newBuilder();
        result.setDispositionValue(budget.scalar(value.disposition().value()));
        if (value.terminalState().isPresent()) result.setTerminalState(budget.text(value.terminalState().get()));
        return result.build();
    }

    public static Management.CancelResponse fromWire(latent.invocation.v1.Invocation.CancelResponse value) {
        return new Management.CancelResponse(
                new Management.CancelDisposition(value.getDispositionValue()),
                value.hasTerminalState() ? Optional.of(value.getTerminalState()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.GetActivationRequest toWire(Management.GetActivationRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.GetActivationRequest toWire(Management.GetActivationRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.GetActivationRequest.newBuilder();
        result.setActivationId(budget.text(value.activationId()));
        return result.build();
    }

    public static Management.GetActivationRequest fromWire(latent.invocation.v1.Invocation.GetActivationRequest value) {
        return new Management.GetActivationRequest(
                value.getActivationId());
    }

    public static latent.invocation.v1.Invocation.ActivationStatus toWire(Management.ActivationStatus value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.ActivationStatus toWire(Management.ActivationStatus value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.ActivationStatus.newBuilder();
        if ((value.succeeded().isPresent() ? 1 : 0) + (value.declaredError().isPresent() ? 1 : 0) + (value.platformFailure().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        result.setActivationId(budget.text(value.activationId()));
        result.setPhase(budget.text(value.phase()));
        if (value.terminalState().isPresent()) result.setTerminalState(budget.text(value.terminalState().get()));
        result.setLastUpdatedUnixMillis(budget.scalar(value.lastUpdatedUnixMillis()));
        result.putAllMetadata(budget.map(value.metadata()));
        if (value.succeeded().isPresent()) result.setSucceeded(toWire(value.succeeded().get(), budget, depth + 1));
        if (value.declaredError().isPresent()) result.setDeclaredError(toWire(value.declaredError().get(), budget, depth + 1));
        if (value.platformFailure().isPresent()) result.setPlatformFailure(toInvocationPlatformError(value.platformFailure().get(), budget, depth + 1));
        if (value.finalConsumption().isPresent()) result.setFinalConsumption(toWire(value.finalConsumption().get(), budget, depth + 1));
        if (value.terminalAtUnixMillis().isPresent()) result.setTerminalAtUnixMillis(budget.scalar(value.terminalAtUnixMillis().get()));
        return result.build();
    }

    public static Management.ActivationStatus fromWire(latent.invocation.v1.Invocation.ActivationStatus value) {
        return new Management.ActivationStatus(
                value.getActivationId(),
                value.getPhase(),
                value.hasTerminalState() ? Optional.of(value.getTerminalState()) : Optional.empty(),
                value.getLastUpdatedUnixMillis(),
                Map.copyOf(value.getMetadataMap()),
                value.hasSucceeded() ? Optional.of(fromWire(value.getSucceeded())) : Optional.empty(),
                value.hasDeclaredError() ? Optional.of(fromWire(value.getDeclaredError())) : Optional.empty(),
                value.hasPlatformFailure() ? Optional.of(fromWire(value.getPlatformFailure())) : Optional.empty(),
                value.hasFinalConsumption() ? Optional.of(fromWire(value.getFinalConsumption())) : Optional.empty(),
                value.hasTerminalAtUnixMillis() ? Optional.of(value.getTerminalAtUnixMillis()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.ActivationSuccessSummary toWire(Management.ActivationSuccessSummary value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.ActivationSuccessSummary toWire(Management.ActivationSuccessSummary value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.ActivationSuccessSummary.newBuilder();
        if (value.committedStateVersion().isPresent()) result.setCommittedStateVersion(budget.text(value.committedStateVersion().get()));
        for (var item : budget.list(value.effectIds(), 128)) result.addEffectIds(budget.text(item));
        result.putAllMetadata(budget.map(value.metadata()));
        return result.build();
    }

    public static Management.ActivationSuccessSummary fromWire(latent.invocation.v1.Invocation.ActivationSuccessSummary value) {
        return new Management.ActivationSuccessSummary(
                value.hasCommittedStateVersion() ? Optional.of(value.getCommittedStateVersion()) : Optional.empty(),
                value.getEffectIdsList().stream().map(item -> item).toList(),
                Map.copyOf(value.getMetadataMap()));
    }

    public static latent.control.v1.PolicyOuterClass.Policy toWire(Management.Policy value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.Policy toWire(Management.Policy value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.Policy.newBuilder();
        result.setId(budget.text(value.id()));
        if (value.metadata().isPresent()) result.setMetadata(toWire(value.metadata().get(), budget, depth + 1));
        result.setDocument(budget.text(value.document()));
        result.setGeneration(budget.scalar(value.generation()));
        result.setLanguage(budget.text(value.language()));
        result.setRecordKindValue(budget.scalar(value.recordKind().value()));
        result.setContentDigest(budget.text(value.contentDigest()));
        result.setRevoked(budget.scalar(value.revoked()));
        return result.build();
    }

    public static Management.Policy fromWire(latent.control.v1.PolicyOuterClass.Policy value) {
        return new Management.Policy(
                value.getId(),
                value.hasMetadata() ? Optional.of(fromWire(value.getMetadata())) : Optional.empty(),
                value.getDocument(),
                value.getGeneration(),
                value.getLanguage(),
                new Management.CapabilityPolicyRecordKind(value.getRecordKindValue()),
                value.getContentDigest(),
                value.getRevoked());
    }

    public static latent.control.v1.PolicyOuterClass.ApplyPolicyRequest toWire(Management.ApplyPolicyRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.ApplyPolicyRequest toWire(Management.ApplyPolicyRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.ApplyPolicyRequest.newBuilder();
        if (value.policy().isPresent()) result.setPolicy(toWire(value.policy().get(), budget, depth + 1));
        if (value.expectedGeneration().isPresent()) result.setExpectedGeneration(budget.scalar(value.expectedGeneration().get()));
        result.setOperationId(budget.text(value.operationId()));
        return result.build();
    }

    public static Management.ApplyPolicyRequest fromWire(latent.control.v1.PolicyOuterClass.ApplyPolicyRequest value) {
        return new Management.ApplyPolicyRequest(
                value.hasPolicy() ? Optional.of(fromWire(value.getPolicy())) : Optional.empty(),
                value.hasExpectedGeneration() ? Optional.of(value.getExpectedGeneration()) : Optional.empty(),
                value.getOperationId());
    }

    public static latent.control.v1.PolicyOuterClass.ApplyPolicyResponse toWire(Management.ApplyPolicyResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.ApplyPolicyResponse toWire(Management.ApplyPolicyResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.ApplyPolicyResponse.newBuilder();
        if (value.policy().isPresent()) result.setPolicy(toWire(value.policy().get(), budget, depth + 1));
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.ApplyPolicyResponse fromWire(latent.control.v1.PolicyOuterClass.ApplyPolicyResponse value) {
        return new Management.ApplyPolicyResponse(
                value.hasPolicy() ? Optional.of(fromWire(value.getPolicy())) : Optional.empty(),
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyRequest toWire(Management.GetPolicyRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.GetPolicyRequest toWire(Management.GetPolicyRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.GetPolicyRequest.newBuilder();
        result.setId(budget.text(value.id()));
        result.setRecordKindValue(budget.scalar(value.recordKind().value()));
        return result.build();
    }

    public static Management.GetPolicyRequest fromWire(latent.control.v1.PolicyOuterClass.GetPolicyRequest value) {
        return new Management.GetPolicyRequest(
                value.getId(),
                new Management.CapabilityPolicyRecordKind(value.getRecordKindValue()));
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyResponse toWire(Management.GetPolicyResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.GetPolicyResponse toWire(Management.GetPolicyResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.GetPolicyResponse.newBuilder();
        if (value.policy().isPresent()) result.setPolicy(toWire(value.policy().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.GetPolicyResponse fromWire(latent.control.v1.PolicyOuterClass.GetPolicyResponse value) {
        return new Management.GetPolicyResponse(
                value.hasPolicy() ? Optional.of(fromWire(value.getPolicy())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.CapabilityPolicyOperation toWire(Management.CapabilityPolicyOperation value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.CapabilityPolicyOperation toWire(Management.CapabilityPolicyOperation value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.CapabilityPolicyOperation.newBuilder();
        result.setOperationId(budget.text(value.operationId()));
        result.setTenant(budget.text(value.tenant()));
        result.setId(budget.text(value.id()));
        result.setRecordKindValue(budget.scalar(value.recordKind().value()));
        result.setGeneration(budget.scalar(value.generation()));
        result.setContentDigest(budget.text(value.contentDigest()));
        result.setRevoked(budget.scalar(value.revoked()));
        return result.build();
    }

    public static Management.CapabilityPolicyOperation fromWire(latent.control.v1.PolicyOuterClass.CapabilityPolicyOperation value) {
        return new Management.CapabilityPolicyOperation(
                value.getOperationId(),
                value.getTenant(),
                value.getId(),
                new Management.CapabilityPolicyRecordKind(value.getRecordKindValue()),
                value.getGeneration(),
                value.getContentDigest(),
                value.getRevoked());
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyOperationRequest toWire(Management.GetPolicyOperationRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.GetPolicyOperationRequest toWire(Management.GetPolicyOperationRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.GetPolicyOperationRequest.newBuilder();
        result.setOperationId(budget.text(value.operationId()));
        return result.build();
    }

    public static Management.GetPolicyOperationRequest fromWire(latent.control.v1.PolicyOuterClass.GetPolicyOperationRequest value) {
        return new Management.GetPolicyOperationRequest(
                value.getOperationId());
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse toWire(Management.GetPolicyOperationResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse toWire(Management.GetPolicyOperationResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.GetPolicyOperationResponse fromWire(latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse value) {
        return new Management.GetPolicyOperationResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.ListPoliciesRequest toWire(Management.ListPoliciesRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.ListPoliciesRequest toWire(Management.ListPoliciesRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.ListPoliciesRequest.newBuilder();
        result.setRecordKindValue(budget.scalar(value.recordKind().value()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.ListPoliciesRequest fromWire(latent.control.v1.PolicyOuterClass.ListPoliciesRequest value) {
        return new Management.ListPoliciesRequest(
                new Management.CapabilityPolicyRecordKind(value.getRecordKindValue()),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.ListPoliciesResponse toWire(Management.ListPoliciesResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.PolicyOuterClass.ListPoliciesResponse toWire(Management.ListPoliciesResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.PolicyOuterClass.ListPoliciesResponse.newBuilder();
        for (var item : budget.list(value.policies(), 128)) result.addPolicies(toWire(item, budget, depth + 1));
        result.setCatalogGeneration(budget.scalar(value.catalogGeneration()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.ListPoliciesResponse fromWire(latent.control.v1.PolicyOuterClass.ListPoliciesResponse value) {
        return new Management.ListPoliciesResponse(
                value.getPoliciesList().stream().map(item -> fromWire(item)).toList(),
                value.getCatalogGeneration(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    public static latent.control.v1.Capability.CapabilityDescriptor toWire(Management.CapabilityDescriptor value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.CapabilityDescriptor toWire(Management.CapabilityDescriptor value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.CapabilityDescriptor.newBuilder();
        result.setId(budget.text(value.id()));
        result.setContract(budget.text(value.contract()));
        result.setProvider(budget.text(value.provider()));
        for (var item : budget.list(value.operations(), 128)) result.addOperations(budget.text(item));
        result.putAllAttributes(budget.map(value.attributes()));
        if (value.inspection().isPresent()) result.setInspection(toWire(value.inspection().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.CapabilityDescriptor fromWire(latent.control.v1.Capability.CapabilityDescriptor value) {
        return new Management.CapabilityDescriptor(
                value.getId(),
                value.getContract(),
                value.getProvider(),
                value.getOperationsList().stream().map(item -> item).toList(),
                Map.copyOf(value.getAttributesMap()),
                value.hasInspection() ? Optional.of(fromWire(value.getInspection())) : Optional.empty());
    }

    public static latent.control.v1.Capability.ListCapabilitiesRequest toWire(Management.ListCapabilitiesRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.ListCapabilitiesRequest toWire(Management.ListCapabilitiesRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.ListCapabilitiesRequest.newBuilder();
        if (value.contractPrefix().isPresent()) result.setContractPrefix(budget.text(value.contractPrefix().get()));
        if (value.provider().isPresent()) result.setProvider(budget.text(value.provider().get()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        result.setDeploymentId(budget.text(value.deploymentId()));
        result.setIncludeNodeUsage(budget.scalar(value.includeNodeUsage()));
        return result.build();
    }

    public static Management.ListCapabilitiesRequest fromWire(latent.control.v1.Capability.ListCapabilitiesRequest value) {
        return new Management.ListCapabilitiesRequest(
                value.hasContractPrefix() ? Optional.of(value.getContractPrefix()) : Optional.empty(),
                value.hasProvider() ? Optional.of(value.getProvider()) : Optional.empty(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty(),
                value.getDeploymentId(),
                value.getIncludeNodeUsage());
    }

    public static latent.control.v1.Capability.ListCapabilitiesResponse toWire(Management.ListCapabilitiesResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.ListCapabilitiesResponse toWire(Management.ListCapabilitiesResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.ListCapabilitiesResponse.newBuilder();
        for (var item : budget.list(value.capabilities(), 128)) result.addCapabilities(toWire(item, budget, depth + 1));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        if (value.revision().isPresent()) result.setRevision(toWire(value.revision().get(), budget, depth + 1));
        if (value.tenantUsage().isPresent()) result.setTenantUsage(toWire(value.tenantUsage().get(), budget, depth + 1));
        if (value.nodeUsage().isPresent()) result.setNodeUsage(toWire(value.nodeUsage().get(), budget, depth + 1));
        result.setState(budget.text(value.state()));
        return result.build();
    }

    public static Management.ListCapabilitiesResponse fromWire(latent.control.v1.Capability.ListCapabilitiesResponse value) {
        return new Management.ListCapabilitiesResponse(
                value.getCapabilitiesList().stream().map(item -> fromWire(item)).toList(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty(),
                value.hasRevision() ? Optional.of(fromWire(value.getRevision())) : Optional.empty(),
                value.hasTenantUsage() ? Optional.of(fromWire(value.getTenantUsage())) : Optional.empty(),
                value.hasNodeUsage() ? Optional.of(fromWire(value.getNodeUsage())) : Optional.empty(),
                value.getState());
    }

    public static latent.control.v1.Capability.CapabilityInspectionRevision toWire(Management.CapabilityInspectionRevision value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.CapabilityInspectionRevision toWire(Management.CapabilityInspectionRevision value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.CapabilityInspectionRevision.newBuilder();
        result.setDeploymentId(budget.text(value.deploymentId()));
        result.setRevisionId(budget.text(value.revisionId()));
        result.setComponentDigest(budget.text(value.componentDigest()));
        if (value.publicationId().isPresent()) result.setPublicationId(budget.text(value.publicationId().get()));
        result.setRouteGeneration(budget.scalar(value.routeGeneration()));
        result.setCatalogTransaction(budget.scalar(value.catalogTransaction()));
        return result.build();
    }

    public static Management.CapabilityInspectionRevision fromWire(latent.control.v1.Capability.CapabilityInspectionRevision value) {
        return new Management.CapabilityInspectionRevision(
                value.getDeploymentId(),
                value.getRevisionId(),
                value.getComponentDigest(),
                value.hasPublicationId() ? Optional.of(value.getPublicationId()) : Optional.empty(),
                value.getRouteGeneration(),
                value.getCatalogTransaction());
    }

    public static latent.control.v1.Capability.CapabilityInspectionPolicy toWire(Management.CapabilityInspectionPolicy value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.CapabilityInspectionPolicy toWire(Management.CapabilityInspectionPolicy value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.CapabilityInspectionPolicy.newBuilder();
        result.setId(budget.text(value.id()));
        result.setRevision(budget.scalar(value.revision()));
        result.setDigest(budget.text(value.digest()));
        return result.build();
    }

    public static Management.CapabilityInspectionPolicy fromWire(latent.control.v1.Capability.CapabilityInspectionPolicy value) {
        return new Management.CapabilityInspectionPolicy(
                value.getId(),
                value.getRevision(),
                value.getDigest());
    }

    public static latent.control.v1.Capability.CapabilityBindingInspection toWire(Management.CapabilityBindingInspection value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.CapabilityBindingInspection toWire(Management.CapabilityBindingInspection value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.CapabilityBindingInspection.newBuilder();
        if (value.definitionDigest().isPresent()) result.setDefinitionDigest(budget.text(value.definitionDigest().get()));
        if (value.providerBinding().isPresent()) result.setProviderBinding(toWire(value.providerBinding().get(), budget, depth + 1));
        for (var item : budget.list(value.policies(), 128)) result.addPolicies(toWire(item, budget, depth + 1));
        result.setProviderProfile(budget.text(value.providerProfile()));
        result.setProviderConfigurationDigest(budget.text(value.providerConfigurationDigest()));
        result.setProviderConfigurationEpoch(budget.scalar(value.providerConfigurationEpoch()));
        result.setState(budget.text(value.state()));
        return result.build();
    }

    public static Management.CapabilityBindingInspection fromWire(latent.control.v1.Capability.CapabilityBindingInspection value) {
        return new Management.CapabilityBindingInspection(
                value.hasDefinitionDigest() ? Optional.of(value.getDefinitionDigest()) : Optional.empty(),
                value.hasProviderBinding() ? Optional.of(fromWire(value.getProviderBinding())) : Optional.empty(),
                value.getPoliciesList().stream().map(item -> fromWire(item)).toList(),
                value.getProviderProfile(),
                value.getProviderConfigurationDigest(),
                value.getProviderConfigurationEpoch(),
                value.getState());
    }

    public static latent.control.v1.Capability.CapabilityInspectionCeiling toWire(Management.CapabilityInspectionCeiling value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.CapabilityInspectionCeiling toWire(Management.CapabilityInspectionCeiling value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.CapabilityInspectionCeiling.newBuilder();
        result.setOperations(budget.scalar(value.operations()));
        result.setInputBytes(budget.scalar(value.inputBytes()));
        result.setOutputBytes(budget.scalar(value.outputBytes()));
        result.setWallTimeMillis(budget.scalar(value.wallTimeMillis()));
        return result.build();
    }

    public static Management.CapabilityInspectionCeiling fromWire(latent.control.v1.Capability.CapabilityInspectionCeiling value) {
        return new Management.CapabilityInspectionCeiling(
                value.getOperations(),
                value.getInputBytes(),
                value.getOutputBytes(),
                value.getWallTimeMillis());
    }

    public static latent.control.v1.Capability.CapabilityResourceUsage toWire(Management.CapabilityResourceUsage value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Capability.CapabilityResourceUsage toWire(Management.CapabilityResourceUsage value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Capability.CapabilityResourceUsage.newBuilder();
        result.setScope(budget.text(value.scope()));
        result.putAllCounters(budget.map(value.counters()));
        for (var item : budget.list(value.unavailable(), 128)) result.addUnavailable(budget.text(item));
        if (value.streamQuarantinedConnections().isPresent()) result.setStreamQuarantinedConnections(budget.scalar(value.streamQuarantinedConnections().get()));
        return result.build();
    }

    public static Management.CapabilityResourceUsage fromWire(latent.control.v1.Capability.CapabilityResourceUsage value) {
        return new Management.CapabilityResourceUsage(
                value.getScope(),
                Map.copyOf(value.getCountersMap()),
                value.getUnavailableList().stream().map(item -> item).toList(),
                value.hasStreamQuarantinedConnections() ? Optional.of(value.getStreamQuarantinedConnections()) : Optional.empty());
    }

    public static latent.control.v1.Release.PublicationRef toWire(Management.PublicationRef value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Release.PublicationRef toWire(Management.PublicationRef value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Release.PublicationRef.newBuilder();
        result.setId(budget.text(value.id()));
        result.setTenant(budget.text(value.tenant()));
        return result.build();
    }

    public static Management.PublicationRef fromWire(latent.control.v1.Release.PublicationRef value) {
        return new Management.PublicationRef(
                value.getId(),
                value.getTenant());
    }

    public static latent.control.v1.Node.ActivationDiagnostic toWire(Management.ActivationDiagnostic value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.ActivationDiagnostic toWire(Management.ActivationDiagnostic value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.ActivationDiagnostic.newBuilder();
        result.setSchemaVersion(budget.scalar(value.schemaVersion()));
        result.setStageValue(budget.scalar(value.stage().value()));
        result.setReasonValue(budget.scalar(value.reason().value()));
        if (value.profile().isPresent()) result.setProfileValue(budget.scalar(value.profile().get().value()));
        if (value.profileDigest().isPresent()) result.setProfileDigest(budget.text(value.profileDigest().get()));
        if (value.configuredBound().isPresent()) result.setConfiguredBound(budget.scalar(value.configuredBound().get()));
        if (value.calculatedRequirement().isPresent()) result.setCalculatedRequirement(budget.scalar(value.calculatedRequirement().get()));
        if (value.fixedBytes().isPresent()) result.setFixedBytes(budget.scalar(value.fixedBytes().get()));
        if (value.liftingFuel().isPresent()) result.setLiftingFuel(budget.scalar(value.liftingFuel().get()));
        if (value.liftMultiplier().isPresent()) result.setLiftMultiplier(budget.scalar(value.liftMultiplier().get()));
        return result.build();
    }

    public static Management.ActivationDiagnostic fromWire(latent.control.v1.Node.ActivationDiagnostic value) {
        return new Management.ActivationDiagnostic(
                value.getSchemaVersion(),
                new Management.DiagnosticStage(value.getStageValue()),
                new Management.DiagnosticReason(value.getReasonValue()),
                value.hasProfile() ? Optional.of(new Management.DiagnosticProfile(value.getProfileValue())) : Optional.empty(),
                value.hasProfileDigest() ? Optional.of(value.getProfileDigest()) : Optional.empty(),
                value.hasConfiguredBound() ? Optional.of(value.getConfiguredBound()) : Optional.empty(),
                value.hasCalculatedRequirement() ? Optional.of(value.getCalculatedRequirement()) : Optional.empty(),
                value.hasFixedBytes() ? Optional.of(value.getFixedBytes()) : Optional.empty(),
                value.hasLiftingFuel() ? Optional.of(value.getLiftingFuel()) : Optional.empty(),
                value.hasLiftMultiplier() ? Optional.of(value.getLiftMultiplier()) : Optional.empty());
    }

    public static latent.control.v1.Node.TransactionStagingWitness toWire(Management.TransactionStagingWitness value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.TransactionStagingWitness toWire(Management.TransactionStagingWitness value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.TransactionStagingWitness.newBuilder();
        result.setSchemaVersion(budget.scalar(value.schemaVersion()));
        result.setActivationSerial(budget.scalar(value.activationSerial()));
        result.setCommandId(budget.text(value.commandId()));
        result.setAttemptId(budget.text(value.attemptId()));
        result.setTransactionId(budget.text(value.transactionId()));
        result.setPublicationId(budget.text(value.publicationId()));
        result.setStagedMutations(budget.scalar(value.stagedMutations()));
        result.setCapturedIntents(budget.scalar(value.capturedIntents()));
        result.setStateWriteBytes(budget.scalar(value.stateWriteBytes()));
        result.setObservedAtUnixMillis(budget.scalar(value.observedAtUnixMillis()));
        return result.build();
    }

    public static Management.TransactionStagingWitness fromWire(latent.control.v1.Node.TransactionStagingWitness value) {
        return new Management.TransactionStagingWitness(
                value.getSchemaVersion(),
                value.getActivationSerial(),
                value.getCommandId(),
                value.getAttemptId(),
                value.getTransactionId(),
                value.getPublicationId(),
                value.getStagedMutations(),
                value.getCapturedIntents(),
                value.getStateWriteBytes(),
                value.getObservedAtUnixMillis());
    }

    public static latent.control.v1.Node.ActivationTreeNode toWire(Management.ActivationTreeNode value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.ActivationTreeNode toWire(Management.ActivationTreeNode value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.ActivationTreeNode.newBuilder();
        result.setActivationId(budget.text(value.activationId()));
        if (value.parentActivationId().isPresent()) result.setParentActivationId(budget.text(value.parentActivationId().get()));
        result.setRootActivationId(budget.text(value.rootActivationId()));
        result.setPhase(budget.text(value.phase()));
        if (value.terminalState().isPresent()) result.setTerminalState(budget.text(value.terminalState().get()));
        result.setLastUpdatedUnixMillis(budget.scalar(value.lastUpdatedUnixMillis()));
        if (value.diagnostic().isPresent()) result.setDiagnostic(toWire(value.diagnostic().get(), budget, depth + 1));
        result.setPrincipalKind(budget.text(value.principalKind()));
        if (value.callerService().isPresent()) result.setCallerService(budget.text(value.callerService().get()));
        if (value.grantedBudget().isPresent()) result.setGrantedBudget(toWire(value.grantedBudget().get(), budget, depth + 1));
        if (value.effectiveDeadlineUnixMillis().isPresent()) result.setEffectiveDeadlineUnixMillis(budget.scalar(value.effectiveDeadlineUnixMillis().get()));
        result.setDiagnosticIsTerminal(budget.scalar(value.diagnosticIsTerminal()));
        result.setTargetService(budget.text(value.targetService()));
        result.setReceivedAtUnixMillis(budget.scalar(value.receivedAtUnixMillis()));
        if (value.transactionStaging().isPresent()) result.setTransactionStaging(toWire(value.transactionStaging().get(), budget, depth + 1));
        return result.build();
    }

    public static Management.ActivationTreeNode fromWire(latent.control.v1.Node.ActivationTreeNode value) {
        return new Management.ActivationTreeNode(
                value.getActivationId(),
                value.hasParentActivationId() ? Optional.of(value.getParentActivationId()) : Optional.empty(),
                value.getRootActivationId(),
                value.getPhase(),
                value.hasTerminalState() ? Optional.of(value.getTerminalState()) : Optional.empty(),
                value.getLastUpdatedUnixMillis(),
                value.hasDiagnostic() ? Optional.of(fromWire(value.getDiagnostic())) : Optional.empty(),
                value.getPrincipalKind(),
                value.hasCallerService() ? Optional.of(value.getCallerService()) : Optional.empty(),
                value.hasGrantedBudget() ? Optional.of(fromWire(value.getGrantedBudget())) : Optional.empty(),
                value.hasEffectiveDeadlineUnixMillis() ? Optional.of(value.getEffectiveDeadlineUnixMillis()) : Optional.empty(),
                value.getDiagnosticIsTerminal(),
                value.getTargetService(),
                value.getReceivedAtUnixMillis(),
                value.hasTransactionStaging() ? Optional.of(fromWire(value.getTransactionStaging())) : Optional.empty());
    }

    public static latent.control.v1.Node.InspectActivationTreeRequest toWire(Management.InspectActivationTreeRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.InspectActivationTreeRequest toWire(Management.InspectActivationTreeRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.InspectActivationTreeRequest.newBuilder();
        result.setActivationId(budget.text(value.activationId()));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        if (value.service().isPresent()) result.setService(budget.text(value.service().get()));
        if (value.fromUnixMillis().isPresent()) result.setFromUnixMillis(budget.scalar(value.fromUnixMillis().get()));
        return result.build();
    }

    public static Management.InspectActivationTreeRequest fromWire(latent.control.v1.Node.InspectActivationTreeRequest value) {
        return new Management.InspectActivationTreeRequest(
                value.getActivationId(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty(),
                value.hasService() ? Optional.of(value.getService()) : Optional.empty(),
                value.hasFromUnixMillis() ? Optional.of(value.getFromUnixMillis()) : Optional.empty());
    }

    public static latent.control.v1.Node.InspectActivationTreeResponse toWire(Management.InspectActivationTreeResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.InspectActivationTreeResponse toWire(Management.InspectActivationTreeResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.InspectActivationTreeResponse.newBuilder();
        result.setSchemaVersion(budget.scalar(value.schemaVersion()));
        for (var item : budget.list(value.nodes(), 128)) result.addNodes(toWire(item, budget, depth + 1));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get(), budget, depth + 1));
        result.setHistoryAvailable(budget.scalar(value.historyAvailable()));
        result.setCursorExpired(budget.scalar(value.cursorExpired()));
        result.setRetainedHistoryOnly(budget.scalar(value.retainedHistoryOnly()));
        return result.build();
    }

    public static Management.InspectActivationTreeResponse fromWire(latent.control.v1.Node.InspectActivationTreeResponse value) {
        return new Management.InspectActivationTreeResponse(
                value.getSchemaVersion(),
                value.getNodesList().stream().map(item -> fromWire(item)).toList(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty(),
                value.getHistoryAvailable(),
                value.getCursorExpired(),
                value.getRetainedHistoryOnly());
    }

    public static latent.control.v1.Node.InspectHttpTargetRequest toWire(Management.InspectHttpTargetRequest value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.InspectHttpTargetRequest toWire(Management.InspectHttpTargetRequest value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.InspectHttpTargetRequest.newBuilder();
        result.setService(budget.text(value.service()));
        result.setContract(budget.text(value.contract()));
        result.setFunction(budget.text(value.function()));
        if (value.route().isPresent()) result.setRoute(budget.text(value.route().get()));
        if (value.revisionId().isPresent()) result.setRevisionId(budget.text(value.revisionId().get()));
        if (value.publication().isPresent()) result.setPublication(toWire(value.publication().get(), budget, depth + 1));
        if (value.routingKey().isPresent()) result.setRoutingKey(budget.text(value.routingKey().get()));
        result.setIncludePreparation(budget.scalar(value.includePreparation()));
        result.setMaximumWaitMillis(budget.scalar(value.maximumWaitMillis()));
        return result.build();
    }

    public static Management.InspectHttpTargetRequest fromWire(latent.control.v1.Node.InspectHttpTargetRequest value) {
        return new Management.InspectHttpTargetRequest(
                value.getService(),
                value.getContract(),
                value.getFunction(),
                value.hasRoute() ? Optional.of(value.getRoute()) : Optional.empty(),
                value.hasRevisionId() ? Optional.of(value.getRevisionId()) : Optional.empty(),
                value.hasPublication() ? Optional.of(fromWire(value.getPublication())) : Optional.empty(),
                value.hasRoutingKey() ? Optional.of(value.getRoutingKey()) : Optional.empty(),
                value.getIncludePreparation(),
                value.getMaximumWaitMillis());
    }

    public static latent.control.v1.Node.TargetDependency toWire(Management.TargetDependency value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.TargetDependency toWire(Management.TargetDependency value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.TargetDependency.newBuilder();
        result.setCapability(budget.text(value.capability()));
        result.setState(budget.text(value.state()));
        result.setPolicyIdentityDigest(budget.text(value.policyIdentityDigest()));
        result.setProviderConfigurationEpoch(budget.scalar(value.providerConfigurationEpoch()));
        if (value.binding().isPresent()) result.setBinding(toWire(value.binding().get(), budget, depth + 1));
        for (var item : budget.list(value.policies(), 128)) result.addPolicies(toWire(item, budget, depth + 1));
        result.setProviderProfile(budget.text(value.providerProfile()));
        result.setConfigurationDigest(budget.text(value.configurationDigest()));
        return result.build();
    }

    public static Management.TargetDependency fromWire(latent.control.v1.Node.TargetDependency value) {
        return new Management.TargetDependency(
                value.getCapability(),
                value.getState(),
                value.getPolicyIdentityDigest(),
                value.getProviderConfigurationEpoch(),
                value.hasBinding() ? Optional.of(fromWire(value.getBinding())) : Optional.empty(),
                value.getPoliciesList().stream().map(item -> fromWire(item)).toList(),
                value.getProviderProfile(),
                value.getConfigurationDigest());
    }

    public static latent.control.v1.Node.TargetDependencyRevision toWire(Management.TargetDependencyRevision value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.TargetDependencyRevision toWire(Management.TargetDependencyRevision value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.TargetDependencyRevision.newBuilder();
        result.setId(budget.text(value.id()));
        result.setDigest(budget.text(value.digest()));
        result.setRevision(budget.scalar(value.revision()));
        return result.build();
    }

    public static Management.TargetDependencyRevision fromWire(latent.control.v1.Node.TargetDependencyRevision value) {
        return new Management.TargetDependencyRevision(
                value.getId(),
                value.getDigest(),
                value.getRevision());
    }

    public static latent.control.v1.Node.PreparedTargetExport toWire(Management.PreparedTargetExport value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.PreparedTargetExport toWire(Management.PreparedTargetExport value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.PreparedTargetExport.newBuilder();
        result.setContract(budget.text(value.contract()));
        result.setFunction(budget.text(value.function()));
        return result.build();
    }

    public static Management.PreparedTargetExport fromWire(latent.control.v1.Node.PreparedTargetExport value) {
        return new Management.PreparedTargetExport(
                value.getContract(),
                value.getFunction());
    }

    public static latent.control.v1.Node.TargetPreparation toWire(Management.TargetPreparation value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.TargetPreparation toWire(Management.TargetPreparation value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.TargetPreparation.newBuilder();
        result.setStateValue(budget.scalar(value.state().value()));
        if (value.diagnostic().isPresent()) result.setDiagnostic(toWire(value.diagnostic().get(), budget, depth + 1));
        if (value.profile().isPresent()) result.setProfileValue(budget.scalar(value.profile().get().value()));
        if (value.engineVersion().isPresent()) result.setEngineVersion(budget.text(value.engineVersion().get()));
        if (value.engineConfigurationDigest().isPresent()) result.setEngineConfigurationDigest(budget.text(value.engineConfigurationDigest().get()));
        if (value.targetTriple().isPresent()) result.setTargetTriple(budget.text(value.targetTriple().get()));
        if (value.cpuFeatureSet().isPresent()) result.setCpuFeatureSet(budget.text(value.cpuFeatureSet().get()));
        if (value.sealedMetadataFingerprint().isPresent()) result.setSealedMetadataFingerprint(budget.text(value.sealedMetadataFingerprint().get()));
        if (value.importCount().isPresent()) result.setImportCount(budget.scalar(value.importCount().get()));
        if (value.functionCount().isPresent()) result.setFunctionCount(budget.scalar(value.functionCount().get()));
        if (value.hostcallFuel().isPresent()) result.setHostcallFuel(budget.scalar(value.hostcallFuel().get()));
        if (value.maximumLiftedBytes().isPresent()) result.setMaximumLiftedBytes(budget.scalar(value.maximumLiftedBytes().get()));
        if (value.maximumTypeNodes().isPresent()) result.setMaximumTypeNodes(budget.scalar(value.maximumTypeNodes().get()));
        if (value.declaredBudget().isPresent()) result.setDeclaredBudget(toWire(value.declaredBudget().get(), budget, depth + 1));
        for (var item : budget.list(value.imports(), 128)) result.addImports(budget.text(item));
        for (var item : budget.list(value.exports(), 128)) result.addExports(toWire(item, budget, depth + 1));
        for (var item : budget.list(value.typeImports(), 128)) result.addTypeImports(budget.text(item));
        return result.build();
    }

    public static Management.TargetPreparation fromWire(latent.control.v1.Node.TargetPreparation value) {
        return new Management.TargetPreparation(
                new Management.TargetPreparationState(value.getStateValue()),
                value.hasDiagnostic() ? Optional.of(fromWire(value.getDiagnostic())) : Optional.empty(),
                value.hasProfile() ? Optional.of(new Management.DiagnosticProfile(value.getProfileValue())) : Optional.empty(),
                value.hasEngineVersion() ? Optional.of(value.getEngineVersion()) : Optional.empty(),
                value.hasEngineConfigurationDigest() ? Optional.of(value.getEngineConfigurationDigest()) : Optional.empty(),
                value.hasTargetTriple() ? Optional.of(value.getTargetTriple()) : Optional.empty(),
                value.hasCpuFeatureSet() ? Optional.of(value.getCpuFeatureSet()) : Optional.empty(),
                value.hasSealedMetadataFingerprint() ? Optional.of(value.getSealedMetadataFingerprint()) : Optional.empty(),
                value.hasImportCount() ? Optional.of(value.getImportCount()) : Optional.empty(),
                value.hasFunctionCount() ? Optional.of(value.getFunctionCount()) : Optional.empty(),
                value.hasHostcallFuel() ? Optional.of(value.getHostcallFuel()) : Optional.empty(),
                value.hasMaximumLiftedBytes() ? Optional.of(value.getMaximumLiftedBytes()) : Optional.empty(),
                value.hasMaximumTypeNodes() ? Optional.of(value.getMaximumTypeNodes()) : Optional.empty(),
                value.hasDeclaredBudget() ? Optional.of(fromWire(value.getDeclaredBudget())) : Optional.empty(),
                value.getImportsList().stream().map(item -> item).toList(),
                value.getExportsList().stream().map(item -> fromWire(item)).toList(),
                value.getTypeImportsList().stream().map(item -> item).toList());
    }

    public static latent.control.v1.Node.TargetCandidate toWire(Management.TargetCandidate value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.TargetCandidate toWire(Management.TargetCandidate value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.TargetCandidate.newBuilder();
        result.setDeploymentId(budget.text(value.deploymentId()));
        result.setDeploymentGeneration(budget.scalar(value.deploymentGeneration()));
        result.setRevisionId(budget.text(value.revisionId()));
        result.setComponentDigest(budget.text(value.componentDigest()));
        if (value.publication().isPresent()) result.setPublication(toWire(value.publication().get(), budget, depth + 1));
        if (value.requestedPublication().isPresent()) result.setRequestedPublication(toWire(value.requestedPublication().get(), budget, depth + 1));
        if (value.packageDigest().isPresent()) result.setPackageDigest(budget.text(value.packageDigest().get()));
        if (value.publicationGeneration().isPresent()) result.setPublicationGeneration(budget.scalar(value.publicationGeneration().get()));
        result.setRoutingWeight(budget.scalar(value.routingWeight()));
        result.setExportCompatible(budget.scalar(value.exportCompatible()));
        result.setHttpCompatible(budget.scalar(value.httpCompatible()));
        result.setEligible(budget.scalar(value.eligible()));
        for (var item : budget.list(value.reasons(), 128)) result.addReasonsValue(budget.scalar(item.value()));
        for (var item : budget.list(value.dependencies(), 128)) result.addDependencies(toWire(item, budget, depth + 1));
        if (value.preparation().isPresent()) result.setPreparation(toWire(value.preparation().get(), budget, depth + 1));
        if (value.publicationKind().isPresent()) result.setPublicationKind(budget.text(value.publicationKind().get()));
        for (var item : budget.list(value.httpBindings(), 128)) result.addHttpBindings(toWire(item, budget, depth + 1));
        return result.build();
    }

    public static Management.TargetCandidate fromWire(latent.control.v1.Node.TargetCandidate value) {
        return new Management.TargetCandidate(
                value.getDeploymentId(),
                value.getDeploymentGeneration(),
                value.getRevisionId(),
                value.getComponentDigest(),
                value.hasPublication() ? Optional.of(fromWire(value.getPublication())) : Optional.empty(),
                value.hasRequestedPublication() ? Optional.of(fromWire(value.getRequestedPublication())) : Optional.empty(),
                value.hasPackageDigest() ? Optional.of(value.getPackageDigest()) : Optional.empty(),
                value.hasPublicationGeneration() ? Optional.of(value.getPublicationGeneration()) : Optional.empty(),
                value.getRoutingWeight(),
                value.getExportCompatible(),
                value.getHttpCompatible(),
                value.getEligible(),
                value.getReasonsValueList().stream().map(item -> new Management.TargetReason(item)).toList(),
                value.getDependenciesList().stream().map(item -> fromWire(item)).toList(),
                value.hasPreparation() ? Optional.of(fromWire(value.getPreparation())) : Optional.empty(),
                value.hasPublicationKind() ? Optional.of(value.getPublicationKind()) : Optional.empty(),
                value.getHttpBindingsList().stream().map(item -> fromWire(item)).toList());
    }

    public static latent.control.v1.Node.InspectedHttpBinding toWire(Management.InspectedHttpBinding value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.InspectedHttpBinding toWire(Management.InspectedHttpBinding value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.InspectedHttpBinding.newBuilder();
        result.setId(budget.text(value.id()));
        result.setGeneration(budget.scalar(value.generation()));
        result.setSelectedDeploymentGeneration(budget.scalar(value.selectedDeploymentGeneration()));
        result.setState(budget.text(value.state()));
        return result.build();
    }

    public static Management.InspectedHttpBinding fromWire(latent.control.v1.Node.InspectedHttpBinding value) {
        return new Management.InspectedHttpBinding(
                value.getId(),
                value.getGeneration(),
                value.getSelectedDeploymentGeneration(),
                value.getState());
    }

    public static latent.control.v1.Node.InspectHttpTargetResponse toWire(Management.InspectHttpTargetResponse value) {
        return toWire(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.control.v1.Node.InspectHttpTargetResponse toWire(Management.InspectHttpTargetResponse value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.control.v1.Node.InspectHttpTargetResponse.newBuilder();
        result.setSchemaVersion(budget.scalar(value.schemaVersion()));
        result.setTenant(budget.text(value.tenant()));
        result.setService(budget.text(value.service()));
        result.setContract(budget.text(value.contract()));
        result.setFunction(budget.text(value.function()));
        result.setRoute(budget.text(value.route()));
        result.setStateValue(budget.scalar(value.state().value()));
        result.setCatalogTransaction(budget.scalar(value.catalogTransaction()));
        result.setRouteGeneration(budget.scalar(value.routeGeneration()));
        result.setBindingGeneration(budget.scalar(value.bindingGeneration()));
        if (value.policyStoreGeneration().isPresent()) result.setPolicyStoreGeneration(budget.scalar(value.policyStoreGeneration().get()));
        for (var item : budget.list(value.candidates(), 128)) result.addCandidates(toWire(item, budget, depth + 1));
        if (value.selectedRevisionId().isPresent()) result.setSelectedRevisionId(budget.text(value.selectedRevisionId().get()));
        result.setLiveGrantsChecked(budget.scalar(value.liveGrantsChecked()));
        return result.build();
    }

    public static Management.InspectHttpTargetResponse fromWire(latent.control.v1.Node.InspectHttpTargetResponse value) {
        return new Management.InspectHttpTargetResponse(
                value.getSchemaVersion(),
                value.getTenant(),
                value.getService(),
                value.getContract(),
                value.getFunction(),
                value.getRoute(),
                new Management.TargetObservationState(value.getStateValue()),
                value.getCatalogTransaction(),
                value.getRouteGeneration(),
                value.getBindingGeneration(),
                value.hasPolicyStoreGeneration() ? Optional.of(value.getPolicyStoreGeneration()) : Optional.empty(),
                value.getCandidatesList().stream().map(item -> fromWire(item)).toList(),
                value.hasSelectedRevisionId() ? Optional.of(value.getSelectedRevisionId()) : Optional.empty(),
                value.getLiveGrantsChecked());
    }

    public static latent.invocation.v1.Invocation.ResourceBudget toInvocationResourceBudget(Management.ResourceBudget value) {
        return toInvocationResourceBudget(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.ResourceBudget toInvocationResourceBudget(Management.ResourceBudget value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.ResourceBudget.newBuilder();
        result.setCpuFuel(budget.scalar(value.cpuFuel()));
        result.setMemoryBytes(budget.scalar(value.memoryBytes()));
        result.setChildCalls(budget.scalar(value.childCalls()));
        result.setOutboundRequests(budget.scalar(value.outboundRequests()));
        result.setStateReadBytes(budget.scalar(value.stateReadBytes()));
        result.setStateWriteBytes(budget.scalar(value.stateWriteBytes()));
        result.setBlobReadBytes(budget.scalar(value.blobReadBytes()));
        result.setBlobWriteBytes(budget.scalar(value.blobWriteBytes()));
        result.setLogBytes(budget.scalar(value.logBytes()));
        result.setEffectCount(budget.scalar(value.effectCount()));
        if (value.wallTimeLimitMillis().isPresent()) result.setWallTimeLimitMillis(budget.scalar(value.wallTimeLimitMillis().get()));
        return result.build();
    }

    public static Management.ResourceBudget fromWire(latent.invocation.v1.Invocation.ResourceBudget value) {
        return new Management.ResourceBudget(
                value.getCpuFuel(),
                value.getMemoryBytes(),
                value.getChildCalls(),
                value.getOutboundRequests(),
                value.getStateReadBytes(),
                value.getStateWriteBytes(),
                value.getBlobReadBytes(),
                value.getBlobWriteBytes(),
                value.getLogBytes(),
                value.getEffectCount(),
                value.hasWallTimeLimitMillis() ? Optional.of(value.getWallTimeLimitMillis()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.ErrorDetail toInvocationErrorDetail(Management.ErrorDetail value) {
        return toInvocationErrorDetail(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.ErrorDetail toInvocationErrorDetail(Management.ErrorDetail value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.ErrorDetail.newBuilder();
        result.setKind(budget.text(value.kind()));
        result.putAllFields(budget.map(value.fields()));
        return result.build();
    }

    public static Management.ErrorDetail fromWire(latent.invocation.v1.Invocation.ErrorDetail value) {
        return new Management.ErrorDetail(
                value.getKind(),
                Map.copyOf(value.getFieldsMap()));
    }

    public static latent.invocation.v1.Invocation.PlatformError toInvocationPlatformError(Management.PlatformError value) {
        return toInvocationPlatformError(value, new TransactionProtocol.EncodeBudget(), 0);
    }

    static latent.invocation.v1.Invocation.PlatformError toInvocationPlatformError(Management.PlatformError value, TransactionProtocol.EncodeBudget budget, int depth) {
        budget.enter(depth);
        var result = latent.invocation.v1.Invocation.PlatformError.newBuilder();
        result.setCode(budget.text(value.code()));
        result.setMessage(budget.text(value.message()));
        result.setRetryable(budget.scalar(value.retryable()));
        for (var item : budget.list(value.detailItems(), 128)) result.addDetailItems(toInvocationErrorDetail(item, budget, depth + 1));
        return result.build();
    }

    public static Management.PlatformError fromWire(latent.invocation.v1.Invocation.PlatformError value) {
        return new Management.PlatformError(
                value.getCode(),
                value.getMessage(),
                value.getRetryable(),
                value.getDetailItemsList().stream().map(item -> fromWire(item)).toList());
    }

}
