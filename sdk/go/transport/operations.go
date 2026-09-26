package transport

import (
	"context"
	"math"
	"reflect"
	"strings"
	"time"

	"google.golang.org/protobuf/proto"
	"latent.dev/sdk/go/internal/rpc/controlv1"
	"latent.dev/sdk/go/internal/rpc/invocationv1"
	"latent.dev/sdk/go/profile"
)

func (client *Client) Invoke(ctx context.Context, request profile.InvokeRequest, options profile.CallOptions) (profile.ClientResponse[profile.InvokeResponse], error) {
	return execute[profile.InvokeResponse](client, ctx, request, options, &invocationv1.InvokeRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.invocation.Invoke(ctx, wire.(*invocationv1.InvokeRequest))
	})
}

func (client *Client) Cancel(ctx context.Context, request profile.CancelRequest, options profile.CallOptions) (profile.ClientResponse[profile.CancelResponse], error) {
	return execute[profile.CancelResponse](client, ctx, request, options, &invocationv1.CancelRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.invocation.Cancel(ctx, wire.(*invocationv1.CancelRequest))
	})
}

func (client *Client) GetActivation(ctx context.Context, request profile.GetActivationRequest, options profile.CallOptions) (profile.ClientResponse[profile.ActivationStatus], error) {
	return execute[profile.ActivationStatus](client, ctx, request, options, &invocationv1.GetActivationRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.invocation.GetActivation(ctx, wire.(*invocationv1.GetActivationRequest))
	})
}

func (client *Client) GetPolicy(ctx context.Context, request profile.GetPolicyRequest, options profile.CallOptions) (profile.ClientResponse[profile.GetPolicyResponse], error) {
	return execute[profile.GetPolicyResponse](client, ctx, request, options, &controlv1.GetPolicyRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.policy.GetPolicy(ctx, wire.(*controlv1.GetPolicyRequest))
	})
}

func (client *Client) ListPolicies(ctx context.Context, request profile.ListPoliciesRequest, options profile.CallOptions) (profile.ClientResponse[profile.ListPoliciesResponse], error) {
	return execute[profile.ListPoliciesResponse](client, ctx, request, options, &controlv1.ListPoliciesRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.policy.ListPolicies(ctx, wire.(*controlv1.ListPoliciesRequest))
	})
}

func (client *Client) ListCapabilities(ctx context.Context, request profile.ListCapabilitiesRequest, options profile.CallOptions) (profile.ClientResponse[profile.ListCapabilitiesResponse], error) {
	return execute[profile.ListCapabilitiesResponse](client, ctx, request, options, &controlv1.ListCapabilitiesRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.capability.ListCapabilities(ctx, wire.(*controlv1.ListCapabilitiesRequest))
	})
}

func (client *Client) ApplyPolicy(ctx context.Context, request profile.ApplyPolicyRequest, options profile.CallOptions) (profile.ClientResponse[profile.ApplyPolicyResponse], error) {
	return execute[profile.ApplyPolicyResponse](client, ctx, request, options, &controlv1.ApplyPolicyRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.policy.ApplyPolicy(ctx, wire.(*controlv1.ApplyPolicyRequest))
	})
}

func (client *Client) GetPolicyOperation(ctx context.Context, request profile.GetPolicyOperationRequest, options profile.CallOptions) (profile.ClientResponse[profile.GetPolicyOperationResponse], error) {
	return execute[profile.GetPolicyOperationResponse](client, ctx, request, options, &controlv1.GetPolicyOperationRequest{}, func(ctx context.Context, wire proto.Message) (proto.Message, error) {
		return client.policy.GetPolicyOperation(ctx, wire.(*controlv1.GetPolicyOperationRequest))
	})
}

