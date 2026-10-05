PYTHON ?= python3
export OPENBLAS_NUM_THREADS = 1
export OMP_NUM_THREADS = 1
export VECLIB_MAXIMUM_THREADS = 1
export PYTHONDONTWRITEBYTECODE = 1

.PHONY: atlas atlas-check atlas-a9 atlas-a10 atlas-a11 atlas-a12 atlas-test atlas-verify atlas-freeze-regression

atlas-check:
	$(PYTHON) src/atlas_a13.py check

atlas-a9: atlas-check
	$(PYTHON) src/atlas_a9.py

atlas-a10: atlas-check
	$(PYTHON) src/atlas_a10.py

atlas-a11: atlas-check
	$(PYTHON) src/atlas_a11.py

atlas-a12: atlas-check
	$(PYTHON) src/atlas_a12.py

atlas-test:
	$(PYTHON) -m pytest --noconftest -p no:cacheprovider -q ../tests/test_atlas_a9.py ../tests/test_atlas_a10.py ../tests/test_atlas_a11.py ../tests/test_atlas_a12.py ../tests/test_atlas_a13.py ../tests/test_atlas_network_icvi.py ../tests/test_atlas_network_audit.py ../tests/test_atlas_a8.py ../tests/test_atlas_stories.py

atlas-freeze-regression:
	$(PYTHON) src/atlas_a13.py freeze-regression

atlas-verify:
	$(PYTHON) src/atlas_a13.py verify

# Recursive invocations preserve order even with make -j.
atlas:
	$(MAKE) atlas-check
	$(MAKE) atlas-test
	$(MAKE) atlas-a9
	$(MAKE) atlas-a10
	$(MAKE) atlas-a11
	$(MAKE) atlas-a12
	$(MAKE) atlas-verify
