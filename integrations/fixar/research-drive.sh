#!/bin/bash
# Драйвер ворот Atlas/Radar: движет исследование по готовности, понятным ритмом.
# Telegram only on explicit HUMAN_REQUIRED.
#
# РИТМ (договор с владельцем 22.09.2026 — читается в журнале одной строкой):
# - каждые 2 часа: цепочка ходов каждого исследователя до первого BLOCKED/FAIL;
# - PASS по воротам → автозавершение связанного шага плана, сдвиг current_gate
#   в progress.json и СРАЗУ следующий ход по новым воротам (внутри того же
#   прогона, следующий тик таймера не ждём);
# - BLOCKED/FAIL, нет GATE_REPORT, ошибки инструментов/API — только запись
#   в журнал, БЕЗ Telegram; Telegram только если агент явно поставил в
#   GATE_REPORT строку HUMAN_REQUIRED: (нужно решение/доступ/согласие
#   владельца). Повтор того же project+gate+reason не шлём (дедуп в
#   /var/lib/fixar-cmd), изменённый reason — шлём. Цепочка СТОП до
#   следующего тика (модель впустую не долбим);
# - шаг со status=skipped в actions.json — не трогаем, идём дальше по depends_on.
# Пропущенный вручную шаг чинится кнопкой «Вернуть» в оболочке (локальный
# unskip) — драйвер пропуски не снимает и не ставит.
#
# ПРЕДЕЛЫ ЦЕПОЧКИ: не больше 4 ходов на проект за прогон (A2→A3→A4→A5) и не
# дольше 20 минут на проект — защита от убегания цепочки при вечных PASS.
set -uo pipefail

export PATH=/opt/node22/bin:$PATH
LOG=/var/log/fixar-cmd/research-drive.log
REPO=/opt/aios2
HUMAN_SEEN_DIR=/var/lib/fixar-cmd
mkdir -p "$HUMAN_SEEN_DIR" 2>/dev/null || true
TODAY=$(date -u +%F)
OWNER=prn_fbab9aa00cd46169

echo "$(date -Is) start research-drive $TODAY" >> "$LOG"

set -a; . /etc/fixar-cmd/service.env 2>/dev/null || true; set +a
API="${FIXAR_API_BASE:-http://10.189.141.153:8020}"
TOKEN="${AIOS_INTERNAL_SERVICE_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  echo "$(date -Is) no service token, skip" >> "$LOG"
  exit 0
fi
auth=(-H "X-AIOS-Service-Token: $TOKEN" -H 'Content-Type: application/json')

# Telegram-аларм владельцу: тот же приём, что у pack_watch.sh/breakage_watch.sh.
# Секрет — из service.env юнита (туда положен рядом со служебным токеном,
# 0600, внутрь контейнера выкладкой, а не руками): WATCH_BOT_TOKEN и
# WATCH_CHAT_ID. Запасной путь — ~/.aios-watch.env, если скрипт однажды
# запустят с хоста.
BOT=""; CHAT=""
for SRC in "${HOME:-/root}/.aios-watch.env" /etc/aios-watch.env; do
  [[ -r "$SRC" ]] || continue
  # shellcheck disable=SC1090
  . "$SRC"
  BOT="${WATCH_BOT_TOKEN:-}"; CHAT="${WATCH_CHAT_ID:-}"
  [[ -n "$BOT" && -n "$CHAT" ]] && break
done
if [[ -z "$BOT" || -z "$CHAT" ]]; then
  # service.env уже подтянут выше через set -a, токены едут тем же путём.
  BOT="${WATCH_BOT_TOKEN:-}"; CHAT="${WATCH_CHAT_ID:-}"
fi

say() {
  if [[ -z "$BOT" || -z "$CHAT" ]]; then
    echo "$(date -Is) ALARM-NOSEND (нет токена): $1" >> "$LOG"
    return 1
  fi
  if curl -s -f -o /dev/null -m 30 -X POST \
    "https://api.telegram.org/bot${BOT}/sendMessage" \
    --data-urlencode "chat_id=${CHAT}" \
    --data-urlencode "text=${1}" \
    --data "disable_web_page_preview=true" >/dev/null 2>/dev/null; then
    echo "$(date -Is) alarm sent: $(echo "$1" | head -c 120)" >> "$LOG"
    return 0
  else
    echo "$(date -Is) alarm SEND-FAIL: $(echo "$1" | head -c 120)" >> "$LOG"
    return 1
  fi
}

