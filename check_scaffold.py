from pathlib import Path
import ast, json
root=Path(__file__).resolve().parent
projects = [slug for slug in ("economic-atlas", "shock-radar") if (root/slug).is_dir()]
assert projects, "No project found"
for slug in projects:
    p=root/slug
    c=json.loads((p/"config.json").read_text())
    e=json.loads((p/"experiments.json").read_text())
    a=json.loads((p/"actions.json").read_text())
    d=json.loads((p/"data-manifest.json").read_text())
    assert sum(c["rubric_weights"]) == 100
    assert c["results"] is None and not c["execution"]["enabled"]
    assert len({x["id"] for x in e}) == len(e)
    assert all(x["status"] in ("planned", "ready_to_run") and x["metrics"] is None for x in e)
    assert len(a)==14 and all(not x["done"] for x in a)
    assert all(x["status"] in ("planned", "active", "blocked", "skipped") for x in a)
    assert all("user_action" in x for x in a)
    assert d["case_id"].startswith("case_") and d["common_datasets"]
    assert all(int(dep)<idx+1 for idx,x in enumerate(a) for dep in x["depends_on"])
    assert len((p/"research-plan.md").read_text()) > 9000
    assert "Исследование ещё не выполнено" in (p/"landing/index.html").read_text()
    ast.parse((p/"src/contracts.py").read_text())
    print(slug, "OK:", len(e), "experiments;", len(a), "actions; weights=100")
