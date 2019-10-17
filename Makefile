format-python: black
black:
	poetry run black tilediiif test_tilediiif integration_test
check-black:
	poetry run black --check tilediiif test_tilediiif integration_test
flake8:
	poetry run flake8
lint: check-black flake8
