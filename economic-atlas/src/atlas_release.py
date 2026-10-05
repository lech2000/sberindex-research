"""Supplementary composition audit and reproducible, offline Atlas demonstration."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from atlas_common import ATLAS, clean, load_module, load_monthly, sha, write_json
from atlas_a12 import consensus_cores, coassociation, population_by_year

OUT = ATLAS / "runs/A14_release_20261005"
SITE = ATLAS / "site/atlas-20261005"
STORY_IDS = [1673, 1333, 2192, 1668, 2190, 1334]


def population_audit(ids, dic, raw):
    totals = raw[raw.territory_id.isin(ids) & raw.age.astype(str).eq("Всего") & raw.year.isin([2023, 2024])]
    correct = population_by_year(raw[raw.territory_id.isin(ids)]).reindex(ids)
    old = totals[totals.year.eq(2024)].groupby("territory_id").value.sum().reindex(ids)
    new = correct[2024]
    changed = old.ne(new)
    current = dic.year_to.eq(9999)
    assert old[current].equals(new[current]), "A8 effective population input changes"
    mod = load_module("release_a8", ATLAS / "runs/A8_wages2025_validation_20261005/run_a8.py")
    own = mod.own_partition_dec2024(str(ATLAS / "data/panel_v1.parquet")).reindex(ids)

    def orientation(pop):
        lp = np.log(pop)
        return bool(own[lp >= lp.median()].mean() > own[lp < lp.median()].mean())

    assert orientation(old) == orientation(new), "A8 secondary label orientation changes"
    table = pd.DataFrame({"territory_id":ids, "name":dic.name_short.to_numpy(),
                          "year_to":dic.year_to.to_numpy(), "population_old":old.to_numpy(),
                          "population_corrected":new.to_numpy(), "changed":changed.to_numpy(),
                          "a8_current_code":current.to_numpy()})
    table[table.changed].to_csv(OUT / "population_changes.csv", index=False)
    rec = {"status":"NO_EFFECT_ON_A8_EFFECTIVE_INPUT", "n_population_changed":int(changed.sum()),
           "changed_ids":table[table.changed].to_dict("records"),
           "exact_duplicate_rows_removed":int(totals.duplicated().sum()),
           "all_changed_excluded_before_a8_models":bool((~current[changed]).all()),
           "n_current_population_rows_identical":int(current.sum()),
           "secondary_label_orientation_old":orientation(old), "secondary_label_orientation_corrected":orientation(new),
           "proof":"All altered population values have year_to!=9999 and are excluded by the unchanged A8 mask. Current-code population values are exactly identical; secondary orientation is identical. No missingness changes. All subsequent numerical model inputs are unchanged.",
           "full_statistical_rerun":False,
           "limits":"Audit of input invariance; original 2025 statistical results retained, not a new independent test."}
    write_json(OUT / "a8_population_audit.json", rec)
    source = ATLAS / "runs/A8_wages2025_validation_20261005/run_a8.py"
    code = source.read_text()
    old_line = 'pop = pop[(pop["age"].astype(str) == "Всего") & (pop["year"] == 2024)].groupby("territory_id")["value"].sum()'
    assert code.count(old_line) == 1
    code = code.replace(old_line, 'from atlas_a12 import population_by_year\n    pop = population_by_year(pop[pop.territory_id.isin(tids)]).reindex(tids)[2024]')
    code = code.replace('"A8-wages2025-validation-20261005"', '"A8-population-corrected-release-20261005"')
    (OUT / "run_a8_corrected.py").write_text(code)
    write_json(OUT / "a8_correction_receipt.json", {"original_code_sha256":sha(source),
               "corrected_code_sha256":sha(OUT / "run_a8_corrected.py"),
               "change":"population input deduplication via audited A12 helper; statistical rules/seeds unchanged",
               "source_results_sha256":sha(source.parent / "results.json")})
    return correct, rec


def coverage_audit(ids, ds, dic):
    raw = pd.read_parquet(ds / "8_consumption.parquet")
    if raw.duplicated(["territory_id","date","category"]).any():
        raise ValueError("Duplicate spending keys")
    counts = raw.groupby("territory_id").size()
    full = set(counts[counts.eq(144)].index)
    sets = {name:set(pd.read_parquet(ds / filename, columns=["territory_id"]).territory_id.unique())
            for name,filename in [("population","2_bdmo_population.parquet"),("migration","3_bdmo_migration.parquet"),
                                  ("salary","4_bdmo_salary.parquet"),("market_access","1_market_access.parquet")]}
    joint = full.intersection(*sets.values())
    table=[]
    for tid in sorted(set(raw.territory_id)-set(ids)):
        reasons = ([] if tid in full else ["incomplete_spending_history"]) + ["absent_"+k for k,s in sets.items() if tid not in s]
        table.append({"territory_id":int(tid),"name":str(dic.name_short.get(tid,"")),"spending_rows":int(counts[tid]),
                      "full_spending":tid in full,"reasons":";".join(reasons) if reasons else "selection_reason_unresolved"})
    pd.DataFrame(table).to_csv(OUT / "coverage_exclusions.csv",index=False)
    rec={"raw_rows":len(raw),"raw_territories":len(counts),"full_spending_territories":len(full),
         "frozen_panel_territories":len(ids),"fully_observed_but_excluded":len(full-set(ids)),
         "full_and_context_intersection":len(joint),"intersection_exactly_equals_panel":joint==set(ids),
         "context_id_counts":{k:len(s) for k,s in sets.items()},
         "interpretation":"The contextual-ID intersection reproduces the frozen mask exactly." if joint==set(ids) else "Contextual intersection does not fully explain frozen mask; residual cases listed explicitly.",
         "limit":"Reconstructed filtering rule, not an original decision log. ID presence does not imply complete context values; primary panel remains unchanged."}
    write_json(OUT / "coverage_audit.json",rec)
    return rec


def supplementary_cores(ids, dic, months, shares):
    stories=load_module("release_a7",ATLAS / "runs/A7_stories_20261004/build_stories.py")
    normalized={norm:stories.normalise(shares,months,norm) for norm in stories.NORMS}
    subsets={"without_moscow":dic.region_code.to_numpy()!=77}
    for typ,n in dic.type.value_counts().items():
        if n>=50: subsets["type:"+typ]=dic.type.eq(typ).to_numpy()
    rows=[]
    memberships=[]
    for tag,mask in subsets.items():
        subids=ids[mask]
        for year in (2023,2024):
            month=f"{year}-12"; mi=months.index(month); cfg=[]
            for norm in stories.NORMS:
                x=normalized[norm][mask,mi,:]
                for k in stories.KS:
                    for family,offset in [("kmeans",off) for off in stories.SEEDS]+[("ward",0)]:
                        labels,_=stories.fit_month(x,k,family,stories.BASE_SEED+1000*offset+mi)
                        cfg.append(labels)
            labels,score,core=consensus_cores(coassociation(cfg))
            ref=pd.read_parquet(ATLAS / f"runs/A12_stable_cores_20261005/cores_{month}.parquet").set_index("territory_id").loc[subids]
            for threshold in (.8,.9,.95):
                take=np.isfinite(score)&(score>=threshold)
                rows.append({"subset":tag,"month":month,"n":len(subids),"threshold":threshold,
                             "n_core_refit":int(take.sum()),"fraction_refit":float(take.mean()),
                             "n_core_primary_restricted":int(ref[f"core_{threshold:.2f}"].sum()),
                             "ari_vs_primary_on_common_ids":float(adjusted_rand_score(ref.cluster,labels)),
                             "n_regions_core":int(dic.loc[subids[take],"region_code"].nunique())})
            memberships.extend({"subset":tag,"month":month,"territory_id":int(tid),"cluster":int(lab),
                                "score":float(s),"core90":bool(c)} for tid,lab,s,c in zip(subids,labels,score,core))
            print("supplementary",tag,month,len(subids),int(core.sum()),flush=True)
    pd.DataFrame(rows).to_csv(OUT / "composition_sensitivity.csv",index=False)
    pd.DataFrame(memberships).to_parquet(OUT / "supplementary_memberships.parquet",index=False)
    return rows


def neighbors(ids, annual, dic, pop):
    from scipy.spatial.distance import cdist
    typ=dic.type.to_numpy(); pp=pop[2024].to_numpy(float)
    eligibility=(typ[:,None]==typ[None,:])&(pp[None,:]>=.5*pp[:,None])&(pp[None,:]<=2*pp[:,None])
    np.fill_diagonal(eligibility,False)
    all_mask=np.ones_like(eligibility); np.fill_diagonal(all_mask,False)
    lists={}
    for mode,mask in [("all",all_mask),("matched",eligibility)]:
        lists[mode]={}
        for year in (2023,2024):
            dist=cdist(annual[year],annual[year])
            dist[~mask]=np.inf
            order=np.argsort(dist,axis=1,kind="stable")[:,:5]
            lists[mode][year]=[[{"id":int(ids[j]),"distance":float(dist[i,j])} for j in order[i] if np.isfinite(dist[i,j])]
                              for i in range(len(ids))]
    records=[]
    for i,tid in enumerate(ids):
        for mode in lists:
            a={v["id"] for v in lists[mode][2023][i]}; b={v["id"] for v in lists[mode][2024][i]}
            records.append({"territory_id":int(tid),"mode":mode,"n2023":len(a),"n2024":len(b),
                            "jaccard":len(a&b)/len(a|b) if a|b else None})
    pd.DataFrame(records).to_csv(OUT / "neighbor_stability.csv",index=False)
    return lists,records


def build_demo(ids,dic,months,shares,z,pop,lists,neighbor_records,audit,coverage,sensitivity):
    panel=pd.read_parquet(ATLAS / "data/panel_v1.parquet")
    total=panel[panel.category.eq("Все категории")].copy()
    total["m"]=pd.to_datetime(total.date).dt.strftime("%Y-%m")
    total=total.pivot(index="territory_id",columns="m",values="value").reindex(index=ids,columns=months)
    stories=json.loads((ATLAS / "runs/A7_stories_20261004/story_inputs.json").read_text())
    records={mode:{r["territory_id"]:r for r in neighbor_records if r["mode"]==mode} for mode in lists}
    core={year:pd.read_parquet(ATLAS / f"runs/A12_stable_cores_20261005/cores_{year}-12.parquet").set_index("territory_id").loc[ids] for year in (2023,2024)}
    data=[]
    for i,tid in enumerate(ids):
        row=dic.loc[tid]
        rec={"id":int(tid),"name":str(row.name_short),"region":str(row.region_name),"regionCode":int(row.region_code),
             "type":str(row.type),"lat":float(row.lat),"lon":float(row.lon),"yearTo":int(row.year_to),
             "population":{str(y):int(pop.loc[tid,y]) for y in (2023,2024)},
             "total":total.loc[tid].round(2).tolist(),"shares":np.round(shares[i]*100,4).tolist(),
             "core":{str(y):{"score":float(core[y].loc[tid,"mean_coassociation"]),"cluster":int(core[y].loc[tid,"cluster"])} for y in (2023,2024)},
             "neighbors":{mode:{str(y):clean(lists[mode][y][i]) for y in (2023,2024)} for mode in lists},
             "neighborJaccard":{mode:records[mode][int(tid)]["jaccard"] for mode in lists}}
        if str(row.name_short) in stories: rec["story"]=stories[str(row.name_short)]
        data.append(rec)
    source_a8=json.loads((ATLAS / "runs/A8_wages2025_validation_20261005/results.json").read_text())
    payload={"created":"2026-10-05","months":months,"categories":["Здоровье","Маркетплейсы","Общественное питание","Продовольствие","Транспорт"],
             "territories":data,"populationAudit":audit,"coverage":coverage,"sensitivity":sensitivity,
             "a8Primary":source_a8["primary"],"limits":["nominal spending indicator; per-person denominator unverified","point locations, not municipal polygons","2025 results are inherited; effective-input equality audited"]}
    SITE.mkdir(parents=True,exist_ok=True)
    write_json(SITE / "data.json",payload)
    template=(ATLAS / "site/atlas-20261005/template.html").read_text()
    literal=json.dumps(clean(payload),ensure_ascii=False,separators=(",",":"),allow_nan=False).replace("</","<\\/")
    (SITE / "index.html").write_text(template.replace("/*__ATLAS_DATA__*/",literal))
    return payload


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--inputs",required=True); ap.add_argument("--skip-refit",action="store_true")
    args=ap.parse_args(); ds=Path(args.inputs)
    os.environ["SBERINDEX_DATA_SENSE_DIR"]=str(ds)
    os.environ["SBERINDEX_MUNICIPAL_DICTIONARY"]=str(ds / "municipal_dictionary.parquet")
    OUT.mkdir(exist_ok=True)
    started=datetime.now(timezone.utc).isoformat()
    baseline={p:sha(ATLAS/p) for p in ["expected_metrics.json","expected_partitions.parquet","runs/A8_wages2025_validation_20261005/results.json"]}
    ids,months,shares,z,_=load_monthly()
    all_dic=pd.read_parquet(ds / "municipal_dictionary.parquet").set_index("territory_id")
    assert all_dic.index.is_unique
    dic=all_dic.loc[ids]
    pop,audit=population_audit(ids,dic,pd.read_parquet(ds / "2_bdmo_population.parquet"))
    print("A8 population audit",audit["status"],flush=True)
    coverage=coverage_audit(ids,ds,all_dic)
    print("coverage",coverage,flush=True)
    if args.skip_refit:
        sensitivity=pd.read_csv(OUT / "composition_sensitivity.csv").to_dict("records")
    else: sensitivity=supplementary_cores(ids,dic,months,shares)
    annual={y:z[:,[i for i,m in enumerate(months) if m.startswith(str(y))]].mean(1) for y in (2023,2024)}
    lists,records=neighbors(ids,annual,dic,pop)
    payload=build_demo(ids,dic,months,shares,z,pop,lists,records,audit,coverage,sensitivity)
    assert all(sha(ATLAS/p)==v for p,v in baseline.items()),"Primary baseline changed"
    inputs={p.name:sha(p) for p in ds.glob("*.parquet")}
    outputs={str(p.relative_to(ATLAS)):sha(p) for directory in (OUT,SITE) for p in directory.rglob("*") if p.is_file() and p.name!="provenance.json" and p.suffix!=".log"}
    write_json(OUT / "provenance.json",{"status":"SUPPLEMENTARY_EXPLORATORY","started_at_utc":started,
               "finished_at_utc":datetime.now(timezone.utc).isoformat(),"input_sha256":inputs,"baseline_sha256_unchanged":baseline,
               "protocol_sha256":sha(OUT / "PROTOCOL.md"),"code_sha256":sha(Path(__file__)),"output_sha256":outputs,
               "n_territories":len(payload["territories"]),"n_months":len(months),"raw_inputs_published":False})
    print("release data and offline page built",flush=True)


if __name__=="__main__": main()
