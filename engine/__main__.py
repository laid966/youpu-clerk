"""让 `python -m engine ...` 可用。"""

from engine.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
