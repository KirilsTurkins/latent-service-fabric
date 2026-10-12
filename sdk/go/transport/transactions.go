package transport

import (
	"context"
	"errors"
	"google.golang.org/protobuf/proto"
	"latent.dev/sdk/go/internal/rpc/statev1"
	"latent.dev/sdk/go/internal/rpc/transactionv1"
	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"math"
	"reflect"
	"time"
)

var _ tx.Client = (*Client)(nil)

func (client *Client) InvokeCommand(ctx context.Context, request tx.InvokeCommandRequest, options profile.CallOptions) (tx.ClientResponse[tx.InvokeCommandResponse], error) {
	return executeTransaction[tx.InvokeCommandResponse](client, ctx, request, options, &transactionv1.InvokeCommandRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.InvokeCommand(ctx, wire.(*transactionv1.InvokeCommandRequest))
	})
}

func (client *Client) Query(ctx context.Context, request tx.QueryRequest, options profile.CallOptions) (tx.ClientResponse[tx.QueryResponse], error) {
	return executeTransaction[tx.QueryResponse](client, ctx, request, options, &transactionv1.QueryRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.Query(ctx, wire.(*transactionv1.QueryRequest))
	})
}

func (client *Client) LookupCommand(ctx context.Context, request tx.LookupCommandRequest, options profile.CallOptions) (tx.ClientResponse[tx.LookupCommandResponse], error) {
	return executeTransaction[tx.LookupCommandResponse](client, ctx, request, options, &transactionv1.LookupCommandRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.LookupCommand(ctx, wire.(*transactionv1.LookupCommandRequest))
	})
}

func (client *Client) LookupCommit(ctx context.Context, request tx.LookupCommitRequest, options profile.CallOptions) (tx.ClientResponse[tx.LookupCommitResponse], error) {
	return executeTransaction[tx.LookupCommitResponse](client, ctx, request, options, &transactionv1.LookupCommitRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.LookupCommit(ctx, wire.(*transactionv1.LookupCommitRequest))
	})
}

func (client *Client) GetEffect(ctx context.Context, request tx.GetEffectRequest, options profile.CallOptions) (tx.ClientResponse[tx.GetEffectResponse], error) {
	return executeTransaction[tx.GetEffectResponse](client, ctx, request, options, &transactionv1.GetEffectRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.GetEffect(ctx, wire.(*transactionv1.GetEffectRequest))
	})
}

func (client *Client) ListEffectHistory(ctx context.Context, request tx.ListEffectHistoryRequest, options profile.CallOptions) (tx.ClientResponse[tx.ListEffectHistoryResponse], error) {
	return executeTransaction[tx.ListEffectHistoryResponse](client, ctx, request, options, &transactionv1.ListEffectHistoryRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.ListEffectHistory(ctx, wire.(*transactionv1.ListEffectHistoryRequest))
	})
}

func (client *Client) CancelCommand(ctx context.Context, request tx.CancelCommandRequest, options profile.CallOptions) (tx.ClientResponse[tx.CancelCommandResponse], error) {
	return executeTransaction[tx.CancelCommandResponse](client, ctx, request, options, &transactionv1.CancelCommandRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.transactionService.CancelCommand(ctx, wire.(*transactionv1.CancelCommandRequest))
	})
}

func (client *Client) InspectNamespace(ctx context.Context, request tx.InspectNamespaceRequest, options profile.CallOptions) (tx.ClientResponse[tx.InspectNamespaceResponse], error) {
	return executeTransaction[tx.InspectNamespaceResponse](client, ctx, request, options, &statev1.InspectNamespaceRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.stateService.InspectNamespace(ctx, wire.(*statev1.InspectNamespaceRequest))
	})
}

func (client *Client) MutateNamespace(ctx context.Context, request tx.MutateNamespaceRequest, options profile.CallOptions) (tx.ClientResponse[tx.MutateNamespaceResponse], error) {
	return executeTransaction[tx.MutateNamespaceResponse](client, ctx, request, options, &statev1.MutateNamespaceRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.stateService.MutateNamespace(ctx, wire.(*statev1.MutateNamespaceRequest))
	})
}

