package export_examples_go_standard_http_api

import (
	"bytes"
	"context"
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"strconv"
	"time"
)

type domain struct {
	ID int `json:"id"`
	Name string `json:"name"`
	Items []string `json:"items"`
	Empty string `json:"empty"`
}

type localTransport struct{}
var invocations uint32
func (localTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	return &http.Response{StatusCode:200, Header:make(http.Header),
		Body:io.NopCloser(bytes.NewBufferString(`{"id":7,"name":"café","items":["λ",""],"empty":""}`)), Request:request}, nil
}

func Run(which uint32, address string) string {
	invocations++
	if invocations != 1 { return "stale-state" }
	if which >= 25 { return valueRequest(which, address) }
	client := &http.Client{Timeout:time.Second}
	defer client.CloseIdleConnections()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	method := http.MethodGet
	var body io.Reader
	if which == 1 { method = http.MethodPost; body = bytes.NewReader([]byte{0,1,2,3}) }
	request, err := http.NewRequestWithContext(ctx, method, address, body)
	if err != nil { return "request-error" }
	if which == 1 { request.Header.Set("Content-Type", "application/octet-stream") }
	if which == 3 { request.Header.Set("Authorization", "must-not-leave-guest") }
	if which == 4 { var timeout context.CancelFunc; ctx, timeout = context.WithTimeout(ctx, 20*time.Millisecond); defer timeout(); request = request.WithContext(ctx) }
	if which == 6 { cancel() }
	if which == 7 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	if which == 8 { client.Transport = &http.Transport{DisableCompression:true} }
	if which == 9 { client.Transport = http.DefaultTransport.(*http.Transport).Clone() }
	if which == 10 { client.Transport = localTransport{} }
	dialed := false
	if which == 11 { client.Transport = &http.Transport{DisableCompression:true,
		DialContext:func(context.Context,string,string)(net.Conn,error){ dialed = true; return nil,errors.New("custom dialer invoked") }} }
	if which == 12 { client.Transport = &http.Transport{DisableCompression:true,DisableKeepAlives:true} }
	if which == 13 { client.Transport = &http.Transport{DisableCompression:true,MaxResponseHeaderBytes:-1} }
	if which == 14 { request.Close = true }
	if which == 15 { request.ContentLength = -2 }
	if which == 16 { request.ContentLength = 1 }
	if which == 17 { client.Transport = &http.Transport{DisableCompression:true,ResponseHeaderTimeout:time.Millisecond} }
	if which == 18 { client.Transport = &http.Transport{DisableCompression:true,MaxResponseHeaderBytes:1024} }
	if which == 19 { client.Transport = &http.Transport{DisableCompression:true,ReadBufferSize:4} }
	if which == 20 { client.Transport = &http.Transport{DisableCompression:true,WriteBufferSize:4} }
	if which == 22 { request.Header.Set("User-Agent", "") }
	if which == 23 { request.Header["User-Agent"] = []string{" fixture-agent/1 ", "must-not-be-sent"} }
	if which == 24 { request.Header["user-agent"] = []string{"noncanonical-field"} }
	response, err := client.Do(request)
	if which == 11 { if dialed { return "custom-dialer-invoked" }; if err == nil { response.Body.Close(); return "custom-dialer-accepted" }; return "custom-dialer-denied" }
	if err != nil { if ctx.Err() != nil { return "cancelled" }; return "transport-error" }
	defer response.Body.Close()
	if which == 2 { first := make([]byte,4); count, _ := io.ReadFull(response.Body, first); return "early:"+strconv.Itoa(count) }
	if which == 5 { go func(){ time.Sleep(20*time.Millisecond); cancel() }() }
	data, err := io.ReadAll(response.Body)
	if err != nil { if ctx.Err() != nil { return "cancelled" }; return "transport-error" }
	if which == 1 {
		var echo struct { Body string `json:"bodyBase64"`; Method string `json:"method"` }
		if json.Unmarshal(data, &echo) != nil || echo.Method != "POST" { return "invalid-json" }
		return strconv.Itoa(response.StatusCode)+":echo:"+echo.Body
	}
	if response.StatusCode >= 400 {
		var failure struct { Status int `json:"status"`; Message string `json:"message"` }
		if json.Unmarshal(data, &failure) != nil || failure.Status != response.StatusCode { return "invalid-json" }
		return strconv.Itoa(response.StatusCode)+":error:"+failure.Message
	}
	var value domain
	if err := json.Unmarshal(data, &value); err != nil {
		if ctx.Err() != nil { return "cancelled" }; return "invalid-json"
	}
	if value.ID != 7 || len(value.Items) != 2 || value.Empty != "" { return "invalid-domain" }
	return strconv.Itoa(response.StatusCode)+":domain:"+strconv.Itoa(value.ID)+":"+value.Name+":"+value.Items[0]+"|"+value.Items[1]
}

//go:embed values.json
var valueInputs []byte

type valueCase struct {
	ID string `json:"id"`
	Method string `json:"method"`
	Body string `json:"bodyBase64"`
	Length string `json:"length"`
	MediaType *string `json:"mediaType"`
	Header *string `json:"header"`
}

// A plain io.Reader keeps NewRequest's ordinary unknown-length path. A
// bytes.Reader instead selects its original known-length/NoBody behavior.
type valueReader struct { source *bytes.Reader }
func (reader *valueReader) Read(target []byte) (int, error) { return reader.source.Read(target) }

func valueRequest(which uint32, address string) string {
	var inputs struct { Profile string `json:"schemaVersion"`; Cases []valueCase `json:"cases"` }
	if json.Unmarshal(valueInputs, &inputs) != nil || inputs.Profile != "latent.standard-http.values.v1" ||
		len(inputs.Cases) > 9 || which < 25 || which-25 >= uint32(len(inputs.Cases)) { return "value-input-error" }
	selected := inputs.Cases[which-25]
	payload, err := base64.StdEncoding.DecodeString(selected.Body)
	if err != nil || len(payload) > 64 { return "value-input-error" }
	var body io.Reader = bytes.NewReader(payload)
	if selected.Length == "unknown" { body = &valueReader{source:bytes.NewReader(payload)}
	} else if selected.Length != "known" { return "value-input-error" }
	request, err := http.NewRequest(selected.Method, address, body)
	if err != nil { return "value-request-error" }
	if selected.MediaType != nil { request.Header.Set("Content-Type", *selected.MediaType) }
	if selected.Header != nil { request.Header.Set("X-Conformance", *selected.Header) }
	client := &http.Client{Timeout:time.Second}
	defer client.CloseIdleConnections()
	response, err := client.Do(request)
	if err != nil { return "value-transport-error" }
	defer response.Body.Close()
	data, err := io.ReadAll(response.Body)
	if err != nil { return "value-body-error" }
	if selected.Method == http.MethodHead {
		return "values-head:"+strconv.Itoa(response.StatusCode)+":"+strconv.FormatInt(response.ContentLength,10)+":"+strconv.Itoa(len(data))
	}
	if response.StatusCode != http.StatusOK { return "value-status-error" }
	return "values:"+string(data)
}
