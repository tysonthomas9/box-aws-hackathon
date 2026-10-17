"""Instant file-based progress check for a background hook."""
import argparse
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser();p.add_argument('target');p.add_argument('log');a=p.parse_args()
    log=Path(a.log).read_text() if Path(a.log).exists() else ''
    path=ROOT/a.target
    complete=path.exists()
    failed='Traceback (most recent call last)' in log or 'An error occurred (' in log
    print(json.dumps({'complete':complete,'failed':failed,'log_tail':log[-1600:]}))


if __name__=='__main__':main()