# Аларм о блокере: в журнал ВСЕГДА; в Telegram — ТОЛЬКО если агент явно
# поставил в GATE_REPORT строку HUMAN_REQUIRED: (нужно решение/доступ/
# согласие владельца). Рутинные BLOCKED/FAIL, нет GATE_REPORT, таймауты
# модели, ошибки инструментов/API — только журнал. 4-й аргумент — полный
# текст ответа агента (ищем HUMAN_REQUIRED: только в его GATE_REPORT).
# Дедуп: повтор того же project+gate+reason шлём один раз (файл состояния
# в $HUMAN_SEEN_DIR, запись атомарно), изменённый reason — шлём заново.
# После аларма цепочка останавливается, следующий шанс — по расписанию.
alarm_blocked() { # project, gate, reason [, agent_reply]
  local project="$1" gate="$2" reason="$3" agent_reply="${4:-}"
  local gate_block human_line=""
  echo "$(date -Is) $gate BLOCKED-log: $reason" >> "$LOG"
  if [[ -z "$agent_reply" || "$agent_reply" != *"GATE_REPORT"* ]]; then
    echo "$(date -Is) $gate BLOCKED-log-only (нет GATE_REPORT, Telegram молчит)" >> "$LOG"
    return 0
  fi
  gate_block=$(printf '%s\n' "$agent_reply" | sed -n '/GATE_REPORT/,$p')
  human_line=$(printf '%s\n' "$gate_block" | grep -i -m1 -E '^[[:space:]]*HUMAN_REQUIRED:.*' | head -c 300 || true)
  if [ -z "$human_line" ]; then
    echo "$(date -Is) $gate BLOCKED-log-only (GATE_REPORT без HUMAN_REQUIRED, Telegram молчит)" >> "$LOG"
    return 0
  fi
  local key_file="$HUMAN_SEEN_DIR/human-required-$project-$gate.seen" tmp
  if [ -f "$key_file" ] && [ "$(cat "$key_file" 2>/dev/null)" = "$human_line" ]; then
    echo "$(date -Is) $gate HUMAN_REQUIRED-dup (повтор, Telegram молчит)" >> "$LOG"
    return 0
  fi
  local text="ФиксАР, исследование $project встало на воротах $gate: $human_line. Следующий ход — по расписанию."
  if ! say "$text"; then
    echo "$(date -Is) $gate HUMAN_REQUIRED-send-fail (не отправлено, повтор на следующем тике)" >> "$LOG"
    return 1
  fi
  tmp=$(mktemp "$HUMAN_SEEN_DIR/.human-required-$project-$gate.XXXXXX" 2>/dev/null) || {
    echo "$(date -Is) $gate HUMAN_REQUIRED-state-fail (нет tmp, аларм отправлен)" >> "$LOG"
    return 0
  }
  printf '%s' "$human_line" > "$tmp" 2>>"$LOG" \
    && mv "$tmp" "$key_file" 2>>"$LOG" \
    || echo "$(date -Is) $gate HUMAN_REQUIRED-state-fail (не записал $key_file)" >> "$LOG"
  echo "$(date -Is) $gate BLOCKED-alarm: $human_line" >> "$LOG"
}

PROG="$REPO/deliverables/sberindex-2026/agents/progress.json"
ATLAS_GATE=$(jq -r '.projects["economic-atlas"].current_gate // "A1"' "$PROG" 2>/dev/null)
RADAR_GATE=$(jq -r '.projects["shock-radar"].current_gate // "R0"' "$PROG" 2>/dev/null)
ATLAS_STATUS=$(jq -r '.projects["economic-atlas"].status // ""' "$PROG" 2>/dev/null)
RADAR_STATUS=$(jq -r '.projects["shock-radar"].status // ""' "$PROG" 2>/dev/null)
ADAM_PROG="$REPO/deliverables/adam-research/adam-flybrain/actions.json"
ADAM_GATE=F5
ADAM_STATUS=""
if [ -f "$ADAM_PROG" ]; then
  ADAM_GATE=$(jq -r '[.[] | select(.status=="active") | .what | split(".")[0]] | first // "05"' "$ADAM_PROG" 2>/dev/null | sed 's/^0*//;s/^$/F5/;s/^[0-9]*$/F&/' 2>/dev/null || echo F5)
  [ "$ADAM_GATE" = "FF" ] && ADAM_GATE=F5
fi

# Карта «ворота → шаг плана дела»: какой act_* закрывает PASS этих ворот.
# Синхронизировано с actions.json обоих проектов 21.09.2026.
atlas_step_for_gate() {
  case "$1" in
    A1) echo "03";; A2) echo "03";; A3|A4) echo "04";;
    A5) echo "05";; A6) echo "06";; A7) echo "07";; A8) echo "08";;
    A9) echo "09;10";; A10) echo "11;12;13";; *) echo "";;
  esac
}
radar_step_for_gate() {
  case "$1" in
    R0) echo "02";; R1|R2) echo "03;04";; R3) echo "04";;
    R4) echo "05";; R5) echo "06";; R6) echo "08";; R7) echo "07";; R8) echo "08";;
    R9) echo "09;10";; R10) echo "11;12;13";; *) echo "";;
  esac
}
# Адам × flybrain: ворота F5–F10 → шаги 05–10 actions.json дела.
# F8 (контур, правка поведения) и F10 (Ева) drive сам НЕ закрывает:
# только BLOCKED/наблюдение до слова владельца — см. вызов ниже.
adam_step_for_gate() {
  case "$1" in
    F5) echo "05";; F6) echo "06";; F7) echo "07";;
    F8) echo "08";; F9) echo "09";; F10) echo "10";; *) echo "";;
  esac
}

