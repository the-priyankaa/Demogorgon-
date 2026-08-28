"""Measure core Buffer RSS for generated source files.

Run with: PYTHONPATH=src python scripts/bench_memory.py
"""
from __future__ import annotations
import gc
import os
import subprocess
import sys
import tempfile

SCRIPT = r'''
import gc, os, sys
sys.path.insert(0, "src")
from stdedit.buffer import Buffer
path = sys.argv[1]
edit = sys.argv[2] == "1"
b = Buffer(path)
if edit:
    b.move_to(0, 0)
    b.insert_char("x")
gc.collect()
with open("/proc/self/statm") as f:
    pages = int(f.read().split()[1])
print(pages * os.sysconf("SC_PAGESIZE"))
'''

def run(size: int, edit: bool = False) -> int:
    with tempfile.NamedTemporaryFile("wb", suffix=".c", delete=False) as f:
        path = f.name
        line = b"int main(void) { return 0; }\n"
        while f.tell() < size:
            f.write(line)
    try:
        out = subprocess.check_output([sys.executable, "-c", SCRIPT, path, "1" if edit else "0"], text=True)
        return int(out.strip())
    finally:
        os.unlink(path)

def fmt(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"

if __name__ == "__main__":
    print("stdedit core RSS benchmark")
    for size in (0, 1_000_000, 10_000_000, 50_000_000):
        rss = run(size, False)
        print(f"file={size / (1024 * 1024):6.1f} MB  open-rss={fmt(rss)}")
        if size >= 10_000_000:
            rss_edit = run(size, True)
            print(f"file={size / (1024 * 1024):6.1f} MB  edit-rss={fmt(rss_edit)}")
