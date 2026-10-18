# Java dependency watch qualification

The [16 October 2026 evidence](evidence/java-dependency-watch-2026-10-16.json)
records actual signed Java components built with the delivered compiler and
controlled by the maintained source-bound frontend. The run used UID 1000,
Docker networking disabled, no checkout mount and `PATH=/nonexistent`.
The local compiler candidate and source node are explicitly unauthenticated.
This evidence does not establish a publisher-authenticated release installation.

An independently compiled local JAR calls a transitive local JAR and reads its
classpath resource. Normal `add-local`, `resolve`, `review-lock`, `dependencies`,
frontend build, Java `watch`, deployment and selected node tests produce
`42/SDK/captured watch resource`. Updating the transitive JAR produces `43`, and
removing both declarations plus their application use produces `removed/SDK`.
The original JARs, source and classes are absent during compilation. Update
resolution explicitly reselects the unchanged original primary JAR bytes, then
removes that file again before compilation.

Unreviewed edits fail without changing the last deployment. Reviewing a new
closure still requires explicit `dev trust`. Granting that trust retries the
current source without another edit. The original signed fixture then refuses
the changed build: fixture signing remains bound to one exact build. The
supported test workflow stops the node normally, selects a fresh `test-`
workspace and explicitly runs `prepare-test --consent-test-fixtures --admission
signed-fixture`. Its watcher deploys and tests only that newly signed build.
There are exactly three successful watcher deployments and three clean normal
shutdowns; all authoring watchers exit zero. No signing or admission guard is
relaxed and no uncertain deployment is retried.

Run the [qualifier](../../tools/qualify_java_dependency_watch.py) with the
delivered SDK Python in an isolated Linux host. Supply the exact verified local
compiler candidate, source helper, contributor source-node probe and ordinary
native source fixture explicitly:

```bash
"$JAVA_TOOLS/sdk/bin/python" -I -B tools/qualify_java_dependency_watch.py \
  --installed "$JAVA_TOOLS" \
  --helper "$HELPER" --helper-sha256 "$HELPER_SHA256" \
  --source-probe "$SOURCE_NODE_PROBE" --source-probe-sha256 "$SOURCE_NODE_PROBE_SHA256" \
  --source-node "$SOURCE_NODE" --output "$FRESH_OUTPUT"
```

The finite programme uses the maintained source-node staging function, normal
controller package/provenance completion and explicit short-lived test signing.
It retains commands, original failures and exact source hashes. It does not
create an authenticated installation receipt. Public/private Maven execution,
processor containment and runtime recovery retain their separate
[library ingestion delivery](https://github.com/KirilsTurkins/latent-service-fabric/pull/998) evidence.
