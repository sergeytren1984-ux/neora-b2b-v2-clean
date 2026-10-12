"""V7R2 mandatory upstream source attestation before ANY new training release.

A matching metadata hash alone does not establish authorship. Verify actual
Cosign OIDC/Rekor bundle, exact identity and source SHA; explicitly reject
legacy unsigned Mac OI as a prospective-valid numerical training input.
"""
from __future__ import annotations
import hashlib,json,pathlib,subprocess
from btc_demand_v7.release_guard import certificate_source_sha

def verify_source(path,bundle,*,issuer,identity,source_sha,expected_digest):
    data=pathlib.Path(path).read_bytes()
    digest=hashlib.sha256(data).hexdigest()
    if digest!=expected_digest:
        raise RuntimeError("training input hash does not match signed manifest")
    if not pathlib.Path(bundle).is_file():
        raise RuntimeError("input source requires GitHub OIDC/Rekor signature")
    check=subprocess.run(["cosign","verify-blob",str(path),"--bundle",str(bundle),
        "--certificate-identity",identity,"--certificate-oidc-issuer",issuer],
        capture_output=True,text=True)
    if check.returncode:
        raise RuntimeError("source signature verification rejected "+str(path))
    if certificate_source_sha(bundle)!=source_sha:
        raise RuntimeError("upstream signer SHA not allowlisted")
    return {"sha256":digest,"signed":True,"source_sha":source_sha,"source_identity":identity}

def validate_train_sources(artifacts,manifest):
    if manifest.get("schema")!="btc-v7r2-training-input-allowlist-v1":
        raise RuntimeError("no frozen source policy")
    receipts={}
    for name in manifest["required"]:
        item=manifest["required"][name]
        path=pathlib.Path(artifacts)/item["raw"]
        bundle=pathlib.Path(artifacts)/item["bundle"]
        receipts[name]=verify_source(path,bundle,
            issuer="https://token.actions.githubusercontent.com",
            identity=item["identity"],
            source_sha=item["source_sha"],
            expected_digest=item["sha256"])
    if manifest.get("unsigned_derivatives_allowed") is not False:
        raise RuntimeError("unsigned historic derivatives cannot be training evidence")
    return {"status":"VERIFIED_SOURCES_ONLY",
            "can_train_with_unsigned_historical_oi":False,"receipts":receipts}