# Последний GATE_REPORT хода: gate + status одной строкой, иначе пусто.
# Две формы: двоеточие (gate: F5 ... status: PASS) и таблица
# (| **gate** | F5 ... | **status** | **PASS** |). 22.09: F5-вердикт пришёл
# таблицей — парсер вернул пусто, лог ослеп, ложный PASS прошёл как «ok».
parse_gate_report() {
  python3 -c '
import sys, re
text = sys.stdin.read()
m = re.search(r"GATE_REPORT.*?gate:\s*(\S+).*?status:\s*(PASS|BLOCKED|FAIL)",
              text, re.S | re.I)
if not m:
    g = re.search(r"\*\*gate\*\*\s*\|\s*(\S+)", text, re.I)
    s = re.search(r"\*\*status\*\*\s*\|\s*\*{0,2}(PASS|BLOCKED|FAIL)\*{0,2}", text, re.I)
    if g and s:
        print(g.group(1) + " " + s.group(1).upper())
        sys.exit()
print((m.group(1) + " " + m.group(2).upper()) if m else "")
' 2>/dev/null
}

# Состояние шага дела по номеру ("03." в начале what) через служебный
# маршрут public_gateway: GET /internal/headless/cases/{id}/actions.
# Публичный GET /cases/{id}/actions со служебным токеном отвечает
# 401 no_token (24.09.2026), поэтому читаем ТОЛЬКО сюда и principal_id
# не передаём (дверь подставляет владельца сама). Печать:
# "open <id>" | "done <id>" | "missing"; выход 1 — транспорт/HTTP/JSON
# ошибка (вызывающий обязан дать BLOCKED, а не already done).
find_open_step() { # case_id, number -> "open|done|missing[ id]"
  local body code
  body=$(curl -sS -m 30 -w '\n%{http_code}' \
    "$API/internal/headless/cases/$1/actions" \
    "${auth[@]}" 2>>"$LOG") || {
      echo "$(date -Is) actions curl FAIL for $1" >>"$LOG"
      return 1
    }
  code=$(echo "$body" | tail -1)
  body=$(echo "$body" | sed '$d')
  if [ "$code" != "200" ]; then
    echo "$(date -Is) actions HTTP $code for $1: $(echo "$body" | head -c 200)" >>"$LOG"
    return 1
  fi
  if [ -z "$body" ]; then
    echo "$(date -Is) actions empty body for $1" >>"$LOG"
    return 1
  fi
  echo "$body" | jq -e 'type == "array"' >/dev/null 2>>"$LOG" || {
    echo "$(date -Is) actions bad JSON for $1: $(echo "$body" | head -c 200)" >>"$LOG"
    return 1
  }
  local line
  line=$(echo "$body" | jq -r --arg n "$2." \
    '.[]? | select((.what // "" | startswith($n))) | "\(.done) \(.id)"' \
    2>>"$LOG" | head -1) || {
      echo "$(date -Is) actions parse FAIL for $1 step $2" >>"$LOG"
      return 1
    }
  if [ -z "$line" ]; then
    echo "missing"
    return 0
  fi
  case "$line" in
    "false "*) echo "open ${line#false }" ;;
    "true "*) echo "done ${line#true }" ;;
    *)
      echo "$(date -Is) actions unexpected row for $1 step $2: $(echo "$line" | head -c 200)" >>"$LOG"
      return 1
      ;;
  esac
}

# Формальное нажатие «Готово» от имени владельца: закрывает существующий
# headless complete. Возврат: 0, если ответ done=true; иначе 1
# (вызывающий обязан дать BLOCKED, а не сдвигать ворота).
complete_step() { # case_id, action_id, gate
  local resp code
  resp=$(curl -sS -m 30 -X POST -w '\n%{http_code}' \
    "$API/internal/headless/cases/$1/actions/$2/complete" \
    "${auth[@]}" -d '{"reason":"GATE_REPORT '"$3"' PASS"}' 2>>"$LOG") || {
      echo "$(date -Is) $3 auto-complete $2 FAIL: curl error" >> "$LOG"
      return 1
    }
  code=$(echo "$resp" | tail -1)
  resp=$(echo "$resp" | sed '$d')
  if [ "$code" != "200" ]; then
    echo "$(date -Is) $3 auto-complete $2 FAIL: HTTP $code $(echo "$resp" | head -c 200)" >> "$LOG"
    return 1
  fi
  if echo "$resp" | jq -e '.done == true' >/dev/null 2>>"$LOG"; then
    echo "$(date -Is) $3 auto-complete $2 ok" >> "$LOG"
    return 0
  fi
  echo "$(date -Is) $3 auto-complete $2 FAIL: $(echo "$resp" | head -c 200)" >> "$LOG"
  return 1
}

# Сдвиг current_gate в progress.json после PASS: следующий ход цепочки идёт
# уже по новым воротам, следующий тик таймера не ждём.
advance_gate() { # project_key, new_gate
  local key="$1" gate="$2" tmp
  tmp=$(mktemp)
  jq --arg k "$key" --arg g "$gate" \
    '.projects[$k].current_gate = $g | .updated_at = (now | todate)' \
    "$PROG" > "$tmp" 2>>"$LOG" && mv "$tmp" "$PROG" \
    && echo "$(date -Is) $key gate -> $gate" >> "$LOG" \
    || echo "$(date -Is) $key gate advance to $gate FAIL" >> "$LOG"
}

