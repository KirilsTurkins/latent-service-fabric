package providerworkflow

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"testing"
	"time"
)

func TestHeldDeadlinePrecedesMaintainedGuestTimeout(t *testing.T) {
	source, failure := os.ReadFile(filepath.Join("..", "..", "..", "..", "tools", "toolchain-smoke", "examples", "guest_http", "component.rs"))
	if failure != nil {
		t.Fatal(failure)
	}
	matched := regexp.MustCompile(`timeout_millis: Some\(([0-9]+)\)`).FindSubmatch(source)
	if len(matched) != 2 {
		t.Fatal("maintained guest HTTP deadline is missing or ambiguous")
	}
	milliseconds, failure := strconv.ParseInt(string(matched[1]), 10, 64)
	if failure != nil {
		t.Fatal(failure)
	}
	guestDeadline := time.Duration(milliseconds) * time.Millisecond
	if heldDeadlineBudget <= 0 || heldDeadlineBudget >= guestDeadline || guestDeadline >= heldWaitBudget || heldWaitBudget >= 3*time.Second {
		t.Fatal("activation deadline must precede guest HTTP timeout and bounded physical cleanup")
	}
}

func TestWaitMarkerEarlyRetirementFailsWithoutWaitingForTimeout(t *testing.T) {
	retired := make(chan struct{})
	close(retired)
	failure := waitMarker(context.Background(), filepath.Join(t.TempDir(), "missing"), retired)
	if !errors.Is(failure, errInvocationBeforeMarker) {
		t.Fatalf("want early invocation result, not a generic timeout: %v", failure)
	}
}

func TestWaitMarkerPublishedBeforeRetirementWins(t *testing.T) {
	path := filepath.Join(t.TempDir(), "started")
	if failure := os.WriteFile(path, []byte("observed\n"), 0o600); failure != nil {
		t.Fatal(failure)
	}
	retired := make(chan struct{})
	close(retired)
	if failure := waitMarker(context.Background(), path, retired); failure != nil {
		t.Fatalf("an observed request must not be mistaken for pre-dispatch failure: %v", failure)
	}
}

func TestWaitMarkerClosureRequiresPhysicalMarker(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	failure := waitMarker(ctx, filepath.Join(t.TempDir(), "closed"), nil)
	if failure == nil || failure.Error() != "participant-private-rendezvous-timeout" {
		t.Fatalf("missing physical closure must not pass: %v", failure)
	}
}

func TestWaitMarkerAcceptsDelayedPhysicalClosure(t *testing.T) {
	path := filepath.Join(t.TempDir(), "closed")
	written := make(chan error, 1)
	go func() {
		time.Sleep(10 * time.Millisecond)
		written <- os.WriteFile(path, []byte("observed\n"), 0o600)
	}()
	failure := waitMarker(context.Background(), path, nil)
	if writeFailure := <-written; writeFailure != nil {
		t.Fatal(writeFailure)
	}
	if failure != nil {
		t.Fatal(failure)
	}
}

func TestPrivateMarkerRejectsInvalidFiles(t *testing.T) {
	directory := t.TempDir()
	regular := filepath.Join(directory, "regular")
	oversized := filepath.Join(directory, "oversized")
	link := filepath.Join(directory, "link")
	for path, size := range map[string]int{regular: 64, oversized: 65} {
		if failure := os.WriteFile(path, make([]byte, size), 0o600); failure != nil {
			t.Fatal(failure)
		}
	}
	if failure := os.Symlink(regular, link); failure != nil {
		t.Fatal(failure)
	}
	for _, path := range []string{directory, oversized, link} {
		if present, failure := privateMarker(path); present || failure == nil || failure.Error() != "participant-invalid-private-rendezvous" {
			t.Fatalf("invalid marker %q accepted: %v, %v", path, present, failure)
		}
	}
	if present, failure := privateMarker(regular); !present || failure != nil {
		t.Fatalf("bounded regular marker rejected: %v", failure)
	}
	if present, failure := privateMarker(filepath.Join(directory, "missing")); present || failure != nil {
		t.Fatalf("absent marker treated as observation: %v, %v", present, failure)
	}
	if present, failure := privateMarker(filepath.Join(regular, "child")); present || failure == nil || failure.Error() != "participant-private-rendezvous-read-failed" {
		t.Fatalf("read error was hidden: %v, %v", present, failure)
	}
}
