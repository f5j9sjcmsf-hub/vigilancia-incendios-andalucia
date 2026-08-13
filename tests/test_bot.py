import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import logic
import main
import sources
import storage
import telegram


def incident(*roads, identity="dgt:s1", situations=("s1",)):
    details = [
        {
            "road": road,
            "section": f"PK {index}",
            "direction": "",
            "datex_ids": [f"record-{index}"],
            "situation_ids": list(situations),
        }
        for index, road in enumerate(roads, start=1)
    ]
    return {
        "incident_id": identity,
        "situation_ids": list(situations),
        "datex_ids": [f"record-{index}" for index in range(1, len(roads) + 1)],
        "fire": "Incendio de prueba",
        "province": "Huelva",
        "municipality": "Niebla",
        "road": ", ".join(roads),
        "road_details": details,
        "detected_at": "2026-08-14T10:00:00+02:00",
        "infoca_matched": True,
    }


def reopening(road, identity="dgt:s1"):
    return {
        "incident_key": identity,
        "situation_ids": ["s1"],
        "fire": "Incendio de prueba",
        "province": "Huelva",
        "municipality": "Niebla",
        "road": road,
        "section": "PK 2",
        "reopened_at": "14/08/2026 10:30",
    }


class DatexTests(unittest.TestCase):
    XML = """<?xml version="1.0" encoding="UTF-8"?>
    <publication>
      <situation id="andalucia-1">
        <situationRecord id="record-a">
          <cause>forestFire</cause><trafficStatus>roadClosed</trafficStatus>
          <roadName>HU-3106</roadName><kilometerPoint>12.5</kilometerPoint>
          <autonomousCommunity>Andalucía</autonomousCommunity>
          <province>Huelva</province><municipality>Niebla</municipality>
          <situationRecordCreationTime>2026-08-14T08:00:00Z</situationRecordCreationTime>
        </situationRecord>
      </situation>
      <situation id="aragon-1">
        <situationRecord id="record-b">
          <cause>forestFire</cause><trafficStatus>roadClosed</trafficStatus>
          <roadName>HU-99</roadName>
          <autonomousCommunity>Aragón</autonomousCommunity>
          <province>Huesca</province><municipality>Jaca</municipality>
        </situationRecord>
      </situation>
    </publication>""".encode("utf-8")

    def test_parser_keeps_only_andalusia_using_native_admin_fields(self):
        result = sources.parse_datex_xml(self.XML, "https://dgt.example/feed.xml")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["road"], "HU-3106")
        self.assertEqual(result[0]["province"], "Huelva")
        self.assertEqual(result[0]["municipality"], "Niebla")
        self.assertEqual(result[0]["datex_id"], "record-a")

    @patch("sources.fetch_infoca_fires", return_value=[])
    @patch("sources._fetch_datex_closures_with_status")
    def test_unmatched_dgt_closure_is_never_discarded(self, fetch_dgt, _):
        fetch_dgt.return_value = (
            [
                {
                    "road": "A-92",
                    "section": "10",
                    "direction": "",
                    "province": "Sevilla",
                    "municipality": "Osuna",
                    "situation_id": "situation-9",
                    "datex_id": "record-9",
                    "detected_at": "14/08/2026 10:00",
                }
            ],
            True,
        )
        result = sources.fetch_official_incidents()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["incident_id"], "dgt:situation-9")
        self.assertFalse(result[0]["infoca_matched"])

    @patch("sources._fetch_datex_closures_with_status", return_value=([], False))
    def test_failed_dgt_query_is_not_reported_as_an_empty_snapshot(self, _):
        with self.assertRaises(RuntimeError):
            sources.fetch_official_incidents()


class TransitionTests(unittest.TestCase):
    def test_partial_reopening_is_deduplicated_and_can_reclose(self):
        state = {}
        logic.initialize_baseline(state, [incident("A-1", "A-2")])

        self.assertEqual(len(logic.process_reopenings(state, [reopening("A-2")])), 1)
        self.assertEqual(logic.process_reopenings(state, [reopening("A-2")]), [])

        current = next(iter(state["incidents"].values()))
        self.assertEqual([d["road"] for d in current["road_details"]], ["A-1"])
        self.assertEqual(len(logic.process_incidents(state, [incident("A-1", "A-2")])), 1)
        current = next(iter(state["incidents"].values()))
        self.assertEqual(current["reopened_roads"], [])
        self.assertFalse(current["road_open"])

    def test_new_road_on_existing_incident_generates_an_alert(self):
        state = {}
        logic.initialize_baseline(state, [incident("A-1")])
        alerts = logic.process_incidents(state, [incident("A-1", "A-2")])
        self.assertEqual(len(alerts), 1)
        self.assertIn("A-2", alerts[0])
        self.assertNotIn("• <b>A-1</b>", alerts[0])

    def test_metadata_change_with_same_situation_does_not_duplicate(self):
        state = {}
        logic.initialize_baseline(state, [incident("A-1")])
        enriched = incident(
            "A-1",
            identity="infoca:name|incendio de prueba",
            situations=("s1",),
        )
        self.assertEqual(logic.process_incidents(state, [enriched]), [])
        self.assertIn("infoca:name|incendio de prueba", state["incidents"])

    def test_complete_reopening_removes_last_active_road(self):
        state = {}
        logic.initialize_baseline(state, [incident("A-3")])
        self.assertEqual(len(logic.process_reopenings(state, [reopening("A-3")])), 1)
        current = next(iter(state["incidents"].values()))
        self.assertEqual(current["road_details"], [])
        self.assertEqual(current["status"], "REABIERTO")
        self.assertTrue(current["road_open"])


class ReopeningSourceTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        logic.initialize_baseline(self.state, [incident("A-5")])

    def test_failed_query_never_creates_reopening(self):
        sources._LAST_DGT_OK = False
        sources._LAST_DGT_ITEMS = []
        self.assertEqual(sources.fetch_official_reopenings(self.state, []), [])

    def test_same_datex_record_remains_active(self):
        sources._LAST_DGT_OK = True
        sources._LAST_DGT_ITEMS = [
            {"road": "A-5", "datex_id": "record-1", "situation_id": "s1"}
        ]
        self.assertEqual(sources.fetch_official_reopenings(self.state, []), [])

    def test_same_road_in_another_situation_does_not_hide_reopening(self):
        sources._LAST_DGT_OK = True
        sources._LAST_DGT_ITEMS = [
            {"road": "A-5", "datex_id": "other", "situation_id": "other"}
        ]
        result = sources.fetch_official_reopenings(self.state, [])
        self.assertEqual([item["road"] for item in result], ["A-5"])


class MessageTests(unittest.TestCase):
    def test_news_fields_and_urls_are_never_visible(self):
        item = incident("A-4")
        item.update(
            {
                "source_url": "https://example.invalid/noticia",
                "source_title": "Titular que no debe verse",
                "other_sources": ["Noticia de prueba"],
            }
        )
        for message in (logic.format_snapshot([item]), logic.format_new_incident(item)):
            self.assertNotIn("http", message.lower())
            self.assertNotIn("titular", message.lower())
            self.assertNotIn("noticia", message.lower())

    def test_snapshot_covers_multiple_andalusian_provinces(self):
        first = incident("HU-1")
        second = incident("SE-1", identity="dgt:s2", situations=("s2",))
        second["province"] = "Sevilla"
        second["municipality"] = "El Madroño"
        message = logic.format_snapshot([first, second])
        self.assertIn("Huelva", message)
        self.assertIn("Sevilla", message)
        self.assertIn("Incidentes con carreteras cortadas: 2", message)

    def test_long_telegram_message_is_split_at_line_boundaries(self):
        text = "<b>carretera</b>\n" * 400
        chunks = telegram._split_message(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4000 for chunk in chunks))
        self.assertEqual("".join(chunks), text)


class ReliabilityTests(unittest.TestCase):
    def test_snapshot_is_due_once_per_hour(self):
        now = datetime.fromisoformat("2026-08-14T12:00:00+02:00")
        self.assertFalse(
            main._snapshot_due(
                {"last_snapshot_at": (now - timedelta(minutes=30)).isoformat()},
                now,
            )
        )
        self.assertTrue(
            main._snapshot_due(
                {"last_snapshot_at": (now - timedelta(minutes=60)).isoformat()},
                now,
            )
        )

    def test_state_path_is_independent_of_working_directory(self):
        self.assertEqual(storage.STATE_FILE, PROJECT_ROOT / "data" / "state.json")

    def test_state_round_trip_is_valid_json(self):
        original = storage.STATE_FILE
        try:
            with tempfile.TemporaryDirectory() as directory:
                storage.STATE_FILE = Path(directory) / "state.json"
                expected = {"monitoring_initialized": True, "incidents": {}}
                storage.save_state(expected)
                self.assertEqual(storage.load_state(), expected)
                self.assertFalse(storage.STATE_FILE.with_suffix(".json.tmp").exists())
        finally:
            storage.STATE_FILE = original

    @patch("main.save_state")
    @patch("main.send_message", side_effect=RuntimeError("Telegram caído"))
    @patch("main.fetch_official_incidents", return_value=[])
    @patch("main.load_state", return_value={})
    def test_telegram_failure_never_advances_state(self, _load, _fetch, _send, save):
        with self.assertRaises(RuntimeError):
            main.main()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
