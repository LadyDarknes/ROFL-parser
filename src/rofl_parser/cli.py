"""Command-line entry point for offline replay inspection."""

import argparse
from pathlib import Path

from . import timeline, transport
from .profiles.v16_23_841_8428 import PACKETS


def combat_packet_id(value: str) -> int:
    packet_id = transport.number(value, 0xFFFF)
    if packet_id not in PACKETS:
        raise argparse.ArgumentTypeError(f"no combat schema for packet 0x{packet_id:04x}")
    return packet_id


def run_combat(args: argparse.Namespace) -> int:
    from . import combat

    return combat.run(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rofl-parser", description="Inspect local League of Legends ROFL2 replays."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="list packets or export raw payloads")
    transport.add_arguments(inspect)
    inspect.set_defaults(run=transport.run)

    decode = commands.add_parser("combat", help="decode builds listed in the support table")
    decode.add_argument("replay", type=Path)
    decode.add_argument("--binary", required=True, type=Path, help="matching local PE snapshot")
    decode.add_argument("--packet-id", action="append", type=combat_packet_id, help="repeatable packet ID")
    decode.add_argument("--output", type=Path, help="new JSONL file; default: stdout")
    decode.add_argument("--limit", type=int, help="maximum number of decoded rows")
    decode.add_argument("--raw", action="store_true", help="include raw payload bytes as hex")
    decode.set_defaults(run=run_combat)

    report = commands.add_parser("timeline", help="sample player stats from an exported event stream")
    report.add_argument("replay", type=Path)
    report.add_argument("--events", type=Path, required=True, help="JSONL from the combat command")
    report.add_argument("--player-id", type=lambda value: transport.number(value, 0xFFFFFFFF))
    report.add_argument("--opponent-id", type=lambda value: transport.number(value, 0xFFFFFFFF))
    report.set_defaults(run=timeline.run)

    args = parser.parse_args(argv)
    if args.command == "combat" and args.limit is not None and args.limit < 1:
        decode.error("--limit must be at least 1")
    if args.command == "timeline" and args.opponent_id is not None:
        if args.player_id is None or args.opponent_id == args.player_id:
            report.error("--opponent-id requires a different --player-id")
    try:
        return args.run(args)
    except ImportError as exc:
        parser.exit(1, f"error: {exc}\n")
