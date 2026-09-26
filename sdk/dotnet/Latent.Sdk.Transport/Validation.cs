using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed partial class BoundedClient
{
    private static bool Text(string? value, int maximum, bool empty = false) => value is not null && (empty || value.Length != 0) && GraphBudget.Utf8.GetByteCount(value) <= maximum;
    private static bool OptionalText(string? value, int maximum) => value is null || Text(value, maximum, true);
    private static bool RecordKind(Profile.CapabilityPolicyRecordKind value) => value == Profile.CapabilityPolicyRecordKind.Policy || value == Profile.CapabilityPolicyRecordKind.ProviderBinding;
    private static void Require(bool valid) { if (!valid) throw new FormatException("invalid bounded profile value"); }

    private static void ValidateRequest(object request)
    {
        switch (request)
        {
            case Profile.InvokeRequest invoke:
                Require(invoke.Target is not null && invoke.Budget is not null && Text(invoke.MediaType, 128) && invoke.Metadata is not null &&
                    OptionalText(invoke.ActivationId, 256) && OptionalText(invoke.RootActivationId, 256) && OptionalText(invoke.ParentActivationId, 256) &&
                    OptionalText(invoke.IdempotencyKey, 256));
                Require(Text(invoke.Target!.Tenant, 256) && Text(invoke.Target.Service, 256) && Text(invoke.Target.Contract, 256) &&
                    Text(invoke.Target.Function, 256) && OptionalText(invoke.Target.Route, 256));
                break;
            case Profile.CancelRequest cancel: Require(Text(cancel.ActivationId, 256) && Text(cancel.Reason, 1024, true)); break;
            case Profile.GetActivationRequest activation: Require(Text(activation.ActivationId, 256)); break;
            case Profile.GetPolicyRequest policy: Require(Text(policy.Id, 256) && RecordKind(policy.RecordKind)); break;
            case Profile.ListPoliciesRequest policies:
                Require(RecordKind(policies.RecordKind) && policies.Page is not null && policies.Page.PageSize is >= 1 and <= 32 && OptionalText(policies.Page.PageToken, 117));
                break;
            case Profile.ListCapabilitiesRequest capabilities:
                Require(Text(capabilities.DeploymentId, 256) && OptionalText(capabilities.ContractPrefix, 256) && OptionalText(capabilities.Provider, 256) &&
                    (capabilities.Page is null || capabilities.Page.PageSize <= 128 && OptionalText(capabilities.Page.PageToken, 160)));
                break;
            case Profile.ApplyPolicyRequest apply:
                Require(apply.ExpectedGeneration.HasValue && Text(apply.OperationId, 256) && apply.Policy is not null);
                Profile.Policy document = apply.Policy!;
                Require(Text(document.Id, 256) && document.Metadata is not null && RecordKind(document.RecordKind) && Text(document.Language, 128) &&
                    Text(document.Document, 128 * 1024) && document.Generation == 0 && document.ContentDigest == "" && !document.Revoked);
                Require(document.Metadata!.Name == document.Id && Text(document.Metadata.Tenant, 256) && document.Metadata.Namespace is null &&
                    document.Metadata.Labels is { Count: 0 } && document.Metadata.Annotations is { Count: 0 });
                break;
            case Profile.GetPolicyOperationRequest operation: Require(Text(operation.OperationId, 256)); break;
            default: throw new FormatException("unsupported profile operation");
        }
    }

    private static void ValidateResponse(object response, object request, CallState state)
    {
        Profile.OutcomeKnowledge outcome = Profile.OutcomeKnowledge.Observed;
        switch (response)
        {
            case Profile.InvokeResponse invocation:
                Require(Text(invocation.ActivationId, 256) && invocation.Consumption is not null &&
                    Count(invocation.Success, invocation.DeclaredError, invocation.PlatformFailure) == 1 &&
                    (state.Identity.ActivationId is null || state.Identity.ActivationId == invocation.ActivationId));
                state.Identity = new(invocation.ActivationId, null);
                break;
            case Profile.CancelResponse cancel:
                Require(OptionalText(cancel.TerminalState, 256));
                if (cancel.Disposition == Profile.CancelDisposition.NotFound) outcome = Profile.OutcomeKnowledge.Unknown;
                break;
            case Profile.ActivationStatus activation:
                Require(activation.ActivationId == state.Identity.ActivationId && Text(activation.Phase, 256) && OptionalText(activation.TerminalState, 256));
                int outcomes = Count(activation.Succeeded, activation.DeclaredError, activation.PlatformFailure);
                Require(activation.TerminalState is null ? outcomes == 0 : outcomes == 1 && activation.FinalConsumption is not null && activation.TerminalAtUnixMillis.HasValue);
                break;
            case Profile.ListPoliciesResponse policies:
                Require(policies.Policies.Count <= ((Profile.ListPoliciesRequest)request).Page!.PageSize && OptionalText(policies.Page?.NextPageToken, 117));
                break;
            case Profile.ListCapabilitiesResponse capabilities:
                uint requested = ((Profile.ListCapabilitiesRequest)request).Page?.PageSize ?? 0;
                Require(capabilities.Capabilities.Count <= (requested == 0 ? 128 : requested) && OptionalText(capabilities.Page?.NextPageToken, 160));
                break;
            case Profile.ApplyPolicyResponse apply:
                Require(apply.Policy is not null && apply.Receipt is not null && apply.Receipt.OperationId == state.Identity.OperationId &&
                    apply.Policy.Id == ((Profile.ApplyPolicyRequest)request).Policy!.Id && apply.Receipt.Id == apply.Policy.Id);
                break;
            case Profile.GetPolicyOperationResponse operation:
                if (operation.Receipt is null) outcome = Profile.OutcomeKnowledge.Unknown;
                else Require(operation.Receipt.OperationId == state.Identity.OperationId);
                break;
        }
        state.Outcome = outcome;
    }

    private static int Count(object? first, object? second, object? third) => (first is null ? 0 : 1) + (second is null ? 0 : 1) + (third is null ? 0 : 1);
}
