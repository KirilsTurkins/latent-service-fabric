// lsf-example-begin: capsule
package export_examples_http_status_api

import (
	wit "go.bytecodealliance.org/pkg/wit/types"
	http "wit_component/lsf/http"
)

func Check(url string) wit.Result[uint16, http.HttpError] {
	result := http.Send(http.Request{Method: http.MethodGet, Url: url,
		Headers: []http.Header{}, Body: wit.None[[]uint8](),
		BodyMediaType: wit.None[string](), IdempotencyKey: wit.None[string](),
		TimeoutMillis: wit.Some[uint64](4000)})
	if result.Tag() == wit.ResultErr {
		return wit.Err[uint16, http.HttpError](result.Err())
	}
	return wit.Ok[uint16, http.HttpError](result.Ok().Status)
}

// lsf-example-end: capsule
