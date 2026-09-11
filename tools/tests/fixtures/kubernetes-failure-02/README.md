Original client bytes from failed Kubernetes smoke02, source
`7a655e7967dbde1431f0ff8a5b928443a5986832`, owner `lsf-112-8c22b65b1529`.
The four client output files were downloaded after cleanup from
`smoke-02/failure-outputs/2`; the parent journals came from `smoke-02/clients/0`.

These are a failed-session regression fixture: 30 successful LSF offers followed
by a native connection failure, with no native Invoke. They are not a qualified
comparison. Full transport, build, resources and cleanup are replayed separately
from the retained failed campaign archive. No credential contents are included.
