"""Explicit finite declarations for the installed version-2 state owners."""
from pathlib import Path


def declaration(checkpoint_root: Path) -> dict:
    return {
        "formatVersion": 2, "createIfMissing": True, "configurationEpoch": 1,
        "storeIdentity": "java-transaction-qualification", "checkpointRoot": str(checkpoint_root),
        "startupTimeoutMillis": 5000,
        "store": {
            "maximumFileBytes": 268435456, "cacheBytes": 8388608, "maximumRows": 16384,
            "maximumLogicalBytes": 33554432, "maximumReadViews": 8, "maximumViewAgeMillis": 30000,
            "ordinary": {"workers": 3, "queuedJobs": 8, "acceptedJobs": 32, "activeReads": 2,
                         "retainedBytes": 117440512, "maximumJobBytes": 41943040},
            "recovery": {"workers": 1, "queuedJobs": 4, "acceptedJobs": 8,
                         "retainedBytes": 16777216, "maximumJobBytes": 8396800},
        },
        "native": {
            "ordinary": {"slots": 128, "bytes": 268435456, "maximumReservationBytes": 67108864},
            "recovery": {"slots": 8, "bytes": 100663296, "maximumReservationBytes": 33554432},
            "maximumLifetimeMillis": 180000,
        },
        "dispatcher": {"workers": 2, "queuedJobs": 4, "acceptedJobs": 16,
                       "maximumCommandOwners": 128, "perTenantJobs": 1, "retainedBytes": 83886080,
                       "pageRows": 16, "pageBytes": 1048576, "scanPagesPerTick": 4,
                       "pollIntervalMillis": 100},
        "operations": [],
    }
