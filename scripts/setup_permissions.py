#!/usr/bin/env python3
from services.wordpress import ensure_permissions
import sys

if ensure_permissions():
    print("✅ Setup complete.")
else:
    print("❌ Setup failed — see logs.", file=sys.stderr)
    sys.exit(1)
