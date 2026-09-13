package latent_test

import (
	"fmt"
	latent "latent.dev/sdk/go"
	"testing"
)

func TestPublicationCoexistenceAndPresence(t *testing.T) {
	component := "sha256:" + fmt.Sprintf("%064x", 10)
	rows := make([]latent.PublicationIdentity, 4)
	ids := make(map[string]bool)
	for i := range rows {
		tenant := "a"
		if i >= 2 {
			tenant = "b"
		}
		rows[i] = latent.PublicationIdentity{Publication: latent.PublicationRef{
			ID: fmt.Sprintf("publication:sha256:%064x", i), Tenant: tenant},
			ComponentDigest: component, PackageDigest: fmt.Sprintf("sha256:%064x", i%2)}
		ids[rows[i].Publication.ID] = true
	}
	if len(ids) != 4 || rows[0].ComponentDigest != rows[3].ComponentDigest ||
		rows[0].PackageDigest != rows[2].PackageDigest || rows[0].PackageDigest == rows[1].PackageDigest {
		t.Fatal("publication, tenant, component and package identities must remain distinct")
	}
	empty := ""
	invalid := latent.ReleaseSelector{ComponentDigest: &empty, Publication: &latent.PublicationRef{ID: "", Tenant: "b"}}
	if invalid.ComponentDigest == nil || invalid.Publication == nil || *invalid.ComponentDigest != "" {
		t.Fatal("present invalid selection must not be normalized")
	}
	legacy := latent.InvocationReceipt{ReleaseDigest: component, RouteGeneration: ^uint64(0),
		Consumption: latent.BudgetConsumption{CPUFuel: ^uint64(0)}}
	current := legacy
	current.PublicationID = &rows[1].Publication.ID
	if legacy.PublicationID != nil || *current.PublicationID != rows[1].Publication.ID ||
		current.ReleaseDigest != component || current.RouteGeneration != ^uint64(0) || current.Consumption.CPUFuel != ^uint64(0) {
		t.Fatal("receipt must preserve presence, component meaning and uint64 values")
	}
}
