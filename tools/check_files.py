"""
Check that this computer can read documents, and show what the app reads
from any files you give it.

    python tools/check_files.py path/to/notice.pdf [more files]
"""

from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import reader  # noqa: E402

print("Python:", sys.executable)
for mod in ["streamlit", "pypdf", "pypdfium2", "docx", "PIL", "pillow_heif", "numpy", "onnxruntime",
            "rapidocr_onnxruntime"]:
    try:
        m = importlib.import_module(mod)
        print(f"  {mod:22} {getattr(m, '__version__', 'installed')}")
    except Exception as exc:
        print(f"  {mod:22} MISSING ({exc.__class__.__name__}: {exc})")

for path in sys.argv[1:]:
    print("\n" + "=" * 70 + f"\n{path}")
    with open(path, "rb") as fh:
        data = fh.read()
    raw, method, warnings = reader.extract_text(os.path.basename(path), data)
    print(f"bytes: {len(data)}   method: {method}   warnings: {warnings}   characters read: {len(raw.strip())}")
    doc = reader.read(os.path.basename(path), data)
    print(f"kind: {doc.kind}")
    for k, v in doc.fields.items():
        if k != "demand":
            print(f"  {k}: {v}")
    print("first lines read:")
    print("\n".join("  | " + l for l in doc.text.strip().splitlines()[:12]))
