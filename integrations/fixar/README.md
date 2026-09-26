# ФиксАР и kb-forge: необязательная интеграция

Научные расчёты запускаются независимо от платформы. agents/, data/*sync*.py,
model-lab/*sync*.py и этот workflow — исходники ранее выполненных интеграций;
для исполнения нужны собственные endpoint/auth и права. Они не запускаются в CI.

Каноническое состояние действий — case-service. Репозиторий хранит датированные
снимки и receipts; они не являются живым кабинетом. Atlas/Radar версии5,
Graph/Curator3; n8n workflow пока закрепляет curator/steward2 по штатному pinned контракту.
MiMo Pro обслуживается платформенным мостом, ключ MiMo не копируется в этот репозиторий.

Редактирование исследовательского кода на платформе — через fixar-devops/F7b.
Выкладка на aios2 — только deploy_lock guard, существующая рабочая папка aiOS2
сохранена до отдельного переключения потребителей. Извлечение в отдельный GitHub
не останавливает текущие службы и не переключает автоматически hardcoded platform paths.

research-agents.yaml содержит только четыре исследовательских агента из software pack.
graph-steward-workflow.json — перенос workflow без секретов; перед импортом надо
подключить credentials в своей n8n. Никакие чужие направления пака сюда не перенесены.


Изменения 26.09.2026: native KB ответ для `research:` ключей компактный; переход к куратору сохраняет целые утверждения с исходными индексами и квитанцию в пределах 4000 символов. Живой проход R8 принят: corpus77/13894 и 13895, execution3278702. Гейт R8 остаётся открытым.

`research-drive.sh` — проверенная копия F7b-скрипта (prod commit3c85652cc). В production он установлен как `/usr/local/bin/fixar_research_drive.sh` в fixar-devops; выбирает A6_v2/R8_v2 только при наличии metrics и manifest, сохраняя стоп на частичном статусе. Научные файлы должны быть синхронизированы также в runtime fixar-devops, а не только в aios2.

Независимая проверка выражения n8n без запуска сети и агентов:

```sh
review_root="$(mktemp -d)"
mkdir -p "$review_root/n8n/workflows" "$review_root/scripts/tests"
cp integrations/fixar/graph-steward-workflow.json "$review_root/n8n/workflows/16_sberindex_graph_steward.json"
cp integrations/fixar/tests/curator_budget_test.cjs "$review_root/scripts/tests/sberindex_curator_budget_test.cjs"
node "$review_root/scripts/tests/sberindex_curator_budget_test.cjs"
bash -n integrations/fixar/research-drive.sh
```

Полное evidence хранится в корпусе77. Не вошедшие утверждения перечисляются в `omitted_claim_indexes` и не могут считаться проверенными. Невместимое даже без утверждений сообщение вызывает явную ошибку.
