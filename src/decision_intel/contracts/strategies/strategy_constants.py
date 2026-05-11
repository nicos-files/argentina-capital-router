from __future__ import annotations

import re

SCHEMA_VERSION = "1.0.0"
HORIZON_ENUM = ("SHORT", "MEDIUM", "LONG")
RULE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
