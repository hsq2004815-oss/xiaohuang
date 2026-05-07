from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from xiaohuang.control_panel_app import parse_args
from xiaohuang.control_panel_ui import run_control_panel

# Re-exports for test backward compatibility (tests import "control_panel" as a module)
from xiaohuang.control_panel_app import (
    OperationUiResult,
    StatusRefreshController,
    StatusRefreshResult,
    apply_operation_ui_result,
    clear_ready_state_error,
    collect_operation_ui_result,
    is_config_path_valid as _is_config_path_valid,
    resolve_operation_result_after_final_status,
    resolve_operation_result_after_statuses,
    show_operation_result,
)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    refresh_interval = args.refresh_interval if args.refresh_interval > 0 else 2.0
    return run_control_panel(
        PROJECT_ROOT,
        Path(args.config),
        refresh_interval,
        src_dir=str(SRC_DIR),
    )


if __name__ == "__main__":
    raise SystemExit(main())
