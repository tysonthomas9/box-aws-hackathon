.PHONY: test lint format

test:
	uv run --locked pytest

lint:
	uv run --locked ruff check .
	uv run --locked ruff format --check .

format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .

.PHONY: answer-smoke
answer-smoke:
	uv run --locked python -m kloop.answer.smoke

AWS_PROFILE ?= box-hackathon
NAME_PREFIX ?= kloop
export AWS_PROFILE NAME_PREFIX

.PHONY: bootstrap build plan deploy destroy
bootstrap:
	uv run --locked python scripts/infra.py bootstrap

build:
	uv run --locked python scripts/infra_build.py

plan: build
	uv run --locked python scripts/infra.py plan

deploy: build
	uv run --locked python scripts/infra.py deploy

destroy:
	uv run --locked python scripts/infra.py destroy

include kloop/box/commands.mk

.PHONY: infra-smoke
infra-smoke:
	uv run --locked python scripts/infra.py smoke
