package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import com.google.protobuf.ByteString;
import java.util.Map;
import java.util.Optional;

public final class Wire {
    private Wire() { }

    public static latent.control.v1.Common.ResourceBudget toWire(Management.ResourceBudget value) {
        var result = latent.control.v1.Common.ResourceBudget.newBuilder();
        result.setCpuFuel(value.cpuFuel());
        result.setMemoryBytes(value.memoryBytes());
        result.setChildCalls(value.childCalls());
        result.setOutboundRequests(value.outboundRequests());
        result.setStateReadBytes(value.stateReadBytes());
        result.setStateWriteBytes(value.stateWriteBytes());
        result.setBlobReadBytes(value.blobReadBytes());
        result.setBlobWriteBytes(value.blobWriteBytes());
        result.setLogBytes(value.logBytes());
        result.setEffectCount(value.effectCount());
        if (value.wallTimeLimitMillis().isPresent()) result.setWallTimeLimitMillis(value.wallTimeLimitMillis().get());
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
        var result = latent.control.v1.Common.ErrorDetail.newBuilder();
        result.setKind(value.kind());
        result.putAllFields(value.fields());
        return result.build();
    }

    public static Management.ErrorDetail fromWire(latent.control.v1.Common.ErrorDetail value) {
        return new Management.ErrorDetail(
                value.getKind(),
                Map.copyOf(value.getFieldsMap()));
    }

    public static latent.control.v1.Common.PlatformError toWire(Management.PlatformError value) {
        var result = latent.control.v1.Common.PlatformError.newBuilder();
        result.setCode(value.code());
        result.setMessage(value.message());
        result.setRetryable(value.retryable());
        for (var item : value.detailItems()) result.addDetailItems(toWire(item));
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
        var result = latent.control.v1.Common.ObjectMetadata.newBuilder();
        result.setName(value.name());
        if (value.tenant().isPresent()) result.setTenant(value.tenant().get());
        if (value.namespace().isPresent()) result.setNamespace(value.namespace().get());
        result.putAllLabels(value.labels());
        result.putAllAnnotations(value.annotations());
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
        var result = latent.control.v1.Common.PageRequest.newBuilder();
        result.setPageSize(value.pageSize());
        if (value.pageToken().isPresent()) result.setPageToken(value.pageToken().get());
        return result.build();
    }

    public static Management.PageRequest fromWire(latent.control.v1.Common.PageRequest value) {
        return new Management.PageRequest(
                value.getPageSize(),
                value.hasPageToken() ? Optional.of(value.getPageToken()) : Optional.empty());
    }

    public static latent.control.v1.Common.PageResponse toWire(Management.PageResponse value) {
        var result = latent.control.v1.Common.PageResponse.newBuilder();
        if (value.nextPageToken().isPresent()) result.setNextPageToken(value.nextPageToken().get());
        return result.build();
    }

    public static Management.PageResponse fromWire(latent.control.v1.Common.PageResponse value) {
        return new Management.PageResponse(
                value.hasNextPageToken() ? Optional.of(value.getNextPageToken()) : Optional.empty());
    }

    public static latent.control.v1.Common.AuditAck toWire(Management.AuditAck value) {
        var result = latent.control.v1.Common.AuditAck.newBuilder();
        result.setStatusValue(value.status().value());
        if (value.attemptSequence().isPresent()) result.setAttemptSequence(value.attemptSequence().get());
        return result.build();
    }

