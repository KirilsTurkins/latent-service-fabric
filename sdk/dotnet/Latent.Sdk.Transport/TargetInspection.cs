using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed partial class BoundedClient
{
    private static bool TargetId(string? value) => Text(value, 512) && !value!.Any(char.IsWhiteSpace) && !value!.Any(char.IsControl);
    private static bool TargetHex(string value) => value.Length == 64 && value.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
    private static bool TargetDigest(string value, string prefix) => value.StartsWith(prefix, StringComparison.Ordinal) && TargetHex(value[prefix.Length..]);
    private static bool TargetPublication(Profile.PublicationRef value, string tenant) => value.Tenant == tenant && TargetId(tenant) && TargetDigest(value.Id, "publication:sha256:");

    private static void ValidateTargetRequest(Profile.InspectHttpTargetRequest value)
    {
        Require(TargetId(value.Service) && TargetId(value.Contract) && TargetId(value.Function) && value.MaximumWaitMillis <= 30000);
        foreach (string? text in new[] { value.Route, value.RevisionId, value.RoutingKey }) Require(text is null || TargetId(text));
        if (value.Publication is { } publication) Require(TargetPublication(publication, publication.Tenant));
    }

    private static void ValidateTargetResponse(Profile.InspectHttpTargetResponse value, Profile.InspectHttpTargetRequest request)
    {
        Require(value.SchemaVersion == 1 && TargetId(value.Tenant) && value.Service == request.Service && value.Contract == request.Contract && value.Function == request.Function && TargetId(value.Route)
            && (request.Route is null || value.Route == request.Route) && (request.Publication is null || value.Tenant == request.Publication.Tenant) && !value.LiveGrantsChecked && value.Candidates.Count <= 32);
        var revisions = new HashSet<string>(StringComparer.Ordinal);
        foreach (var candidate in value.Candidates)
        {
            Require(TargetId(candidate.DeploymentId) && TargetId(candidate.RevisionId) && revisions.Add(candidate.RevisionId) && TargetDigest(candidate.ComponentDigest,"sha256:")
                && (candidate.PackageDigest is null || TargetDigest(candidate.PackageDigest,"sha256:")) && (request.RevisionId is null || candidate.RevisionId == request.RevisionId)
                && candidate.RoutingWeight <= 65535 && candidate.Reasons.Count <= 16 && candidate.Dependencies.Count <= 32 && candidate.HttpBindings.Count <= 32);
            foreach (var publication in new[] { candidate.Publication, candidate.RequestedPublication }) Require(publication is null || TargetPublication(publication,value.Tenant));
            Require(request.Publication is null || candidate.Publication == request.Publication);
            Require(candidate.PublicationKind is null || candidate.PackageDigest is not null && candidate.PublicationKind is "capsule" or "browser-assets" or "ssr-package");
            foreach (var binding in candidate.HttpBindings) Require(TargetId(binding.Id) && binding.Generation != 0 && binding.State is "configured-current" or "deployment-changed");
            foreach (var dependency in candidate.Dependencies)
            {
                Require(TargetId(dependency.Capability) && TargetId(dependency.ProviderProfile) && TargetId(dependency.ConfigurationDigest) && TargetHex(dependency.PolicyIdentityDigest)
                    && dependency.Binding is not null && dependency.Policies.Count <= 32 && dependency.State is "configured-current" or "policy-changed-or-revoked" or "provider-unavailable" or "publication-unavailable" or "route-changed-or-unavailable" or "inspection-indeterminate");
                Require(TargetId(dependency.Binding!.Id) && TargetId(dependency.Binding.Digest));
                foreach (var revision in dependency.Policies) Require(TargetId(revision.Id) && TargetId(revision.Digest));
            }
            var preparation = candidate.Preparation;
            Require(preparation is not null);
            Require((request.IncludePreparation ? preparation!.State.Value != 4 : preparation!.State.Value == 4) && preparation.Imports.Count + preparation.TypeImports.Count <= 64 && preparation.Exports.Count <= 128);
            foreach (string? text in new[] { preparation.EngineVersion, preparation.TargetTriple, preparation.CpuFeatureSet }) Require(text is null || TargetId(text));
            Require((preparation.EngineConfigurationDigest is null || TargetDigest(preparation.EngineConfigurationDigest,"blake3:")) && (preparation.SealedMetadataFingerprint is null || TargetHex(preparation.SealedMetadataFingerprint)));
            foreach (var imported in preparation.Imports) Require(TargetId(imported));
            foreach (var imported in preparation.TypeImports) Require(TargetId(imported));
            foreach (var exported in preparation.Exports) Require(TargetId(exported.Contract) && TargetId(exported.Function));
            if (preparation.Diagnostic is { } diagnostic) Require(diagnostic.SchemaVersion == 1 && (diagnostic.ProfileDigest is null || TargetHex(diagnostic.ProfileDigest)));
            if (preparation.State.Value == 1) Require(preparation.Profile is not null && preparation.EngineVersion is not null && preparation.EngineConfigurationDigest is not null && preparation.TargetTriple is not null
                && preparation.CpuFeatureSet is not null && preparation.DeclaredBudget is not null && preparation.ImportCount == (ulong)(preparation.Imports.Count + preparation.TypeImports.Count) && preparation.FunctionCount == (ulong)preparation.Exports.Count
                && preparation.HostcallFuel is not null && preparation.MaximumLiftedBytes is not null && preparation.MaximumTypeNodes is not null);
            if (candidate.Eligible) Require(value.State.Value == 1 && candidate.ExportCompatible && candidate.Publication is not null && candidate.PackageDigest is not null && candidate.PublicationGeneration is not null
                && candidate.RoutingWeight > 0 && candidate.Reasons.Count == 1 && candidate.Reasons[0].Value == 1 && preparation.State.Value is 1 or 4 && candidate.Dependencies.All(d => d.State == "configured-current"));
        }
        Require(value.SelectedRevisionId is null || request.RoutingKey is not null && revisions.Contains(value.SelectedRevisionId));
    }
}
