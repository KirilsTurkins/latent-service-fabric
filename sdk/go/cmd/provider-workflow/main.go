package main

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"time"

	"latent.dev/sdk/go/internal/providerworkflow"
)

func main() {
	if len(os.Args) != 3 || os.Args[1] != "--config" {
		fail("participant-requires-config-file")
	}
	input, token, failure := providerworkflow.Load(os.Args[2])
	if failure != nil {
		fail(failure.Error())
	}
	ctx, cancel := context.WithTimeout(context.Background(), 80*time.Second)
	defer cancel()
	result, failure := providerworkflow.Run(ctx, input, token)
	if failure != nil {
		fail(failure.Error())
	}
	if json.NewEncoder(os.Stdout).Encode(result) != nil {
		os.Exit(1)
	}
}

func fail(stage string) {
	// These are fixed, local workflow labels. Match the shared harness's bounded
	// stderr contract so a failed assertion is not collapsed into "unavailable".
	_ = json.NewEncoder(os.Stderr).Encode(map[string]string{"stage": "go-participant", "reason": strings.ToLower(stage)})
	os.Exit(1)
}
