"""Scaled checkpoint-prefix benchmark at expected 42-day journal size."""
from __future__ import annotations

import json
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from predictive_vnext4r71.checkpoint import (
    event_files,
    git_prefix_binding,
    prefix_file_digest,
)


def pct95(values):
    x=sorted(values)
    return x[min(len(x)-1,int(0.95*(len(x)-1)))]


def run(n=12098, repeats=5):
    with tempfile.TemporaryDirectory(prefix="r71-scale-") as td:
        root=Path(td)
        subprocess.run(["git","init"],cwd=root,check=True,capture_output=True)
        subprocess.run(["git","config","user.email","scale@example.com"],cwd=root,check=True)
        subprocess.run(["git","config","user.name","scale"],cwd=root,check=True)
        d=root/"events"; d.mkdir()
        bundle_payload=(b'{"verificationMaterial":{"tlogEntries":[]},'
                        b'"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}')
        bundle_payload=bundle_payload+b" "*max(0,4096-len(bundle_payload))
        for i in range(1,n+1):
            event=(f'{{"sequence":{i},"payload":"'+("x"*512)+'"}\n').encode()
            p=d/f"{i:08d}.json"
            p.write_bytes(event)
            p.with_suffix(".sigstore.json").write_bytes(bundle_payload)
        subprocess.run(["git","add","."],cwd=root,check=True,capture_output=True)
        subprocess.run(["git","commit","-m","scaled prefix"],cwd=root,check=True,capture_output=True)
        commit=subprocess.run(
            ["git","rev-parse","HEAD"],cwd=root,check=True,
            capture_output=True,text=True
        ).stdout.strip()
        files=event_files(d)

        archive_times=[]
        local_times=[]
        expected=None
        for _ in range(repeats):
            t=time.perf_counter()
            binding=git_prefix_binding(root,d,commit,n)
            archive_times.append(time.perf_counter()-t)
            t=time.perf_counter()
            local=prefix_file_digest(files,n)
            local_times.append(time.perf_counter()-t)
            if binding["verified_commit_prefix_files_sha256"]!=local:
                raise RuntimeError("scaled commit/local prefix mismatch")
            expected=local

        out={
            "schema":"btc-predictive-vnext4r71-checkpoint-scale-benchmark-v1",
            "events":n,
            "event_plus_bundle_files":2*n,
            "approx_payload_mb":(n*(512+4096))/(1024*1024),
            "repeats":repeats,
            "git_archive_prefix_seconds":{
                "p50":statistics.median(archive_times),
                "p95":pct95(archive_times),
                "max":max(archive_times),
            },
            "local_prefix_hash_seconds":{
                "p50":statistics.median(local_times),
                "p95":pct95(local_times),
                "max":max(local_times),
            },
            "combined_prefix_work_p95_seconds":pct95(archive_times)+pct95(local_times),
            "forecast_safe_budget_seconds":720,
            "prefix_only_budget_fraction":(
                (pct95(archive_times)+pct95(local_times))/720.0
            ),
            "digest":expected,
        }
        if out["combined_prefix_work_p95_seconds"]>=120:
            raise RuntimeError("checkpoint prefix work exceeds frozen engineering guard")
        return out


if __name__=="__main__":
    print(json.dumps(run(),indent=2,sort_keys=True))
