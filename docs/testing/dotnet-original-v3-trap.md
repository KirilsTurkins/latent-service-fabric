# Observe the original .NET v3 terminal traps

Issue #746 still needs the original causes of its unhandled-fault and opaque
quiescence outcomes. The successful normal v3 programme has fifteen recorded
outcomes, including those two expected guest traps. Its success does not explain
either trap or satisfy all of AC7.

`dotnet-original-trap.yml` is a nonqualifying observation restricted to the reviewed
`diag/dotnet-original-v3-trap-20261031` branch. A source push to that branch or an
explicit manual dispatch runs it; ordinary branches do not. It authenticates
the completed normal v3 archive from run 41191304300, artifact 13038749267, verifies
every admitted payload and CRC, and restores fourteen exact package inputs. WIT
bodies come from that same archive. The original component is 2,476,558 bytes,
SHA-256 `9c20e7025c9a2672ee256d93fb51efd631b609064953a11dc2491a94639552af`.
No guest, compiler, CoreLib or auxiliary package is rebuilt or rewritten.

Only the current `latent-wasmtime` library and `local_service` integration host
are built with the existing `development-test-host` feature. The existing numeric
observer control runs first. The new ignored integration control signs and admits
the original package in process, then invokes original modes 9 and 8 through two
separate backends. Each observer arms once. The request retains the original
1,000,000,000 fuel, 128 MiB memory and 120-second wall limit, four original grants,
and fixed 8/2/8/16/8/8/8 runtime-owner capacities.

Each observation contains at most sixteen numeric frames and no guest names,
messages, addresses, memory or exception contents. Missing, ambiguous or unexpected
observations fail the control. Host diagnostic I/O can perturb timing and terminal
observation. These results cannot qualify normal runtime behaviour. Logical idle
checks do not prove physical owner retirement or complete native accounting.

The programme retains its original 1,320-second absolute deadline, five-second
cleanup reserve, two build jobs, at most 128 commands, shared 16 MiB diagnostics,
and 128 MiB public artifact union. Source cleanliness, tool/executable identities,
the original archive and package inputs are checked after execution. All whole
ticket, AC7, original-cause, physical-retirement and native-accounting qualification
flags remain false; the existing fifteen-outcome receipt stays unchanged.
