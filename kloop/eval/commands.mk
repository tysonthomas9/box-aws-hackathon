MODE ?= without
SPLIT ?= hidden
.PHONY: eval-live
eval-live: export AWS_PROFILE := $(AWS_PROFILE)
eval-live:
	uv run --locked python -m kloop.eval.live --mode $(MODE) --split $(SPLIT)
