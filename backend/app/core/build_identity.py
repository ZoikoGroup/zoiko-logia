"""Non-sensitive identity captured once per serving Python process."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import subprocess


def capture_build_identity(app_root: Path) -> dict[str, str]:
    digest = hashlib.sha256()
    for path in sorted(app_root.rglob('*.py')):
        digest.update(path.relative_to(app_root).as_posix().encode())
        digest.update(b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    revision = os.getenv('APP_REVISION') or os.getenv('RAILWAY_GIT_COMMIT_SHA')
    revision_file = app_root.parent / 'release_revision.txt'
    if not revision and revision_file.exists():
        revision = revision_file.read_text().strip()
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=app_root,
                                capture_output=True, text=True, timeout=2, check=True)
        commit = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = revision if revision and re.fullmatch(r'[a-fA-F0-9]{40,64}', revision) else 'unknown'
    revision = revision or commit
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', revision):
        revision = 'unknown'
    source_hash = digest.hexdigest()
    from app.domains.evaluation.gold_set_contamination import runtime_config_hash
    return {'revision': revision, 'commit': commit, 'source_hash': source_hash,
            'build_id': f'{revision}:{source_hash}',
            'config_hash': runtime_config_hash(app_root),
            'captured_at': datetime.now(timezone.utc).isoformat()}


@lru_cache(maxsize=1)
def process_build_identity() -> dict[str, str]:
    return capture_build_identity(Path(__file__).resolve().parents[1])
