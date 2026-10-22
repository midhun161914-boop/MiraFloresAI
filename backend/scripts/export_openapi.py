"""Write the FastAPI OpenAPI schema to a file (no server, no packet load needed).

    python scripts/export_openapi.py ../frontend/src/api/openapi.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import create_app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(create_app().openapi(), indent=2), encoding="utf-8")
print(f"wrote {out}")