# Следующие ворота по лестнице: A2->A3 ... A9->A10, R1->R2 ... R9->R10.
# Дальше A10/R10 цепочка останавливается — релиз собирает человек.
next_gate() { # gate -> next or empty
  case "$1" in
    A1) echo "A2";; A2) echo "A3";; A3) echo "A4";; A4) echo "A5";;
    A5) echo "A6";; A6) echo "A7";; A7) echo "A8";; A8) echo "A9";;
    A9) echo "A10";; A10) echo "";;
    R0) echo "R1";; R1) echo "R2";; R2) echo "R3";; R3) echo "R4";;
    R4) echo "R5";; R5) echo "R6";; R6) echo "R7";; R7) echo "R8";;
    R8) echo "R9";; R9) echo "R10";; R10) echo "";;
    *) echo "";;
  esac
}

drive_one() { # case_id, agent, version, gate, title, tool_hint, project, step_fn
  local case_id="$1" agent="$2" version="$3" gate="$4" title="$5" hint="$6"
  local project="$7" step_fn="$8"
  # Маршрут перепингует сам /internal/headless/dialog (у него внутренние
  # заголовки); здесь только ход. Версия в теле обязана совпадать с паком.
  # Инструмент — строго по воротам: перескок (cluster на A1) модель
  # отклоняет по лестнице, и правильно делает. Счёт/прогноз заказываем
  # только на воротах моделей (A4/R2), иначе — kb_search/каталог.
  local msg="Это плановый прогон research-drive (доверенный контур владельца).
Вызови РОВНО ОДИН инструмент прямо сейчас, без вопросов и подтверждений: \
$hint. Затем коротко зафиксируй измеренное и заверши \
GATE_REPORT $gate. Не перескакивай ворота. Строку HUMAN_REQUIRED: в \
GATE_REPORT ставь ТОЛЬКО если дальше никак без решения/доступа/согласия \
владельца, иначе никакого маркера."
  local body
  # message_id УНИКАЛЕН на тик (22.09): dialog-service дедуплицирует по
  # client_message_id и повторный тик с тем же id отвечает кэшем первого
  # хода вместо нового прогона — F5 получал stale-ответ вместо измерения.
  body=$(jq -n --arg c "$case_id" --arg t "$title" --arg m "$msg" \
    --arg a "$agent" --argjson v "$version" --arg o "$OWNER" \
    --arg mid "sberindex-drive-$gate-$TODAY-$(date -u +%H%M%S)" \
    '{case_id: $c, case_title: $t, message: $m, domain: "software",
      agent: $a, agent_version: $v, assurance: 2, principal_id: $o,
      client_message_id: $mid}')
  local resp
  resp=$(curl -sS -m 600 -X POST "$API/internal/headless/dialog" "${auth[@]}" -d "$body" 2>>"$LOG" || echo '{}')
  local reply
  reply=$(echo "$resp" | jq -r '.reply // empty' 2>/dev/null)
  # Возврат: "PASS <next>" — идти дальше; "BLOCKED <причина>" — журнал и стоп
  # (Telegram только при HUMAN_REQUIRED: в GATE_REPORT); "FAIL <причина>" —
  # то же; пусто — журнал и стоп, без Telegram.
  if ! echo "$reply" | grep -q "GATE_REPORT"; then
    echo "$(date -Is) $gate drive no-gate-report reply_chars=${#reply}" >> "$LOG"
    alarm_blocked "$project" "$gate" "нет GATE_REPORT (ответ ${#reply} знаков)" "$reply"
    echo "BLOCKED no-gate-report"
    return 0
  fi
  local parsed reported_gate reported_status
  parsed=$(echo "$reply" | parse_gate_report)
  reported_gate=$(echo "$parsed" | cut -d" " -f1)
  reported_status=$(echo "$parsed" | cut -d" " -f2)
  echo "$(date -Is) $gate drive ok (GATE_REPORT $parsed)" >> "$LOG"
  # ИНСТРУМЕНТАЛЬНЫЙ PASS (Адам, 22.09): вердикт без вызова инструмента —
  # галлюцинация, не измерение. PASS по F-воротам принимается только если
  # в ответе виден след вызова adam_kb_search (имя инструмента в тексте).
  # Иначе — unexpected-verdict, аларм, шаг не закрываем.
  if [ "$reported_status" = "PASS" ] && [[ "$gate" == F* ]]; then
    if ! echo "$reply" | grep -qi "adam_kb_search"; then
      echo "$(date -Is) $gate no-tool-pass: PASS без вызова adam_kb_search — вердикт недействителен" >> "$LOG"
      alarm_blocked "$project" "$gate" "PASS без инструмента: модель не вызывала adam_kb_search" "$reply"
      echo "BLOCKED no-tool-pass"
      return 0
    fi
  fi
  if [ "$reported_status" = "FAIL" ] || { [ "$reported_status" = "BLOCKED" ] && [ "$reported_gate" = "$gate" ]; }; then
    local reason
    reason=$(echo "$reply" | grep -i -m1 -o -E "(не хватает|нужн[оа]|нет [^.,]{5,80}|требуется[^.,]{5,80}|blocked[^.,]{5,120})" | head -c 200)
    [ -z "$reason" ] && reason="причина в журнале $LOG"
    alarm_blocked "$project" "$gate" "$reported_status: $reason" "$reply"
    if [ "$reported_status" = "BLOCKED" ] && [ "$reported_gate" = "$gate" ] && [ "$project" = "shock-radar" ] && [ "$gate" = "R7" ]; then
      local r7m="$REPO/deliverables/sberindex-2026/shock-radar/runs/R7/metrics.json" r7sha r7tmp
      if [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/metrics.json" ] && [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/manifest.json" ]; then
        r7m="$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/metrics.json"
      fi
      if [ -s "$r7m" ]; then
        r7sha=$(sha256sum "$r7m" 2>/dev/null | cut -d' ' -f1)
        if [ -n "${r7sha:-}" ]; then
          r7tmp=$(mktemp "$HUMAN_SEEN_DIR/.shock-radar-R7-blocked-metrics.XXXXXX" 2>/dev/null) && {
            printf '%s' "$r7sha" > "$r7tmp" 2>>"$LOG" \
              && mv "$r7tmp" "$HUMAN_SEEN_DIR/shock-radar-R7-blocked-metrics.sha" 2>>"$LOG" \
              && echo "$(date -Is) R7 BLOCKED-reviewed metrics SHA saved: $r7sha" >> "$LOG" \
              || echo "$(date -Is) R7 BLOCKED-reviewed metrics SHA save FAIL" >> "$LOG"
          } || echo "$(date -Is) R7 BLOCKED-reviewed metrics SHA save FAIL (нет tmp)" >> "$LOG"
        fi
      fi
    fi
    echo "BLOCKED $reason"
    return 0
  fi
  # PASS по ТЕКУЩИМ воротам → каждый требуемый source action должен быть
  # реально done, иначе BLOCKED без сдвига progress.json. Шаг со
  # status=skipped в actions.json пропускаем: 04 Радара уже закрыт делом
  # (F03 впереди графика), закрывать его повторно не нужно.
  if [ "$reported_status" = "PASS" ] && [ "$reported_gate" = "$gate" ]; then
    local numbers number step_id skipped
    if [ "$project" = "economic-atlas" ] && [ "$gate" = "A6" ]; then
      local a6mf_check="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6/temporal_manifest.json"
      [ -s "$a6mf_check" ] || a6mf_check="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6/manifest.json"
      if [ -s "$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/metrics.json" ] && [ -s "$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/manifest.json" ]; then
        a6mf_check="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/manifest.json"
      fi
      local e04_note=""
      e04_note=$(jq -r '.e04 // empty' "$a6mf_check" 2>>"$LOG")
      case "$(printf '%s' "$e04_note" | tr '[:upper:]' '[:lower:]')" in
        *incomplete*)
          alarm_blocked "$project" "$gate" "manifest E04_incomplete: source 06 не закрываем без full completion" "$reply"
          echo "BLOCKED e04-incomplete"
          return 0
          ;;
      esac
    fi
    numbers=$($step_fn "$gate")
    for number in $(echo "$numbers" | tr ';' ' '); do
      skipped=$(jq -r --arg n "$number" \
        '.[] | select((.what // "" | startswith($n + ".")) and .status == "skipped") | .what' \
        "$REPO/deliverables/sberindex-2026/$project/actions.json" 2>/dev/null | head -1)
      if [ -n "$skipped" ]; then
        echo "$(date -Is) $gate step $number skipped-by-owner, not touching" >> "$LOG"
        continue
      fi
      step_id=$(find_open_step "$case_id" "$number") || {
        alarm_blocked "$project" "$gate" "шаг $number: дело не прочиталось (см. журнал)" "$reply"
        echo "BLOCKED actions-read-fail"
        return 0
      }
      case "$step_id" in
        "open "*)
          if ! complete_step "$case_id" "${step_id#open }" "$gate"; then
            alarm_blocked "$project" "$gate" "шаг $number не закрылся (complete отказал)" "$reply"
            echo "BLOCKED complete-fail"
            return 0
          fi
          ;;
        "done "*) echo "$(date -Is) $gate step $number already done" >> "$LOG" ;;
        missing|*)
          alarm_blocked "$project" "$gate" "шаг $number не найден в деле" "$reply"
          echo "BLOCKED action-missing"
          return 0
          ;;
      esac
    done
    # PASS: сдвигаем ворота и СРАЗУ идём дальше — возврат "PASS <next>".
    # Ключ в progress.json совпадает с каталогом (economic-atlas/shock-radar).
    local next
    next=$(next_gate "$gate")
    if [ -n "$next" ]; then
      advance_gate "$project" "$next"
      echo "PASS $next"
    else
      echo "$(date -Is) $gate PASS, лестница кончилась — релиз собирает человек" >> "$LOG"
      say "ФиксАР, исследование $project: ворота $gate PASS, лестница пройдена до конца — релиз за вами."
      echo "PASS "
    fi
    return 0
  fi
  # PASS по другим воротам или без разбора — не цепочка, а повод разобраться.
  echo "$(date -Is) $gate unexpected: reported $parsed" >> "$LOG"
  alarm_blocked "$project" "$gate" "неожиданный вердикт: $parsed" "$reply"
  echo "BLOCKED unexpected-verdict"
}

