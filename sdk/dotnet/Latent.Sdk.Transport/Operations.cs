using System.Reflection;
using Google.Protobuf;
using WireControl = global::Latent.Control.V1;
using WireInvocation = global::Latent.Invocation.V1;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed partial class BoundedClient : Profile.IClientProfile
{
    public ValueTask<Profile.ClientResponse<Profile.InvokeResponse>> InvokeAsync(Profile.InvokeRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.InvokeResponse, WireInvocation.InvokeRequest, WireInvocation.InvokeResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireInvocation.InvocationService.InvocationServiceClient(invoker).InvokeAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.CancelResponse>> CancelAsync(Profile.CancelRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.CancelResponse, WireInvocation.CancelRequest, WireInvocation.CancelResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireInvocation.InvocationService.InvocationServiceClient(invoker).CancelAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.ActivationStatus>> GetActivationAsync(Profile.GetActivationRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.ActivationStatus, WireInvocation.GetActivationRequest, WireInvocation.ActivationStatus>(request, options, cancellationToken,
            (invoker, wire) => new WireInvocation.InvocationService.InvocationServiceClient(invoker).GetActivationAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.GetPolicyResponse>> GetPolicyAsync(Profile.GetPolicyRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.GetPolicyResponse, WireControl.GetPolicyRequest, WireControl.GetPolicyResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.PolicyService.PolicyServiceClient(invoker).GetPolicyAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.ListPoliciesResponse>> ListPoliciesAsync(Profile.ListPoliciesRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.ListPoliciesResponse, WireControl.ListPoliciesRequest, WireControl.ListPoliciesResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.PolicyService.PolicyServiceClient(invoker).ListPoliciesAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.ListCapabilitiesResponse>> ListCapabilitiesAsync(Profile.ListCapabilitiesRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.ListCapabilitiesResponse, WireControl.ListCapabilitiesRequest, WireControl.ListCapabilitiesResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.CapabilityService.CapabilityServiceClient(invoker).ListCapabilitiesAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.ApplyPolicyResponse>> ApplyPolicyAsync(Profile.ApplyPolicyRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.ApplyPolicyResponse, WireControl.ApplyPolicyRequest, WireControl.ApplyPolicyResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.PolicyService.PolicyServiceClient(invoker).ApplyPolicyAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    public ValueTask<Profile.ClientResponse<Profile.GetPolicyOperationResponse>> GetPolicyOperationAsync(Profile.GetPolicyOperationRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default) =>
        ExecuteAsync<Profile.GetPolicyOperationResponse, WireControl.GetPolicyOperationRequest, WireControl.GetPolicyOperationResponse>(request, options, cancellationToken,
            (invoker, wire) => new WireControl.PolicyService.PolicyServiceClient(invoker).GetPolicyOperationAsync(wire, cancellationToken: invoker.Token).ResponseAsync);

    private async ValueTask<Profile.ClientResponse<Response>> ExecuteAsync<Response, WireRequest, WireResponse>(object request,
        Profile.CallOptions options, CancellationToken caller, Func<UnaryInvoker, WireRequest, Task<WireResponse>> dispatch)
        where WireRequest : IMessage, new() where WireResponse : IMessage
    {
        var state = new CallState(config, request, options, caller);
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(caller, lifetime.Token);
        deadline.CancelAfter(state.Remaining);
        bool admitted = false;
        try
        {
            CheckDeadline(state, deadline.Token);
            await AcquireAsync(state, deadline.Token).ConfigureAwait(false);
            admitted = true;
            new GraphBudget(config.MaxGraphBytes, config.MaxGraphNodes, deadline.Token).Scan(request);
            ValidateRequest(request);
            var wireRequest = (WireRequest)ProfileCodec.ToWire(request, new WireRequest());
            CheckDeadline(state, deadline.Token);
            WireResponse wireResponse = await dispatch(new(this, state, deadline.Token), wireRequest).ConfigureAwait(false);
            CheckDeadline(state, deadline.Token);
            var value = (Response)ProfileCodec.FromWire(wireResponse, typeof(Response));
            ValidateResponse(value!, request, state);
            CheckDeadline(state, deadline.Token);
            return new(value, state.Metadata);
        }
        catch (Profile.ClientException) { throw; }
        catch (Profile.ClientCancellationException) { throw; }
        catch (OperationCanceledException) { throw state.Cancelled(deadline.Token); }
        catch (GraphLimitException) { throw state.Error(Profile.FailureCategory.Limit, "request or response graph exceeds client limit"); }
        catch (InvalidProtocolBufferException)
        {
            throw state.Error(Profile.FailureCategory.Decode, "response contradicts the bounded protobuf profile");
        }
        catch (Exception failure) when (failure is IOException or HttpRequestException or ObjectDisposedException)
        {
            if (deadline.IsCancellationRequested || state.Remaining == TimeSpan.Zero) throw state.Cancelled(deadline.Token);
            throw state.Error(Profile.FailureCategory.Transport, "owned HTTP/2 connection failed; remote outcome may remain unknown");
        }
        catch (Exception failure) when (failure is FormatException or ArgumentException or OverflowException or TargetInvocationException)
        {
            throw state.Error(state.Dispatched ? Profile.FailureCategory.Decode : Profile.FailureCategory.InvalidRequest,
                "value contradicts the bounded protobuf profile");
        }
        finally { if (admitted) Release(state); }
    }
}
