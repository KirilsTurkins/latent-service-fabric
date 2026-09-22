/* Shared with the executable C contract fixture. All borrowed bytes outlive use. */
static void publication_models(void) {
    latent_publication_identity original = {
        .publication = {.id = TEXT("publication:sha256:0000000000000000000000000000000000000000000000000000000000000000"), .tenant = TEXT("a")},
        .component_digest = TEXT("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
        .package_digest = TEXT("sha256:0000000000000000000000000000000000000000000000000000000000000000")
    };
    latent_publication_identity corrected = original;
    corrected.publication.id = TEXT("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111");
    corrected.package_digest = TEXT("sha256:1111111111111111111111111111111111111111111111111111111111111111");
    latent_publication_identity other = corrected;
    other.publication.tenant = TEXT("b");
    other.publication.id = TEXT("publication:sha256:2222222222222222222222222222222222222222222222222222222222222222");
    assert(memcmp(original.component_digest.data, other.component_digest.data, original.component_digest.length) == 0);
    assert(memcmp(original.package_digest.data, corrected.package_digest.data, original.package_digest.length) != 0);
    assert(memcmp(other.package_digest.data, corrected.package_digest.data, other.package_digest.length) == 0);
    latent_publication_ref invalid = {.id = TEXT(""), .tenant = TEXT("b")};
    assert(invalid.id.length == 0 && invalid.tenant.length == 1);
    latent_invocation_receipt unresolved = {.release_digest = original.component_digest, .route_generation = UINT64_MAX,
        .consumption = {.cpu_fuel = UINT64_MAX}};
    latent_invocation_receipt current = unresolved;
    current.has_publication_id = true;
    current.publication_id = corrected.publication.id;
    assert(!unresolved.has_publication_id && current.has_publication_id && current.publication_id.length == 83);
    assert(current.route_generation == UINT64_MAX && current.consumption.cpu_fuel == UINT64_MAX);
}
