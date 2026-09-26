package providerworkflow

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"latent.dev/sdk/go/profile"
)

const exampleToken = "LSF-GO-PROTECTED-INPUT-TEST-ONLY"

func protectedInput(test *testing.T) (Input, string) {
	test.Helper()
	if runtime.GOOS != "linux" {
		test.Skip("the shared separate-node participant requires Linux file permissions")
	}
	root := test.TempDir()
	if failure := os.Chmod(root, 0700); failure != nil {
		test.Fatal(failure)
	}
	input := Input{SchemaVersion: "latent.sdk.provider.workflow.input.v1", Language: "go", Tenant: "tests",
		Endpoint: "http://127.0.0.1:12345", CredentialFile: filepath.Join(root, "credential"), ControlDirectory: filepath.Join(root, "control"),
		UpstreamURL: "http://localhost:12346/allowed", PolicyDocument: `{"formatVersion":1,"tenant":"tests","rules":[]}`, Targets: make(map[string]Target)}
	for _, name := range []string{"http", "blob", "callee"} {
		input.Targets[name] = Target{Service: name, Route: name + "-route", Contract: "tests:local/api@1.0.0", Function: "run",
			Publication: "publication:sha256:" + strings.Repeat("a", 64), ComponentDigest: "sha256:" + strings.Repeat("b", 64)}
	}
	if failure := os.Mkdir(input.ControlDirectory, 0700); failure != nil {
		test.Fatal(failure)
	}
	if failure := os.WriteFile(input.CredentialFile, []byte(exampleToken), 0600); failure != nil {
		test.Fatal(failure)
	}
	path := filepath.Join(root, "input.json")
	writeInput(test, path, input)
	return input, path
}

func writeInput(test *testing.T, path string, input Input) {
	test.Helper()
	data, failure := json.Marshal(input)
	if failure != nil {
		test.Fatal(failure)
	}
	if failure = os.WriteFile(path, data, 0600); failure != nil {
		test.Fatal(failure)
	}
}

func TestProtectedInputAndFiniteGuestValues(test *testing.T) {
	input, path := protectedInput(test)
	loaded, token, failure := Load(path)
	if failure != nil || token != exampleToken || loaded.Targets["http"] != input.Targets["http"] {
		test.Fatal("protected fixture input did not load")
	}
	owner := &workflow{input: loaded}
	for _, name := range []string{"http", "blob", "callee"} {
		request := owner.request(name, "go-native-test")
		if request.ActivationId == nil || *request.ActivationId != "go-native-test" || request.RootActivationId != nil || request.ParentActivationId != nil ||
			request.Target.Tenant != "tests" || request.Budget == nil || request.Budget.WallTimeLimitMillis == nil || *request.Budget.WallTimeLimitMillis > 5000 || request.MediaType != mediaType {
			test.Fatal("native request changed scope, authority or budgets")
		}
		var expected string
		switch name {
		case "http":
			expected = `[0,"http://localhost:12346/allowed","0"]`
		case "blob":
			expected = `[0,"","0"]`
			if request.Budget.BlobReadBytes != 65536 || request.Budget.BlobWriteBytes != 65536 {
				test.Fatal("blob example escaped the guest budget")
			}
		case "callee":
			expected = `[]`
		}
		if string(request.Payload) != expected {
			test.Fatalf("native WIT values were reinterpreted for %s", name)
		}
	}
	value := profile.InvokeResponse{Success: &profile.Success{MediaType: mediaType, Payload: []byte(`["18446744073709551615"]`)}}
	if !u64Result(value, math.MaxUint64) {
		test.Fatal("WIT u64 result lost precision")
	}
	for _, invalid := range []string{`[18446744073709551615]`, `["18446744073709551616"]`, `["01"]`, `["1","2"]`} {
		value.Success.Payload = []byte(invalid)
		if u64Result(value, 1) {
			test.Fatal("noncanonical WIT result accepted")
		}
	}
}

