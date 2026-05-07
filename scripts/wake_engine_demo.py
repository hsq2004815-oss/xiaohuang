from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.wake_engine_demo_service import (
    build_demo_config,
    configure_output_encoding,
    list_devices,
    parse_args,
    print_dry_run,
    print_install_report,
    run_realtime_demo,
    run_safety_check,
)
from xiaohuang.openwakeword_adapter import check_openwakeword_dependencies

# Re-exports for test backward compatibility (tests import "wake_engine_demo" as a module)
from xiaohuang.wake_engine_demo_service import (
    DetectionStats,
    collect_install_statuses,
    collect_safety_check_result,
    print_detection_summary,
)
from xiaohuang.wake_engine_service import WakeEventCoalescer, WakeEventStats


def main(argv: Sequence[str] | None = None) -> int:
    configure_output_encoding()
    args = parse_args(argv)
    config = build_demo_config(args)
    if args.check_install:
        print_install_report(check_openwakeword_dependencies())
        return 0
    if args.list_devices:
        return list_devices()
    if args.dry_run:
        print_dry_run(config)
        return 0
    if args.safety_check:
        return run_safety_check(config, repeat=args.repeat, gap_seconds=args.gap_seconds)
    return run_realtime_demo(config)


if __name__ == "__main__":
    raise SystemExit(main())
