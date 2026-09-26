# Воспроизведение загрузки и аудита

Все команды запускаются из корня `ai_OS2`. Скрипты не удаляют существующие данные и пишут временные части отдельно.

```bash
# Публичный пакет конкурса Data Sense 2025
bash deliverables/sberindex-2026/data/download_sberindex_2025.sh

# Текущие публичные таблицы двух дашбордов СберИндекса
uv pip install --target /tmp/sberindex-python-deps pyarrow
PYTHONPATH=/tmp/sberindex-python-deps .venv/bin/python \
  deliverables/sberindex-2026/data/download_sberindex_current.py

# Большая сетка населения НИУ ВШЭ с проверкой ZIP
bash deliverables/sberindex-2026/data/download_hse_population_grid.sh

# Нормализация уже скачанных ответов ЦБ и календаря
python3 deliverables/sberindex-2026/data/prepare_supplementary_data.py

# Схемы, пропуски, SHA-256 и проектные манифесты
PYTHONPATH=/tmp/sberindex-python-deps .venv/bin/python \
  deliverables/sberindex-2026/data/build_catalog.py
```

`manifest.json` — источник статусов. `schema-report.json` содержит число строк, типы, пропуски и кардинальности ключевых полей. Большие бинарные файлы не кладутся в kb-forge: там индексируются `DATA_CATALOG.md`, проектные манифесты, планы и проверенные аналитические выводы.

Созданы семантические корпуса kb-forge: общий `74`, Атлас `75`, Радар `76`. Политика наполнения и план инструментов — в `SEMANTIC_CORPORA.md`, подтверждение — в `semantic-corpora-receipts.json`. Идемпотентная настройка выполняется `setup_semantic_corpora.py` на хосте, где доступен kb-forge.
