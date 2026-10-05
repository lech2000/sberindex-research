"""A13 input/receipt checks and independently stored numerical regression baseline."""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from atlas_a10 import primary_partitions
from atlas_common import (ATLAS, check_inputs, load_features, provenance,
                          run_dir, sha, verify_artifacts, write_json)


def measured():
    return {str(n):json.loads((run_dir(n)/"results.json").read_text()) for n in (9,10,11,12)}


def compare(expected, actual, path="root"):
    errors=[]
    if isinstance(expected,dict):
        if not isinstance(actual,dict) or set(expected)!=set(actual):
            return [path+": keys differ"]
        for k in expected:
            errors.extend(compare(expected[k],actual[k],path+"/"+k))
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(expected)!=len(actual):
            return [path+": list length differs"]
        for i,(e,a) in enumerate(zip(expected,actual)):
            errors.extend(compare(e,a,path+"/"+str(i)))
    elif isinstance(expected,float):
        if actual is None or not isinstance(actual,(float,int)) or not np.isclose(expected,actual,rtol=1e-7,atol=1e-8):
            errors.append(f"{path}: {expected} != {actual}")
    elif expected!=actual:
        errors.append(f"{path}: {expected!r} != {actual!r}")
    return errors


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=["check","freeze-regression","verify"])
    args=parser.parse_args()
    paths=check_inputs(external=True)
    if args.command=="check":
        load_features()
        print("7 frozen inputs and 5 protocol SHA-256 checks passed")
        return
    for n in (9,10,11,12):
        verify_artifacts(n)
    baseline=ATLAS/"expected_metrics.json"
    ids,_=load_features()
    if args.command=="freeze-regression":
        if baseline.exists():
            raise ValueError("Regression baseline already exists; atlas must not rewrite it")
        write_json(baseline,{"status":"POST_RUN_REGRESSION_BASELINE_NOT_SCIENTIFIC_CRITERIA",
                             "rtol":1e-7,"atol":1e-8,"results":measured()})
        pd.DataFrame({"territory_id":ids,**primary_partitions()}).to_parquet(ATLAS/"expected_partitions.parquet",index=False)
        print("Regression baseline frozen after first run; no scientific selection")
        return
    expected=json.loads(baseline.read_text())
    errors=compare(expected["results"],measured())
    labels=pd.read_parquet(ATLAS/"expected_partitions.parquet")
    if not np.array_equal(labels.territory_id,ids):
        errors.append("Baseline territory mask differs")
    else:
        for name,lab in primary_partitions().items():
            if adjusted_rand_score(labels[name],lab)!=1:
                errors.append("Baseline label partition differs: "+name)
    write_json(run_dir(13)/"results.json",{"status":"VERIFIED" if not errors else "FAILED",
        "input_checks":len(paths),"protocol_checks":5,"run_receipt_checks":4,
        "partition_checks":len(primary_partitions()),"errors":errors,
        "expected_metrics_sha256":sha(baseline),"expected_partitions_sha256":sha(ATLAS/"expected_partitions.parquet"),
        "rtol":1e-7,"atol":1e-8})
    provenance(13,external=True,dependencies=[run_dir(n)/"provenance.json" for n in (9,10,11,12)])
    if errors:
        raise ValueError("Regression failed: "+"; ".join(errors[:10]))
    print("atlas-verify: all values/statuses/counts match baseline, 19 label partitions ARI=1")


if __name__=="__main__":
    main()
