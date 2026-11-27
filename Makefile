PYTHON ?= .venv/Scripts/python.exe
PYTEST ?= .venv/Scripts/pytest.exe
RUFF ?= .venv/Scripts/ruff.exe

.PHONY: all audit lint test benchmarks clean

all: audit lint test benchmarks

audit:
	$(PYTHON) -m cli audit

lint:
	$(RUFF) check contracts rtl_studio sim_loop quartus_driver report_gen tests cli.py

test:
	$(PYTEST) -v tests/

benchmarks:
	$(PYTHON) -m cli run --spec benchmarks/lab_specs.yaml --all

clean:
	$(PYTHON) -c "import shutil, pathlib; [shutil.rmtree(p, ignore_errors=True) for p in [pathlib.Path('outputs/.work')]]"
