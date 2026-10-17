"""Explicit live submission only; never used by test/lint or deployment."""

import argparse
import json
import os
import time

from kloop.train.runtime import service, session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args()
    if os.getenv("KLOOP_ALLOW_LIVE_TRAIN") != "yes":
        raise RuntimeError(
            "Live Train now is coordinator-sequenced; set KLOOP_ALLOW_LIVE_TRAIN=yes"
        )
    result = service(session()).start(args.request_id, int(time.time()))
    print(json.dumps(result.model_dump(mode="json")))


if __name__ == "__main__":
    main()
