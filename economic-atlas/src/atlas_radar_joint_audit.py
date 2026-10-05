"""Separate closed-form seasonal audit, with no use of the forecast implementation."""
from pathlib import Path
import json,hashlib,argparse
import pandas as pd
import numpy as np
a=argparse.ArgumentParser();a.add_argument('--repo',type=Path,required=True);a.add_argument('--data-sense-dir',type=Path,required=True);a.add_argument('--run',type=Path,required=True);args=a.parse_args()
R,S,O=args.repo,args.data_sense_dir,args.run
panel=pd.read_parquet(R/'economic-atlas/data/panel_v1.parquet')
res=pd.read_parquet(O/'selected-residuals.parquet');seasonal=res.loc[res.model=='category_seasonal']
med=panel.groupby(['category','ym']).value.median()
obs=panel.set_index(['territory_id','category','ym']).value
errors=[]
for r in seasonal.itertuples():
    previous_target=f'2023-{r.target[-2:]}'
    expected=float(obs.loc[(r.territory_id,r.category,'2024-03')])*float(med.loc[(r.category,previous_target)])/float(med.loc[(r.category,'2023-03')])
    errors.append(abs(expected-r.forecast))
    np.testing.assert_allclose(expected,r.forecast,rtol=1e-12,atol=1e-9)
    np.testing.assert_allclose(100*(r.actual/expected-1),r.residual_percent,rtol=1e-12,atol=1e-9)
for q in json.loads((O/'case-summary.json').read_text()):
    data=res.loc[(res.territory_id==q['territory_id'])&(res.category==q['category'])&(res.model==q['model'])]
    quarter=data.loc[data.target.isin(['2024-04','2024-05','2024-06'])]
    expected=100*(quarter.actual.sum()/quarter.forecast.sum()-1)
    np.testing.assert_allclose(q['quarter_residual_percent'],expected,rtol=1e-12,atol=1e-9)
# Independently check the A14 proof about the original A8 population input.
pop=pd.read_parquet(S/'2_bdmo_population.parquet')
pop=pop.loc[(pop.year==2024)&(pop.age=='Всего')&pop.territory_id.isin(panel.territory_id.unique())]
original=pop.groupby('territory_id').value.sum(min_count=2)
dedup=pop.drop_duplicates().groupby('territory_id').value.sum(min_count=2)
difference=original.loc[original.ne(dedup)&original.notna()&dedup.notna()]
dictionary=pd.read_parquet(S/'municipal_dictionary.parquet').set_index('territory_id')
current=dictionary.index[(dictionary.year_to==9999)&dictionary.index.isin(panel.territory_id.unique())]
np.testing.assert_allclose(original.reindex(current),dedup.reindex(current),rtol=0,atol=0,equal_nan=True)
changed=[{'territory_id':int(t),'year_to':int(dictionary.at[t,'year_to']),'original':float(original[t]),'deduplicated':float(dedup[t])} for t in difference.index]
assert {x['territory_id'] for x in changed}=={1240,1912}
report={'checked_at':'2026-10-05','place':'Mac, separate audit.py, frozen native panel/population/dictionary',
        'independent_closed_form_seasonal_forecasts':len(seasonal),'maximum_absolute_prediction_difference':max(errors),
        'independent_quarter_sums':36,'A8_population_input_invariance_current_codes':True,'changed_but_preexcluded':changed,
        'A8_current_code_population_count':len(current),'A8_full_statistics_recomputed':False,'scientific_pass':False}
(O/'independent-numeric-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False))
