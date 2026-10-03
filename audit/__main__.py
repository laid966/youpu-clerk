"""让 `python -m audit ...` 可用。"""

from audit.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
