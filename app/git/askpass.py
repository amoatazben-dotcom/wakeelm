"""Trusted Git-only credential helper; never located inside a project workspace."""

import os
import sys

if __name__ == "__main__":
    print(
        "x-access-token"
        if "username" in sys.argv[1].lower()
        else os.environ.get("WAKEELM_GIT_CREDENTIAL", "")
    )