# Цепочка проекта: ходы до первого BLOCKED/FAIL, не больше 4 ходов и 20 минут.
# project_key — ключ в progress.json (economic-atlas / shock-radar).
drive_chain() { # case_id, agent, version, gate, title, hint_fn, project_key, project_dir, step_fn
  local case_id="$1" agent="$2" version="$3" gate="$4" title="$5"
  local hint_fn="$6" project_key="$7" project_dir="$8" step_fn="$9"
  local moves=0 start_ts=$(date +%s) out next hint status r7_sha
  while [ $moves -lt 4 ]; do
    if [ $(( $(date +%s) - start_ts )) -gt 1200 ]; then
      echo "$(date -Is) $project_key chain: 20 минут вышло, стоп, остальное — по расписанию" >> "$LOG"
      break
    fi
    if [ "$project_key" = "economic-atlas" ] && [ "$gate" = "A5" ]; then
      if [ ! -s "$REPO/deliverables/sberindex-2026/economic-atlas/runs/A5/graph_manifest.json" ]; then
        echo "$(date -Is) RESEARCH_TASK A5 needs graph nodes/edges/weights, mobility crosswalk and connected-components audit (economic-atlas/runs/A5/graph_manifest.json absent/empty), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
        break
      fi
    fi
    if [ "$project_key" = "economic-atlas" ] && [ "$gate" = "A6" ]; then
      local a6m="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6/metrics.json"
      local a6mf="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6/temporal_manifest.json"
      [ -s "$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6/manifest.json" ] && [ ! -s "$a6mf" ] && a6mf="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6/manifest.json"
      if [ -s "$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/metrics.json" ] && [ -s "$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/manifest.json" ]; then
        a6m="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/metrics.json"
        a6mf="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A6_v2/manifest.json"
      fi
      if [ ! -s "$a6m" ] || [ ! -s "$a6mf" ]; then
        echo "$(date -Is) RESEARCH_TASK A6 needs transitions+lambda sensitivity (${a6m#"$REPO/deliverables/sberindex-2026/"}+${a6mf#"$REPO/deliverables/sberindex-2026/"} absent/empty), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
        break
      fi
      if ! jq -e . "$a6m" >/dev/null 2>>"$LOG" || ! jq -e . "$a6mf" >/dev/null 2>>"$LOG"; then
        echo "$(date -Is) RESEARCH_TASK A6 metrics/manifest JSON invalid (${a6m#"$REPO/deliverables/sberindex-2026/"}+${a6mf#"$REPO/deliverables/sberindex-2026/"}), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
        break
      fi
      local a6st a6mfst
      a6st=$(jq -r '.status // empty' "$a6m" 2>>"$LOG")
      a6mfst=$(jq -r '.status // empty' "$a6mf" 2>>"$LOG")
      case "$(printf '%s' "$a6st $a6mfst" | tr '[:upper:]' '[:lower:]')" in
        *partial*)
          echo "$(date -Is) RESEARCH_TASK A6 metrics/manifest status partial ($a6st $a6mfst, PARTIAL_NOT_GATE_PASS is not gate pass), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
          break
          ;;
      esac
    fi
    if [ "$project_key" = "shock-radar" ] && [ "$gate" = "R8" ]; then
      local r8m="$REPO/deliverables/sberindex-2026/shock-radar/runs/R8/metrics.json"
      if [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R8_v2/metrics.json" ] && [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R8_v2/manifest.json" ]; then
        r8m="$REPO/deliverables/sberindex-2026/shock-radar/runs/R8_v2/metrics.json"
      fi
      if [ ! -s "$r8m" ]; then
        echo "$(date -Is) RESEARCH_TASK R8 needs paired forecasting ablations and leakage checks (${r8m#"$REPO/deliverables/sberindex-2026/"} absent/empty, asof-audit alone is not full R8), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
        break
      fi
      if ! jq -e . "$r8m" >/dev/null 2>>"$LOG"; then
        echo "$(date -Is) RESEARCH_TASK R8 metrics.json JSON invalid (${r8m#"$REPO/deliverables/sberindex-2026/"}), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
        break
      fi
      local r8st
      r8st=$(jq -r '.status // empty' "$r8m" 2>>"$LOG")
      case "$(printf '%s' "$r8st" | tr '[:upper:]' '[:lower:]')" in
        *partial*)
          echo "$(date -Is) RESEARCH_TASK R8 metrics status partial ($r8st, PARTIAL_NOT_GATE_PASS is not gate pass, asof-audit alone is not full R8), chain stop without model/Telegram, curator can dispatch open action" >> "$LOG"
          break
          ;;
      esac
    fi
    if [ "$project_key" = "shock-radar" ] && [ "$gate" = "R7" ]; then
      local r7m="$REPO/deliverables/sberindex-2026/shock-radar/runs/R7/metrics.json"
      local r7mf="$REPO/deliverables/sberindex-2026/shock-radar/runs/R7/manifest.json"
      if [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/metrics.json" ] && [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/manifest.json" ]; then
        r7m="$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/metrics.json"
        r7mf="$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/manifest.json"
      fi
      if [ ! -s "$r7m" ] || [ ! -s "$r7mf" ]; then
        echo "$(date -Is) CODE_TASK R7 missing reproducible detectors (shock-radar/runs/R7/metrics.json+manifest.json absent/empty, F7b first), chain stop without model/Telegram" >> "$LOG"
        break
      else
        r7_sha=$(sha256sum "$r7m" 2>/dev/null | cut -d' ' -f1)
        if [ -n "${r7_sha:-}" ] && [ -f "$HUMAN_SEEN_DIR/shock-radar-R7-blocked-metrics.sha" ] && [ "$(cat "$HUMAN_SEEN_DIR/shock-radar-R7-blocked-metrics.sha" 2>/dev/null)" = "$r7_sha" ]; then
          echo "$(date -Is) R7 evidence-stable (metrics SHA $r7_sha already reviewed BLOCKED), skip duplicate model call, chain stop without model/Telegram" >> "$LOG"
          break
        fi
      fi
    fi
    hint=$($hint_fn "$gate")
    out=$(drive_one "$case_id" "$agent" "$version" "$gate" "$title" "$hint" "$project_dir" "$step_fn")
    status=$(echo "$out" | tail -1)
    moves=$((moves + 1))
    case "$status" in
      PASS\ *)
        next=$(echo "$status" | cut -d" " -f2)
        [ -z "$next" ] && break
        gate="$next"
        ;;
      *) break ;;
    esac
  done
  echo "$(date -Is) $project_key chain done: $moves ходов, ворота $gate" >> "$LOG"
}

