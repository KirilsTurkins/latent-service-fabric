package export_examples_go_standard_http_api

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
)

type delegatedTransport struct{ calls *uint32 }

func (transport delegatedTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	*transport.calls++
	return http.DefaultTransport.RoundTrip(request)
}

func tenantControl(which uint32, address string) string {
	client := &http.Client{}
	request, err := http.NewRequestWithContext(context.Background(), http.MethodGet, address, nil)
	if err != nil {
		return "request-error"
	}
	if which == 301 || which == 302 {
		ready := make(chan error, 1)
		go func() {
			response, openErr := client.Do(request)
			if openErr != nil {
				ready <- openErr
				return
			}
			defer response.Body.Close()
			ready <- nil
			_, _ = io.ReadAll(response.Body)
		}()
		if <-ready != nil {
			return "pending-open-error"
		}
		if which == 302 {
			panic("root-with-pending-http-body")
		}
		return "root-returned-with-pending-body"
	}
	var calls uint32
	client.Transport = delegatedTransport{calls: &calls}
	response, err := client.Do(request)
	if err != nil {
		return "delegated-transport-error:" + strconv.FormatUint(uint64(calls), 10)
	}
	defer response.Body.Close()
	var value domain
	if json.NewDecoder(response.Body).Decode(&value) != nil || response.StatusCode != 200 || value.ID != 7 {
		return "delegated-domain-error"
	}
	return "delegated:200:" + strconv.FormatUint(uint64(calls), 10) + ":" + value.Name
}
