"""Tests for uptime_report.py. Run with: python3 -m unittest discover tests"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import uptime_report as ur  # noqa: E402


# Trimmed-down versions of real responses from each status API.
STATUSPAGE_OK = {
    "status": {"indicator": "none", "description": "All Systems Operational"},
    "incidents": [],
    "components": [{"name": "Git Operations", "status": "operational", "group": False}],
}

STATUSPAGE_INCIDENT = {
    "status": {"indicator": "minor", "description": "Minor Service Outage"},
    "incidents": [
        {"name": "Delayed webhooks", "status": "investigating"},
        {"name": "Old issue", "status": "resolved"},
    ],
    "components": [
        {"name": "Webhooks", "status": "degraded_performance", "group": False},
        {"name": "API group", "status": "degraded_performance", "group": True},
    ],
}

SLACK_OK = {"status": "ok", "active_incidents": []}
SLACK_OUTAGE = {
    "status": "active",
    "active_incidents": [{"title": "Messages failing to send", "type": "outage"}],
}


class ParserTests(unittest.TestCase):
    def test_statuspage_operational(self):
        self.assertEqual(ur.parse_statuspage(STATUSPAGE_OK), ("operational", []))

    def test_statuspage_incident_skips_resolved_and_groups(self):
        state, notes = ur.parse_statuspage(STATUSPAGE_INCIDENT)
        self.assertEqual(state, "degraded")
        self.assertEqual(notes, ["Delayed webhooks", "Webhooks: degraded performance"])

    def test_statuspage_caps_long_component_lists(self):
        data = {
            "status": {"indicator": "major"},
            "components": [{"name": f"DC{i}", "status": "major_outage", "group": False}
                           for i in range(10)],
        }
        state, notes = ur.parse_statuspage(data)
        self.assertEqual(state, "outage")
        self.assertEqual(len(notes), 4)
        self.assertEqual(notes[-1], "and 7 more components affected")

    def test_statuspage_unknown_indicator(self):
        self.assertEqual(ur.parse_statuspage({"status": {"indicator": "new"}})[0], "unknown")

    def test_slack_operational(self):
        self.assertEqual(ur.parse_slack(SLACK_OK), ("operational", []))

    def test_slack_outage(self):
        self.assertEqual(ur.parse_slack(SLACK_OUTAGE), ("outage", ["Messages failing to send"]))

    def test_slack_notice_is_degraded(self):
        data = {"status": "active", "active_incidents": [{"title": "Slow search", "type": "notice"}]}
        self.assertEqual(ur.parse_slack(data)[0], "degraded")


class CheckServiceTests(unittest.TestCase):
    def test_uses_injected_fetch(self):
        service = {"name": "GitHub", "kind": "statuspage", "url": "unused"}
        result = ur.check_service(service, fetch=lambda url: STATUSPAGE_OK)
        self.assertEqual(result, {"name": "GitHub", "state": "operational", "notes": []})

    def test_unreachable_page_is_unknown_not_crash(self):
        def broken_fetch(url):
            raise TimeoutError("timed out")

        service = {"name": "Slack", "kind": "slack", "url": "unused"}
        result = ur.check_service(service, fetch=broken_fetch)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("TimeoutError", result["notes"][0])


class HistoryTests(unittest.TestCase):
    def test_uptime_percent_skips_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "history.csv")
            ur.append_history(path, [{"name": "Slack", "state": "operational"}], "t1")
            ur.append_history(path, [{"name": "Slack", "state": "outage"}], "t2")
            ur.append_history(path, [{"name": "Slack", "state": "unknown"}], "t3")
            ur.append_history(path, [{"name": "Slack", "state": "operational"}], "t4")
            percent, count = ur.uptime_from_history(path)["Slack"]
        self.assertEqual(count, 3)
        self.assertAlmostEqual(percent, 66.7, places=1)

    def test_no_history_file(self):
        self.assertEqual(ur.uptime_from_history("/no/such/history.csv"), {})


class ReportTests(unittest.TestCase):
    def test_headline_names_services_needing_attention(self):
        results = [
            {"name": "Slack", "state": "operational", "notes": []},
            {"name": "GitHub", "state": "degraded", "notes": ["Delayed webhooks"]},
        ]
        report = ur.build_report(results, {"Slack": (100.0, 4)}, "now")
        self.assertIn("1 of 2 services need attention: GitHub.", report)
        self.assertIn("| Slack | operational | 100.0% of 4 | - |", report)
        self.assertIn("| GitHub | degraded | no history yet | Delayed webhooks |", report)


    def test_pipe_in_note_is_escaped(self):
        results = [{"name": "GitHub", "state": "degraded", "notes": ["Actions | Pages slow"]}]
        report = ur.build_report(results, {}, "now")
        self.assertIn("Actions \\| Pages slow", report)


if __name__ == "__main__":
    unittest.main()
