"""Tests for api_validator.py. Run with: python3 -m unittest discover tests"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import api_validator as av  # noqa: E402


RULES = {
    "unique": ["id", "email"],
    "fields": {
        "id": {"required": True, "type": "integer"},
        "email": {"required": True, "type": "string", "pattern": r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"},
        "role": {"allowed": ["staff", "intern"]},
        "address.zipcode": {"required": True, "pattern": r"^\d{5}$"},
    },
}


def good_record(**overrides):
    record = {"id": 1, "email": "a@example.com", "role": "intern", "address": {"zipcode": "78701"}}
    record.update(overrides)
    return record


class GetPathTests(unittest.TestCase):
    def test_nested_value(self):
        self.assertEqual(av.get_path({"a": {"b": 5}}, "a.b"), 5)

    def test_missing_value(self):
        self.assertIs(av.get_path({"a": {}}, "a.b"), av.MISSING)

    def test_path_through_non_object(self):
        self.assertIs(av.get_path({"a": "text"}, "a.b"), av.MISSING)


class CheckFieldTests(unittest.TestCase):
    def test_required_missing(self):
        self.assertEqual(av.check_field(av.MISSING, {"required": True}), ["is required but missing"])

    def test_optional_missing_is_fine(self):
        self.assertEqual(av.check_field(av.MISSING, {"type": "string"}), [])

    def test_null_counts_as_missing(self):
        self.assertEqual(av.check_field(None, {"required": True}), ["is required but missing"])

    def test_wrong_type_stops_further_checks(self):
        problems = av.check_field(123, {"type": "string", "pattern": "^x$"})
        self.assertEqual(problems, ["should be string, got int"])

    def test_boolean_is_not_integer(self):
        self.assertEqual(av.check_field(True, {"type": "integer"}), ["should be integer, got bool"])

    def test_pattern_must_match_whole_value(self):
        self.assertEqual(len(av.check_field("78701-extra", {"pattern": r"\d{5}"})), 1)

    def test_min_length(self):
        self.assertEqual(av.check_field("ab", {"min_length": 3}), ["is shorter than 3 characters"])

    def test_allowed_values(self):
        self.assertEqual(len(av.check_field("admin", {"allowed": ["staff"]})), 1)


class ValidateTests(unittest.TestCase):
    def test_clean_data_has_no_violations(self):
        records = [good_record(), good_record(id=2, email="b@example.com")]
        self.assertEqual(av.validate(records, RULES), [])

    def test_bad_email_and_zip(self):
        records = [good_record(email="not-an-email", address={"zipcode": "7870"})]
        fields = sorted(v["field"] for v in av.validate(records, RULES))
        self.assertEqual(fields, ["address.zipcode", "email"])

    def test_duplicate_email_is_case_insensitive(self):
        records = [good_record(), good_record(id=2, email="A@Example.com")]
        violations = av.validate(records, RULES)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["field"], "email")
        self.assertEqual(violations[0]["problem"], "duplicates record 0")

    def test_unique_works_on_lists(self):
        rules = {"unique": ["tags"]}
        violations = av.validate([{"tags": ["a"]}, {"tags": ["a"]}], rules)
        self.assertEqual(violations[0]["problem"], "duplicates record 0")

    def test_non_object_record(self):
        violations = av.validate(["oops"], RULES)
        self.assertEqual(violations[0]["problem"], "is not a JSON object")


class CheckRulesTests(unittest.TestCase):
    def test_valid_rules_pass(self):
        av.check_rules(RULES)  # does not raise

    def test_bad_pattern(self):
        with self.assertRaisesRegex(ValueError, "invalid pattern"):
            av.check_rules({"fields": {"zip": {"pattern": "(unclosed"}}})

    def test_unknown_type(self):
        with self.assertRaisesRegex(ValueError, "unknown type 'text'"):
            av.check_rules({"fields": {"name": {"type": "text"}}})


class MainTests(unittest.TestCase):
    """End-to-end through main() with temp files, so no network is needed."""

    def run_main(self, records):
        with tempfile.TemporaryDirectory() as tmp:
            data_path = os.path.join(tmp, "data.json")
            rules_path = os.path.join(tmp, "rules.json")
            with open(data_path, "w") as f:
                json.dump(records, f)
            with open(rules_path, "w") as f:
                json.dump(RULES, f)
            with contextlib.redirect_stdout(io.StringIO()):
                return av.main(["--file", data_path, "--rules", rules_path, "--json"])

    def test_exit_code_zero_when_clean(self):
        self.assertEqual(self.run_main([good_record()]), 0)

    def test_exit_code_one_when_violations(self):
        self.assertEqual(self.run_main([good_record(role="admin")]), 1)

    def test_exit_code_two_when_file_missing(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = av.main(["--file", "/no/such/file.json", "--rules", "/no/rules.json"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
