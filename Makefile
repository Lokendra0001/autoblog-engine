CLIENT ?= bhandari
PORT ?= 8085

.PHONY: start dev test

start:
	@CLIENT=$(CLIENT) PORT=$(PORT) ./start.sh

dev:
	@CLIENT=$(CLIENT) PORT=$(PORT) ./start.sh

test:
	@./venv/bin/python -m unittest discover tests