func (client *Client) SelectEntity(ctx context.Context, request tx.SelectEntityRequest, options profile.CallOptions) (tx.ClientResponse[tx.SelectEntityResponse], error) {
	return executeTransaction[tx.SelectEntityResponse](client, ctx, request, options, &statev1.SelectEntityRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.stateService.SelectEntity(ctx, wire.(*statev1.SelectEntityRequest))
	})
}

func (client *Client) MutateState(ctx context.Context, request tx.MutateStateRequest, options profile.CallOptions) (tx.ClientResponse[tx.MutateStateResponse], error) {
	return executeTransaction[tx.MutateStateResponse](client, ctx, request, options, &statev1.MutateStateRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.stateService.MutateState(ctx, wire.(*statev1.MutateStateRequest))
	})
}

func (client *Client) PlanEffectMutation(ctx context.Context, request tx.PlanEffectMutationRequest, options profile.CallOptions) (tx.ClientResponse[tx.PlanEffectMutationResponse], error) {
	return executeTransaction[tx.PlanEffectMutationResponse](client, ctx, request, options, &statev1.PlanEffectMutationRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.stateService.PlanEffectMutation(ctx, wire.(*statev1.PlanEffectMutationRequest))
	})
}

func (client *Client) GetStateOperationReceipt(ctx context.Context, request tx.GetStateOperationReceiptRequest, options profile.CallOptions) (tx.ClientResponse[tx.GetStateOperationReceiptResponse], error) {
	return executeTransaction[tx.GetStateOperationReceiptResponse](client, ctx, request, options, &statev1.GetStateOperationReceiptRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.stateService.GetStateOperationReceipt(ctx, wire.(*statev1.GetStateOperationReceiptRequest))
	})
}

func (client *Client) InspectDispatcher(ctx context.Context, request tx.InspectDispatcherRequest, options profile.CallOptions) (tx.ClientResponse[tx.InspectDispatcherResponse], error) {
	return executeTransaction[tx.InspectDispatcherResponse](client, ctx, request, options, &statev1.InspectDispatcherRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.dispatcherService.InspectDispatcher(ctx, wire.(*statev1.InspectDispatcherRequest))
	})
}

func (client *Client) ControlDispatcher(ctx context.Context, request tx.ControlDispatcherRequest, options profile.CallOptions) (tx.ClientResponse[tx.ControlDispatcherResponse], error) {
	return executeTransaction[tx.ControlDispatcherResponse](client, ctx, request, options, &statev1.ControlDispatcherRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.dispatcherService.ControlDispatcher(ctx, wire.(*statev1.ControlDispatcherRequest))
	})
}

func (client *Client) GetDispatcherOperation(ctx context.Context, request tx.GetDispatcherOperationRequest, options profile.CallOptions) (tx.ClientResponse[tx.GetDispatcherOperationResponse], error) {
	return executeTransaction[tx.GetDispatcherOperationResponse](client, ctx, request, options, &statev1.GetDispatcherOperationRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.dispatcherService.GetDispatcherOperation(ctx, wire.(*statev1.GetDispatcherOperationRequest))
	})
}

