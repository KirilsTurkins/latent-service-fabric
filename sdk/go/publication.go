package latent

// PublicationRef selects a publication in the authenticated tenant, never authority.
type PublicationRef struct {
	ID     string
	Tenant string
}

type PublicationIdentity struct {
	Publication     PublicationRef
	ComponentDigest string
	PackageDigest   string
}
