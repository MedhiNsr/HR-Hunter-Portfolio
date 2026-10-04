import hashlib
import json
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "profile" / "candidate_cv_content.json"


@lru_cache(maxsize=1)
def verify_source_truth():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    source = profile["source_truth"]
    source_path = ROOT / source["original_file"]
    if not source_path.exists():
        raise RuntimeError(f"Immutable source CV is missing: {source_path}")
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    expected = source["sha256"].upper()
    if digest != expected:
        raise RuntimeError("Immutable source CV checksum mismatch; candidate generation is blocked.")
    return profile