func executeTransaction[Response any](client *Client, parent context.Context, request any, options profile.CallOptions, wire proto.Message, invoke func(context.Context, proto.Message) (proto.Message, error)) (result tx.ClientResponse[Response], failure error) {
	state, _ := client.state(request)
	state.transactional = true
	state.transactionIdentity = transactionIdentity(request)
	state.identity = profile.RequestIdentity{ActivationId: state.transactionIdentity.ActivationId, OperationId: state.transactionIdentity.OperationId}
	state.requestLimit = min(client.config.MaxRequestBytes, 2*1024*1024)
	state.responseLimit = min(client.config.MaxResponseBytes, 2*1024*1024)
	defer func() {
		if failure != nil {
			var native *profile.ClientFailure
			if !errors.As(failure, &native) {
				native = state.fail(profile.FailureCategoryDecode, "invalid bounded transaction value")
			}
			if native.UnsupportedWireValue != nil {
				raw := *native.UnsupportedWireValue
				raw.Value = redact(raw.Value, client.config.BearerToken)
				native.UnsupportedWireValue = &raw
			}
			failure = &tx.ClientFailure{Transport: native, Identity: state.transactionIdentity, Observed: state.transactionObserved}
		}
	}()
	if parent == nil {
		return result, state.fail(profile.FailureCategoryInvalidRequest, "a caller context is required")
	}
	timeout := client.config.DefaultTimeout
	if options.TimeoutMillis != nil {
		if *options.TimeoutMillis > uint64(math.MaxInt64/int64(time.Millisecond)) {
			return result, state.fail(profile.FailureCategoryInvalidRequest, "local timeout cannot be represented")
		}
		requested := time.Duration(*options.TimeoutMillis) * time.Millisecond
		if requested > 30*time.Second {
			return result, state.fail(profile.FailureCategoryLimit, "local timeout exceeds its ceiling")
		}
		timeout = min(timeout, requested)
	}
	if wall := transactionWallDeadline(request); wall != nil {
		now := uint64(time.Now().UnixMilli())
		if *wall <= now {
			timeout = 0
		} else if *wall-now < uint64(timeout/time.Millisecond) {
			timeout = time.Duration(*wall-now) * time.Millisecond
		}
	}
	deadline, finish := context.WithTimeout(parent, timeout)
	defer finish()
	if deadline.Err() != nil {
		return result, callContextFailure(deadline, state)
	}
	if failure = transactionCollections(reflect.ValueOf(request), 0, ""); failure != nil {
		return result, state.fail(profile.FailureCategoryLimit, "transaction collections exceed their bounded shape")
	}
	budget := graphBudget{bytes: min(client.config.MaxGraphBytes, 8*1024*1024), nodes: min(client.config.MaxGraphNodes, 4096)}
	if budget.scan(reflect.ValueOf(request), 0) != nil {
		return result, state.fail(profile.FailureCategoryLimit, "transaction request graph exceeds client limit")
	}
	if failure = validateTransactionRequest(request); failure != nil {
		return result, transactionInvalid(state, failure, false)
	}
	if toProto(request, wire) != nil || proto.Size(wire) > state.requestLimit {
		return result, state.fail(profile.FailureCategoryInvalidRequest, "transaction request contradicts the bounded protobuf profile")
	}
	original := reflect.New(reflect.TypeOf(request))
	if fromProto(wire, original.Interface()) != nil {
		return result, state.fail(profile.FailureCategoryInvalidRequest, "transaction request cannot be captured")
	}
	state.transactionIdentity = transactionIdentity(original.Elem().Interface())
	state.transactionResponse = func(response proto.Message) error {
		if fromProto(response, &result.Value) != nil {
			return state.fail(profile.FailureCategoryDecode, "response contradicts the bounded transaction profile")
		}
		if invalid := validateTransactionResponse(result.Value, original.Elem().Interface(), state); invalid != nil {
			return transactionInvalid(state, invalid, true)
		}
		return nil
	}
	release, invalid := client.acquire(deadline, transactionRecovery(request))
	if invalid != nil {
		native := invalid.(*profile.ClientFailure)
		native.Identity = state.identity
		return result, native
	}
	defer release()
	ctx, cancel := context.WithCancel(deadline)
	defer cancel()
	stopClose := context.AfterFunc(client.lifetime, cancel)
	defer stopClose()
	ctx = context.WithValue(ctx, callKey{}, state)
	_, failure = invoke(ctx, wire)
	if deadline.Err() != nil {
		return tx.ClientResponse[Response]{}, callContextFailure(deadline, state)
	}
	if client.lifetime.Err() != nil {
		return tx.ClientResponse[Response]{}, state.fail(profile.FailureCategoryTransport, "client connection closed; recover the original identity")
	}
	if failure != nil {
		return tx.ClientResponse[Response]{}, failure
	}
	state.metadata.Identity = state.identity
	result.Metadata = tx.ResponseMetadata{Transport: state.metadata, Identity: state.transactionIdentity, Observed: state.transactionObserved}
	return result, nil
}