func execute[Response any](client *Client, parent context.Context, request any, options profile.CallOptions, wire proto.Message, invoke func(context.Context, proto.Message) (proto.Message, error)) (profile.ClientResponse[Response], error) {
	var result profile.ClientResponse[Response]
	state, recovery := client.state(request)
	if parent == nil {
		return result, state.fail(profile.FailureCategoryInvalidRequest, "a caller context is required")
	}
	timeout := client.config.DefaultTimeout
	if options.TimeoutMillis != nil {
		if *options.TimeoutMillis > uint64(math.MaxInt64/int64(time.Millisecond)) {
			return result, state.fail(profile.FailureCategoryInvalidRequest, "local timeout cannot be represented")
		}
		timeout = time.Duration(*options.TimeoutMillis) * time.Millisecond
		if timeout > 30*time.Second {
			return result, state.fail(profile.FailureCategoryLimit, "local timeout exceeds the 30 second ceiling")
		}
	}
	deadline, finish := context.WithTimeout(parent, timeout)
	defer finish()
	release, failure := client.acquire(deadline, recovery)
	if failure != nil {
		failure.(*profile.ClientFailure).Identity = state.identity
		return result, failure
	}
	defer release()
	ctx, cancel := context.WithCancel(deadline)
	defer cancel()
	stopClose := context.AfterFunc(client.lifetime, cancel)
	defer stopClose()
	ctx = context.WithValue(ctx, callKey{}, state)
	budget := graphBudget{bytes: client.config.MaxGraphBytes, nodes: client.config.MaxGraphNodes}
	if budget.scan(reflect.ValueOf(request), 0) != nil {
		return result, state.fail(profile.FailureCategoryLimit, "request graph exceeds client limits")
	}
	if failure = validateRequest(request, state.requestLimit); failure != nil {
		return result, state.fail(profile.FailureCategoryInvalidRequest, "invalid bounded profile request")
	}
	if failure = toProto(request, wire); failure != nil {
		return result, state.fail(profile.FailureCategoryInvalidRequest, "request contradicts the protobuf profile")
	}
	if deadline.Err() != nil {
		return result, callContextFailure(deadline, state)
	}
	response, failure := invoke(ctx, wire)
	if deadline.Err() != nil {
		return result, callContextFailure(deadline, state)
	}
	if client.lifetime.Err() != nil {
		return result, state.fail(profile.FailureCategoryTransport, "client connection closed; recover by the original identity")
	}
	if failure != nil {
		return result, failure
	}
	if fromProto(response, &result.Value) != nil {
		return result, state.fail(profile.FailureCategoryDecode, "response does not match the protobuf profile")
	}
	if failure = validateResponse(&result.Value, request, state); failure != nil {
		return profile.ClientResponse[Response]{}, failure
	}
	state.metadata.Identity = state.identity
	if deadline.Err() != nil {
		return profile.ClientResponse[Response]{}, callContextFailure(deadline, state)
	}
	result.Metadata = state.metadata
	return result, nil
}

func (client *Client) state(request any) (*callState, bool) {
	state := &callState{requestLimit: min(client.config.MaxRequestBytes, 128*1024), responseLimit: min(client.config.MaxResponseBytes, 1024*1024)}
	state.metadata.Outcome = profile.OutcomeKnowledgeUnknown
	recovery := false
	switch value := request.(type) {
	case profile.InvokeRequest:
		state.identity.ActivationId = copyIdentity(value.ActivationId)
		state.requestLimit = client.config.MaxRequestBytes
		state.responseLimit = client.config.MaxResponseBytes
	case profile.CancelRequest:
		state.identity.ActivationId = copyIdentity(&value.ActivationId)
		recovery = true
	case profile.GetActivationRequest:
		state.identity.ActivationId = copyIdentity(&value.ActivationId)
		recovery = true
	case profile.ApplyPolicyRequest:
		state.identity.OperationId = copyIdentity(&value.OperationId)
	case profile.GetPolicyOperationRequest:
		state.identity.OperationId = copyIdentity(&value.OperationId)
		recovery = true
	case profile.ListCapabilitiesRequest:
		state.requestLimit = min(client.config.MaxRequestBytes, 8*1024)
		state.responseLimit = min(client.config.MaxResponseBytes, 128*1024)
	}
	return state, recovery
}

func copyIdentity(value *string) *string {
	if value == nil || len(*value) > 256 {
		return nil
	}
	owned := strings.Clone(*value)
	return &owned
}