func TestProtectedInputRejectsUnsafeFilesAndAuthority(test *testing.T) {
	cases := []struct {
		name   string
		change func(*testing.T, *Input, string)
	}{
		{"credential-readable", func(test *testing.T, input *Input, path string) { checked(test, os.Chmod(input.CredentialFile, 0644)) }},
		{"credential-symlink", func(test *testing.T, input *Input, path string) {
			link := filepath.Join(filepath.Dir(path), "credential-link")
			checked(test, os.Symlink(input.CredentialFile, link))
			input.CredentialFile = link
		}},
		{"credential-oversized", func(test *testing.T, input *Input, path string) {
			checked(test, os.WriteFile(input.CredentialFile, []byte(strings.Repeat("a", 513)), 0600))
		}},
		{"control-public", func(test *testing.T, input *Input, path string) {
			checked(test, os.Chmod(input.ControlDirectory, 0755))
		}},
		{"wrong-tenant", func(test *testing.T, input *Input, path string) { input.Tenant = "another" }},
		{"remote-upstream", func(test *testing.T, input *Input, path string) {
			input.UpstreamURL = "http://example.com:12346/allowed"
		}},
		{"encoded-upstream", func(test *testing.T, input *Input, path string) {
			input.UpstreamURL = "http://localhost:12346/%61llowed"
		}},
		{"policy-rule", func(test *testing.T, input *Input, path string) {
			input.PolicyDocument = `{"formatVersion":1,"tenant":"tests","rules":[{}]}`
		}},
		{"policy-duplicate", func(test *testing.T, input *Input, path string) {
			input.PolicyDocument = `{"formatVersion":1,"tenant":"tests","rules":[{}],"rules":[]}`
		}},
		{"missing-publication", func(test *testing.T, input *Input, path string) {
			target := input.Targets["http"]
			target.Publication = ""
			input.Targets["http"] = target
		}},
	}
	for _, scenario := range cases {
		test.Run(scenario.name, func(test *testing.T) {
			input, path := protectedInput(test)
			scenario.change(test, &input, path)
			writeInput(test, path, input)
			_, token, failure := Load(path)
			if failure == nil || token != "" || strings.Contains(failure.Error(), exampleToken) || strings.Contains(failure.Error(), path) {
				test.Fatal("unsafe protected input accepted or echoed")
			}
		})
	}
}

func TestClosedJSONAndCurrentAuditAbsence(test *testing.T) {
	for _, data := range []string{`{"language":"go","unknown":true}`, `{"language":"go","language":"rust"}`, `{"language":"go"} {}`, strings.Repeat("[", 18) + strings.Repeat("]", 18)} {
		var input Input
		if decodeJSON([]byte(data), &input) == nil {
			test.Fatal("open or oversized JSON structure accepted")
		}
	}
	owner := &workflow{}
	owner.observe(profile.ResponseMetadata{})
	if owner.auditSeen {
		test.Fatal("absence was converted into an audit acknowledgement")
	}
	for _, metadata := range []profile.ResponseMetadata{
		{AuditAck: &profile.AuditAck{Status: profile.AuditAckStatusDurable}},
		{AuditStatus: reference("future-state")},
		{AuditAttemptSequence: reference(uint64(0))},
	} {
		owner.auditSeen = false
		owner.observe(metadata)
		if !owner.auditSeen {
			test.Fatal("current-node assertion ignored a present audit fact")
		}
	}
	data, failure := json.Marshal(Result{})
	if failure != nil || !strings.Contains(string(data), `"auditAttempt":null`) {
		test.Fatal("result fabricates an audit attempt")
	}
}

func TestRendezvousPublishesAtomically(test *testing.T) {
	input, _ := protectedInput(test)
	owner := &workflow{input: input}
	for _, mode := range []string{"hold-go-local-cancel", "reply"} {
		checked(test, owner.mode(mode))
		data, failure := os.ReadFile(filepath.Join(input.ControlDirectory, "mode"))
		if failure != nil || string(data) != mode {
			test.Fatal("rendezvous did not publish the complete mode")
		}
		entries, failure := os.ReadDir(input.ControlDirectory)
		if failure != nil || len(entries) != 1 || entries[0].Name() != "mode" {
			test.Fatal("rendezvous temporary owner leaked")
		}
	}
}

func checked(test *testing.T, failure error) {
	test.Helper()
	if failure != nil {
		test.Fatal(failure)
	}
}
