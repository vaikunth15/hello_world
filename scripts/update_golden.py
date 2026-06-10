"""Regenerate the golden signal file. Review the diff before committing —
a changed golden file means strategy behavior changed."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.test_signals import GOLDEN, compute_golden  # noqa: E402

GOLDEN.parent.mkdir(parents=True, exist_ok=True)
GOLDEN.write_text(json.dumps(compute_golden(), indent=1) + "\n")
print(f"wrote {GOLDEN}")
