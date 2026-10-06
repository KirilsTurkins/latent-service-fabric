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

    public static latent.control.v1.Node.ActivationDiagnostic toWire(Management.ActivationDiagnostic value) {
        var result = latent.control.v1.Node.ActivationDiagnostic.newBuilder();
        result.setSchemaVersion(value.schemaVersion());
        result.setStageValue(value.stage().value());
        result.setReasonValue(value.reason().value());
        if (value.profile().isPresent()) result.setProfileValue(value.profile().get().value());
        if (value.profileDigest().isPresent()) result.setProfileDigest(value.profileDigest().get());
        if (value.configuredBound().isPresent()) result.setConfiguredBound(value.configuredBound().get());
        if (value.calculatedRequirement().isPresent()) result.setCalculatedRequirement(value.calculatedRequirement().get());
        if (value.fixedBytes().isPresent()) result.setFixedBytes(value.fixedBytes().get());
        if (value.liftingFuel().isPresent()) result.setLiftingFuel(value.liftingFuel().get());
        if (value.liftMultiplier().isPresent()) result.setLiftMultiplier(value.liftMultiplier().get());
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

    public static latent.control.v1.Node.ActivationTreeNode toWire(Management.ActivationTreeNode value) {
        var result = latent.control.v1.Node.ActivationTreeNode.newBuilder();
        result.setActivationId(value.activationId());
        if (value.parentActivationId().isPresent()) result.setParentActivationId(value.parentActivationId().get());
        result.setRootActivationId(value.rootActivationId());
        result.setPhase(value.phase());
        if (value.terminalState().isPresent()) result.setTerminalState(value.terminalState().get());
        result.setLastUpdatedUnixMillis(value.lastUpdatedUnixMillis());
        if (value.diagnostic().isPresent()) result.setDiagnostic(toWire(value.diagnostic().get()));
        result.setPrincipalKind(value.principalKind());
        if (value.callerService().isPresent()) result.setCallerService(value.callerService().get());
        if (value.grantedBudget().isPresent()) result.setGrantedBudget(toWire(value.grantedBudget().get()));
        if (value.effectiveDeadlineUnixMillis().isPresent()) result.setEffectiveDeadlineUnixMillis(value.effectiveDeadlineUnixMillis().get());
        result.setDiagnosticIsTerminal(value.diagnosticIsTerminal());
        result.setTargetService(value.targetService());
        result.setReceivedAtUnixMillis(value.receivedAtUnixMillis());
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
                value.getReceivedAtUnixMillis());
    }

    public static latent.control.v1.Node.InspectActivationTreeRequest toWire(Management.InspectActivationTreeRequest value) {
        var result = latent.control.v1.Node.InspectActivationTreeRequest.newBuilder();
        result.setActivationId(value.activationId());
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        if (value.service().isPresent()) result.setService(value.service().get());
        if (value.fromUnixMillis().isPresent()) result.setFromUnixMillis(value.fromUnixMillis().get());
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
        var result = latent.control.v1.Node.InspectActivationTreeResponse.newBuilder();
        result.setSchemaVersion(value.schemaVersion());
        for (var item : value.nodes()) result.addNodes(toWire(item));
        if (value.page().isPresent()) result.setPage(toWire(value.page().get()));
        result.setHistoryAvailable(value.historyAvailable());
        result.setCursorExpired(value.cursorExpired());
        result.setRetainedHistoryOnly(value.retainedHistoryOnly());
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
        var result = latent.control.v1.Node.InspectHttpTargetRequest.newBuilder();
        result.setService(value.service());
        result.setContract(value.contract());
        result.setFunction(value.function());
        if (value.route().isPresent()) result.setRoute(value.route().get());
        if (value.revisionId().isPresent()) result.setRevisionId(value.revisionId().get());
        if (value.publication().isPresent()) result.setPublication(toWire(value.publication().get()));
        if (value.routingKey().isPresent()) result.setRoutingKey(value.routingKey().get());
        result.setIncludePreparation(value.includePreparation());
        result.setMaximumWaitMillis(value.maximumWaitMillis());
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
        var result = latent.control.v1.Node.TargetDependency.newBuilder();
        result.setCapability(value.capability());
        result.setState(value.state());
        result.setPolicyIdentityDigest(value.policyIdentityDigest());
        result.setProviderConfigurationEpoch(value.providerConfigurationEpoch());
        if (value.binding().isPresent()) result.setBinding(toWire(value.binding().get()));
        for (var item : value.policies()) result.addPolicies(toWire(item));
        result.setProviderProfile(value.providerProfile());
        result.setConfigurationDigest(value.configurationDigest());
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
        var result = latent.control.v1.Node.TargetDependencyRevision.newBuilder();
        result.setId(value.id());
        result.setDigest(value.digest());
        result.setRevision(value.revision());
        return result.build();
    }

    public static Management.TargetDependencyRevision fromWire(latent.control.v1.Node.TargetDependencyRevision value) {
        return new Management.TargetDependencyRevision(
                value.getId(),
                value.getDigest(),
                value.getRevision());
    }

    public static latent.control.v1.Node.PreparedTargetExport toWire(Management.PreparedTargetExport value) {
        var result = latent.control.v1.Node.PreparedTargetExport.newBuilder();
        result.setContract(value.contract());
        result.setFunction(value.function());
        return result.build();
    }

    public static Management.PreparedTargetExport fromWire(latent.control.v1.Node.PreparedTargetExport value) {
        return new Management.PreparedTargetExport(
                value.getContract(),
                value.getFunction());
    }

    public static latent.control.v1.Node.TargetPreparation toWire(Management.TargetPreparation value) {
        var result = latent.control.v1.Node.TargetPreparation.newBuilder();
        result.setStateValue(value.state().value());
        if (value.diagnostic().isPresent()) result.setDiagnostic(toWire(value.diagnostic().get()));
        if (value.profile().isPresent()) result.setProfileValue(value.profile().get().value());
        if (value.engineVersion().isPresent()) result.setEngineVersion(value.engineVersion().get());
        if (value.engineConfigurationDigest().isPresent()) result.setEngineConfigurationDigest(value.engineConfigurationDigest().get());
        if (value.targetTriple().isPresent()) result.setTargetTriple(value.targetTriple().get());
        if (value.cpuFeatureSet().isPresent()) result.setCpuFeatureSet(value.cpuFeatureSet().get());
        if (value.sealedMetadataFingerprint().isPresent()) result.setSealedMetadataFingerprint(value.sealedMetadataFingerprint().get());
        if (value.importCount().isPresent()) result.setImportCount(value.importCount().get());
        if (value.functionCount().isPresent()) result.setFunctionCount(value.functionCount().get());
        if (value.hostcallFuel().isPresent()) result.setHostcallFuel(value.hostcallFuel().get());
        if (value.maximumLiftedBytes().isPresent()) result.setMaximumLiftedBytes(value.maximumLiftedBytes().get());
        if (value.maximumTypeNodes().isPresent()) result.setMaximumTypeNodes(value.maximumTypeNodes().get());
        if (value.declaredBudget().isPresent()) result.setDeclaredBudget(toWire(value.declaredBudget().get()));
        for (var item : value.imports()) result.addImports(item);
        for (var item : value.exports()) result.addExports(toWire(item));
        for (var item : value.typeImports()) result.addTypeImports(item);
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
        var result = latent.control.v1.Node.TargetCandidate.newBuilder();
        result.setDeploymentId(value.deploymentId());
        result.setDeploymentGeneration(value.deploymentGeneration());
        result.setRevisionId(value.revisionId());
        result.setComponentDigest(value.componentDigest());
        if (value.publication().isPresent()) result.setPublication(toWire(value.publication().get()));
        if (value.requestedPublication().isPresent()) result.setRequestedPublication(toWire(value.requestedPublication().get()));
        if (value.packageDigest().isPresent()) result.setPackageDigest(value.packageDigest().get());
        if (value.publicationGeneration().isPresent()) result.setPublicationGeneration(value.publicationGeneration().get());
        result.setRoutingWeight(value.routingWeight());
        result.setExportCompatible(value.exportCompatible());
        result.setHttpCompatible(value.httpCompatible());
        result.setEligible(value.eligible());
        for (var item : value.reasons()) result.addReasonsValue(item.value());
        for (var item : value.dependencies()) result.addDependencies(toWire(item));
        if (value.preparation().isPresent()) result.setPreparation(toWire(value.preparation().get()));
        if (value.publicationKind().isPresent()) result.setPublicationKind(value.publicationKind().get());
        for (var item : value.httpBindings()) result.addHttpBindings(toWire(item));
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
        var result = latent.control.v1.Node.InspectedHttpBinding.newBuilder();
        result.setId(value.id());
        result.setGeneration(value.generation());
        result.setSelectedDeploymentGeneration(value.selectedDeploymentGeneration());
        result.setState(value.state());
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
        var result = latent.control.v1.Node.InspectHttpTargetResponse.newBuilder();
        result.setSchemaVersion(value.schemaVersion());
        result.setTenant(value.tenant());
        result.setService(value.service());
        result.setContract(value.contract());
        result.setFunction(value.function());
        result.setRoute(value.route());
        result.setStateValue(value.state().value());
        result.setCatalogTransaction(value.catalogTransaction());
        result.setRouteGeneration(value.routeGeneration());
        result.setBindingGeneration(value.bindingGeneration());
        if (value.policyStoreGeneration().isPresent()) result.setPolicyStoreGeneration(value.policyStoreGeneration().get());
        for (var item : value.candidates()) result.addCandidates(toWire(item));
        if (value.selectedRevisionId().isPresent()) result.setSelectedRevisionId(value.selectedRevisionId().get());
        result.setLiveGrantsChecked(value.liveGrantsChecked());
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
