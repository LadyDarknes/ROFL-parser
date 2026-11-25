import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rofl_parser.cli import main
from rofl_parser.coaching import entity_catalog, minion_history


def event(t, event_name, **fields):
    return {"t": t, "event": event_name, "fields": fields}


class CoachingTests(unittest.TestCase):
    def test_match_report_output_is_versioned_and_preserves_existing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            replay = folder / "EUW1-123.rofl"
            source = folder / "events.jsonl"
            output = folder / "match_report.json"
            source.write_text("", encoding="utf-8")
            fake_replay = SimpleNamespace(
                path=replay, version="16.23.841.8428", participants=(),
                metadata={"gameLength": 1000},
            )
            with patch("rofl_parser.timeline.Replay.open", return_value=fake_replay):
                self.assertEqual(main(["match-report", str(replay), "--events", str(source), "--output", str(output)]), 0)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["parser_version"], "0.2.1")
            self.assertEqual(data["match_id"], "EUW1-123")
            self.assertEqual(data["match"], data["match_id"])
            self.assertIn("snapshots", data)
            self.assertIsNone(data["validation"]["event_stream_complete"])
            self.assertIsNone(data["coverage"]["continuous_positions"])

    def test_farm_uses_named_minion_and_preserves_unverified_opportunities(self):
        events = [
            event(1, "EntityCreate", entity_id=20, kind="lane_minion", minion_type="cannon_minion"),
            event(1, "EntityCreate", entity_id=21, kind="jungle", name="SRU_Blue.1.1", skin="SRU_Blue"),
            event(2, "DamageEvent", source=1, target=20, amount=60, effect=34),
            event(3, "DamageEvent", source=2, target=20, amount=50, effect=99),
            event(3, "MinionDeath", entity_id=20, killer_id=2),
        ]
        catalog = entity_catalog(events, {1: {"SKIN": "Ezreal"}})
        self.assertEqual(catalog[21]["name"], "SRU_Blue")
        own, opponent = minion_history(events, [1, 2], catalog)
        self.assertEqual(own["damaged_before_other_kill"], 1)
        self.assertIsNone(own["missed_last_hit_opportunities"])
        self.assertEqual(opponent["killing_blows"], 1)
        self.assertEqual(opponent["observations"][0]["minion"]["kind"], "cannon_minion")
        self.assertEqual(opponent["observations"][0]["killing_effect_hash"], 99)
        self.assertEqual(own["by_minion_type"]["cannon_minion"]["damaged_before_other_kill"], 1)
        self.assertEqual(opponent["by_minute"][0]["killing_blow"], 1)


if __name__ == "__main__":
    unittest.main()
