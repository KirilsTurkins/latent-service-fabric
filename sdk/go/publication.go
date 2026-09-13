package latent

// PublicationRef selects a publication in the authenticated tenant, never authority.
type PublicationRef struct {
	ID     string
	Tenant string
}

// ReleaseSelector requires exactly one member. Preserve non-nil empty/invalid
// values for validation instead of silently choosing the other member.
type ReleaseSelector struct {
	ComponentDigest *string
	Publication     *PublicationRef
}

type PublicationIdentity struct {
	Publication     PublicationRef
	ComponentDigest string
	PackageDigest   string
}
