#!/usr/bin/env bash
# Self-test wrapper for repository-tools.
# Read-only: never installs packages, never alters the environment.
# If the scientific runtime (numpy/pandas/...) is missing, code self-checks
# are reported as SKIP and only --help + byte-compile checks run.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PY="${PYTHON:-python3}"
pass=0; fail=0; skip=0
say() { printf '%s\n' "$*"; }
ok() { pass=$((pass+1)); say "PASS: $*"; }
no() { fail=$((fail+1)); say "FAIL: $*"; }
sk() { skip=$((skip+1)); say "SKIP: $*"; }

say "== --help probes =="
if "$PY" repository-tools/reproduce.py --help >/dev/null 2>&1; then ok "reproduce.py --help"; else no "reproduce.py --help"; fi
if "$PY" repository-tools/validate_repository.py --help >/dev/null 2>&1; then ok "validate_repository.py --help"; else no "validate_repository.py --help"; fi

say "== byte-compile tool + module files =="
if "$PY" -m py_compile repository-tools/reproduce.py repository-tools/validate_repository.py \
  economic-atlas/src/a4_metrics.py economic-atlas/src/a5_graph.py economic-atlas/src/a6_temporal.py \
  shock-radar/src/r7_causal_signal.py shock-radar/src/d02_d03_detectors.py \
  shock-radar/src/r8_news_audit.py; then
  ok "py_compile (tools + 6 modules)"
else
  no "py_compile (tools + 6 modules)"
fi

say "== scientific runtime probe (no install, no env change) =="
if "$PY" -c "import numpy, pandas, sklearn, networkx, scipy, pyarrow" 2>/dev/null; then
  say "scientific runtime present: running module --self-check suite"
  if "$PY" repository-tools/reproduce.py --self-check; then
    ok "reproduce.py --self-check (all stages)"
  else
    no "reproduce.py --self-check (all stages)"
  fi
else
  sk "scientific runtime unavailable (numpy/pandas/...); compile-only mode, env untouched"
fi

say "== stdlib validator =="
if "$PY" repository-tools/validate_repository.py; then
  ok "validate_repository.py"
else
  no "validate_repository.py"
fi

say "selftest: pass=$pass fail=$fail skip=$skip"
[ "$fail" -eq 0 ]
