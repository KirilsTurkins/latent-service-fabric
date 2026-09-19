using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Examples;

internal sealed partial class Workflow
{
    private async Task Management(BoundedClient client)
    {
        Stage = "bounded-pages";
        Profile.ListPoliciesResponse first = (await client.ListPoliciesAsync(new(Profile.CapabilityPolicyRecordKind.Policy, new(1, null)), Calls, stop)).Value;
        Require(first.Policies.Count == 1 && first.Page?.NextPageToken is { Length: > 0 });
        Profile.ListPoliciesResponse next = (await client.ListPoliciesAsync(new(Profile.CapabilityPolicyRecordKind.Policy, new(1, first.Page!.NextPageToken)), Calls, stop)).Value;
        Require(next.Policies.Count == 1 && next.Policies[0].Id != first.Policies[0].Id && next.CatalogGeneration == first.CatalogGeneration);
        Passed("boundedPages");
        Stage = "provider-inspection";
        Profile.ListCapabilitiesResponse providers = (await client.ListCapabilitiesAsync(new(null, null, new(1, null), input.Targets["http"].Route, false), Calls, stop)).Value;
        Require(providers.Capabilities.Count == 1 && providers.Revision?.PublicationId == input.Targets["http"].Publication);
        Profile.CapabilityDescriptor capability = providers.Capabilities[0];
        Require(capability.Contract == "latent:http/client@0.2.0" && capability.Inspection?.ProviderBinding is not null &&
            capability.Inspection.ProviderProfile.Length != 0 && capability.Inspection.ProviderConfigurationDigest.StartsWith("sha256:", StringComparison.Ordinal));
        Passed("providerInspection");
        Stage = "mutation-receipt";
        var policy = new Profile.Policy("dotnet-example-policy", new("dotnet-example-policy", input.Tenant, null,
            new Dictionary<string, string>(), new Dictionary<string, string>()), input.PolicyDocument, 0,
            "lsf-capability-policy-v1", Profile.CapabilityPolicyRecordKind.Policy, "", false);
        var request = new Profile.ApplyPolicyRequest(policy, 0, "dotnet-policy-create");
        Profile.ClientResponse<Profile.ApplyPolicyResponse> created = await client.ApplyPolicyAsync(request, Calls, stop);
        AbsentAudit(created.Metadata);
        Require(created.Metadata.Outcome == Profile.OutcomeKnowledge.Observed && created.Value.Receipt is not null && created.Value.Policy is not null);
        Profile.CapabilityPolicyOperation receipt = created.Value.Receipt!;
        Require(receipt.OperationId == request.OperationId && receipt.Generation == created.Value.Policy!.Generation && receipt.Generation != 0 &&
            receipt.ContentDigest == created.Value.Policy.ContentDigest && receipt.Id == policy.Id && receipt.Tenant == input.Tenant);
        Profile.ClientResponse<Profile.GetPolicyResponse> inspected = await client.GetPolicyAsync(new(policy.Id, policy.RecordKind), Calls, stop);
        AbsentAudit(inspected.Metadata);
        Require(inspected.Value.Policy?.Generation == receipt.Generation && inspected.Value.Policy?.ContentDigest == receipt.ContentDigest);
        Profile.ClientResponse<Profile.GetPolicyOperationResponse> recovered = await client.GetPolicyOperationAsync(new(request.OperationId), Calls, stop);
        AbsentAudit(recovered.Metadata);
        Require(recovered.Value.Receipt == receipt);
        Profile.ClientResponse<Profile.GetPolicyOperationResponse> missing = await client.GetPolicyOperationAsync(new("dotnet-not-retained"), Calls, stop);
        AbsentAudit(missing.Metadata);
        Require(missing.Value.Receipt is null && missing.Metadata.Outcome == Profile.OutcomeKnowledge.Unknown);
        Passed("mutationReceipt");
        Stage = "exact-replay";
        Profile.ClientResponse<Profile.ApplyPolicyResponse> replay = await client.ApplyPolicyAsync(request, Calls, stop);
        AbsentAudit(replay.Metadata);
        Require(replay.Value.Receipt == receipt);
        Passed("exactReplay");
        Stage = "precondition-conflict";
        Profile.ClientFailure conflict = await Failure(client.ApplyPolicyAsync(request with { OperationId = "dotnet-stale-precondition" }, Calls, stop).AsTask());
        AbsentAudit(conflict);
        Require(conflict.Category == Profile.FailureCategory.Rpc && conflict.GrpcStatus is 9 or 10 &&
            conflict.Outcome == Profile.OutcomeKnowledge.Observed && conflict.Identity.OperationId == "dotnet-stale-precondition");
        Profile.ClientFailure changed = await Failure(client.ApplyPolicyAsync(request with
        {
            Policy = policy with { Id = "dotnet-changed-policy", Metadata = policy.Metadata! with { Name = "dotnet-changed-policy" } }
        }, Calls, stop).AsTask());
        AbsentAudit(changed);
        Require(changed.Category == Profile.FailureCategory.Rpc && changed.GrpcStatus is 3 or 9 or 10 && changed.Identity.OperationId == request.OperationId);
        Passed("preconditionConflict");
    }
}
