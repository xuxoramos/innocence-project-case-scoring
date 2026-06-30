"""Run the intake-flagging web UI: ``python -m risk_engine.ui``."""

from __future__ import annotations

import uvicorn


def main() -> None:  # pragma: no cover - process entry point
    uvicorn.run("risk_engine.ui.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
