"""Fail-closed source lock for v7 research. Must run BEFORE joblib.load.

Cryptographic verification of Sigstore bundles is performed separately by
cosign verify-blob (OIDC issuer and workflow identity). This guard additionally
enforces exact certificate source SHA and artifact hashes of the frozen release.
"""
from __future__ import annotations
import base64,hashlib,json,pathlib,re,subprocess,sys

FILE_KEYS={"candidate.joblib":"model_sha256",
           "audit.json":"audit_sha256",
           "spot_paired_validation_errors.json":"paired_sha256"}
BUNDLE_FILES={"candidate.joblib":"candidate.sigstore.json",
              "audit.json":"audit.sigstore.json",
              "spot_paired_validation_errors.json":"spot_paired_validation_errors.sigstore.json"}

def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def certificate_source_sha(bundle):
    obj=json.loads(pathlib.Path(bundle).read_text())
    material=obj.get("verificationMaterial",{})
    encoded=material.get("certificate",{}).get("rawBytes")
    if not encoded:raise RuntimeError("Sigstore certificate absent")
    der=base64.b64decode(encoded,validate=True)
    proc=subprocess.run(["openssl","x509","-inform","DER","-text","-noout"],
                        input=der,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if proc.returncode:raise RuntimeError("certificate decoding failed")
    output=proc.stdout.decode("utf-8",errors="replace")
    match=re.search(r"1\.3\.6\.1\.4\.1\.57264\.1\.3:\s*\n\s*([0-9a-f]{40})",output)
    if not match:raise RuntimeError("GitHub source commit extension missing")
    return match.group(1)

def check(root,manifest_path):
    root=pathlib.Path(root);mfile=pathlib.Path(manifest_path)
    m=json.loads(mfile.read_text())
    if m.get("schema")!="btc-v7r1-frozen-research-inputs-v1":
        raise RuntimeError("unrecognized frozen release manifest")
    if m.get("trading_authority") is not False or m.get("prospective_skill_proven") is not False:
        raise RuntimeError("unsanctioned trade/skill authority in manifest")
    if m.get("source_run_id")!=38169934478 or m.get("source_commit_sha")!="3d08e5a767f1848a9e10d6bea1ef939c2b77238a":
        raise RuntimeError("unexpected training run or source SHA")
    for name,key in FILE_KEYS.items():
        path=root/name
        if sha(path)!=m[key]:
            raise RuntimeError("mixed release or tampered SHA256: "+name)
        cert_sha=certificate_source_sha(root/BUNDLE_FILES[name])
        if cert_sha!=m["source_commit_sha"]:
            raise RuntimeError("signed file from different training source SHA: "+name)
    return {"schema":"btc-v7r1-verified-model-input-binding",
            "source_commit_sha":m["source_commit_sha"],
            "source_run_id":m["source_run_id"],
            "model_sha256":m["model_sha256"],
            "audit_sha256":m["audit_sha256"],
            "paired_sha256":m["paired_sha256"],
            "release_manifest_sha256":sha(mfile)}

if __name__=="__main__":
    if len(sys.argv)!=3:raise SystemExit("usage: python -m btc_demand_v7.release_guard ROOT TRUSTED_RELEASE_JSON")
    print("V7R1_RELEASE_GUARD_PASS",json.dumps(check(sys.argv[1],sys.argv[2]),sort_keys=True))
