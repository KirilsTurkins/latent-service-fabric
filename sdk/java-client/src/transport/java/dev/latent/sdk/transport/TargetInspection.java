package dev.latent.sdk.transport;

import dev.latent.sdk.Management;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;

final class TargetInspection {
    private TargetInspection() { }
    private static boolean id(String value) { return Protocol.treeIdentity(value); }
    private static boolean hex(String value) { return value.matches("[0-9a-f]{64}"); }
    private static boolean digest(String value, String prefix) { return value.startsWith(prefix) && hex(value.substring(prefix.length())); }
    private static void require(boolean value) { Protocol.require(value); }
    private static void publication(Management.PublicationRef value, String tenant) {
        require(value.tenant().equals(tenant) && id(tenant) && digest(value.id(), "publication:sha256:"));
    }
    static void request(Management.InspectHttpTargetRequest value, String tenant) {
        require(id(value.service()) && id(value.contract()) && id(value.function()) && Long.compareUnsigned(value.maximumWaitMillis(),30000) <= 0);
        for (var text : List.of(value.route(),value.revisionId(),value.routingKey())) text.ifPresent(v -> require(id(v)));
        value.publication().ifPresent(v -> publication(v,tenant));
    }
    static void response(Management.InspectHttpTargetResponse value, Management.InspectHttpTargetRequest request, String tenant) {
        require(value.schemaVersion() == 1 && value.tenant().equals(tenant) && value.service().equals(request.service()) && value.contract().equals(request.contract()) && value.function().equals(request.function())
            && id(value.route()) && request.route().map(value.route()::equals).orElse(true) && !value.liveGrantsChecked() && value.candidates().size() <= 32);
        var revisions = new HashSet<String>();
        for (var candidate : value.candidates()) {
            require(id(candidate.deploymentId()) && id(candidate.revisionId()) && revisions.add(candidate.revisionId()) && digest(candidate.componentDigest(),"sha256:")
                && candidate.packageDigest().map(v -> digest(v,"sha256:")).orElse(true) && request.revisionId().map(candidate.revisionId()::equals).orElse(true)
                && Integer.compareUnsigned(candidate.routingWeight(),65535) <= 0 && candidate.reasons().size() <= 16 && candidate.dependencies().size() <= 32 && candidate.httpBindings().size() <= 32);
            for (var reference : List.of(candidate.publication(),candidate.requestedPublication())) reference.ifPresent(v -> publication(v,tenant));
            require(request.publication().isEmpty() || candidate.publication().equals(request.publication()));
            candidate.publicationKind().ifPresent(v -> require(candidate.packageDigest().isPresent() && Set.of("capsule","browser-assets","ssr-package").contains(v)));
            for (var binding : candidate.httpBindings()) require(id(binding.id()) && binding.generation() != 0 && Set.of("configured-current","deployment-changed").contains(binding.state()));
            for (var dependency : candidate.dependencies()) {
                require(id(dependency.capability()) && id(dependency.providerProfile()) && id(dependency.configurationDigest()) && hex(dependency.policyIdentityDigest()) && dependency.binding().isPresent() && dependency.policies().size() <= 32
                    && Set.of("configured-current","policy-changed-or-revoked","provider-unavailable","publication-unavailable","route-changed-or-unavailable","inspection-indeterminate").contains(dependency.state()));
                var binding = dependency.binding().orElseThrow();
                require(id(binding.id()) && id(binding.digest()));
                for (var revision : dependency.policies()) require(id(revision.id()) && id(revision.digest()));
            }
            var preparation = candidate.preparation().orElseThrow(Protocol.Invalid::new);
            require((request.includePreparation() ? preparation.state().value() != 4 : preparation.state().value() == 4) && preparation.imports().size() + preparation.typeImports().size() <= 64 && preparation.exports().size() <= 128);
            for (var text : List.of(preparation.engineVersion(),preparation.targetTriple(),preparation.cpuFeatureSet())) text.ifPresent(v -> require(id(v)));
            preparation.engineConfigurationDigest().ifPresent(v -> require(digest(v,"blake3:")));
            preparation.sealedMetadataFingerprint().ifPresent(v -> require(hex(v)));
            preparation.imports().forEach(v -> require(id(v)));
            preparation.typeImports().forEach(v -> require(id(v)));
            preparation.exports().forEach(v -> require(id(v.contract()) && id(v.function())));
            preparation.diagnostic().ifPresent(v -> { require(v.schemaVersion() == 1); v.profileDigest().ifPresent(d -> require(hex(d))); });
            if (preparation.state().value() == 1) require(preparation.profile().isPresent() && preparation.engineVersion().isPresent() && preparation.engineConfigurationDigest().isPresent() && preparation.targetTriple().isPresent()
                && preparation.cpuFeatureSet().isPresent() && preparation.declaredBudget().isPresent() && preparation.importCount().equals(Optional.of((long)(preparation.imports().size()+preparation.typeImports().size()))) && preparation.functionCount().equals(Optional.of((long)preparation.exports().size()))
                && preparation.hostcallFuel().isPresent() && preparation.maximumLiftedBytes().isPresent() && preparation.maximumTypeNodes().isPresent());
            if (candidate.eligible()) require(value.state().value() == 1 && candidate.exportCompatible() && candidate.publication().isPresent() && candidate.packageDigest().isPresent() && candidate.publicationGeneration().isPresent()
                && candidate.routingWeight() != 0 && candidate.reasons().size() == 1 && candidate.reasons().getFirst().value() == 1 && (preparation.state().value() == 1 || preparation.state().value() == 4)
                && candidate.dependencies().stream().allMatch(v -> v.state().equals("configured-current")));
        }
        value.selectedRevisionId().ifPresent(v -> require(request.routingKey().isPresent() && revisions.contains(v)));
    }
}
