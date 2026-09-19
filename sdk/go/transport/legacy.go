package transport

import (
	"context"

	latent "latent.dev/sdk/go"
	"latent.dev/sdk/go/profile"
)

type LegacyClient struct {
	client *Client
}

var _ latent.Client = (*LegacyClient)(nil)

func NewLegacy(ctx context.Context, config Config) (*LegacyClient, error) {
	client, failure := New(ctx, config)
	if failure != nil {
		return nil, failure
	}
	return client.Legacy(), nil
}

func (client *Client) Legacy() *LegacyClient { return &LegacyClient{client: client} }

func (client *LegacyClient) Close() error { return client.client.Close() }

func (client *LegacyClient) Invoke(ctx context.Context, request latent.InvokeRequest) (latent.InvocationOutcome, error) {
	budget := request.Options.Budget
	response, failure := client.client.Invoke(ctx, profile.InvokeRequest{
		ActivationId: request.ActivationID, RootActivationId: request.RootActivationID, ParentActivationId: request.ParentActivationID,
		Target: &profile.InvocationTarget{Tenant: request.Target.Tenant, Service: request.Target.Service,
			Contract: request.Target.Contract, Function: request.Target.Function, Route: request.Target.Route},
		Payload: request.Payload, MediaType: request.MediaType, DeadlineUnixMillis: request.Options.DeadlineUnixMillis,
		Priority: uint32(request.Options.Priority), IdempotencyKey: request.Options.IdempotencyKey, Metadata: request.Options.Metadata,
		Budget: &profile.ResourceBudget{
			CpuFuel: budget.CPUFuel, MemoryBytes: budget.MemoryBytes, WallTimeLimitMillis: budget.WallTimeLimitMillis,
			ChildCalls: budget.ChildCalls, OutboundRequests: budget.OutboundRequests,
			StateReadBytes: budget.StateReadBytes, StateWriteBytes: budget.StateWriteBytes,
			BlobReadBytes: budget.BlobReadBytes, BlobWriteBytes: budget.BlobWriteBytes,
			LogBytes: budget.LogBytes, EffectCount: budget.EffectCount,
		},
	}, profile.CallOptions{})
	if failure != nil {
		return latent.InvocationOutcome{}, failure
	}
	value := response.Value
	receipt := latent.InvocationReceipt{ActivationID: value.ActivationId, RevisionID: value.RevisionId,
		ReleaseDigest: value.ReleaseDigest, PublicationID: value.PublicationId, RouteGeneration: value.RouteGeneration,
		Consumption: legacyConsumption(*value.Consumption)}
	if value.Success != nil {
		return latent.InvocationOutcome{Success: &latent.InvokeResponse{
			ActivationID: receipt.ActivationID, RevisionID: receipt.RevisionID, ReleaseDigest: receipt.ReleaseDigest,
			PublicationID: receipt.PublicationID, RouteGeneration: receipt.RouteGeneration, Consumption: receipt.Consumption,
			Payload: value.Success.Payload, MediaType: value.Success.MediaType, CommittedStateVersion: value.Success.CommittedStateVersion,
			EffectIDs: value.Success.EffectIds, Metadata: value.Success.Metadata,
		}}, nil
	}
	if value.DeclaredError != nil {
		return latent.InvocationOutcome{DeclaredError: &latent.DeclaredInvocationError{Receipt: receipt, Error: legacyDeclared(*value.DeclaredError)}}, nil
	}
	return latent.InvocationOutcome{PlatformFailure: &latent.PlatformInvocationFailure{Receipt: receipt, Error: legacyPlatform(*value.PlatformFailure)}}, nil
}

func (client *LegacyClient) Cancel(ctx context.Context, activationID, reason string) (latent.CancelResponse, error) {
	response, failure := client.client.Cancel(ctx, profile.CancelRequest{ActivationId: activationID, Reason: reason}, profile.CallOptions{})
	if failure != nil {
		return latent.CancelResponse{}, failure
	}
	dispositions := map[profile.CancelDisposition]latent.CancelDisposition{
		profile.CancelDispositionAccepted:        latent.CancelAccepted,
		profile.CancelDispositionAlreadyTerminal: latent.CancelAlreadyTerminal,
		profile.CancelDispositionNotFound:        latent.CancelNotFound,
	}
	return latent.CancelResponse{Disposition: dispositions[response.Value.Disposition], TerminalState: response.Value.TerminalState}, nil
}

func (client *LegacyClient) GetActivation(ctx context.Context, activationID string) (latent.ActivationStatus, error) {
	response, failure := client.client.GetActivation(ctx, profile.GetActivationRequest{ActivationId: activationID}, profile.CallOptions{})
	if failure != nil {
		return latent.ActivationStatus{}, failure
	}
	value := response.Value
	result := latent.ActivationStatus{ActivationID: value.ActivationId, Phase: value.Phase,
		TerminalState: value.TerminalState, LastUpdatedUnixMS: value.LastUpdatedUnixMillis,
		TerminalAtUnixMS: value.TerminalAtUnixMillis, Metadata: value.Metadata}
	if value.FinalConsumption != nil {
		consumption := legacyConsumption(*value.FinalConsumption)
		result.FinalConsumption = &consumption
	}
	if value.Succeeded != nil {
		result.TerminalOutcome = &latent.RetainedInvocationOutcome{Succeeded: &latent.ActivationSuccessSummary{
			CommittedStateVersion: value.Succeeded.CommittedStateVersion, EffectIDs: value.Succeeded.EffectIds, Metadata: value.Succeeded.Metadata}}
	} else if value.DeclaredError != nil {
		declared := legacyDeclared(*value.DeclaredError)
		result.TerminalOutcome = &latent.RetainedInvocationOutcome{DeclaredError: &declared}
	} else if value.PlatformFailure != nil {
		platform := legacyPlatform(*value.PlatformFailure)
		result.TerminalOutcome = &latent.RetainedInvocationOutcome{PlatformFailure: &platform}
	}
	return result, nil
}

func legacyConsumption(value profile.BudgetConsumption) latent.BudgetConsumption {
	return latent.BudgetConsumption{CPUFuel: value.CpuFuel, PeakMemoryBytes: value.PeakMemoryBytes,
		WallTimeMicros: value.WallTimeMicros, ChildCalls: value.ChildCalls, OutboundRequests: value.OutboundRequests,
		StateReadBytes: value.StateReadBytes, StateWriteBytes: value.StateWriteBytes,
		BlobReadBytes: value.BlobReadBytes, BlobWriteBytes: value.BlobWriteBytes, LogBytes: value.LogBytes, EffectCount: value.EffectCount}
}

func legacyDeclared(value profile.DeclaredError) latent.DeclaredError {
	return latent.DeclaredError{Code: value.Code, Message: value.Message, Payload: value.Payload, MediaType: value.MediaType, Metadata: value.Metadata}
}

func legacyPlatform(value profile.PlatformError) latent.PlatformError {
	details := make([]latent.ErrorDetail, len(value.DetailItems))
	for index, detail := range value.DetailItems {
		details[index] = latent.ErrorDetail{Kind: detail.Kind, Fields: detail.Fields}
	}
	return latent.PlatformError{Code: value.Code, Message: value.Message, Retryable: value.Retryable, Details: details}
}
