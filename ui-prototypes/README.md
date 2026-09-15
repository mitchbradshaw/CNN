# ui-prototypes/ — frozen evidence archive

This directory is the record of the stack-selection prototypes for the UI rebuild (overnight
2026-09-14 → 15). It is kept as evidence and is not maintained.

- **Prototype A (React + TypeScript + FastAPI) moved to [`../webui/`](../webui/)** on 2026-09-15
  and is now the product web UI. Only its screenshots stay here, under
  `A-react-fastapi/screenshots/`, so the paths in `REPORT.md` §6 still resolve.
- **Prototype B (`B-panel/`) imports A's old path** (`../A-react-fastapi/server`) and is no longer
  expected to run. Its code, smoke test and screenshots are kept as they were.
- **[`REPORT.md`](REPORT.md) is the decision evidence** (scorecard §8); `DECISIONS.md` is the build log;
  `REAL_DATA_WRITES.md` inventories the files the prototype night wrote into the real `DATA/`.
- The decision itself is recorded in [`../docs/adr/0001-web-ui-stack.md`](../docs/adr/0001-web-ui-stack.md).
