.PHONY: seed box-smoke

BOX_AUTH ?= ccg

seed:
	AWS_PROFILE=$${AWS_PROFILE:-box-hackathon} uv run --locked python -m kloop.box.cli seed --auth $(BOX_AUTH)

box-smoke:
	AWS_PROFILE=$${AWS_PROFILE:-box-hackathon} uv run --locked python -m kloop.box.cli smoke --auth $(BOX_AUTH)
