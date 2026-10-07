#!/usr/bin/env bash
set -u
cd /source
rustc --version > /reports/rustc.txt
cargo --version > /reports/cargo.txt
sha256sum /reports/source.tar > /reports/source-archive.sha256
status=0
run_case() {
  local label="$1" package="$2" name="$3" result=0
  timeout --signal=TERM --kill-after=30s 900s cargo --config .cargo/managed-guest.toml test -p "$package" --lib --locked --offline "$name" -- --exact --nocapture --test-threads=1 > "/reports/$label.log" 2>&1 || result=$?
  printf '%s\n' "$result" > "/reports/$label.cargo-exit.txt"
  tail -n 20 "/reports/$label.log"
  if [ "$result" -eq 0 ]; then
    grep -q '^test result: ok\. 1 passed; 0 failed; 0 ignored;' "/reports/$label.log" || result=92
  fi
  printf '%s\n' "$result" > "/reports/$label.verified-exit.txt"
  if [ "$result" -ne 0 ]; then status=1; fi
}
run_case namespace-stage latent-capabilities namespace::tests::authority::intents::retained_staging_revocation_blocks_actual_commit_without_revoking_state_or_running_effect_fence
run_case native-policy latent-policy capability::store::tests::authority::publication::dispatch::explicit_native_dispatch_decision_keeps_current_source_policy_and_original_deadline
run_case missing-dispatch latent-effects runtime::tests::admission::missing_dispatch_authority_retains_policy_blocked_without_provider_admission_and_retires
result=0
timeout --signal=TERM --kill-after=30s 1200s cargo --config .cargo/managed-guest.toml check -p latentd --lib --all-features --locked --offline > /reports/app-check.log 2>&1 || result=$?
printf '%s\n' "$result" > /reports/app-check.exit.txt
tail -n 28 /reports/app-check.log
if [ "$result" -ne 0 ]; then status=1; fi
result=0
timeout --signal=TERM --kill-after=30s 1200s cargo --config .cargo/managed-guest.toml clippy -p latentd --lib --all-features --locked --offline --no-deps -- -D warnings > /reports/app-clippy.log 2>&1 || result=$?
printf '%s\n' "$result" > /reports/app-clippy.exit.txt
tail -n 40 /reports/app-clippy.log
if [ "$result" -ne 0 ]; then status=1; fi
printf '%s\n' "$status" > /reports/native-exit-code.txt
exit "$status"
