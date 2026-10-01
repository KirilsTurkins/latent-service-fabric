/* Private descriptor views; preparation data supplies no authority or proof. */
static void effect_version(tx_validator *v, tx_value value) {
    bytes(v, value, 32, true);
    latent_bytes input = data(value);
    bool nonzero = false;
    if (input.length == 32 && input.data != NULL)
        for (size_t index = 0; index < input.length; ++index) nonzero |= input.data[index] != 0;
    check(v, input.length == 32 && nonzero);
}

static void effect_mutation(tx_validator *v, tx_value value) {
    tx_value target = field(value, "effect"); lookup(v, target);
    latent_string effect_id = text(field(target, "effect_id"));
    bool canonical = effect_id.length == 64 && effect_id.data != NULL;
    if (canonical) for (size_t index = 0; index < 64; ++index)
        canonical &= (effect_id.data[index] >= '0' && effect_id.data[index] <= '9')
            || (effect_id.data[index] >= 'a' && effect_id.data[index] <= 'f');
    check(v, canonical); id(v, field(value, "operation_id")); effect_version(v, field(value, "expected_version"));
    digest(v, field(value, "expected_policy_digest")); string_value(v, field(value, "reason"), 1024, true, true);
    int32_t action = enumeration(v, field(value, "mutation"), 5, "state.mutation");
    uint64_t delay = number(field(value, "retry_delay_millis"));
    check(v, action == 1 ? delay >= 1 && delay <= 60000 : (action == 2 || action == 5) && delay == 0);
}

static void effect_plan(tx_validator *v, tx_value value) {
    tx_value original = field(value, "original"); effect_mutation(v, original); effect_version(v, field(value, "plan_digest"));
    uint64_t slot = number(field(value, "management_sequence")), owner = number(field(value, "owner_epoch"));
    uint64_t claim = number(field(value, "claim_generation")), attempt = number(field(value, "dispatch_attempt"));
    uint64_t prepared = number(field(value, "prepared_at_unix_millis")), expires = number(field(value, "expires_at_unix_millis"));
    bool attempted = owner != 0 && claim != 0 && attempt != 0;
    check(v, slot >= 1 && slot <= 128 && attempt <= 128
        && (attempted || (owner == 0 && claim == 0 && attempt == 0))
        && prepared != 0 && expires > prepared && expires - prepared <= 30000);
    int32_t before = enumeration(v, field(value, "before"), 10, "effect.disposition");
    int32_t safety = enumeration(v, field(value, "safety"), 4, "effect.plan.safety");
    int32_t action = enumeration(v, field(original, "mutation"), 5, "state.mutation");
    check(v, (action == 1 && attempted && ((safety == 1 && before == 4) || (safety == 2 && (before == 4 || before == 5))))
        || (action == 5 && attempted && safety == 3 && (before == 4 || before == 5))
        || (action == 2 && safety == 4 && (before == 1 || before == 4 || before == 5 || before == 7 || before == 9)));
    tx_value dedup = field(value, "dedup_valid_until_unix_millis");
    check(v, (safety == 2) == has(dedup));
    if (has(dedup)) check(v, number(dedup) > expires);
    /* Historical receipt decoding never compares expiry with the current clock. */
}

static void effect_plan_association(tx_validator *v, tx_value value, tx_value plan, bool recovery) {
    effect_plan(v, plan);
    tx_value original = field(plan, "original"), target = field(original, "effect"), current = field(value, "namespace");
    check(v, equal(field(current, "namespace"), field(field(target, "command"), "namespace"))
        && equal(field(current, "profile"), field(target, "profile"))
        && equal(field(value, "operation_id"), field(original, "operation_id")));
    if (!recovery) {
        check(v, equal(field(current, "authorization_publication"), field(target, "authorization_publication"))
            && equal(field(value, "record_id"), field(target, "effect_id")));
        const char *names[] = {"mutation", "expected_version", "expected_policy_digest", "reason"};
        for (size_t index = 0; index < sizeof(names) / sizeof(names[0]); ++index)
            check(v, equal(field(value, names[index]), field(original, names[index])));
    }
}

static void effect_plan_receipt(tx_validator *v, tx_value value, tx_value expected) {
    tx_value details = field(value, "effect"), plan = field(details, "original_plan"), original = field(plan, "original");
    effect_plan(v, plan);
    check(v, equal(plan, expected) && equal(field(details, "before"), field(plan, "before"))
        && equal(field(value, "mutation"), field(original, "mutation"))
        && equal(field(value, "operation_id"), field(original, "operation_id"))
        && equal(field(value, "record_id"), field(field(original, "effect"), "effect_id"))
        && equal(field(value, "before_version"), field(original, "expected_version"))
        && equal(field(value, "policy_digest"), field(original, "expected_policy_digest")));
    effect_version(v, field(value, "before_version")); effect_version(v, field(value, "after_version"));
    uint64_t completed = number(field(value, "completed_at_unix_millis"));
    check(v, enumeration(v, field(value, "disposition"), 5, "state.disposition") == 1
        && completed >= number(field(plan, "prepared_at_unix_millis")) && completed < number(field(plan, "expires_at_unix_millis")));
    int32_t fact = enumeration(v, field(details, "fact"), 3, "effect.management.fact");
    int32_t action = enumeration(v, field(original, "mutation"), 5, "state.mutation");
    int32_t after = enumeration(v, field(details, "after"), 10, "effect.disposition");
    check(v, (fact == 1 && action == 1 && after == 9) || (fact == 2 && action == 5 && after == 3)
        || (fact == 3 && action == 2 && (after == 8 || after == 10)));
    tx_value provider = field(details, "provider_receipt"), observed = field(details, "provider_observed_at_unix_millis");
    check(v, (fact == 2) == has(provider) && has(provider) == has(observed));
    optional_id(v, provider);
    if (has(observed)) check(v, number(observed) != 0 && number(observed) <= completed);
}
