.PHONY: train-live train-definition
train-live: export AWS_PROFILE := $(AWS_PROFILE)
train-live:
	uv run --locked python -m kloop.train.live --request-id "$(REQUEST_ID)"

train-definition:
	uv run --locked python -m kloop.train.workflow > infra/training.asl.json
