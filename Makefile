.PHONY: help check parse lint lint-python lint-yaml lint-prettier format-proofs format-prettier test test-unit test-render-performance clean

UV ?= uv
UV_CACHE_DIR ?= .uv-cache
UV_RUN ?= $(UV) run --active
PYTHON ?= $(UV_RUN) python
PYTEST ?= $(UV_RUN) pytest
PRETTIER ?= npx --yes prettier

PROOF_DB_GLOBS := '**/*.proof' '**/*.proofs' '**/*.manifest'
PY_FILES := $(shell find elements/pl-proof-yaml/pl_proof_yaml -name '*.py' -not -path '*/__pycache__/*')

help:
	@printf '%s\n' \
		'Targets:' \
		'  check        Run parser validation, linters, and tests' \
		'  parse        Parse all .proof, .proofs, and .manifest files' \
		'  lint         Run Python syntax checks, YAML proof linting, and Prettier checks' \
		'  lint-python  Byte-compile Python parser/test/source files' \
		'  lint-yaml    Run the YAML proof linter without rewriting files' \
		'  lint-prettier Check .proof, .proofs, and .manifest files with Prettier as YAML' \
		'  format       Rewrite all proofs and then format with prettier' \
		'  format-proofs  Rewrite all proofs with proof_yaml_parser.linter' \
		'  format-prettier Format .proof, .proofs, and .manifest files with Prettier as YAML' \
		'  test         Run pytest' \
		'  test-unit    Run pytest filtered to proof_yaml_parser tests' \
		'  test-render-performance  Benchmark end-to-end rendering of contradiction proofs' \
		'  clean        Remove Python cache directories'

check: parse lint test

parse:
	$(PYTHON) -c "import glob, shlex; from pl_proof_yaml.proof_yaml_parser.parse import loads; patterns = shlex.split(\"$(PROOF_DB_GLOBS)\"); paths = sorted({path for pattern in patterns for path in glob.glob(pattern, recursive=True)}); [print(f'{path}: {len(loads(path))} theorem(s)') for path in paths]"

lint: lint-python lint-yaml lint-prettier

lint-python:
	$(PYTHON) -c "import ast, pathlib, warnings; warnings.filterwarnings('ignore', category=SyntaxWarning); files = [pathlib.Path(path) for path in '$(PY_FILES)'.split()]; [ast.parse(path.read_text(encoding='utf-8'), filename=str(path)) for path in files]; print(f'Checked {len(files)} Python file(s).')"

lint-yaml:
	@for pattern in $(PROOF_DB_GLOBS); do $(PYTHON) -m pl_proof_yaml.proof_yaml_parser.linter "$$pattern" >/dev/null || exit; done

lint-prettier:
	$(PRETTIER) --check --parser yaml $(PROOF_DB_GLOBS)

format: format-proofs format-prettier

format-proofs:
	@for pattern in $(PROOF_DB_GLOBS); do $(PYTHON) -m pl_proof_yaml.proof_yaml_parser.linter "$$pattern" --in-place || exit; done

format-prettier:
	$(PRETTIER) --write --parser yaml $(PROOF_DB_GLOBS)

test:
	$(PYTEST)

test-unit:
	$(PYTEST) elements/pl-proof-yaml/pl_proof_yaml/proof_yaml_parser/tests

test-render-performance:
	$(PYTHON) scripts/benchmark-render.py

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	find . -type d -name *.egg-info -prune -exec rm -rf {} +
