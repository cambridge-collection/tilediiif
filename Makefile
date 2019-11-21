python_dirs = tilediiif test_tilediiif integration_test

default: lint

format-python: isort black
# isort automatically groups & sorts Python imports (black intentionally
# doesn't do this).
isort:
	poetry run isort --recursive $(python_dirs)
black:
	poetry run black $(python_dirs)
check-black:
	poetry run black --check $(python_dirs)
check-isort:
	poetry run isort --check-only --recursive $(python_dirs)
flake8:
	poetry run flake8 $(python_dirs)
lint: check-isort check-black flake8
dist:
	poetry build
integration-test-target-venv:
	tox --recreate -e py37-target
integration-test: dist integration-test-target-venv
	tox -e py37-testrunner

.PHONY: format-python isort black check-black check-isort flake8 lint dist integration-test-target-venv integration-test
