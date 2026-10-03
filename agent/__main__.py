"""让 `python -m agent ...` 可用。"""

from agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
