PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
RADAR_RAW ?= data/raw/sberindex-data-sense-2025/8_consumption.parquet
RADAR_R9 ?= data/frozen/radar/predictions-r9.parquet
RADAR_PILOT ?= data/frozen/radar/predictions-pilot.parquet
RADAR_DICTIONARY ?= data/frozen/radar/municipal-dictionary.parquet
RADAR_NATIONAL ?= data/raw/sberindex-national-20261005/consumer-spending.parquet
RADAR_BUNDLE ?=
RADAR_OUT ?= output/radar

.PHONY: radar radar-selfcheck
radar:
ifneq ($(strip $(RADAR_BUNDLE)),)
	$(PYTHON) repository-tools/radar_prepare.py --bundle "$(RADAR_BUNDLE)" --raw "$(RADAR_RAW)" --r9 "$(RADAR_R9)" --pilot "$(RADAR_PILOT)" --dictionary "$(RADAR_DICTIONARY)" --national "$(RADAR_NATIONAL)"
endif
	$(PYTHON) repository-tools/radar_reproduce.py --raw "$(RADAR_RAW)" --r9 "$(RADAR_R9)" --pilot "$(RADAR_PILOT)" --dictionary "$(RADAR_DICTIONARY)" --national "$(RADAR_NATIONAL)" --output-root "$(RADAR_OUT)"

radar-selfcheck:
	$(PYTHON) repository-tools/radar_reproduce.py --self-check
