#!/usr/bin/env python3
# Name: chronyc sources status check
# Description: chronyc sources status must be valid.
"""Check chronyc sources on this host."""

from __future__ import annotations
from utils import exec_cmd, parse_csv_str

import os
import sys


CHRONYC_SOURCES_CSV_HEADER = "m,s,name,stratum,poll,reach,lastrx,last_sample1,last_sample2,last_sample3"


def parse_chronyc_sources_csv(chronyc_sources_csv_rows: str) -> list[dict]:
    return parse_csv_str(CHRONYC_SOURCES_CSV_HEADER, chronyc_sources_csv_rows)


def faulty_chronyc_sources(chronyc_sources: list[dict]) -> dict:
    faulty_sources = {"unreachable": [], "degraded": [], "delayed": []}
    for item in chronyc_sources:
        name = item["name"]
        if int(item["reach"]) == 0:
            faulty_sources["unreachable"].append(name)
        if int(item["stratum"]) > 2:
            faulty_sources["degraded"].append(name)
        if int(item["lastrx"]) > 0.5 * (int(item["poll"]) * 1000):
            faulty_sources["delayed"].append(name)
    return faulty_sources


def main() -> int:

    try:
        chronyc_sources = parse_chronyc_sources_csv(exec_cmd("chronyc -c sources"))
        if not chronyc_sources:
            print("Empty chronyc sources.")
            return 1
        faulty_sources = faulty_chronyc_sources(chronyc_sources)
        if any([faulty_sources["unreachable"], faulty_sources["degraded"], faulty_sources["delayed"]]):
            print(
                "Faulty sources found in chronyc.",
                f"  Unreachable: [{', '.join(faulty_sources['unreachable'])}]",
                f"  Degraded: [{', '.join(faulty_sources['degraded'])}]",
                f"  Delayed: [{', '.join(faulty_sources['delayed'])}]",
                sep="\n"
            )
            return 1
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    print("All sources in chronyc are ok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