atlas_hint() { # gate
  case "$1" in
    A4)
      local km="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A4/kmeans.json"
      local ag="$REPO/deliverables/sberindex-2026/economic-atlas/runs/A4/agglomerative.json"
      if [ -s "$km" ] && [ -s "$ag" ]; then
        echo "sberindex_atlas_kb_search(query=a4_gate:20260925_v2,limit=1) для $1 — квитанция project-corpus 75 document 13570 проверена, используй её и не выдумывай недостающие метрики, повторный кластер не запускать. Критерий PASS A4: два семейства кластеризации на одной маске 2190 территорий плюс assignments/prototypes и воспроизводимый runs/A4/metrics.json — эти артефакты на месте. Независимая экономическая валидация — это A9, не блокер A4. Если квитанция подтверждает эти факты — верни GATE_REPORT $1 PASS, драйвер сам закроет source action 04 через case-service"
      elif [ -s "$km" ]; then
        echo "sberindex_cluster(dataset=historical_spending,feature_set=shares,method=agglomerative,k=5,seed=20260921) для $1 — второй метод кластеризации МО, затем GATE_REPORT $1"
      else
        echo "sberindex_cluster(dataset=historical_spending, feature_set=shares, method=kmeans, k=5, seed=20260921) для $1 — базовая кластеризация МО по структуре расходов, затем GATE_REPORT $1"
      fi
      ;;
    A3) echo "sberindex_atlas_kb_search(query=Экономический атлас A3 признаки E01, limit=2) для $1" ;;
    A5) echo "sberindex_atlas_kb_search(query=a5_results:20260926,limit=1) для $1 — критерий PASS: graph_manifest + common-mask E01/E02/E03 + edge ablations; road-distance graph допустим, mobility excluded это не OD (исключение мобильности — не происхождение-destination); это не PASS по качеству экономики — экономика валидируется на A9. Используй квитанцию и не выдумывай метрики. Затем GATE_REPORT $1" ;;
    A6) echo "sberindex_atlas_kb_search(query=a6_results:20260926,limit=1) для $1 — критерий PASS: transitions + lambda sensitivity + synthetic shift; A6 — чувствительность временной связки, НЕ bootstrap (bootstrap — это A8); при fixed K births/split-merge неотличимы от переразметки и НЕ доказательство. Используй квитанцию и не выдумывай метрики. Затем GATE_REPORT $1" ;;
    *) echo "sberindex_data_catalog(dataset=historical_spending) — проверить схему панели для кроссволка $1" ;;
  esac
}

