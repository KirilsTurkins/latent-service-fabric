namespace Latent.Sdk;

/// <summary>Selects a publication within authenticated tenant scope, never authority.</summary>
/// <param name="Id">The canonical publication ID.</param>
/// <param name="Tenant">The authenticated tenant scope.</param>
public sealed record PublicationRef(string Id, string Tenant);

/// <summary>Exactly one member is valid. Preserve present empty/both for rejection.</summary>
/// <param name="ComponentDigest">The optional legacy component identity.</param>
/// <param name="Publication">The optional exact scoped selector.</param>
public sealed record ReleaseSelector(string? ComponentDigest = null, PublicationRef? Publication = null);

/// <summary>Distinct publication, executable and immutable package identities.</summary>
/// <param name="Publication">The scoped publication.</param>
/// <param name="ComponentDigest">The executable component bytes digest.</param>
/// <param name="PackageDigest">The complete immutable package digest.</param>
public sealed record PublicationIdentity(PublicationRef Publication, string ComponentDigest, string PackageDigest);
