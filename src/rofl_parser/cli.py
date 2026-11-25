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

    report = commands.add_parser("timeline", aliases=["match-report"],
                                 help="build a versioned report from an exported event stream")
    report.add_argument("replay", type=Path)
    report.add_argument("--events", type=Path, required=True, help="JSONL or JSONL.GZ from the combat command")
    report.add_argument("--output", type=Path, help="report path (match-report defaults to match_report.json)")
    identity = report.add_mutually_exclusive_group()
    identity.add_argument("--player-id", type=lambda value: transport.number(value, 0xFFFFFFFF))
    identity.add_argument("--riot-id", help="select a uniquely matched GameName#TagLine")
    report.add_argument("--verify-events", action="store_true", help="reject partial, filtered or reordered packet exports")
    report.add_argument("--opponent-id", type=lambda value: transport.number(value, 0xFFFFFFFF))
    report.add_argument("--casts", action="store_true", help="include observed Q/W/E/R cast rows and footer counters")
    report.add_argument("--cooldowns", action="store_true", help="include cooldown updates by spell slot")
    report.add_argument("--buffs", action="store_true", help="include buff applications, removals and stack updates")
    report.add_argument("--ezreal-q", action="store_true", help="include observed Mystic Shot outcomes")
    report.add_argument("--ezreal-w", action="store_true", help="include observed Essence Flux marks and detonations")
    report.add_argument("--positions", action="store_true", help="include observed position samples")
    report.add_argument("--attacks", action="store_true", help="include basic attack and projectile phase observations")
    report.add_argument("--death-windows", action="store_true", help="include the 30 seconds before each champion death")
    report.add_argument("--farm", action="store_true", help="include observed per-minion farming events")
    report.set_defaults(run=timeline.run)

    args = parser.parse_args(argv)
    if args.command == "combat" and args.limit is not None and args.limit < 1:
        decode.error("--limit must be at least 1")
    if args.command in {"timeline", "match-report"} and args.opponent_id is not None:
        if (args.player_id is None and args.riot_id is None) or args.opponent_id == args.player_id:
            report.error("--opponent-id requires a different player selected by --player-id or --riot-id")
    if args.command == "match-report":
        args.output = args.output or Path("match_report.json")
        for section in ("casts", "cooldowns", "buffs", "ezreal_q", "ezreal_w", "positions", "attacks", "death_windows", "farm"):
            setattr(args, section, True)
    try:
        return args.run(args)
    except ImportError as exc:
        parser.exit(1, f"error: {exc}\n")
