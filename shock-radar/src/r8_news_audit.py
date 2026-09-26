"""R8: as-of аудит новостных событий shock-radar (НЕ прогноз, НЕ гейт).

Что делает:
  - читает events/news_events.json (N событий) и events/news_features.parquet;
  - strict_available = max(published_at, first_seen_at), потому что отдельного
    проверенного immutable archive available_at в данных НЕТ;
  - updated_at для исторической целостности НЕ используется, его достоверность
    помечается как unknown;
  - cutoff исключает future (strict_available > cutoff) и unknown (нет даты);
  - дедуп по (url, content_hash) идёт по версиям, отсортированным
    максимально причинно по strict_available: future-копия, известная
    раньше past-версии, не скрывает прошлое; дубликаты уходят в карантин;
  - quality_audit НЕЗАВИСИМ от cutoff: сканирует ВСЕ входные события,
    включая future, на suspected_topic_error (regex по title) и
    ambiguous_city_multi_tid; counts и items сохраняются в news_audit и
    quarantined.json отдельно от asof exclusion; eligible-правила те же;
  - география: city с >1 tid -> ambiguous audit (карантин, без молчаливого
    выбора одного города); region используется явно как регион, precise city
    из него НЕ выводится;
  - топик: natural_disaster на поздравлениях/профилактике/инструктажах/
    учебных рейдах/тренировках/готовности/рекомендациях -> карантин как
    suspected_topic_error БЕЗ silent relabel (исходный топик сохраняется);
  - пишет news_audit.json, quarantined.json, asof_features.parquet
    (колонки published/firstseen/strictavailable) + общий metrics.json;
  - НИКАКИХ forecast_metrics: news-only evaluation = NA, статус всегда
    PARTIAL_NOT_GATE_PASS, 0 eligible - валидный аудит, а не PASS R8;
  - проверка prefix invariance: статьи из будущего и правки после cutoff
    не могут менять прошлые фичи; shuffle-control только диагностический
    (evidence, не performance claim).

Модуль unit-safe: импорт не трогает файлы и argv; pandas/pyarrow нужны
только для чтения/записи parquet при реальном прогоне. `python
r8_news_audit.py --self-check` гоняет игрушечные датированные события
в памяти без входных файлов (future/duplicates/wrongtopic/ambiguouscity,
quality_audit всех входов включая future, dedup future-first не скрывает
past, future-контент с тем же url не меняет past включая фичи).
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

try:
    import pandas as pd
except ImportError:
    pd = None

RUN_ID = "R8-news-asof-audit"
STATUS = "PARTIAL_NOT_GATE_PASS"
COMPLETED_COMPONENTS = ["asof_audit", "temporal_controls"]
PENDING_COMPONENTS = [
    "causal_paired_forecasting",
    "ablations",
    "calendar",
    "strict_lag",
    "shuffle",
    "geography_reviewed",
]

NO_ARCHIVE_AVAILABLE_AT = True

ROUTINE_TITLE_RE = re.compile(
    r"поздравл|профилакти|инструктаж|рейд|учебн|трениров|тренировка|"
    r"готовност|рекоменд|безопасност.*мероприят|обеспеч.*безопасност|"
    r"встрет.*обществен|школьник.*поздрави|годовщин|праздник",
    re.IGNORECASE,
)


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _code_sha256():
    try:
        return _sha256(__file__)
    except NameError:
        return None


def _git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def _versions():
    v = {"python": sys.version.split()[0]}
    for name in ("pandas", "pyarrow", "numpy"):
        try:
            mod = __import__(name)
            v[name] = getattr(mod, "__version__", "present")
        except ImportError:
            v[name] = None
    return v


def parse_ts(s):
    if s is None or (isinstance(s, str) and not s.strip()):
        return None
    t = str(s).strip()
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    except ValueError:
        try:
            dt = datetime.strptime(str(s).strip(), "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_cutoff(s):
    dt = parse_ts(s)
    if dt is None:
        raise ValueError("bad --cutoff %r" % s)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s).strip()):
        dt = dt.replace(hour=23, minute=59, second=59, microsecond=0)
    return dt


def strict_available(ev):
    pub = parse_ts(ev.get("published_at"))
    seen = parse_ts(ev.get("first_seen_at"))
    if pub is None or seen is None:
        return None
    return pub if pub >= seen else seen


def quality_issue_of(ev):
    issues = []
    tids = ev.get("geography_tids") or []
    level = ev.get("geography_level")
    if level == "city" and len(tids) > 1:
        issues.append("ambiguous_city_multi_tid")
    topic = ev.get("topic")
    title = ev.get("title") or ""
    if topic == "natural_disaster" and ROUTINE_TITLE_RE.search(title):
        issues.append("suspected_topic_error")
    return issues


def quality_audit(events):
    items = []
    n_topic = 0
    n_amb = 0
    for i, ev in enumerate(events):
        url = ev.get("url") or ""
        for reason in quality_issue_of(ev):
            item = {"index": i, "url": url, "reason": reason}
            if reason == "ambiguous_city_multi_tid":
                item["tids"] = list(ev.get("geography_tids") or [])
                n_amb += 1
            elif reason == "suspected_topic_error":
                item["topic_original"] = ev.get("topic")
                item["title"] = ev.get("title") or ""
                item["note"] = ("routine/preventive content kept as-is, "
                                "no relabel")
                n_topic += 1
            sav = strict_available(ev)
            item["strict_available_at"] = sav.isoformat() if sav else None
            items.append(item)
    return {
        "n_events_scanned": len(events),
        "n_suspected_topic_error": n_topic,
        "n_ambiguous_city_multi_tid": n_amb,
        "n_items": len(items),
        "items": items,
    }


def audit_events(events, cutoff):
    eligible, quarantined, excluded = [], [], []
    seen_keys = {}
    def _causal_key(i):
        sav = strict_available(events[i])
        return (sav is None, sav.timestamp() if sav is not None else 0, i)
    order = sorted(range(len(events)), key=_causal_key)
    for i in order:
        ev = events[i]
        url = ev.get("url") or ""
        ch = ev.get("content_hash") or ""
        key = (url, ch)
        if key in seen_keys:
            quarantined.append({
                "index": i, "url": url,
                "reason": "duplicate_url_contenthash",
                "first_index": seen_keys[key],
            })
            continue
        seen_keys[key] = i
        sav = strict_available(ev)
        if sav is None:
            excluded.append({"index": i, "url": url,
                             "reason": "unknown_timestamp"})
            continue
        if sav > cutoff:
            excluded.append({"index": i, "url": url,
                             "reason": "future_strict_available",
                             "strict_available_at": sav.isoformat()})
            continue
        tids = ev.get("geography_tids") or []
        level = ev.get("geography_level")
        if level == "city" and len(tids) > 1:
            quarantined.append({
                "index": i, "url": url,
                "reason": "ambiguous_city_multi_tid",
                "tids": list(tids),
            })
            continue
        if not tids or level not in ("city", "region"):
            quarantined.append({
                "index": i, "url": url,
                "reason": "geo_unknown",
            })
            continue
        topic = ev.get("topic")
        title = ev.get("title") or ""
        if topic == "natural_disaster" and ROUTINE_TITLE_RE.search(title):
            quarantined.append({
                "index": i, "url": url,
                "reason": "suspected_topic_error",
                "topic_original": topic,
                "title": title,
                "note": "routine/preventive content kept as-is, no relabel",
            })
            continue
        eligible.append({
            "index": i, "url": url,
            "published_at": ev.get("published_at"),
            "first_seen_at": ev.get("first_seen_at"),
            "strict_available_at": sav.isoformat(),
            "topic_original": topic,
            "geography_level": level,
            "geography_tids": list(tids),
            "no_precise_city": bool(level == "region"),
        })
    return eligible, quarantined, excluded


def past_feature_rows(eligible, feature_rows):
    by_url = {}
    for r in feature_rows or []:
        by_url.setdefault(r.get("url"), []).append(r)
    out = []
    for e in eligible:
        for r in by_url.get(e["url"], []):
            out.append({
                "url": e["url"],
                "territory_id": r.get("territory_id"),
                "ym": r.get("ym"),
                "topic_original": e["topic_original"],
                "published_at": e["published_at"],
                "first_seen_at": e["first_seen_at"],
                "strict_available_at": e["strict_available_at"],
                "geography_level": e["geography_level"],
            })
    out.sort(key=lambda r: (str(r["url"]), str(r["territory_id"]),
                            str(r["ym"])))
    return out


def check_prefix_invariance(events, feature_rows, cutoff):
    past_elig, _, _ = audit_events(events, cutoff)
    past = past_feature_rows(past_elig, feature_rows)
    future_extra = []
    for e in events:
        c = dict(e)
        c["published_at"] = "2099-01-01T00:00:00Z"
        c["first_seen_at"] = "2099-01-02T00:00:00Z"
        c["updated_at"] = "2099-01-02T00:00:00Z"
        c["content_hash"] = "%s#future-%s" % (
            e.get("content_hash") or "nohash", e.get("url") or "nourl")
        future_extra.append(c)
    edited = []
    for e in events:
        c = dict(e)
        c["title"] = "%s [future edited version]" % (e.get("title") or "")
        c["topic"] = "edited_topic_future"
        tids = list(e.get("geography_tids") or [])
        tids.append("future-tid")
        c["geography_tids"] = tids
        c["first_seen_at"] = "2099-06-01T00:00:00Z"
        c["updated_at"] = "2099-06-01T00:00:00Z"
        c["content_hash"] = "%s#edited-future" % (
            e.get("content_hash") or "nohash")
        edited.append(c)
    again_elig, _, _ = audit_events(events + future_extra + edited, cutoff)
    again = past_feature_rows(again_elig, feature_rows)
    norm = lambda rows: sorted(
        json.dumps(r, sort_keys=True, default=str) for r in rows)
    if norm(past) != norm(again):
        raise AssertionError("future append / post-cutoff edit changed "
                             "past features")
    return True


def shuffle_control_diagnostic(rows, seed=20260926):
    import random
    rng = random.Random(seed)
    idx = list(range(len(rows)))
    rng.shuffle(idx)
    before = hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    after_rows = [rows[i] for i in idx]
    after_multi = hashlib.sha256(
        json.dumps(sorted([json.dumps(r, sort_keys=True, default=str)
                           for r in after_rows])).encode()).hexdigest()
    return {
        "diagnostic_only": True,
        "n_rows": len(rows),
        "seed": int(seed),
        "checksum_ordered": before,
        "checksum_multiset": after_multi,
        "performance_claim": None,
        "note": ("shuffle control is diagnostic evidence only, "
                 "not a performance claim"),
    }


def _write_parquet_or_csv(df, path_parquet):
    import os
    if pd is None:
        raise RuntimeError("pandas/pyarrow required for parquet IO")
    try:
        df.to_parquet(path_parquet, index=False)
        return path_parquet, "parquet"
    except Exception:
        csv_path = path_parquet.replace(".parquet", ".csv")
        df.to_csv(csv_path, index=False)
        return csv_path, "csv_fallback"


def build(news_events_path, news_features_path, outdir, cutoff_str):
    import os
    cutoff = parse_cutoff(cutoff_str)
    with open(news_events_path, encoding="utf-8") as f:
        events = json.load(f)
    if not isinstance(events, list):
        raise ValueError("news_events must be a JSON list")

    eligible, quarantined, excluded = audit_events(events, cutoff)
    qa = quality_audit(events)

    feature_rows, features_status = None, "not_read"
    n_feature_rows_total = None
    if pd is not None:
        try:
            fdf = pd.read_parquet(news_features_path)
            n_feature_rows_total = int(len(fdf))
            feature_rows = fdf.to_dict(orient="records")
            features_status = "read_parquet"
        except Exception as exc:
            features_status = "read_failed_%s" % type(exc).__name__
    else:
        features_status = "not_read_missing_pandas"

    past = past_feature_rows(eligible, feature_rows)
    check_prefix_invariance(events, feature_rows, cutoff)
    shuffle_evidence = shuffle_control_diagnostic(past)

    os.makedirs(outdir, exist_ok=True)
    run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    provenance = {
        "run_utc": run_utc,
        "command": " ".join(sys.argv),
        "cutoff": cutoff.isoformat(),
        "inputs": {
            "news_events": str(news_events_path),
            "news_events_sha256": _sha256(news_events_path),
            "news_events_n": len(events),
            "news_features": str(news_features_path),
            "news_features_sha256": _sha256(news_features_path),
            "news_features_rows": n_feature_rows_total,
            "news_features_status": features_status,
        },
        "code_sha256": _code_sha256(),
        "git_commit": _git_commit(),
        "versions": _versions(),
    }
    availability_note = (
        "strict_available=max(published_at, first_seen_at): no separate "
        "verified immutable archive available_at exists in the data "
        "(NO_ARCHIVE_AVAILABLE_AT=true); updated_at is NOT used for "
        "availability, its historical integrity is marked unknown")
    coverage = {
        "n_events_total": len(events),
        "n_eligible": len(eligible),
        "n_quarantined": len(quarantined),
        "n_excluded_future_unknown": len(excluded),
        "n_feature_rows_total": n_feature_rows_total,
        "n_asof_feature_rows": len(past),
        "quality_audit_all_inputs": {
            "n_events_scanned": qa["n_events_scanned"],
            "n_suspected_topic_error": qa["n_suspected_topic_error"],
            "n_ambiguous_city_multi_tid": qa["n_ambiguous_city_multi_tid"],
            "n_items": qa["n_items"],
        },
        "zero_eligible_is_valid_audit": True,
    }
    audit = {
        "run_id": RUN_ID,
        "cutoff": cutoff_str,
        "availability_rule": availability_note,
        "updated_at_historical_integrity": "unknown",
        "coverage": coverage,
        "quality_audit_all_inputs": qa,
        "eligible": eligible,
        "excluded": excluded,
        "checks": {
            "prefix_invariance_future_append_postcutoff_edit": True,
            "shuffle_control": shuffle_evidence,
        },
        "forecast_metrics": None,
        "forecast_metrics_note": ("no forecasts are built or claimed; "
                                  "news-only evaluation is NA"),
        "provenance": provenance,
    }
    with open(os.path.join(outdir, "news_audit.json"), "w",
              encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1)
    with open(os.path.join(outdir, "quarantined.json"), "w",
              encoding="utf-8") as f:
        json.dump({"run_id": RUN_ID, "cutoff": cutoff_str,
                   "n_quarantined": len(quarantined),
                   "items": quarantined,
                   "quality_audit_all_inputs": qa,
                   "note": ("quarantine preserves original topic/geo, "
                            "no silent relabel; ambiguous city stays "
                            "ambiguous, region never yields precise city; "
                            "quality_audit_all_inputs is cutoff-independent "
                            "and also covers future events"),
                   "provenance": provenance},
                  f, ensure_ascii=False, indent=1)

    asof_path, asof_fmt = None, None
    if pd is not None:
        cols = ["url", "territory_id", "ym", "topic_original",
                "published_at", "first_seen_at", "strict_available_at",
                "geography_level"]
        df = pd.DataFrame(past, columns=cols) if past else pd.DataFrame(
            {c: [] for c in cols})
        asof_path, asof_fmt = _write_parquet_or_csv(
            df, os.path.join(outdir, "asof_features.parquet"))

    metrics = {
        "run_id": RUN_ID,
        "status": STATUS,
        "gate_pass": False,
        "gate_pass_reason": ("R8 is an as-of news audit, not a forecasting "
                             "gate; PASS is forbidden by design, including "
                             "at 0 eligible events"),
        "completed_components": COMPLETED_COMPONENTS,
        "pending_components": PENDING_COMPONENTS,
        "news_only_evaluation": "NA",
        "na_reason": ("audit covers news as-of availability/coverage only; "
                      "no paired forecasting target exists at this stage"),
        "forecast_metrics": None,
        "coverage": coverage,
        "asof_features_file": asof_path,
        "asof_features_format": asof_fmt,
        "provenance": provenance,
    }
    with open(os.path.join(outdir, "metrics.json"), "w",
              encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": STATUS, "eligible": len(eligible),
                      "quarantined": len(quarantined),
                      "excluded": len(excluded),
                      "asof_rows": len(past),
                      "asof_file": asof_path},
                     ensure_ascii=False, indent=1))
    return audit, metrics


def self_check():
    toy = [
        {"url": "u-ok", "title": "Паводок подтопил дороги района",
         "published_at": "2024-03-01T00:00:00Z",
         "first_seen_at": "2024-03-02T00:00:00Z",
         "updated_at": "2024-03-02T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [7], "content_hash": "h1"},
        {"url": "u-future", "title": "Паводок",
         "published_at": "2025-06-01T00:00:00Z",
         "first_seen_at": "2025-06-02T00:00:00Z",
         "updated_at": "2025-06-02T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [7], "content_hash": "h2"},
        {"url": "u-unknown", "title": "Паводок",
         "published_at": None, "first_seen_at": "2024-01-01T00:00:00Z",
         "updated_at": "2024-01-01T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [7], "content_hash": "h3"},
        {"url": "u-ok", "title": "Паводок подтопил дороги района",
         "published_at": "2024-03-01T00:00:00Z",
         "first_seen_at": "2024-03-02T00:00:00Z",
         "updated_at": "2024-03-02T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [7], "content_hash": "h1"},
        {"url": "u-congrats",
         "title": "Школьники поздравили пожарных с Новым годом",
         "published_at": "2023-12-30T00:00:00Z",
         "first_seen_at": "2024-01-05T00:00:00Z",
         "updated_at": "2024-01-05T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [9], "content_hash": "h4"},
        {"url": "u-raid", "title": "Профилактические рейды проведены в городе",
         "published_at": "2023-12-30T00:00:00Z",
         "first_seen_at": "2024-01-05T00:00:00Z",
         "updated_at": "2024-01-05T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "region",
         "geography_tids": [100, 101], "content_hash": "h5"},
        {"url": "u-amb", "title": "Пожар в округе",
         "published_at": "2024-02-01T00:00:00Z",
         "first_seen_at": "2024-02-01T00:00:00Z",
         "updated_at": "2024-02-01T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [11, 12], "content_hash": "h6"},
        {"url": "u-region", "title": "Наводнение в области",
         "published_at": "2024-04-01T00:00:00Z",
         "first_seen_at": "2024-04-01T00:00:00Z",
         "updated_at": "2024-04-01T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "region",
         "geography_tids": [100, 101], "content_hash": "h7"},
    ]
    feats = [
        {"url": "u-ok", "territory_id": 7, "ym": "2024-03",
         "topic": "natural_disaster"},
        {"url": "u-region", "territory_id": 100, "ym": "2024-04",
         "topic": "natural_disaster"},
    ]
    cutoff = parse_cutoff("2024-12-31")
    elig, quar, excl = audit_events(toy, cutoff)
    assert [e["url"] for e in elig] == ["u-ok", "u-region"], elig
    reasons = sorted(q["reason"] for q in quar)
    assert reasons == ["ambiguous_city_multi_tid", "duplicate_url_contenthash",
                       "suspected_topic_error", "suspected_topic_error"], \
        reasons
    assert sorted(e["reason"] for e in excl) == [
        "future_strict_available", "unknown_timestamp"], excl
    qa = quality_audit(toy)
    assert qa["n_events_scanned"] == len(toy), qa
    qa_reasons = sorted(i["reason"] for i in qa["items"])
    assert qa_reasons == ["ambiguous_city_multi_tid",
                          "suspected_topic_error",
                          "suspected_topic_error"], qa_reasons
    fut_qa = quality_audit([
        {"url": "u-future-q", "title": "Поздравляем спасателей",
         "published_at": "2099-01-01T00:00:00Z",
         "first_seen_at": "2099-01-02T00:00:00Z",
         "topic": "natural_disaster", "geography_level": "city",
         "geography_tids": [5, 6], "content_hash": "hq"},
    ])
    assert fut_qa["n_suspected_topic_error"] == 1, fut_qa
    assert fut_qa["n_ambiguous_city_multi_tid"] == 1, fut_qa
    ok = [e for e in elig if e["url"] == "u-ok"][0]
    assert ok["strict_available_at"].startswith("2024-03-02"), ok
    reg = [e for e in elig if e["url"] == "u-region"][0]
    assert reg["no_precise_city"] is True
    past = past_feature_rows(elig, feats)
    assert len(past) == 2 and all(
        {"published_at", "first_seen_at", "strict_available_at"} <= set(
            r) for r in past), past
    assert check_prefix_invariance(toy, feats, cutoff) is True
    ev = shuffle_control_diagnostic(past)
    assert ev["diagnostic_only"] is True and ev["performance_claim"] is None
    empty_elig, _, _ = audit_events(
        [dict(toy[1])], cutoff)
    assert empty_elig == []
    fut_first = [dict(toy[0], published_at="2099-01-01T00:00:00Z",
                      first_seen_at="2099-01-02T00:00:00Z",
                      content_hash="h1"),
                 dict(toy[0])]
    ff_elig, ff_quar, ff_excl = audit_events(fut_first, cutoff)
    assert [e["url"] for e in ff_elig] == ["u-ok"], (ff_elig, ff_excl)
    assert len(ff_quar) == 1 and ff_quar[0]["reason"] == (
        "duplicate_url_contenthash"), (ff_quar, ff_excl)
    same_url_future = [dict(toy[0])] + [dict(
        toy[0], title="Паводок: будущая версия того же url",
        topic="edited_topic_future", geography_tids=[7, 999],
        published_at="2099-01-01T00:00:00Z",
        first_seen_at="2099-01-02T00:00:00Z",
        content_hash="h1-future-same-url")]
    sf_elig, _, _ = audit_events(same_url_future, cutoff)
    sf_past = past_feature_rows(sf_elig, feats)
    assert sf_past == past_feature_rows(
        audit_events([dict(toy[0])], cutoff)[0], feats), (sf_past, past)
    print("SELF-CHECK OK")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="R8: as-of audit of news events (no forecasts, "
                    "never a gate PASS)")
    p.add_argument("--news-events", default=None)
    p.add_argument("--news-features", default=None)
    p.add_argument("--cutoff", default="2024-12-31")
    p.add_argument("--outdir", default=None)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.news_events and a.news_features and a.outdir):
        p.error("--news-events, --news-features and --outdir are required")
    build(a.news_events, a.news_features, a.outdir, a.cutoff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
