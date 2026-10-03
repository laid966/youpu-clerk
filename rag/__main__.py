"""让 `python -m rag ...` 可用。"""

from rag.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
