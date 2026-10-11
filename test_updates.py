import io
import json
from unittest.mock import patch
import unittest

from examnet import updates


def fake_reply(payload):
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


class ParseVersionTests(unittest.TestCase):
    def test_parses_tags_and_short_versions(self):
        self.assertEqual(updates.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updates.parse_version("1.2"), (1, 2, 0))
        self.assertEqual(updates.parse_version("1.10.0") > updates.parse_version("1.9.9"), True)

    def test_rejects_non_versions(self):
        self.assertIsNone(updates.parse_version("latest"))
        self.assertIsNone(updates.parse_version(None))


class CheckForUpdateTests(unittest.TestCase):
    def test_reports_newer_release(self):
        reply = {"tag_name": "v1.0.1", "html_url": "https://github.com/x/y/releases/tag/v1.0.1"}
        with patch("examnet.updates.urlopen", return_value=fake_reply(reply)):
            self.assertEqual(
                updates.check_for_update("1.0.0"), ("1.0.1", "https://github.com/x/y/releases/tag/v1.0.1")
            )

    def test_ignores_same_or_older_release(self):
        with patch("examnet.updates.urlopen", return_value=fake_reply({"tag_name": "v1.0.0"})):
            self.assertIsNone(updates.check_for_update("1.0.0"))
        with patch("examnet.updates.urlopen", return_value=fake_reply({"tag_name": "v0.9.0"})):
            self.assertIsNone(updates.check_for_update("1.0.0"))

    def test_network_errors_mean_no_update(self):
        with patch("examnet.updates.urlopen", side_effect=OSError("offline")):
            self.assertIsNone(updates.check_for_update("1.0.0"))


if __name__ == "__main__":
    unittest.main()
