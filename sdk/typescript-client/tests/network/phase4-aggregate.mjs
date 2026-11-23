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
