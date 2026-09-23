package export_tests_caller_api

import (
	wit "go.bytecodealliance.org/pkg/wit/types"
	service "wit_component/lsf/service"
)

func Run(which uint32, _ string, _ uint64) uint64 {
	function := "spin"
	if which == 0 {
		function = "answer"
	}
	if which == 1 {
		function = "fail"
	}
	outcome := service.Call(service.Target{Tenant: wit.None[string](), Service: "callee",
		Contract: "tests:local/api@1.0.0", Function: function, Route: wit.Some("callee")}, []byte("[]"),
		"application/vnd.latent.wit-values.v1+json", service.CallOptions{DeadlineUnixMillis: wit.None[uint64](),
			Priority: 0, IdempotencyKey: wit.None[string](), Metadata: []wit.Tuple2[string, string]{}})
	switch outcome.Tag() {
	case service.InvocationOutcomeSuccess:
		if string(outcome.Success().Payload) != "[42]" {
			panic("child output changed")
		}
		return 42
	case service.InvocationOutcomeDeclaredError:
		if len(outcome.DeclaredError().Payload) == 0 {
			panic("missing declared error")
		}
		return 10
	case service.InvocationOutcomePlatformFailure:
		switch outcome.PlatformFailure().Code {
		case service.PlatformErrorCodePermissionDenied:
			return 11
		case service.PlatformErrorCodeCancelled:
			return 12
		case service.PlatformErrorCodeDeadlineExceeded:
			return 13
		case service.PlatformErrorCodeResourceExhausted:
			return 14
		}
	}
	panic("unexpected child outcome")
}
