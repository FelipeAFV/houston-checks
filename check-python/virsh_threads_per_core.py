#!/usr/bin/env python3
# Name: virsh threads per core check
# Description: virsh threads per core must be valid.
"""Check virsh threads per core on this host."""

from __future__ import annotations
from utils import exec_cmd, parse_xml_str

import os
import re
import sys


THREADS_PER_CORE = os.environ.get("THREADS_PER_CORE", "2")


def main() -> int:

    try:
        xml_str = exec_cmd("docker exec nova_libvirt sh -c 'for d in $(virsh list --all --name); do virsh dumpxml $d; done'")
        if not xml_str:
            print("XMLs not found.")
            return 1

        faulty_domains_summary = []
        for element_tree in parse_xml_str(xml_str, "(?=<\?xml)|(?=<domain\s)"):

            xmlns, name, threads = "", "", ""

            try:
                xmlns = re.match(r"\{(.*)\}", element_tree.find("metadata/*").tag).group(1)
            except (SyntaxError, AttributeError):
                print("XML namespace not found.")

            try:
                name = element_tree.find("metadata/ns0:instance/ns0:name", namespaces={"ns0": xmlns}).text if xmlns else ""
            except (SyntaxError, AttributeError):
                print("VM name not found.")

            try:
                threads = element_tree.find("cpu/topology").attrib.get("threads", "")
            except (SyntaxError, AttributeError):
                print("VM threads not found.")

            if not threads:
                faulty_domains_summary.append(f"Faulty VM (xmlns: '{xmlns}', name: '{name}', thread/s: '{threads}').")
                continue

            if int(threads) < int(THREADS_PER_CORE):
                faulty_domains_summary.append(f"'{name}' has '{threads}' thread/s per core.")

        if faulty_domains_summary:
            print(f"VMs with less than '{THREADS_PER_CORE}' thread/s per core found.", *faulty_domains_summary, sep="\n  ")
            return 1
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Threads per core of all VMs are greater than or equal to '{THREADS_PER_CORE}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
