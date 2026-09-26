source latent.fish
function latent
    echo 'unexpected latent callback' > unexpected-callback
    return 99
end

function assert_completion
    set -l expected $argv[1]
    set -l candidates (complete -C "$argv[2]" | string split -f 1 \t)
    if not contains -- "$expected" $candidates
        printf 'missing completion %s for [%s]\n' "$expected" "$argv[2]" >&2
        exit 1
    end
end

function reject_completion
    set -l candidates (complete -C "$argv[2]" | string split -f 1 \t)
    if contains -- "$argv[1]" $candidates
        printf 'unexpected completion %s for [%s]\n' "$argv[1]" "$argv[2]" >&2
        exit 1
    end
end

assert_completion completions 'latent comp'
assert_completion build 'latent package bu'
assert_completion build 'latent --quiet package bu'
assert_completion --connect-timeout-ms 'latent package build --connect'
assert_completion phase3 'latent invoke --budget-profile ph'
assert_completion provider-binding 'latent policy get --kind provider'
assert_completion rolled-back 'latent rollout list --state rolled'
assert_completion json 'latent package build --output j'
assert_completion powershell 'latent completions pow'
assert_completion powershell 'latent --quiet completions pow'
assert_completion powershell 'latent --profile local completions pow'
assert_completion powershell 'latent completions --profile=local pow'
assert_completion powershell 'latent completions -- pow'
reject_completion powershell 'latent completions fish pow'
reject_completion powershell 'latent --config completions pow'
reject_completion powershell 'latent completions --profile pow'
printf '{}\n' > 'sample capsule.json'
assert_completion 'sample capsule.json' 'latent --config sample'
printf 'fish completion smoke passed\n'
