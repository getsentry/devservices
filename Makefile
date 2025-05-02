all: requirements-frozen.txt requirements-dev-frozen.txt

requirements-frozen.txt: requirements.txt
	.venv/bin/pip-compile --allow-unsafe --no-annotate --quiet --strip-extras requirements.txt -o requirements-frozen.txt

requirements-dev-frozen.txt: requirements.txt requirements-dev.txt
	.venv/bin/pip-compile --allow-unsafe --no-annotate --quiet --strip-extras requirements.txt requirements-dev.txt -o requirements-dev-frozen.txt
