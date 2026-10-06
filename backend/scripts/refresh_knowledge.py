"""Daily governed source refresh; failures are visible as a nonzero job exit."""
from pathlib import Path
import os
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]


def main() -> int:
    scripts = ["ingest_govuk.py"]
    if os.getenv("GST_INGESTION_RIGHTS_APPROVED", "").lower() == "true":
        scripts.append("ingest_official.py")
    failed = False
    for script in scripts:
        result = subprocess.run([sys.executable, str(BACKEND / "scripts" / script)], cwd=BACKEND, check=False)
        failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
