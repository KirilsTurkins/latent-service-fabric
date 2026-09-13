# Pinned CycloneDX validation schemas

These unmodified files are the offline authority for CycloneDX JSON 1.6 tests
and the observer's conservative SPDX declaration subset.
[SOURCES.json](SOURCES.json) records their upstream revision, URLs, byte counts
and SHA-256 hashes. [LICENSE](LICENSE) preserves the upstream Apache-2.0 license;
individual files retain their original notices.

The BOM schema references the included SPDX and JSON Signature Format schemas.
Tests register all three locally and reject attempts to retrieve other resources.
The narrower LSF profile excludes inline signatures and standalone SPDX ID
objects, but the full upstream reference closure stays available for validation.

The schemas are validation inputs, not benchmark reports or generated evidence.
Do not reformat them or update them silently. A deliberate version change must
update the pinned source manifest and rerun upstream/profile parity tests.

`spdx.schema.json` combines license and exception identifiers. The observer uses
[spdx-license-ids.json](spdx-license-ids.json), a derived list of 605 nondeprecated
license identifiers, to avoid accepting an exception as a standalone license.
[SPDX-DERIVATION.json](SPDX-DERIVATION.json) records its exact upstream
classification source, source/output hashes and filtering rule. Only identifier
facts are retained; no full license texts or legal conclusions are copied.
The list also intersects the nondeprecated vocabulary of pinned `spdx` 0.13.5;
for example, `Net-SNMP` became deprecated after SPDX 3.23 and is excluded.
Its narrower SPDX 3.23 vocabulary is deliberate. Unsupported declarations stay
unavailable in observer output; the Rust parser independently validates supported
received expressions using its pinned vocabulary.
