package main

import (
	"context"
	"encoding/json"
	"os"
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
	_ = json.NewEncoder(os.Stdout).Encode(map[string]string{"schemaVersion": "latent.sdk.provider.workflow.failure.v1", "language": "go", "stage": stage})
	os.Exit(1)
}
