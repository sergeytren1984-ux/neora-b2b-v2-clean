"""Sigstore/OIDC verification helpers parameterized for audit and production refs."""
from __future__ import annotations
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

UTC=timezone.utc
ISSUER="https://token.actions.githubusercontent.com"


def bundle_time(path: Path):
    bundle=json.loads(Path(path).read_bytes())
    entries=bundle.get("verificationMaterial",{}).get("tlogEntries",[])
    if not entries:
        raise ValueError("Rekor entry missing")
    for entry in entries:
        proof=entry.get("inclusionProof")
        if not isinstance(proof,dict) or not proof.get("checkpoint") or "hashes" not in proof:
            raise ValueError("Rekor inclusion proof missing")
    return min(datetime.fromtimestamp(int(x["integratedTime"]),UTC) for x in entries)


def make_blob_verifier(*,repository:str,workflow_path:str,ref:str,trigger:str,repo_root:Path):
    identity=f"https://github.com/{repository}/{workflow_path}@{ref}"
    def verify(path:Path,bundle:Path,doc:dict):
        sha=str(doc.get("workflow_commit",""))
        if len(sha)!=40:
            raise ValueError("invalid workflow_commit")
        cmd=[
            "cosign","verify-blob",str(path),
            "--bundle",str(bundle),
            "--certificate-identity",identity,
            "--certificate-oidc-issuer",ISSUER,
            "--certificate-github-workflow-sha",sha,
            "--certificate-github-workflow-repository",repository,
            "--certificate-github-workflow-ref",ref,
            "--certificate-github-workflow-trigger",trigger,
        ]
        subprocess.run(cmd,check=True,capture_output=True,text=True,timeout=180,cwd=repo_root)
        return bundle_time(bundle)
    return verify


def sign_blob(path:Path,bundle:Path,*,repo_root:Path):
    subprocess.run(
        ["cosign","sign-blob","--yes","--bundle",str(bundle),str(path)],
        check=True,capture_output=True,text=True,timeout=180,cwd=repo_root,
    )
    return bundle_time(bundle)
