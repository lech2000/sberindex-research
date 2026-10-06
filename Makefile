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

JOINT_DATA_SENSE ?= data/raw/sberindex-data-sense-2025
JOINT_OUT ?= output/atlas-radar
.PHONY: atlas-radar
atlas-radar:
	$(PYTHON) repository-tools/atlas_radar_reproduce.py --data-sense-dir "$(JOINT_DATA_SENSE)" --out "$(JOINT_OUT)"

ABLATION_WAGES ?= data/external/tochno_bdmo_20260928/data_Y48423007_112_v20260928.parquet
ABLATION_EMPLOYMENT ?= data/external/tochno_bdmo_20260928/data_Y48423005_112_v20260928.parquet
ABLATION_OUT ?= output/atlas-radar-ablation
.PHONY: atlas-radar-ablation
atlas-radar-ablation:
	$(PYTHON) repository-tools/atlas_radar_ablation_reproduce.py --data-sense-dir "$(JOINT_DATA_SENSE)" --wages "$(ABLATION_WAGES)" --employment "$(ABLATION_EMPLOYMENT)" --out "$(ABLATION_OUT)"

H12_EQUAL_OUT ?= output/radar-h12-equal
.PHONY: radar-h12-equal
# Explicit fresh-fit target: 2160 CPU fits; existing make radar remains cached.
radar-h12-equal:
	$(PYTHON) repository-tools/radar_h12_equal_reproduce.py --raw "$(RADAR_RAW)" --r9 "$(RADAR_R9)" --national "$(RADAR_NATIONAL)" --out "$(H12_EQUAL_OUT)"
