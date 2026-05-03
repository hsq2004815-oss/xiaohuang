from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.wake_command_bridge_service import (  # noqa: E402
    FakeCommandStarter,
    WakeCommandBridge,
    WakeCommandBridgeConfig,
)
from xiaohuang.wake_engine_service import WakeEvent  # noqa: E402


DEFAULT_EVENTS = 3
DEFAULT_INTERVAL_SECONDS = 0.5
DEFAULT_COOLDOWN_SECONDS = 2.5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate WakeEvent to command recorder bridging without touching XiaoHuang's main wake path.",
    )
    parser.add_argument("--events", type=positive_int, default=DEFAULT_EVENTS, help="Number of fake WakeEvents to send. Defaults to 3.")
    parser.add_argument(
        "--interval-seconds",
        type=nonnegative_float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Seconds between fake WakeEvents. Defaults to 0.5.",
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=nonnegative_float,
        default=DEFAULT_COOLDOWN_SECONDS,
        help="Bridge cooldown after an accepted WakeEvent. Defaults to 2.5.",
    )
    parser.add_argument("--simulate-tts", action="store_true", help="Mark TTS active before fake WakeEvents.")
    parser.add_argument("--simulate-command-active", action="store_true", help="Mark command recorder active before fake WakeEvents.")
    parser.add_argument("--simulate-error", action="store_true", help="Make the fake command starter raise on start.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved configuration only; do not run the state machine.")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed


def print_config(args: argparse.Namespace, *, dry_run: bool) -> None:
    print("bridge_demo=true")
    print(f"dry_run={_bool_text(dry_run)}")
    print(f"events={args.events}")
    print(f"interval_seconds={args.interval_seconds:g}")
    print(f"cooldown_seconds={args.cooldown_seconds:g}")
    print(f"simulate_tts={_bool_text(args.simulate_tts)}")
    print(f"simulate_command_active={_bool_text(args.simulate_command_active)}")
    print(f"simulate_error={_bool_text(args.simulate_error)}")
    print("will_open_microphone=false")
    print("will_start_openwakeword=false")
    print("will_start_stt_server=false")
    print("will_start_voice_overlay=false")
    print("will_call_llm=false")
    print("will_call_tts=false")


def run_bridge_demo(args: argparse.Namespace) -> int:
    print_config(args, dry_run=False)
    clock = FakeClock()
    starter = FakeCommandStarter(raise_on_start=bool(args.simulate_error))
    bridge = WakeCommandBridge(
        WakeCommandBridgeConfig(post_wake_cooldown_seconds=float(args.cooldown_seconds)),
        starter,
        time_fn=clock.now,
    )
    if args.simulate_tts:
        bridge.mark_tts_started()
    if args.simulate_command_active:
        bridge.mark_command_started()

    for event_index in range(1, int(args.events) + 1):
        event = build_fake_wake_event(event_index, detected_at=clock.current)
        decision = bridge.handle_wake_event(event)
        print(
            f"event_index={event_index} "
            f"decision={'accepted' if decision.accepted else 'suppressed'} "
            f"reason={decision.reason}"
        )
        clock.advance(float(args.interval_seconds))

    state = bridge.state()
    print(f"command_starts={starter.call_count}")
    print(f"accepted_count={state.accepted_count}")
    print(f"suppressed_count={state.suppressed_count}")
    print(
        "final_state "
        f"command_active={_bool_text(state.command_active)} "
        f"tts_active={_bool_text(state.tts_active)} "
        f"bridge_busy={_bool_text(state.bridge_busy)} "
        f"last_reason={state.last_reason or '-'}"
    )
    return 0


def build_fake_wake_event(index: int, *, detected_at: float) -> WakeEvent:
    return WakeEvent(
        engine_type="fake",
        wake_phrase="贾维斯",
        label="hey_jarvis",
        score=0.9,
        detected_at=detected_at,
        raw_event_count=index,
        suppressed_event_count=0,
    )


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def now(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += float(seconds)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    configure_output_encoding()
    args = parse_args(argv)
    if args.dry_run:
        print_config(args, dry_run=True)
        return 0
    return run_bridge_demo(args)


if __name__ == "__main__":
    raise SystemExit(main())
