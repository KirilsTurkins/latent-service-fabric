export function aggregateTarget(tenant, operation) {
  const commandRoute = process.env.LSF_401_AGGREGATE_ROUTE ?? "transaction-java-aggregate";
  const route = operation === "query" ? process.env.LSF_401_AGGREGATE_QUERY_ROUTE ?? commandRoute : commandRoute;
  return {
    tenant,
    service: process.env.LSF_401_AGGREGATE_SERVICE ?? "examples/transaction-java-aggregate",
    contract: "examples:transactional-aggregate/api@1.0.0",
    function: operation,
    route,
  };
}

export function fixtureWallLimitMillis() {
  const value = process.env.LSF_401_WALL_TIME_MILLIS;
  if (value === undefined) return 120000n;
  if (!/^[1-9][0-9]{0,5}$/.test(value) || BigInt(value) > 120000n) {
    throw new RangeError("invalid fixture wall-time limit");
  }
  return BigInt(value);
}
