# Release .NET and Jackson security backport

This source review covers 26 NuGet runtime findings and four Jackson findings
from the release SDK advisory report. It leaves the separate 26 Go standard
library findings for a qualified compiler upgrade.

The .NET host client selects SDK 8.0.426 and runtime 8.0.32 with runtime
roll-forward disabled. The three NuGet package locks are unchanged: the runtime
coordinates come from the projects' explicit RuntimeFrameworkVersion fields.
All seven generated Protobuf output hashes and existing package selections stay
bound to the release inputs. No development client/API expansion is included.

Both Java compiler configurations select Jackson 2.18.11. The three Jackson
JAR records and eight exact Gradle verification checksums use the existing
development selections, authenticated against Maven Central checksum metadata.
All other 67 Maven JAR records, TeaVM, Jetty and Java selections are unchanged.

The [data receipt](release-sdk-security-2026-10-19.json) lists the 30 original
findings, fixed versions, upstream identities and preserved source contracts.
Focused source controls and live advisory data do not qualify a native runtime.
The maintained clean .NET generation/restore/peer checks and locked Java
qualification must run on the combined release head before merge approval.

This branch starts at the current release without copying scanner exceptions.
After the separately reviewed policy and npm backports merge, rebase this leaf
onto that exact release and retain their changes when refreshing inventory and
CI identities. No release merge is authorized by this receipt.
