MODE ?= without
SPLIT ?= hidden
CORPUS ?= halvard
EVAL_OUTPUT ?= .intent/artifacts/medical-evaluation/$(VERSION_ID)/$(SPLIT)-$(MODE)
.PHONY: eval-live
eval-live: export AWS_PROFILE := $(AWS_PROFILE)
eval-live:
ifeq ($(CORPUS),medical)
	uv run --locked python -m kloop.eval.medical_live --version-id "$(VERSION_ID)" --mode $(MODE) --split $(SPLIT) --output "$(EVAL_OUTPUT)"
else
	uv run --locked python -m kloop.eval.live --mode $(MODE) --split $(SPLIT)
endif
