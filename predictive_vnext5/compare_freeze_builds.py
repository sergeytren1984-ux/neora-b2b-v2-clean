"""Exact-byte comparison for two independent vNext5R1 freeze builds."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
CONTRACT=json.loads((HERE/"reproducibility_contract.json").read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def locate(root,name):
    hits=list(Path(root).rglob(name))
    if len(hits)!=1:
        raise RuntimeError(f"expected exactly one {name} under {root}, got {hits}")
    return hits[0]


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--a",required=True)
    p.add_argument("--b",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)

    files=CONTRACT["acceptance"]["exact_byte_match_required"]
    result={}
    mismatches=[]
    for name in files:
        pa=locate(args.a,name); pb=locate(args.b,name)
        sa=sha(pa); sb=sha(pb)
        equal=sa==sb and pa.read_bytes()==pb.read_bytes()
        result[name]={
            "build_a_sha256":sa,
            "build_b_sha256":sb,
            "exact_bytes_equal":bool(equal),
            "size_bytes":pa.stat().st_size,
        }
        if not equal:
            mismatches.append(name)

    report={
        "schema":"btc-predictive-vnext5r1-reproducibility-report-v1",
        "status":"PASS" if not mismatches else "FAIL",
        "independent_builds":2,
        "exact_byte_files":result,
        "mismatches":mismatches,
        "predictive_model_change":False,
        "historical_model_selection_change":False,
    }
    Path(args.output).write_text(
        json.dumps(report,indent=2,sort_keys=True)+"\n"
    )
    print(json.dumps(report,indent=2,sort_keys=True))
    if mismatches:
        raise SystemExit("exact-byte reproducibility failed")


if __name__=="__main__":
    main()
