"""Signed prospective worker for BTC Predictive vNext4R7.1.

R6 is a new prospective epoch. R5 is not modified. Executable code is loaded
from one immutable R6 source commit; mutable evidence branches contain only
signed evidence/raw observations and are never executable authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import sklearn

UTC = timezone.utc
CODE_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path(
    os.environ.get("BTC_VNEXT4R71_EVIDENCE_ROOT", str(CODE_ROOT))
).resolve()
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from predictive_vnext4r7.integrity import verify_event_workflow_against_manifest
from predictive_vnext4r71.journal_runtime import load_incremental_journal
from predictive_vnext4r71.checkpoint_writer import (
    should_checkpoint,
    create_signed_checkpoint,
    commit_and_push_checkpoint,
)
from predictive_vnext4r71.anchor import publish_checkpoint_anchor

START = datetime.fromisoformat(os.environ.get("BTC_VNEXT4R71_START_UTC", "2099-01-01T00:00:00+00:00")).astimezone(UTC)
DELIVERY_SAFETY = timedelta(minutes=2)
ISSUER = "https://token.actions.githubusercontent.com"
CLASS_TO_ID = {
    "LOWER_FIRST": 0,
    "UPPER_FIRST": 1,
    "NEITHER": 2,
    "AMBIGUOUS_SAME_BAR": 3,
}

PROTOCOL_PATHS = (
    "predictive_vnext4r71/protocol_1h.json",
    "predictive_vnext4r71/protocol_4h.json",
    "predictive_vnext4r71/protocol_24h.json",
)
PRODUCTION_WORKFLOWS = (
    ".github/workflows/btc-predictive-vnext4r71-1h.yml",
    ".github/workflows/btc-predictive-vnext4r71-4h.yml",
    ".github/workflows/btc-predictive-vnext4r71-24h.yml",
    ".github/workflows/btc-predictive-vnext4r71-watchdog.yml",
    ".github/workflows/btc-predictive-vnext4r71-health.yml",
)

CONFIG = {
    "1h": {
        "head": "1h",
        "branch": "btc-predictive-vnext4r71-1h",
        "protocol": "predictive_vnext4r71/protocol_1h.json",
        "artifact": "predictive_vnext4r6/head_1h.joblib",
        "baseline": "predictive_vnext4r6/baseline_1h.json",
        "events": "predictive_vnext4r71_1h_events",
        "raw": "predictive_vnext4r71_1h_raw",
        "checkpoint": "predictive_vnext4r71_checkpoints/1h.json",
        "anchor_branch": "btc-predictive-vnext4r71-1h-checkpoint-anchors",
        "cadence": timedelta(minutes=15),
        "deadline": timedelta(minutes=14),
        "interval": "15m",
        "duration_ms": 900000,
        "min_history": 385,
        "horizon": timedelta(hours=1),
        "bars": 4,
        "forecast_workflow": ".github/workflows/btc-predictive-vnext4r71-1h.yml",
        "outcome_workflow": ".github/workflows/btc-predictive-vnext4r71-1h.yml",
    },
    "4h": {
        "head": "4h",
        "branch": "btc-predictive-vnext4r71-4h",
        "protocol": "predictive_vnext4r71/protocol_4h.json",
        "artifact": "predictive_vnext4r6/head_4h.joblib",
        "baseline": "predictive_vnext4r6/baseline_4h.json",
        "events": "predictive_vnext4r71_4h_events",
        "raw": "predictive_vnext4r71_4h_raw",
        "checkpoint": "predictive_vnext4r71_checkpoints/4h.json",
        "anchor_branch": "btc-predictive-vnext4r71-4h-checkpoint-anchors",
        "cadence": timedelta(minutes=15),
        "deadline": timedelta(minutes=14),
        "interval": "15m",
        "duration_ms": 900000,
        "min_history": 385,
        "horizon": timedelta(hours=4),
        "bars": 16,
        "forecast_workflow": ".github/workflows/btc-predictive-vnext4r71-4h.yml",
        "outcome_workflow": ".github/workflows/btc-predictive-vnext4r71-4h.yml",
    },
    "24h": {
        "head": "24h",
        "branch": "btc-predictive-vnext4r71-24h",
        "protocol": "predictive_vnext4r71/protocol_24h.json",
        "artifact": "predictive_vnext4r6/head_24h.joblib",
        "baseline": "predictive_vnext4r6/baseline_24h.json",
        "events": "predictive_vnext4r71_24h_events",
        "raw": "predictive_vnext4r71_24h_raw",
        "checkpoint": "predictive_vnext4r71_checkpoints/24h.json",
        "anchor_branch": "btc-predictive-vnext4r71-24h-checkpoint-anchors",
        "cadence": timedelta(hours=1),
        "deadline": timedelta(minutes=45),
        "interval": "1h",
        "duration_ms": 3600000,
        "min_history": 170,
        "horizon": timedelta(hours=24),
        "bars": 24,
        "forecast_workflow": ".github/workflows/btc-predictive-vnext4r71-24h.yml",
        "outcome_workflow": ".github/workflows/btc-predictive-vnext4r71-24h.yml",
    },
}


def utcnow():
    return datetime.now(UTC)


def canonical(obj):
    return (
        json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def cmd(*args):
    return subprocess.run(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=EVIDENCE_ROOT,
    ).stdout.strip()


def git_bytes(commit, path):
    return subprocess.run(
        ["git", "-C", str(EVIDENCE_ROOT), "show", f"{commit}:{path}"],
        check=True,
        capture_output=True,
        timeout=180,
    ).stdout


def identity(path):
    expected_ref = os.environ.get(
        "BTC_VNEXT4R71_EXPECTED_REF", "refs/heads/main"
    )
    return (
        "https://github.com/sergeytren1984-ux/neora-b2b-v2-clean/"
        f"{path}@{expected_ref}"
    )


def bundle_time(path):
    bundle = json.loads(Path(path).read_bytes())
    entries = bundle.get("verificationMaterial", {}).get("tlogEntries", [])
    if not entries:
        raise ValueError("Rekor entry missing")
    for entry in entries:
        proof = entry.get("inclusionProof")
        if (
            not isinstance(proof, dict)
            or not proof.get("checkpoint")
            or "hashes" not in proof
        ):
            raise ValueError("Rekor inclusion proof missing")
    return min(
        datetime.fromtimestamp(int(entry["integratedTime"]), UTC)
        for entry in entries
    )


def event_identity(cfg, event_type):
    path = (
        cfg["outcome_workflow"]
        if event_type == "OUTCOME_RECORDED"
        else cfg["forecast_workflow"]
    )
    return identity(path)


def signature_claim_args(event):
    sha = str(event.get("workflow_commit", ""))
    if (
        len(sha) != 40
        or any(ch not in "0123456789abcdef" for ch in sha.lower())
    ):
        raise ValueError("invalid event workflow_commit")
    return [
        "--certificate-github-workflow-sha",
        sha,
        "--certificate-github-workflow-repository",
        "sergeytren1984-ux/neora-b2b-v2-clean",
        "--certificate-github-workflow-ref",
        os.environ.get(
            "BTC_VNEXT4R71_EXPECTED_REF", "refs/heads/main"
        ),
        "--certificate-github-workflow-trigger",
        os.environ.get(
            "BTC_VNEXT4R71_EXPECTED_TRIGGER", "workflow_dispatch"
        ),
    ]


def verify_signature(path, bundle, cfg, event):
    subprocess.run(
        [
            "cosign",
            "verify-blob",
            str(path),
            "--bundle",
            str(bundle),
            "--certificate-identity",
            event_identity(cfg, event.get("type")),
            "--certificate-oidc-issuer",
            ISSUER,
            *signature_claim_args(event),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=EVIDENCE_ROOT,
    )
    return bundle_time(bundle)


def _event_files(cfg):
    directory = EVIDENCE_ROOT / cfg["events"]
    directory.mkdir(exist_ok=True)
    return sorted(
        p for p in directory.glob("*.json")
        if len(p.stem) == 8 and p.stem.isdigit()
    )


def prior_events(cfg):
    files = _event_files(cfg)
    # Bootstrap before the signed freeze exists: at most the pre-start authority
    # events are verified directly. Once event #2 exists, the checkpoint-aware
    # loader is mandatory.
    if len(files) < 2:
        out = []
        previous = None
        keys = set()
        for i, path in enumerate(files, 1):
            raw = path.read_bytes()
            event = json.loads(raw)
            integrated = verify_signature(
                path, path.with_suffix(".sigstore.json"), cfg, event
            )
            if (
                raw != canonical(event)
                or event.get("sequence") != i
                or event.get("previous_hash") != previous
            ):
                raise ValueError("event hash chain broken")
            key = event.get("idempotency_key")
            if not isinstance(key, str) or key in keys:
                raise ValueError("duplicate/missing event key")
            keys.add(key)
            previous = digest(raw)
            out.append((event, integrated))
        return out

    current_tip = cmd("git", "rev-parse", "HEAD")
    checkpoint = EVIDENCE_ROOT / cfg["checkpoint"]
    result = load_incremental_journal(
        repo_root=EVIDENCE_ROOT,
        events_dir=EVIDENCE_ROOT / cfg["events"],
        checkpoint_path=checkpoint,
        checkpoint_bundle_path=checkpoint.with_suffix(".sigstore.json"),
        head=cfg["head"],
        horizon=cfg["horizon"],
        issuance_deadline=cfg["deadline"],
        start_utc=START,
        current_branch_tip=current_tip,
        forecast_workflow=cfg["forecast_workflow"],
        outcome_workflow=cfg["outcome_workflow"],
        verify_event_blob=lambda p,b,e: verify_signature(p,b,cfg,e),
        verify_checkpoint_blob=lambda p,b,e: verify_signature(p,b,cfg,e),
        verify_workflow_binding=verify_event_workflow_against_manifest,
    )
    integrated = {}
    integrated.update(result["authority_rekor"])
    integrated.update(result["suffix_rekor"])
    return [
        (event, integrated.get(int(event["sequence"])))
        for event in result["events"]
    ]

def remote_clean(cfg):
    cmd("git", "fetch", "origin", cfg["branch"])
    if cmd("git", "rev-parse", "HEAD") != cmd(
        "git", "rev-parse", "origin/" + cfg["branch"]
    ):
        raise RuntimeError("remote evidence branch advanced")


def publish(cfg, obj, deadline=None, attachments=()):
    if deadline and utcnow() >= deadline - DELIVERY_SAFETY:
        raise TimeoutError("deadline safety margin reached")
    remote_clean(cfg)
    prior = prior_events(cfg)
    keys = {e["idempotency_key"] for e, _ in prior}
    if obj["idempotency_key"] in keys:
        return

    n = len(prior) + 1
    event = {
        "schema": "btc-predictive-vnext4r71-event-v1",
        "sequence": n,
        "previous_hash": digest(canonical(prior[-1][0])) if prior else None,
        "workflow_commit": os.environ["GITHUB_SHA"],
        "published_at_utc": utcnow().isoformat(),
        **obj,
    }
    events = EVIDENCE_ROOT / cfg["events"]
    path = events / f"{n:08d}.json"
    bundle = path.with_suffix(".sigstore.json")
    path.write_bytes(canonical(event))

    subprocess.run(
        ["cosign", "sign-blob", "--yes", "--bundle", str(bundle), str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=EVIDENCE_ROOT,
    )
    if deadline and (
        bundle_time(bundle) >= deadline or utcnow() >= deadline
    ):
        path.unlink(missing_ok=True)
        bundle.unlink(missing_ok=True)
        raise TimeoutError("signed forecast missed deadline")
    verify_signature(path, bundle, cfg, event)

    for attachment in (path, bundle, *attachments):
        rel = str(Path(attachment).resolve().relative_to(EVIDENCE_ROOT))
        cmd("git", "add", rel)
    cmd(
        "git",
        "commit",
        "-m",
        f"BTC predictive vNext4R7.1 {obj.get('head','')} evidence #{n}: {event['type']}",
    )
    cmd("git", "push", "origin", "HEAD:" + cfg["branch"])
    remote_sha = cmd(
        "git", "ls-remote", "origin", "refs/heads/" + cfg["branch"]
    ).split()[0]
    local_sha = cmd("git", "rev-parse", "HEAD")
    if remote_sha != local_sha:
        raise RuntimeError("remote publication unconfirmed")

    if deadline and event.get("type") == "FORECAST_ISSUED":
        if not ensure_delivery_receipt(cfg, event, deadline):
            raise TimeoutError(
                "delivery receipt could not be recovered before deadline"
            )


def _verify_remote_forecast_commit(cfg, forecast_event, commit):
    seq = int(forecast_event["sequence"])
    path = f"{cfg['events']}/{seq:08d}.json"
    if git_bytes(commit, path) != canonical(forecast_event):
        raise RuntimeError(
            "remote commit does not contain exact forecast event"
        )
    cmd("git", "fetch", "origin", cfg["branch"])
    remote_tip = cmd("git", "rev-parse", "origin/" + cfg["branch"])
    subprocess.run(
        [
            "git",
            "-C",
            str(EVIDENCE_ROOT),
            "merge-base",
            "--is-ancestor",
            commit,
            remote_tip,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )


def forecast_commit_for_event(cfg, forecast_event):
    remote_clean(cfg)
    seq = int(forecast_event["sequence"])
    path = f"{cfg['events']}/{seq:08d}.json"
    commit = cmd("git", "log", "-1", "--format=%H", "--", path)
    if not commit:
        raise RuntimeError("forecast commit not found")
    _verify_remote_forecast_commit(cfg, forecast_event, commit)
    return commit


def ensure_delivery_receipt(cfg, forecast_event, deadline):
    prior = prior_events(cfg)
    key = "delivery:" + forecast_event["idempotency_key"]
    matches = [x for x in prior if x[0].get("idempotency_key") == key]
    if len(matches) > 1:
        raise RuntimeError("duplicate delivery receipt")
    if len(matches) == 1:
        receipt, integrated = matches[0]
        if integrated is None:
            receipt_path = (
                EVIDENCE_ROOT / cfg["events"]
                / f"{int(receipt['sequence']):08d}.json"
            )
            integrated = verify_signature(
                receipt_path,
                receipt_path.with_suffix(".sigstore.json"),
                cfg,
                receipt,
            )
        if (
            receipt.get("target_sequence") != forecast_event.get("sequence")
            or receipt.get("target_event_hash")
            != digest(canonical(forecast_event))
            or receipt.get("slot") != forecast_event.get("slot")
        ):
            raise RuntimeError("delivery receipt target mismatch")
        if integrated >= deadline:
            raise RuntimeError("delivery receipt Rekor time is late")
        remote_commit = receipt.get("remote_commit_sha")
        if not remote_commit:
            raise RuntimeError("delivery receipt remote commit missing")
        _verify_remote_forecast_commit(
            cfg, forecast_event, remote_commit
        )
        return True

    if utcnow() >= deadline - DELIVERY_SAFETY:
        return False
    remote_commit = forecast_commit_for_event(cfg, forecast_event)
    confirmed_at = utcnow()
    if confirmed_at >= deadline - DELIVERY_SAFETY:
        return False
    publish(
        cfg,
        {
            "type": "DELIVERY_CONFIRMED",
            "idempotency_key": key,
            "head": forecast_event.get("head"),
            "slot": forecast_event.get("slot"),
            "target_sequence": int(forecast_event["sequence"]),
            "target_event_hash": digest(canonical(forecast_event)),
            "remote_commit_sha": remote_commit,
            "remote_confirmed_at_utc": confirmed_at.isoformat(),
            "deadline_utc": deadline.isoformat(),
            "trading_authority": False,
        },
        deadline=deadline,
    )
    return True


def static_paths(cfg):
    paths = [
        "predictive_vnext4r71/worker.py",
        "predictive_vnext4r71/integrity.py",
        "predictive_vnext4r71/checkpoint.py",
        "predictive_vnext4r71/checkpoint_writer.py",
        "predictive_vnext4r71/journal_runtime.py",
        "predictive_vnext4r71/crypto.py",
        "predictive_vnext4r71/admission.py",
        "predictive_vnext4r71/anchor.py",
        "predictive_vnext4r71/scheduler.py",
        "predictive_vnext4r71/chain_liveness.py",
        "predictive_vnext4r71/health.py",
        "predictive_vnext4r7/scorecard_core.py",
        "predictive_vnext4r7/episodes.py",
        "predictive_vnext4r6/live_features.py",
        "predictive_vnext4r6/predict.py",
        "predictive_vnext4r6/control.py",
        "predictive_vnext4r6/freeze_metadata.json",
        "predictive_vnext4r6/baseline_metadata.json",
        cfg["artifact"],
        cfg["baseline"],
    ]
    paths.extend(PROTOCOL_PATHS)
    return list(dict.fromkeys(paths))

def workflow_hash(commit, path):
    return digest(git_bytes(commit, path))


def manifest(cfg, source_sha):
    if not source_sha or len(source_sha) != 40:
        raise ValueError("immutable source commit missing")
    subprocess.run(
        [
            "git",
            "-C",
            str(EVIDENCE_ROOT),
            "cat-file",
            "-e",
            source_sha + "^{commit}",
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    paths = {}
    for path in static_paths(cfg):
        local = (CODE_ROOT / path).read_bytes()
        committed = git_bytes(source_sha, path)
        if local != committed:
            raise RuntimeError(
                "clean runtime does not match immutable source: " + path
            )
        paths[path] = digest(local)

    workflow_commit = os.environ["GITHUB_SHA"]
    for path in PRODUCTION_WORKFLOWS:
        paths[path] = workflow_hash(workflow_commit, path)

    return {
        "schema": "btc-predictive-vnext4r71-frozen-manifest-v1",
        "source_commit_sha": source_sha,
        "paths_sha256": paths,
        "forecast_workflow": cfg["forecast_workflow"],
        "outcome_workflow": cfg["outcome_workflow"],
        "all_protocols": list(PROTOCOL_PATHS),
        "deployment_workflows": list(PRODUCTION_WORKFLOWS),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "numpy_version": np.__version__,
        "sklearn_version": sklearn.__version__,
        "joblib_version": joblib.__version__,
        "cosign_version": cmd("cosign", "version"),
        "evidence_branch": cfg["branch"],
        "runtime_isolation": (
            "python -I + clean git archive of immutable source commit"
        ),
    }


def signed_freeze(cfg):
    events = prior_events(cfg)
    freezes = [
        x for x in events if x[0].get("type") == "CONFIG_FROZEN_PRESTART"
    ]
    if len(freezes) != 1:
        raise RuntimeError(
            "exactly one signed pre-start freeze required"
        )
    event, integrated = freezes[0]
    if integrated >= START:
        raise RuntimeError("freeze Rekor time is not pre-start")
    manifest_obj = event.get("manifest")
    if (
        not isinstance(manifest_obj, dict)
        or digest(canonical(manifest_obj))
        != event.get("manifest_sha256")
    ):
        raise RuntimeError("signed freeze manifest hash mismatch")
    return event, manifest_obj, events


def verify_signed_freeze(cfg, head, action):
    freeze, manifest_obj, events = signed_freeze(cfg)
    source = os.environ.get("BTC_VNEXT4R71_SOURCE_SHA", "")
    if source != manifest_obj.get("source_commit_sha"):
        raise RuntimeError(
            "runtime source SHA differs from signed freeze"
        )
    expected = (
        cfg["forecast_workflow"]
        if action == "forecast"
        else cfg["outcome_workflow"]
    )
    if os.environ.get("BTC_VNEXT4R71_WORKFLOW_PATH") != expected:
        raise RuntimeError("workflow path environment mismatch")
    deployment = manifest_obj.get("deployment_workflows")
    if deployment != list(PRODUCTION_WORKFLOWS):
        raise RuntimeError("signed deployment workflow set mismatch")
    for workflow_path in PRODUCTION_WORKFLOWS:
        if (
            workflow_hash(os.environ["GITHUB_SHA"], workflow_path)
            != manifest_obj["paths_sha256"].get(workflow_path)
        ):
            raise RuntimeError(
                "deployment workflow content differs from signed freeze: "
                + workflow_path
            )
    if expected not in deployment:
        raise RuntimeError("active workflow absent from signed deployment set")
    for path in static_paths(cfg):
        local = (CODE_ROOT / path).read_bytes()
        if digest(local) != manifest_obj["paths_sha256"].get(path):
            raise RuntimeError(
                "runtime path differs from signed freeze: " + path
            )
        if local != git_bytes(source, path):
            raise RuntimeError(
                "runtime path differs from immutable source: " + path
            )

    copy_path = (
        EVIDENCE_ROOT
        / "predictive_vnext4r71"
        / f"frozen_manifest_{head}.json"
    )
    if (
        not copy_path.exists()
        or copy_path.read_bytes() != canonical(manifest_obj)
    ):
        raise RuntimeError(
            "evidence manifest copy differs from signed manifest"
        )
    return events


def initialize(cfg, head):
    now = utcnow()
    protocol = json.loads((CODE_ROOT / cfg["protocol"]).read_bytes())
    events = prior_events(cfg)
    if protocol["start_utc"] != START.strftime("%Y-%m-%dT%H:%M:%SZ"):
        raise ValueError("start mismatch")
    source = os.environ.get("BTC_VNEXT4R71_SOURCE_SHA", "")

    if not events:
        if now >= START:
            raise RuntimeError("no registration before start")
        publish(
            cfg,
            {
                "type": "SCHEDULE_REGISTERED",
                "idempotency_key": f"{head}:schedule",
                "head": head,
                "start_utc": START.isoformat(),
                "deadline_minutes": int(
                    cfg["deadline"].total_seconds() / 60
                ),
                "protocol_sha256": digest(
                    (CODE_ROOT / cfg["protocol"]).read_bytes()
                ),
                "source_commit_sha": source,
                "trading_authority": False,
            },
        )
        events = prior_events(cfg)

    if not any(
        e["type"] == "CONFIG_FROZEN_PRESTART" for e, _ in events
    ):
        if now >= START:
            raise RuntimeError("no freeze before start")
        manifest_obj = manifest(cfg, source)
        directory = EVIDENCE_ROOT / "predictive_vnext4r71"
        directory.mkdir(exist_ok=True)
        path = directory / f"frozen_manifest_{head}.json"
        path.write_bytes(canonical(manifest_obj))
        publish(
            cfg,
            {
                "type": "CONFIG_FROZEN_PRESTART",
                "idempotency_key": f"{head}:freeze",
                "head": head,
                "start_utc": START.isoformat(),
                "manifest_sha256": digest(path.read_bytes()),
                "manifest": manifest_obj,
                "trading_authority": False,
            },
            attachments=(path,),
        )
        return False

    verify_signed_freeze(cfg, head, "forecast")
    return True


def slot_floor(now, cadence):
    if cadence == timedelta(hours=1):
        return now.replace(minute=0, second=0, microsecond=0)
    return now.replace(
        minute=(now.minute // 15) * 15,
        second=0,
        microsecond=0,
    )


def slot_text(anchor):
    return anchor.strftime("%Y%m%dT%H%M%SZ")


def fetch_recent(anchor, cfg):
    params = urllib.parse.urlencode(
        {
            "symbol": "BTCUSDT",
            "interval": cfg["interval"],
            "limit": 1000,
        }
    )
    req = urllib.request.Request(
        "https://data-api.binance.vision/api/v3/klines?" + params,
        headers={"User-Agent": "btc-predictive-vnext4r6"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("Binance HTTP not 200")
        raw = json.loads(response.read())

    closed = []
    for row in raw:
        if int(row[6]) != int(row[0]) + cfg["duration_ms"] - 1:
            raise ValueError("invalid candle timestamp")
        close_time = datetime.fromtimestamp((int(row[6]) + 1) / 1000, UTC)
        if close_time > anchor:
            continue
        o, h, l, c = map(float, (row[1], row[2], row[3], row[4]))
        vol = float(row[5])
        taker = float(row[9])
        trades = int(row[8])
        if (
            not all(map(math.isfinite, (o, h, l, c, vol, taker)))
            or min(o, h, l, c) <= 0
            or l > min(o, c)
            or h < max(o, c)
            or h < l
            or vol < 0
            or taker < 0
            or taker > vol
            or trades < 0
        ):
            raise ValueError("invalid OHLC/activity")
        closed.append(row)

    if len(closed) < cfg["min_history"]:
        raise ValueError("insufficient closed candles")
    if (
        datetime.fromtimestamp((int(closed[-1][6]) + 1) / 1000, UTC)
        != anchor
    ):
        raise ValueError("latest closed candle != anchor")
    if any(
        int(b[0]) - int(a[0]) != cfg["duration_ms"]
        for a, b in zip(closed, closed[1:])
    ):
        raise ValueError("candle gap or duplicate")
    return raw, closed


def arrays(closed):
    return tuple(
        np.asarray([float(row[j]) for row in closed])
        for j in (2, 3, 4, 5, 8, 9)
    )


def resolved_control_records(events):
    forecasts = {
        event["slot"]: event
        for event, _ in events
        if event.get("type") == "FORECAST_ISSUED"
    }
    out = []
    for event, _ in events:
        if event.get("type") != "OUTCOME_RECORDED":
            continue
        forecast_event = forecasts.get(event["slot"])
        if not forecast_event:
            continue
        cls = CLASS_TO_ID.get(event.get("outcome_class"))
        vb = forecast_event.get("control", {}).get("volatility_bin")
        if cls is None or vb not in (0, 1, 2):
            continue
        out.append(
            {
                "anchor_utc": forecast_event["anchor_utc"],
                "due_utc": forecast_event["due_utc"],
                "class_id": cls,
                "vol_bin": int(vb),
            }
        )
    return out


def forecast(cfg, head):
    events = verify_signed_freeze(cfg, head, "forecast")
    now = utcnow()
    anchor = slot_floor(now, cfg["cadence"])
    deadline = anchor + cfg["deadline"]
    if anchor < START or now >= deadline:
        return False

    keys = {event["idempotency_key"] for event, _ in events}
    slot = slot_text(anchor)
    existing = [
        event
        for event, _ in events
        if event.get("idempotency_key") == "forecast:" + slot
    ]
    if existing:
        return ensure_delivery_receipt(
            cfg, existing[0], deadline
        )

    protocol = json.loads((CODE_ROOT / cfg["protocol"]).read_bytes())
    try:
        from predictive_vnext4r6.control import (
            load_baseline,
            control_prediction,
        )
        from predictive_vnext4r6.live_features import (
            HOURLY_NAMES,
            EARLY15M_NAMES,
            hourly_feature,
            early15m_feature,
        )
        from predictive_vnext4r6.predict import (
            load_artifact,
            predict_selected,
        )

        raw, closed = fetch_recent(anchor, cfg)
        hi, lo, c, v, trades, taker = arrays(closed)
        artifact = load_artifact(
            CODE_ROOT / cfg["artifact"],
            protocol["artifact_sha256"],
        )
        baseline_path = CODE_ROOT / cfg["baseline"]
        if digest(baseline_path.read_bytes()) != protocol["baseline_sha256"]:
            raise ValueError("R6 baseline SHA256 mismatch")
        baseline = load_baseline(baseline_path)

        if head in ("1h", "4h"):
            x, meta = early15m_feature(
                hi, lo, c, v, trades, taker
            )
            if artifact["feature_names"] != EARLY15M_NAMES:
                raise ValueError("15m feature schema mismatch")
            vol_value = meta["rv4h"]
            distance = (
                meta["reference_price"]
                * vol_value
                * math.sqrt(float(cfg["bars"]))
            )
        else:
            x, meta = hourly_feature(
                hi, lo, c, v, trades, taker
            )
            if artifact["feature_names"] != HOURLY_NAMES:
                raise ValueError("hourly feature schema mismatch")
            vol_value = meta["rv24"]
            distance = (
                meta["reference_price"]
                * vol_value
                * math.sqrt(24.0)
            )

        selected = predict_selected(artifact, x)
        control = control_prediction(
            baseline,
            vol_value,
            anchor.isoformat(),
            resolved_control_records(events),
        )
        lower = meta["reference_price"] - distance
        upper = meta["reference_price"] + distance
        due = anchor + cfg["horizon"]
    except Exception as ex:
        key = "abstain-data:" + slot
        if key not in keys:
            publish(
                cfg,
                {
                    "type": "ABSTAIN_DATA_INVALID",
                    "idempotency_key": key,
                    "head": head,
                    "slot": slot,
                    "reason": type(ex).__name__ + ": " + str(ex)[:300],
                    "retryable_before_deadline": True,
                    "trading_authority": False,
                },
                deadline=deadline,
            )
        return False

    rawdir = EVIDENCE_ROOT / cfg["raw"]
    rawdir.mkdir(exist_ok=True)
    raw_path = rawdir / (slot + ".json")
    raw_path.write_bytes(
        canonical(
            {
                "slot": slot,
                "anchor_utc": anchor.isoformat(),
                "retrieved_at_utc": utcnow().isoformat(),
                "source": (
                    "Binance BTCUSDT closed "
                    + cfg["interval"]
                    + " klines"
                ),
                "klines": raw,
            }
        )
    )

    event = {
        "type": "FORECAST_ISSUED",
        "idempotency_key": "forecast:" + slot,
        "slot": slot,
        "head": head,
        "anchor_utc": anchor.isoformat(),
        "due_utc": due.isoformat(),
        "reference_price": meta["reference_price"],
        "lower_price": float(lower),
        "upper_price": float(upper),
        "selected_model": selected["selected_model"],
        "class_distribution": selected["class_distribution"],
        "components": selected["components"],
        "control": control,
        "probability_status": (
            "HISTORICALLY_SELECTED_PROSPECTIVE_UNVALIDATED"
        ),
        "artifact_sha256": protocol["artifact_sha256"],
        "baseline_sha256": protocol["baseline_sha256"],
        "raw_path": str(raw_path.relative_to(EVIDENCE_ROOT)),
        "raw_sha256": digest(raw_path.read_bytes()),
        "trading_authority": False,
    }
    publish(
        cfg,
        event,
        deadline=deadline,
        attachments=(raw_path,),
    )
    return True


def mark_missed(cfg, head):
    events = verify_signed_freeze(cfg, head, "forecast")
    now = utcnow()
    keys = {event["idempotency_key"] for event, _ in events}
    slot = START
    while slot + cfg["deadline"] <= now:
        text = slot_text(slot)
        if (
            "forecast:" + text not in keys
            and "missed:" + text not in keys
        ):
            publish(
                cfg,
                {
                    "type": "SLOT_MISSED",
                    "idempotency_key": "missed:" + text,
                    "head": head,
                    "slot": text,
                    "reason": "NO_TIMELY_FORECAST",
                    "deadline_utc": (
                        slot + cfg["deadline"]
                    ).isoformat(),
                    "trading_authority": False,
                },
            )
            keys.add("missed:" + text)
        slot += cfg["cadence"]


def fetch_outcome_rows(anchor, due, cfg):
    start_ms = int(anchor.timestamp() * 1000)
    end_ms = int(due.timestamp() * 1000) - 1
    params = urllib.parse.urlencode(
        {
            "symbol": "BTCUSDT",
            "interval": cfg["interval"],
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": 1000,
        }
    )
    req = urllib.request.Request(
        "https://data-api.binance.vision/api/v3/klines?" + params,
        headers={"User-Agent": "btc-predictive-vnext4r6-outcome"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError("Binance outcome HTTP not 200")
        rows = json.loads(response.read())

    expected = int(
        (due - anchor).total_seconds()
        * 1000
        / cfg["duration_ms"]
    )
    if len(rows) != expected:
        raise ValueError(
            f"outcome candle count {len(rows)} != {expected}"
        )
    if (
        int(rows[0][0]) != start_ms
        or int(rows[-1][6]) + 1 != int(due.timestamp() * 1000)
    ):
        raise ValueError("outcome boundaries mismatch")
    if any(
        int(b[0]) - int(a[0]) != cfg["duration_ms"]
        for a, b in zip(rows, rows[1:])
    ):
        raise ValueError("outcome candle gap")
    return rows


def classify(rows, lower, upper):
    for row in rows:
        down = float(row[3]) <= lower
        up = float(row[2]) >= upper
        close = datetime.fromtimestamp(
            (int(row[6]) + 1) / 1000, UTC
        ).isoformat()
        if down and up:
            return "AMBIGUOUS_SAME_BAR", close
        if down:
            return "LOWER_FIRST", close
        if up:
            return "UPPER_FIRST", close
    return "NEITHER", None


def outcomes(cfg, head):
    events = verify_signed_freeze(cfg, head, "outcome")
    now = utcnow()
    keys = {event["idempotency_key"] for event, _ in events}
    for forecast_event, _ in events:
        if forecast_event.get("type") != "FORECAST_ISSUED":
            continue
        key = "outcome:" + forecast_event["slot"]
        due = datetime.fromisoformat(forecast_event["due_utc"])
        if key in keys or due > now:
            continue
        try:
            rows = fetch_outcome_rows(
                datetime.fromisoformat(
                    forecast_event["anchor_utc"]
                ),
                due,
                cfg,
            )
            cls, touch = classify(
                rows,
                float(forecast_event["lower_price"]),
                float(forecast_event["upper_price"]),
            )
        except Exception:
            continue

        rawdir = EVIDENCE_ROOT / cfg["raw"]
        rawdir.mkdir(exist_ok=True)
        path = rawdir / (
            forecast_event["slot"] + "-outcome.json"
        )
        path.write_bytes(
            canonical(
                {
                    "slot": forecast_event["slot"],
                    "due_utc": forecast_event["due_utc"],
                    "retrieved_at_utc": utcnow().isoformat(),
                    "klines": rows,
                }
            )
        )
        publish(
            cfg,
            {
                "type": "OUTCOME_RECORDED",
                "idempotency_key": key,
                "slot": forecast_event["slot"],
                "head": head,
                "anchor_utc": forecast_event["anchor_utc"],
                "due_utc": forecast_event["due_utc"],
                "outcome_class": cls,
                "first_touch_time_utc": touch,
                "lower_price": forecast_event["lower_price"],
                "upper_price": forecast_event["upper_price"],
                "raw_path": str(path.relative_to(EVIDENCE_ROOT)),
                "raw_sha256": digest(path.read_bytes()),
                "trading_authority": False,
            },
            attachments=(path,),
        )
        keys.add(key)


def _sign_checkpoint(path, bundle):
    subprocess.run(
        ["cosign", "sign-blob", "--yes", "--bundle", str(bundle), str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        cwd=EVIDENCE_ROOT,
    )


def _ensure_checkpoint_anchor(cfg, head, checkpoint, manifest_obj):
    if not checkpoint.exists():
        return None
    bundle = checkpoint.with_suffix(".sigstore.json")
    if not bundle.exists():
        raise RuntimeError("checkpoint exists without signature bundle")
    doc = json.loads(checkpoint.read_bytes())
    rel = str(checkpoint.resolve().relative_to(EVIDENCE_ROOT))
    checkpoint_commit = cmd("git", "log", "-1", "--format=%H", "--", rel)
    if not checkpoint_commit:
        raise RuntimeError("checkpoint publication commit missing")
    return publish_checkpoint_anchor(
        repo_root=EVIDENCE_ROOT,
        anchor_branch=cfg["anchor_branch"],
        base_commit=manifest_obj["source_commit_sha"],
        evidence_branch=cfg["branch"],
        head=head,
        checkpoint_path=checkpoint,
        checkpoint_bundle_path=bundle,
        checkpoint_doc=doc,
        checkpoint_remote_commit=checkpoint_commit,
        workflow_commit=os.environ["GITHUB_SHA"],
        sign_blob=_sign_checkpoint,
        require_bundle_time=bundle_time,
        verify_blob=lambda p,b,e: verify_signature(p,b,cfg,e),
    )


def maybe_checkpoint(cfg, head):
    checkpoint = EVIDENCE_ROOT / cfg["checkpoint"]
    events_with_time = prior_events(cfg)
    events = [event for event, _ in events_with_time]
    freezes = [
        event for event in events
        if event.get("type") == "CONFIG_FROZEN_PRESTART"
    ]
    if len(freezes) != 1:
        raise RuntimeError("checkpoint requires exactly one signed freeze")
    manifest_obj = freezes[0]["manifest"]

    if should_checkpoint(
        len(events), checkpoint, interval_events=24
    ):
        checkpoint_doc = create_signed_checkpoint(
            repo_root=EVIDENCE_ROOT,
            events_dir=EVIDENCE_ROOT / cfg["events"],
            checkpoint_path=checkpoint,
            checkpoint_bundle_path=checkpoint.with_suffix(".sigstore.json"),
            events=events,
            head=head,
            manifest=manifest_obj,
            workflow_commit=os.environ["GITHUB_SHA"],
            sign_blob=_sign_checkpoint,
            require_bundle_time=bundle_time,
        )
        checkpoint_commit = commit_and_push_checkpoint(
            repo_root=EVIDENCE_ROOT,
            branch=cfg["branch"],
            checkpoint_path=checkpoint,
            checkpoint_bundle_path=checkpoint.with_suffix(".sigstore.json"),
            head=head,
        )
        publish_checkpoint_anchor(
            repo_root=EVIDENCE_ROOT,
            anchor_branch=cfg["anchor_branch"],
            base_commit=manifest_obj["source_commit_sha"],
            evidence_branch=cfg["branch"],
            head=head,
            checkpoint_path=checkpoint,
            checkpoint_bundle_path=checkpoint.with_suffix(".sigstore.json"),
            checkpoint_doc=checkpoint_doc,
            checkpoint_remote_commit=checkpoint_commit,
            workflow_commit=os.environ["GITHUB_SHA"],
            sign_blob=_sign_checkpoint,
            require_bundle_time=bundle_time,
            verify_blob=lambda p,b,e: verify_signature(p,b,cfg,e),
        )
        return True

    # Recovery is fail-closed: a checkpoint without its independent anchor is
    # repaired/verified on the next worker action instead of being silently trusted.
    _ensure_checkpoint_anchor(
        cfg, head, checkpoint, manifest_obj
    )
    return False


def main():
    head = os.environ.get("BTC_VNEXT4R71_HEAD")
    action = os.environ.get("BTC_VNEXT4R71_ACTION")
    if head not in CONFIG or action not in ("forecast", "outcome"):
        raise ValueError("invalid head/action")
    cfg = CONFIG[head]
    if action == "forecast":
        if not initialize(cfg, head):
            return False
        if utcnow() < START:
            return False
        mark_missed(cfg, head)
        result = forecast(cfg, head)
        # Checkpoint publication is deliberately after forecast delivery recovery.
        maybe_checkpoint(cfg, head)
        return result
    if utcnow() < START:
        return
    outcomes(cfg, head)
    maybe_checkpoint(cfg, head)


if __name__ == "__main__":
    main()