radar_hint() { # gate
  case "$1" in
    R7)
      if [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/metrics.json" ] && [ -s "$REPO/deliverables/sberindex-2026/shock-radar/runs/R7_v2/manifest.json" ]; then
        echo "sberindex_radar_kb_search(query=r7v2_results:20260926,limit=1) для $1 — отрицательный результат сравнения D01/D02/D03 допустим по ladder fallback detector without warning claim; нужны causal pretrain и val-calibrated monthly budget и три метода; run test exploratory, не production. Используй квитанцию R7_v2 и не выдумывай метрики, код не писать (код — только F7б). Затем GATE_REPORT $1"
      else
        echo "sberindex_radar_kb_search(query=r7_results:20260925,limit=1) — квитанция project-corpus 76 document 13566 с полными тестовыми метриками D01/D02/D03, используй её и не выдумывай недостающие результаты для $1, код не писать (код — только F7б). Затем GATE_REPORT $1"
      fi
      ;;
    R8) echo "sberindex_radar_kb_search(query=r8_results:20260926,limit=1) для $1 — asof-audit alone НЕ весь R8: нужны paired forecasting ablations и leakage checks; zero eligible news это NA, не эффект. Используй квитанцию и не выдумывай метрики. Затем GATE_REPORT $1" ;;
    R6) echo "sberindex_radar_kb_search(query=news-event-corpus 60 DISCOVERED 13259, limit=3) — отличить discovery от F06-ready для $1" ;;
    *) echo "sberindex_radar_kb_search(query=availability vintage published, limit=2) — свидетельства доступности для $1" ;;
  esac
}