    public static Management.AuditAck fromWire(latent.control.v1.Common.AuditAck value) {
        return new Management.AuditAck(
                new Management.AuditAckStatus(value.getStatusValue()),
                value.hasAttemptSequence() ? Optional.of(value.getAttemptSequence()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.InvocationTarget toWire(Management.InvocationTarget value) {
        var result = latent.invocation.v1.Invocation.InvocationTarget.newBuilder();
        result.setTenant(value.tenant());
        result.setService(value.service());
        result.setContract(value.contract());
        result.setFunction(value.function());
        if (value.route().isPresent()) result.setRoute(value.route().get());
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
        var result = latent.invocation.v1.Invocation.InvokeRequest.newBuilder();
        if (value.activationId().isPresent()) result.setActivationId(value.activationId().get());
        if (value.parentActivationId().isPresent()) result.setParentActivationId(value.parentActivationId().get());
        if (value.rootActivationId().isPresent()) result.setRootActivationId(value.rootActivationId().get());
        if (value.target().isPresent()) result.setTarget(toWire(value.target().get()));
        result.setPayload(ByteString.copyFrom(value.payload().asReadOnlyBuffer()));
        result.setMediaType(value.mediaType());
        if (value.deadlineUnixMillis().isPresent()) result.setDeadlineUnixMillis(value.deadlineUnixMillis().get());
        result.setPriority(value.priority());
        if (value.idempotencyKey().isPresent()) result.setIdempotencyKey(value.idempotencyKey().get());
        if (value.budget().isPresent()) result.setBudget(toInvocationResourceBudget(value.budget().get()));
        result.putAllMetadata(value.metadata());
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
        var result = latent.invocation.v1.Invocation.BudgetConsumption.newBuilder();
        result.setCpuFuel(value.cpuFuel());
        result.setPeakMemoryBytes(value.peakMemoryBytes());
        result.setWallTimeMicros(value.wallTimeMicros());
        result.setChildCalls(value.childCalls());
        result.setOutboundRequests(value.outboundRequests());
        result.setStateReadBytes(value.stateReadBytes());
        result.setStateWriteBytes(value.stateWriteBytes());
        result.setBlobReadBytes(value.blobReadBytes());
        result.setBlobWriteBytes(value.blobWriteBytes());
        result.setLogBytes(value.logBytes());
        result.setEffectCount(value.effectCount());
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
        var result = latent.invocation.v1.Invocation.InvokeResponse.newBuilder();
        if ((value.success().isPresent() ? 1 : 0) + (value.declaredError().isPresent() ? 1 : 0) + (value.platformFailure().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        result.setActivationId(value.activationId());
        result.setRevisionId(value.revisionId());
        result.setReleaseDigest(value.releaseDigest());
        result.setRouteGeneration(value.routeGeneration());
        if (value.success().isPresent()) result.setSuccess(toWire(value.success().get()));
        if (value.declaredError().isPresent()) result.setDeclaredError(toWire(value.declaredError().get()));
        if (value.platformFailure().isPresent()) result.setPlatformFailure(toInvocationPlatformError(value.platformFailure().get()));
        if (value.consumption().isPresent()) result.setConsumption(toWire(value.consumption().get()));
        if (value.publicationId().isPresent()) result.setPublicationId(value.publicationId().get());
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
        var result = latent.invocation.v1.Invocation.Success.newBuilder();
        result.setPayload(ByteString.copyFrom(value.payload().asReadOnlyBuffer()));
        result.setMediaType(value.mediaType());
        if (value.committedStateVersion().isPresent()) result.setCommittedStateVersion(value.committedStateVersion().get());
        for (var item : value.effectIds()) result.addEffectIds(item);
        result.putAllMetadata(value.metadata());
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
        var result = latent.invocation.v1.Invocation.DeclaredError.newBuilder();
        result.setCode(value.code());
        result.setMessage(value.message());
        result.setPayload(ByteString.copyFrom(value.payload().asReadOnlyBuffer()));
        result.setMediaType(value.mediaType());
        result.putAllMetadata(value.metadata());
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
        var result = latent.invocation.v1.Invocation.CancelRequest.newBuilder();
        result.setActivationId(value.activationId());
        result.setReason(value.reason());
        return result.build();
    }

    public static Management.CancelRequest fromWire(latent.invocation.v1.Invocation.CancelRequest value) {
        return new Management.CancelRequest(
                value.getActivationId(),
                value.getReason());
    }

    public static latent.invocation.v1.Invocation.CancelResponse toWire(Management.CancelResponse value) {
        var result = latent.invocation.v1.Invocation.CancelResponse.newBuilder();
        result.setDispositionValue(value.disposition().value());
        if (value.terminalState().isPresent()) result.setTerminalState(value.terminalState().get());
        return result.build();
    }

    public static Management.CancelResponse fromWire(latent.invocation.v1.Invocation.CancelResponse value) {
        return new Management.CancelResponse(
                new Management.CancelDisposition(value.getDispositionValue()),
                value.hasTerminalState() ? Optional.of(value.getTerminalState()) : Optional.empty());
    }

    public static latent.invocation.v1.Invocation.GetActivationRequest toWire(Management.GetActivationRequest value) {
        var result = latent.invocation.v1.Invocation.GetActivationRequest.newBuilder();
        result.setActivationId(value.activationId());
        return result.build();
    }

    public static Management.GetActivationRequest fromWire(latent.invocation.v1.Invocation.GetActivationRequest value) {
        return new Management.GetActivationRequest(
                value.getActivationId());
    }

    public static latent.invocation.v1.Invocation.ActivationStatus toWire(Management.ActivationStatus value) {
        var result = latent.invocation.v1.Invocation.ActivationStatus.newBuilder();
        if ((value.succeeded().isPresent() ? 1 : 0) + (value.declaredError().isPresent() ? 1 : 0) + (value.platformFailure().isPresent() ? 1 : 0) > 1) throw new IllegalArgumentException("contradictory oneof");
        result.setActivationId(value.activationId());
        result.setPhase(value.phase());
        if (value.terminalState().isPresent()) result.setTerminalState(value.terminalState().get());
        result.setLastUpdatedUnixMillis(value.lastUpdatedUnixMillis());
        result.putAllMetadata(value.metadata());
        if (value.succeeded().isPresent()) result.setSucceeded(toWire(value.succeeded().get()));
        if (value.declaredError().isPresent()) result.setDeclaredError(toWire(value.declaredError().get()));
        if (value.platformFailure().isPresent()) result.setPlatformFailure(toInvocationPlatformError(value.platformFailure().get()));
        if (value.finalConsumption().isPresent()) result.setFinalConsumption(toWire(value.finalConsumption().get()));
        if (value.terminalAtUnixMillis().isPresent()) result.setTerminalAtUnixMillis(value.terminalAtUnixMillis().get());
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
        var result = latent.invocation.v1.Invocation.ActivationSuccessSummary.newBuilder();
        if (value.committedStateVersion().isPresent()) result.setCommittedStateVersion(value.committedStateVersion().get());
        for (var item : value.effectIds()) result.addEffectIds(item);
        result.putAllMetadata(value.metadata());
        return result.build();
    }

    public static Management.ActivationSuccessSummary fromWire(latent.invocation.v1.Invocation.ActivationSuccessSummary value) {
        return new Management.ActivationSuccessSummary(
                value.hasCommittedStateVersion() ? Optional.of(value.getCommittedStateVersion()) : Optional.empty(),
                value.getEffectIdsList().stream().map(item -> item).toList(),
                Map.copyOf(value.getMetadataMap()));
    }

    public static latent.control.v1.PolicyOuterClass.Policy toWire(Management.Policy value) {
        var result = latent.control.v1.PolicyOuterClass.Policy.newBuilder();
        result.setId(value.id());
        if (value.metadata().isPresent()) result.setMetadata(toWire(value.metadata().get()));
        result.setDocument(value.document());
        result.setGeneration(value.generation());
        result.setLanguage(value.language());
        result.setRecordKindValue(value.recordKind().value());
        result.setContentDigest(value.contentDigest());
        result.setRevoked(value.revoked());
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
        var result = latent.control.v1.PolicyOuterClass.ApplyPolicyRequest.newBuilder();
        if (value.policy().isPresent()) result.setPolicy(toWire(value.policy().get()));
        if (value.expectedGeneration().isPresent()) result.setExpectedGeneration(value.expectedGeneration().get());
        result.setOperationId(value.operationId());
        return result.build();
    }

    public static Management.ApplyPolicyRequest fromWire(latent.control.v1.PolicyOuterClass.ApplyPolicyRequest value) {
        return new Management.ApplyPolicyRequest(
                value.hasPolicy() ? Optional.of(fromWire(value.getPolicy())) : Optional.empty(),
                value.hasExpectedGeneration() ? Optional.of(value.getExpectedGeneration()) : Optional.empty(),
                value.getOperationId());
    }

    public static latent.control.v1.PolicyOuterClass.ApplyPolicyResponse toWire(Management.ApplyPolicyResponse value) {
        var result = latent.control.v1.PolicyOuterClass.ApplyPolicyResponse.newBuilder();
        if (value.policy().isPresent()) result.setPolicy(toWire(value.policy().get()));
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        return result.build();
    }

    public static Management.ApplyPolicyResponse fromWire(latent.control.v1.PolicyOuterClass.ApplyPolicyResponse value) {
        return new Management.ApplyPolicyResponse(
                value.hasPolicy() ? Optional.of(fromWire(value.getPolicy())) : Optional.empty(),
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyRequest toWire(Management.GetPolicyRequest value) {
        var result = latent.control.v1.PolicyOuterClass.GetPolicyRequest.newBuilder();
        result.setId(value.id());
        result.setRecordKindValue(value.recordKind().value());
        return result.build();
    }

    public static Management.GetPolicyRequest fromWire(latent.control.v1.PolicyOuterClass.GetPolicyRequest value) {
        return new Management.GetPolicyRequest(
                value.getId(),
                new Management.CapabilityPolicyRecordKind(value.getRecordKindValue()));
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyResponse toWire(Management.GetPolicyResponse value) {
        var result = latent.control.v1.PolicyOuterClass.GetPolicyResponse.newBuilder();
        if (value.policy().isPresent()) result.setPolicy(toWire(value.policy().get()));
        return result.build();
    }

    public static Management.GetPolicyResponse fromWire(latent.control.v1.PolicyOuterClass.GetPolicyResponse value) {
        return new Management.GetPolicyResponse(
                value.hasPolicy() ? Optional.of(fromWire(value.getPolicy())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.CapabilityPolicyOperation toWire(Management.CapabilityPolicyOperation value) {
        var result = latent.control.v1.PolicyOuterClass.CapabilityPolicyOperation.newBuilder();
        result.setOperationId(value.operationId());
        result.setTenant(value.tenant());
        result.setId(value.id());
        result.setRecordKindValue(value.recordKind().value());
        result.setGeneration(value.generation());
        result.setContentDigest(value.contentDigest());
        result.setRevoked(value.revoked());
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
        var result = latent.control.v1.PolicyOuterClass.GetPolicyOperationRequest.newBuilder();
        result.setOperationId(value.operationId());
        return result.build();
    }

    public static Management.GetPolicyOperationRequest fromWire(latent.control.v1.PolicyOuterClass.GetPolicyOperationRequest value) {
        return new Management.GetPolicyOperationRequest(
                value.getOperationId());
    }

    public static latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse toWire(Management.GetPolicyOperationResponse value) {
        var result = latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse.newBuilder();
        if (value.receipt().isPresent()) result.setReceipt(toWire(value.receipt().get()));
        return result.build();
    }

    public static Management.GetPolicyOperationResponse fromWire(latent.control.v1.PolicyOuterClass.GetPolicyOperationResponse value) {
        return new Management.GetPolicyOperationResponse(
                value.hasReceipt() ? Optional.of(fromWire(value.getReceipt())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.ListPoliciesRequest toWire(Management.ListPoliciesRequest value) {
        var result = latent.control.v1.PolicyOuterClass.ListPoliciesRequest.newBuilder();
        result.setRecordKindValue(value.recordKind().value());
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        return result.build();
    }

    public static Management.ListPoliciesRequest fromWire(latent.control.v1.PolicyOuterClass.ListPoliciesRequest value) {
        return new Management.ListPoliciesRequest(
                new Management.CapabilityPolicyRecordKind(value.getRecordKindValue()),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    public static latent.control.v1.PolicyOuterClass.ListPoliciesResponse toWire(Management.ListPoliciesResponse value) {
        var result = latent.control.v1.PolicyOuterClass.ListPoliciesResponse.newBuilder();
        for (var item : value.policies()) result.addPolicies(toWire(item));
        result.setCatalogGeneration(value.catalogGeneration());
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        return result.build();
    }

    public static Management.ListPoliciesResponse fromWire(latent.control.v1.PolicyOuterClass.ListPoliciesResponse value) {
        return new Management.ListPoliciesResponse(
                value.getPoliciesList().stream().map(item -> fromWire(item)).toList(),
                value.getCatalogGeneration(),
                value.hasPage() ? Optional.of(fromWire(value.getPage())) : Optional.empty());
    }

    public static latent.control.v1.Capability.CapabilityDescriptor toWire(Management.CapabilityDescriptor value) {
        var result = latent.control.v1.Capability.CapabilityDescriptor.newBuilder();
        result.setId(value.id());
        result.setContract(value.contract());
        result.setProvider(value.provider());
        for (var item : value.operations()) result.addOperations(item);
        result.putAllAttributes(value.attributes());
        if (value.inspection().isPresent()) result.setInspection(toWire(value.inspection().get()));
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
        var result = latent.control.v1.Capability.ListCapabilitiesRequest.newBuilder();
        if (value.contractPrefix().isPresent()) result.setContractPrefix(value.contractPrefix().get());
        if (value.provider().isPresent()) result.setProvider(value.provider().get());
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        result.setDeploymentId(value.deploymentId());
        result.setIncludeNodeUsage(value.includeNodeUsage());
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
        var result = latent.control.v1.Capability.ListCapabilitiesResponse.newBuilder();
        for (var item : value.capabilities()) result.addCapabilities(toWire(item));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        if (value.revision().isPresent()) result.setRevision(toWire(value.revision().get()));
        if (value.tenantUsage().isPresent()) result.setTenantUsage(toWire(value.tenantUsage().get()));
        if (value.nodeUsage().isPresent()) result.setNodeUsage(toWire(value.nodeUsage().get()));
        result.setState(value.state());
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
        var result = latent.control.v1.Capability.CapabilityInspectionRevision.newBuilder();
        result.setDeploymentId(value.deploymentId());
        result.setRevisionId(value.revisionId());
        result.setComponentDigest(value.componentDigest());
        if (value.publicationId().isPresent()) result.setPublicationId(value.publicationId().get());
        result.setRouteGeneration(value.routeGeneration());
        result.setCatalogTransaction(value.catalogTransaction());
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
        var result = latent.control.v1.Capability.CapabilityInspectionPolicy.newBuilder();
        result.setId(value.id());
        result.setRevision(value.revision());
        result.setDigest(value.digest());
        return result.build();
    }

    public static Management.CapabilityInspectionPolicy fromWire(latent.control.v1.Capability.CapabilityInspectionPolicy value) {
        return new Management.CapabilityInspectionPolicy(
                value.getId(),
                value.getRevision(),
                value.getDigest());
    }

    public static latent.control.v1.Capability.CapabilityBindingInspection toWire(Management.CapabilityBindingInspection value) {
        var result = latent.control.v1.Capability.CapabilityBindingInspection.newBuilder();
        if (value.definitionDigest().isPresent()) result.setDefinitionDigest(value.definitionDigest().get());
        if (value.providerBinding().isPresent()) result.setProviderBinding(toWire(value.providerBinding().get()));
        for (var item : value.policies()) result.addPolicies(toWire(item));
        result.setProviderProfile(value.providerProfile());
        result.setProviderConfigurationDigest(value.providerConfigurationDigest());
        result.setProviderConfigurationEpoch(value.providerConfigurationEpoch());
        result.setState(value.state());
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
        var result = latent.control.v1.Capability.CapabilityInspectionCeiling.newBuilder();
        result.setOperations(value.operations());
        result.setInputBytes(value.inputBytes());
        result.setOutputBytes(value.outputBytes());
        result.setWallTimeMillis(value.wallTimeMillis());
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
        var result = latent.control.v1.Capability.CapabilityResourceUsage.newBuilder();
        result.setScope(value.scope());
        result.putAllCounters(value.counters());
        for (var item : value.unavailable()) result.addUnavailable(item);
        return result.build();
    }

    public static Management.CapabilityResourceUsage fromWire(latent.control.v1.Capability.CapabilityResourceUsage value) {
        return new Management.CapabilityResourceUsage(
                value.getScope(),
                Map.copyOf(value.getCountersMap()),
                value.getUnavailableList().stream().map(item -> item).toList());
    }

    public static latent.control.v1.Release.PublicationRef toWire(Management.PublicationRef value) {
        var result = latent.control.v1.Release.PublicationRef.newBuilder();
        result.setId(value.id());
        result.setTenant(value.tenant());
        return result.build();
    }

    public static Management.PublicationRef fromWire(latent.control.v1.Release.PublicationRef value) {
        return new Management.PublicationRef(
                value.getId(),
                value.getTenant());
    }

    public static latent.invocation.v1.Invocation.ResourceBudget toInvocationResourceBudget(Management.ResourceBudget value) {
        var result = latent.invocation.v1.Invocation.ResourceBudget.newBuilder();
        result.setCpuFuel(value.cpuFuel());
        result.setMemoryBytes(value.memoryBytes());
        result.setChildCalls(value.childCalls());
        result.setOutboundRequests(value.outboundRequests());
        result.setStateReadBytes(value.stateReadBytes());
        result.setStateWriteBytes(value.stateWriteBytes());
        result.setBlobReadBytes(value.blobReadBytes());
        result.setBlobWriteBytes(value.blobWriteBytes());
        result.setLogBytes(value.logBytes());
        result.setEffectCount(value.effectCount());
        if (value.wallTimeLimitMillis().isPresent()) result.setWallTimeLimitMillis(value.wallTimeLimitMillis().get());
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
        var result = latent.invocation.v1.Invocation.ErrorDetail.newBuilder();
        result.setKind(value.kind());
        result.putAllFields(value.fields());
        return result.build();
    }

    public static Management.ErrorDetail fromWire(latent.invocation.v1.Invocation.ErrorDetail value) {
        return new Management.ErrorDetail(
                value.getKind(),
                Map.copyOf(value.getFieldsMap()));
    }

    public static latent.invocation.v1.Invocation.PlatformError toInvocationPlatformError(Management.PlatformError value) {
        var result = latent.invocation.v1.Invocation.PlatformError.newBuilder();
        result.setCode(value.code());
        result.setMessage(value.message());
        result.setRetryable(value.retryable());
        for (var item : value.detailItems()) result.addDetailItems(toInvocationErrorDetail(item));
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
