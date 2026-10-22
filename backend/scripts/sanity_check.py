"""Load the packet through the real loader and print what was validated.

Run from backend/:  .venv\\Scripts\\python scripts\\sanity_check.py
Exit code 0 = packet parsed into Pydantic models and every integrity check passed.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services.loader import PacketIntegrityError, load_packet  # noqa: E402


def main() -> int:
    t0 = time.perf_counter()
    try:
        idx = load_packet()
    except PacketIntegrityError as exc:
        print("FAIL", exc)
        return 1
    ms = (time.perf_counter() - t0) * 1000
    p = idx.packet

    n_docs, n_ev, n_ver = len(p.documents), len(p.extracted_values), len(p.return_versions)
    assert n_docs == 74, n_docs
    assert n_ev == 3012, n_ev
    assert n_ver == 3, n_ver

    print(f"Packet      : {p.packet.name} (client {p.packet.client_id}, packet v{p.packet.version})")
    print(f"Source      : {idx.source_path}  (read-only, never modified)")
    print(f"Load path   : {idx.load_path}")
    print(f"SHA-256     : {idx.sha256}")
    print(f"Validated   : Pydantic v2 Packet model in {ms:.0f} ms")
    print(f"ASSERT OK   : documents={n_docs}  extracted_values={n_ev}  return_versions={n_ver}")
    for v in p.return_versions:
        print(
            f"  {v.version}: {len(v.lines)} lines, {len(v.assets)} assets, "
            f"{len(v.diagnostics)} diagnostics, fed total tax {v.summary.federal.total_tax:,}"
            f"{'   <- current' if v.version == config.CURRENT_VERSION else ''}"
        )
    status = Counter(d.extraction.status for d in p.documents)
    print(f"Extraction  : {dict(status)}")
    print(f"Min conf.   : {min(e.confidence for e in p.extracted_values)}")
    matches = Counter(m.status for m in idx.text_matches.values())
    print(f"Text match  : {dict(matches)}  (text_as_read located in printed_content)")
    print("Integrity   : page counts, per-document value counts, unique ids, "
          "line sources/inputs/rules all consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