case "$ATLAS_STATUS" in
  done|complete|released) echo "$(date -Is) atlas $ATLAS_STATUS, skip" >> "$LOG" ;;
  *) drive_chain "case_66cae4a89ba6473f" "sberindex_atlas_researcher" 5 "$ATLAS_GATE" "Экономический атлас муниципалитетов" \
    "atlas_hint" "economic-atlas" "economic-atlas" "atlas_step_for_gate" ;;
esac
case "$RADAR_STATUS" in
  done|complete|released) echo "$(date -Is) radar $RADAR_STATUS, skip" >> "$LOG" ;;
  *) drive_chain "case_008f37d03cf541e5" "sberindex_radar_researcher" 5 "$RADAR_GATE" "Радар потребительских сдвигов" \
    "radar_hint" "shock-radar" "shock-radar" "radar_step_for_gate" ;;
esac
# Адам × flybrain: ход каждые 2 часа рядом с Atlas/Radar. F8 (контур) и F10
# (Ева) drive сам НЕ закрывает — агент обязан вернуть BLOCKED до слова
# владельца; complete_step для 08/10 здесь не вызывается никогда.
# Цепочки у Адама НЕТ (посторонний контур, один ход за тик): drive_one зовём
# напрямую, его возврат PASS/BLOCKED здесь только для журнала.
case "$ADAM_STATUS" in
  *done*|*frozen*) echo "$(date -Is) adam $ADAM_STATUS, skip" >> "$LOG" ;;
  *)
    ADAM_HINT="adam_kb_search(query=fly_candidate goal_source F5, limit=3) — связь кандидата с целью для $ADAM_GATE"
    [ "$ADAM_GATE" = "F8" ] || [ "$ADAM_GATE" = "F10" ] && ADAM_HINT="adam_kb_search(query=ворота $ADAM_GATE слово владельца, limit=2) — только наблюдение, верни BLOCKED до слова владельца"
    if [ "$ADAM_GATE" = "F6" ]; then
      ADAM_EXP="$REPO/deliverables/adam-research/adam-flybrain/experiments.json"
      if [ ! -f "$ADAM_EXP" ]; then
        echo "$(date -Is) DATA_ERROR F6 experiments.json missing ($ADAM_EXP), stop without model/Telegram" >> "$LOG"
      elif ! E08_JSON=$(jq -c 'if type == "array" then ([.[] | select(.id=="E08")] | first // empty) else error("not array") end' "$ADAM_EXP" 2>>"$LOG"); then
        echo "$(date -Is) DATA_ERROR F6 experiments.json broken/unparseable, stop without model/Telegram" >> "$LOG"
      elif [ -z "${E08_JSON:-}" ] || [ "$E08_JSON" = "null" ]; then
        echo "$(date -Is) DATA_ERROR F6 E08 entry missing in experiments.json, stop without model/Telegram" >> "$LOG"
      else
        E08_STATUS=$(echo "$E08_JSON" | jq -r '.status // ""' 2>>"$LOG")
        E08_ART=$(echo "$E08_JSON" | jq -r '.artifact // ""' 2>>"$LOG")
        if [ "$E08_STATUS" != "completed" ] || [ -z "$(printf '%s' "${E08_ART:-}" | tr -d '[:space:]')" ] || [ "${E08_ART:-}" = "null" ]; then
          echo "$(date -Is) RESEARCH_TASK F6 needs E08 co-occurrence f×b/exo leave-one-episode-out; stop without model/Telegram" >> "$LOG"
        else
          ADAM_HINT="adam_kb_search(query=E08 f b exo leave-one-episode-out,limit=3) — связки f×b/exo leave-one-episode-out для F6; F5/E07 уже закрыт (completed 24.09), его не повторять"
          drive_one "case_2fe97ab4537544dc" "adam_flybrain_researcher" 1 "$ADAM_GATE" "Адам × flybrain" \
            "$ADAM_HINT" \
            "adam-flybrain" "adam_step_for_gate" >> "$LOG" 2>&1
        fi
      fi
    else
      drive_one "case_2fe97ab4537544dc" "adam_flybrain_researcher" 1 "$ADAM_GATE" "Адам × flybrain" \
        "$ADAM_HINT" \
        "adam-flybrain" "adam_step_for_gate" >> "$LOG" 2>&1
    fi
    echo "$(date -Is) adam one-shot done" >> "$LOG" ;;
esac

echo "$(date -Is) research-drive done" >> "$LOG"
exit 0
