import importlib.util,sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
SRC=Path(__file__).resolve().parents[1]/'shock-radar/src'
sys.path.insert(0,str(SRC))
import news_value_ablation as news

def event(**kwargs):
    return dict(publication_month='2024-04',tid=1,rate_delta=0.,historical_asof_verified=False,available_at=None,first_seen_at='2026-10-03T10:00:00+00:00',**kwargs)

def test_publication_date_cannot_override_historical_availability():
    e=event();assert not news.event_features([1,2],'2024-04',[e],'strict').any()
    e['historical_asof_verified']=True;e['available_at']='2024-04-06T10:00:00+00:00'
    assert not news.event_features([1,2],'2024-04',[e],'strict').any()
    e['first_seen_at']='2024-04-06T10:00:00+00:00'
    np.testing.assert_array_equal(news.event_features([1,2],'2024-04',[e],'strict'),[[1,0],[0,0]])

def test_future_events_and_delayed_control_cannot_move_into_past():
    e=event()
    assert not news.event_features([1],'2024-03',[e],'publication_proxy').any()
    assert not news.event_features([1],'2024-04',[e],'delayed_one_month').any()
    assert not news.event_features([1],'2024-12',[e],'shifted_twelve_months').any()
    e['publication_month']='2025-01';e['tid']=None;e['rate_delta']=1e8
    assert not news.event_features([1,2],'2024-12',[e],'publication_proxy').any()

def test_geography_is_exact_and_national_feature_does_not_multiply_event_count():
    e=event();np.testing.assert_array_equal(news.event_features([1,2],'2024-05',[e],'publication_proxy'),[[1,0],[0,0]])
    e['tid']=None;e['rate_delta']=2
    np.testing.assert_array_equal(news.event_features([1,2],'2024-05',[e],'publication_proxy'),[[0,2],[0,2]])
    assert not news.event_features([1,2],'2024-07',[e],'publication_proxy').any()

def test_ambiguous_municipality_is_rejected_before_news_features():
    e={'event_id':'x','entity_name':'town','scope':'municipality','source_claimed_published_date':'2024-04-06'}
    dictionary=pd.DataFrame({'territory_id':[1,2],'name_short':['town','town']})
    with pytest.raises(ValueError,match='ambiguous municipal'):news.compile_events({'events':[e]},dictionary)
    with pytest.raises(ValueError,match='duplicate event'):news.compile_events({'events':[e,e]},dictionary.iloc[:1])
