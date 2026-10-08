"""Adversarial regression for vNext5R4.2 trusted source bootstrap.

Reproduces the R41-01 attack shape with a local Git origin:
- evidence schedule claims an attacker commit containing a sentinel worker;
- approved source is supplied outside the journal;
- launcher must never import/execute the attacker worker;
- consumer must expose no arbitrary decision-object ingestion API.

No external repositories are modified.
"""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from predictive_vnext4r7.integrity import canonical, digest
from predictive_vnext5 import admission_consumer
from predictive_vnext5.prospective_admission import run_verified_admission

UTC=timezone.utc
ROOT=Path(__file__).resolve().parents[1]


def run(*args,cwd=None,check=True):
    return subprocess.run(
        args,cwd=cwd,check=check,capture_output=True,text=True,timeout=240
    )


def git(root:Path,*args):
    return run("git","-C",str(root),*args).stdout.strip()


def main():
    approved=git(ROOT,"rev-parse","HEAD")
    with tempfile.TemporaryDirectory(prefix="vnext5r42-trust-") as td:
        base=Path(td)
        origin=base/"origin.git"
        victim=base/"victim"
        sentinel=base/"ATTACKER_WORKER_EXECUTED"

        run("git","clone","--bare",str(ROOT),str(origin))
        run("git","clone",str(origin),str(victim))
        git(victim,"config","user.name","vNext5R4.2 trust regression")
        git(victim,"config","user.email","audit@local.invalid")
        git(victim,"checkout","-B","audit-coupled",approved)

        worker=victim/"predictive_vnext5/admission_worker.py"
        worker.write_text(
            "from pathlib import Path\n"
            "import json\n"
            "def main(argv=None):\n"
            f" Path({str(sentinel)!r}).write_text('EXECUTED')\n"
            " print(json.dumps({'schema':'btc-predictive-vnext5r42-verified-admission-v1',"
            "'head':'4h','cutoff_utc':'2026-12-01T00:00:00Z',"
            "'admission_ready':True,'selected_candidate':'4h',"
            "'prospective_skill_proven':False,'trading_authority':False,"
            "'governance':{}}))\n"
        )
        git(victim,"add","predictive_vnext5/admission_worker.py")
        git(victim,"commit","-m","Unsigned attacker worker")
        attacker=git(victim,"rev-parse","HEAD")

        template=json.loads(
            (ROOT/"predictive_vnext5/evidence_protocol_template.json").read_text()
        )
        events_rel=template["journal"]["events_dir_template"].format(head="4h")
        protocol={
            "schema":"btc-predictive-vnext5r42-trust-attack-protocol-v1",
            "mode":"PROSPECTIVE",
            "head":"4h",
            "events_dir":events_rel,
            "repository":template["repository"],
            "workflow_path":template["workflow_path"],
            "canonical_target":template["canonical_target"],
            "head_config":template["heads"]["4h"],
            "trading_authority":False,
        }
        protocol_path=victim/"protocol.json"
        protocol_path.write_bytes(canonical(protocol))
        events=victim/events_rel
        events.mkdir(parents=True,exist_ok=True)
        start=datetime(2026,12,1,tzinfo=UTC)
        source_ref="refs/heads/audit-coupled"
        trigger="workflow_dispatch"
        schedule={
            "schema":"btc-predictive-vnext5r42-evidence-event-v1",
            "sequence":1,
            "previous_hash":None,
            "workflow_commit":attacker,
            "published_at_utc":(start-timedelta(hours=2)).isoformat(),
            "type":"SCHEDULE_REGISTERED",
            "idempotency_key":"4h:schedule",
            "head":"4h",
            "start_utc":start.isoformat(),
            "evidence_branch":"audit-coupled",
            "source_ref":source_ref,
            "workflow_trigger":trigger,
            "source_commit_sha":attacker,
            "protocol_sha256":digest(protocol_path.read_bytes()),
            "trading_authority":False,
        }
        manifest={
            "schema":"btc-predictive-vnext5r42-trust-attack-manifest-v1",
            "source_commit_sha":attacker,
            "source_ref":source_ref,
            "workflow_trigger":trigger,
            "evidence_branch":"audit-coupled",
            "protocol_sha256":digest(protocol_path.read_bytes()),
            "model_artifact_sha256":template["heads"]["4h"]["artifact_sha256"],
            "paths_sha256":{
                "predictive_vnext5/execution_contract.json":"0"*64
            },
            "trading_authority":False,
        }
        freeze={
            "schema":"btc-predictive-vnext5r42-evidence-event-v1",
            "sequence":2,
            "previous_hash":digest(canonical(schedule)),
            "workflow_commit":attacker,
            "published_at_utc":(start-timedelta(hours=1)).isoformat(),
            "type":"CONFIG_FROZEN_PRESTART",
            "idempotency_key":"4h:freeze",
            "head":"4h",
            "start_utc":start.isoformat(),
            "evidence_branch":"audit-coupled",
            "source_ref":source_ref,
            "workflow_trigger":trigger,
            "source_commit_sha":attacker,
            "manifest_sha256":digest(canonical(manifest)),
            "manifest":manifest,
            "trading_authority":False,
        }
        (events/"00000001.json").write_bytes(canonical(schedule))
        (events/"00000002.json").write_bytes(canonical(freeze))
        git(victim,"add",".")
        git(victim,"commit","-m","Unsigned journal claims attacker source")
        git(victim,"push","origin","HEAD:audit-coupled")

        rejected=False
        error=None
        try:
            run_verified_admission(
                repo_root=str(victim),
                approved_source_sha=approved,
                head="4h",
                evidence_branch="audit-coupled",
                protocol_path="protocol.json",
                cutoff_utc="2026-12-01T04:00:00Z",
                model_root=str(base/"missing-models"),
            )
        except Exception as ex:
            rejected=True
            error=str(ex)

        if not rejected:
            raise AssertionError("unsigned source attack unexpectedly accepted")
        if sentinel.exists():
            raise AssertionError("attacker worker executed before source authentication")

        sig=inspect.signature(admission_consumer.consume_verified_admission)
        if "decision" in sig.parameters:
            raise AssertionError("consumer still accepts arbitrary decision objects")
        if hasattr(admission_consumer,"assert_current_snapshot"):
            raise AssertionError("legacy arbitrary-decision consumer API still exists")
        try:
            admission_consumer.consume_verified_admission(
                decision={"admission_ready":True}
            )
        except TypeError:
            forged_injection_rejected=True
        else:
            raise AssertionError("forged decision injection unexpectedly accepted")

        print(json.dumps({
            "status":"VNEXT5R42_TRUST_BOOTSTRAP_REGRESSION_PASS",
            "approved_source_sha":approved,
            "attacker_source_sha":attacker,
            "unsigned_source_attack_rejected":True,
            "attacker_worker_executed":False,
            "consumer_arbitrary_decision_api_present":False,
            "forged_decision_injection_rejected":forged_injection_rejected,
            "error":error,
            "external_writes":False,
            "prospective_skill_proven":False,
            "trading_authority":False,
        },indent=2,sort_keys=True))


if __name__=="__main__":
    main()
