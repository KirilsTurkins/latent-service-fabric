package export_tests_metrics_api

import (
	wit "go.bytecodealliance.org/pkg/wit/types"
	metrics "wit_component/lsf/metrics"
)

func Run(which uint32, name string, _ uint64) uint64 {
	if which > 3 {
		which = 3
	}
	r := metrics.EmitMetric(metrics.Metric{Name: name, Kind: uint8(which), Value: 2.0,
		Unit: "1", Attributes: []wit.Tuple2[string, string]{{F0: "region", F1: "east"}}})
	if r.IsOk() {
		if r.Ok() {
			return 1
		}
		return 0
	}
	switch r.Err().Tag() {
	case metrics.TelemetryErrorInvalidName:
		return 10
	case metrics.TelemetryErrorBudgetExhausted:
		return 11
	case metrics.TelemetryErrorUnavailable:
		return 12
	default:
		panic("unknown metric error")
	}
}
