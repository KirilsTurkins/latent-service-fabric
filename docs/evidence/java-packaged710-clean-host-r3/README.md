# Original four-build packaged attempt

The authenticated approved runtime and Java tool installation succeeded on the
clean disposable Ubuntu host. All four real Java components compiled through
the supported native frontend using its pinned TeaVM/C tool bundle. Their
original build receipts and distinct component/source identities are retained
in the [observation](observation.json) and [retention receipt](receipt.json).
These are new artifacts; they are not the earlier C4 components or native66.

The former-profile managed runtime then started. Preflight setup failed before
the delivered frontend schedule ran: the actual operator Client stores its
executable as a string, while the identity reader expected a `Path`. The
corrected schedule converts that existing path before the same bounded hash
and regular-file checks. The original [stderr](qualification.stderr.txt),
[environment](environment.json) and [process receipt](process.json) preserve
the failed 879.29-second attempt. The observed owned node shutdown was clean,
reaped, and all provider counters were zero.

Compiler log retention separately reported `DevError`; its producer code was
not included in the original observation. The stopped original containers and
build volume data subsequently became unavailable during user-confirmed
Docker maintenance. A read-only named-volume reader recreated empty volumes
after their original names were absent; those empty volumes are explicitly not
the original build data. The original host receipts had already been copied
and remain unchanged. Original component files and detailed compiler logs
cannot be recovered from this evidence, and no cause for the retention error
is inferred. The conductor now retains its finite producer-owned error code.
The original 128-file, 4 MiB per-file and 16 MiB aggregate log bounds remain.

This attempt does not qualify live preflight, HTTP execution, context, authority
changes, or the complete packaged campaign. No LSF native code was rebuilt.
The approved producer source remains
`761172002e4a4d02102f8c757235b888fe4859e1`, and the independently approved
combined policy digest remains
`ce36420661807326255232c0542f334045af5a637a157ad3c99b7e77328ffcba`.
The conductor source was `5cb1a74184f5b2f789c8d4b468d03d699c05fad4`.
Original authenticated support and image inputs are retained with the
[earlier attempt](../java-packaged710-clean-host-r1/README.md).

The 29 focused Windows packaged cases passed with three original platform
skips. New cases exercise the actual string operator API against real files
and the unchanged 128/129 log-count boundary. All 27 previous case guards and
fixture hashes are preserved. These source tests do not replace execution of
the pending corrected packaged schedule.
