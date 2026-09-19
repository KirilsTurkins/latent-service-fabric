package providerworkflow

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
)

type Target struct {
	Service         string `json:"service"`
	Route           string `json:"route"`
	Contract        string `json:"contract"`
	Function        string `json:"function"`
	Publication     string `json:"publication"`
	ComponentDigest string `json:"componentDigest"`
}

type Input struct {
	SchemaVersion    string            `json:"schemaVersion"`
	Language         string            `json:"language"`
	Endpoint         string            `json:"endpoint"`
	Tenant           string            `json:"tenant"`
	CredentialFile   string            `json:"credentialFile"`
	ControlDirectory string            `json:"controlDirectory"`
	UpstreamURL      string            `json:"upstreamUrl"`
	PolicyDocument   string            `json:"policyDocument"`
	Targets          map[string]Target `json:"targets"`
}

func Load(path string) (Input, string, error) {
	var input Input
	if runtime.GOOS != "linux" || !filepath.IsAbs(path) {
		return input, "", errors.New("participant-requires-linux-and-absolute-config")
	}
	data, failure := readProtected(path, 32768, false)
	if failure != nil || decodeJSON(data, &input) != nil {
		return input, "", errors.New("participant-invalid-protected-input")
	}
	if input.SchemaVersion != "latent.sdk.provider.workflow.input.v1" || input.Language != "go" || input.Tenant != "tests" ||
		len(input.Targets) != 3 || len(input.PolicyDocument) > 16384 || !filepath.IsAbs(input.ControlDirectory) {
		return input, "", errors.New("participant-invalid-input-profile")
	}
	for _, name := range []string{"http", "blob", "callee"} {
		target, present := input.Targets[name]
		if !present || target.Service == "" || target.Route == "" || target.Contract == "" || target.Function == "" || target.Publication == "" || target.ComponentDigest == "" {
			return input, "", errors.New("participant-missing-exact-target")
		}
	}
	origin, failure := url.Parse(input.UpstreamURL)
	if failure != nil {
		return input, "", errors.New("participant-invalid-fixture-upstream")
	}
	port, failure := strconv.ParseUint(origin.Port(), 10, 16)
	if failure != nil || port == 0 || input.UpstreamURL != "http://localhost:"+strconv.FormatUint(port, 10)+"/allowed" {
		return input, "", errors.New("participant-invalid-fixture-upstream")
	}
	control, failure := os.Lstat(input.ControlDirectory)
	if failure != nil || !control.IsDir() || control.Mode().Perm() != 0700 {
		return input, "", errors.New("participant-control-directory-not-private")
	}
	var policy struct {
		FormatVersion int               `json:"formatVersion"`
		Tenant        string            `json:"tenant"`
		Rules         []json.RawMessage `json:"rules"`
	}
	if decodeJSON([]byte(input.PolicyDocument), &policy) != nil || policy.FormatVersion != 1 || policy.Tenant != input.Tenant || policy.Rules == nil || len(policy.Rules) != 0 {
		return input, "", errors.New("participant-policy-must-grant-no-authority")
	}
	token, failure := readProtected(input.CredentialFile, 512, true)
	if failure != nil || len(token) == 0 {
		return input, "", errors.New("participant-invalid-protected-credential")
	}
	return input, string(token), nil
}

func readProtected(path string, maximum int64, credential bool) ([]byte, error) {
	if !filepath.IsAbs(path) {
		return nil, errors.New("absolute-input-path-required")
	}
	parent, failure := os.Lstat(filepath.Dir(path))
	if failure != nil || !parent.IsDir() || parent.Mode().Perm() != 0700 {
		return nil, errors.New("private-input-directory-required")
	}
	before, failure := os.Lstat(path)
	if failure != nil || !before.Mode().IsRegular() || before.Size() > maximum || (credential && before.Mode().Perm() != 0600) {
		return nil, errors.New("invalid-protected-input-file")
	}
	file, failure := os.Open(path)
	if failure != nil {
		return nil, errors.New("protected-input-open-failed")
	}
	defer file.Close()
	opened, failure := file.Stat()
	if failure != nil || !os.SameFile(before, opened) || opened.Mode() != before.Mode() {
		return nil, errors.New("protected-input-changed")
	}
	data, failure := io.ReadAll(io.LimitReader(file, maximum+1))
	if failure != nil || int64(len(data)) > maximum {
		return nil, errors.New("protected-input-exceeds-bound")
	}
	return data, nil
}

func decodeJSON(data []byte, target any) error {
	structure := json.NewDecoder(bytes.NewReader(data))
	structure.UseNumber()
	remaining := 2048
	if uniqueJSON(structure, 0, &remaining) != nil {
		return errors.New("invalid-closed-json-input")
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if failure := decoder.Decode(target); failure != nil {
		return errors.New("invalid-closed-json-input")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return errors.New("trailing-json-input")
	}
	return nil
}

func uniqueJSON(decoder *json.Decoder, depth int, remaining *int) error {
	*remaining--
	if depth > 16 || *remaining < 0 {
		return errors.New("json-structure-exceeds-bound")
	}
	value, failure := decoder.Token()
	if failure != nil {
		return failure
	}
	delimiter, container := value.(json.Delim)
	if !container {
		return nil
	}
	if delimiter != '{' && delimiter != '[' {
		return errors.New("invalid-json-container")
	}
	keys := make(map[string]bool)
	for decoder.More() {
		if delimiter == '{' {
			key, failure := decoder.Token()
			if failure != nil {
				return failure
			}
			name, valid := key.(string)
			if !valid || keys[name] {
				return errors.New("duplicate-json-field")
			}
			keys[name] = true
		}
		if failure := uniqueJSON(decoder, depth+1, remaining); failure != nil {
			return failure
		}
	}
	_, failure = decoder.Token()
	return failure
}
