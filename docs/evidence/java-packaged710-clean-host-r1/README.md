# Original clean-host packaged Java attempt

This attempt failed before runtime installation or Java compilation. The
authenticated native frontend successfully negotiated `connect`; the source
conductor then required a backend workspace that the supported handshake does
not create. The installed helper creates that private workspace during
`install` or asset transfer. The corrected conductor validates the actual
private workspace and its original owner record only after installation.

The retained [observation](observation.json), [environment](environment.json)
and [process receipt](process.json) remain failed evidence. They do not prove
Java execution, live preflight, signing, grants, or a successful node campaign.
The original stderr is retained in [qualification.stderr.log](qualification.stderr.log).

The producer source is `761172002e4a4d02102f8c757235b888fe4859e1`; the independently
approved combined policy digest is
`ce36420661807326255232c0542f334045af5a637a157ad3c99b7e77328ffcba`.
The original conductor source is
`d39efecac856ad8e833479075318e461f8192008`. Authenticated prepared support came
from run `36829995045`, artifact `11158489692`. Its immutable inputs and the
four embedded preflight resources were preserved.

The disposable environment used Python 3.13.5, Ubuntu 24.04.5, glibc 2.39,
unprivileged UID 23001, two CPUs, 6 GiB memory and 512 PIDs. No guest SDK or
workspace existed before the attempt. Its native frontend, helper and runtime
were original approved publisher artifacts; no LSF native code was rebuilt.
The campaign was nonpublishing. Its original image and owned volumes remain
separate from compiler caches and other workers.

Two finite regression cases cover negotiation without an installed workspace
and rejection of missing or mismatched private owner records. The 24 original
packaged probe cases and their execution guards are unchanged. The 34 focused
Windows cases passed with three original platform skips; this unit result does
not replace the pending actual packaged campaign.
