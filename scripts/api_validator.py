#!/usr/bin/env python3
"""
api_validator.py: Pull records from a REST API (or a local JSON file) and
check every record against a set of rules you define in a JSON file.

Why: before data from one system is loaded into another (for example, a
user list going into an HR or CRM tool), someone has to confirm it is
complete and in the right format. This automates that check and prints a
report a non-developer can read.

Usage:
  python3 scripts/api_validator.py --url https://jsonplaceholder.typicode.com/users \
      --rules config/user_rules.json
  python3 scripts/api_validator.py --file saved_response.json --rules config/user_rules.json
  python3 scripts/api_validator.py ... --json     # machine-readable output

Exit codes: 0 = all records passed, 1 = at least one violation, 2 = could not run.

Rules file format (see config/user_rules.json):
  {
    "unique": ["id", "email"],               # no two records may share these values
    "fields": {
      "email": {"required": true, "type": "string", "pattern": "^...$"},
      "address.zipcode": {"type": "string", "min_length": 5}   # dots reach into nested objects
    }
  }

Supported checks per field: required, type, pattern, min_length, allowed.
Uses only the Python standard library.
"""

import argparse
import json
import re
import sys
import urllib.request

# Map rule type names to Python types. bool is checked before int because
# in Python, True is also an int.
TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
}

MISSING = object()  # marker for "field not present", distinct from a null value


def get_path(record, path):
    """Return the value at a dotted path like 'address.zipcode', or MISSING."""
    value = record
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return MISSING
        value = value[key]
    return value


def check_field(value, rule):
    """Return a list of problems (strings) for one field value. Empty means it passed."""
    if value is MISSING or value is None:
        return ["is required but missing"] if rule.get("required") else []

    expected = rule.get("type")
    if expected and not TYPE_CHECKS[expected](value):
        # No point running format checks on the wrong type.
        return [f"should be {expected}, got {type(value).__name__}"]

    problems = []
    if "pattern" in rule and isinstance(value, str) and not re.fullmatch(rule["pattern"], value):
        problems.append(f"'{value}' does not match the expected format")
    if "min_length" in rule and isinstance(value, (str, list)) and len(value) < rule["min_length"]:
        problems.append(f"is shorter than {rule['min_length']} characters")
    if "allowed" in rule and value not in rule["allowed"]:
        problems.append(f"'{value}' is not one of {rule['allowed']}")
    return problems


def check_rules(rules):
    """Raise ValueError if the rules file itself is broken, so it fails clearly up front."""
    for path, rule in rules.get("fields", {}).items():
        if rule.get("type") and rule["type"] not in TYPE_CHECKS:
            raise ValueError(f"rule for '{path}' has unknown type '{rule['type']}'")
        if "pattern" in rule:
            try:
                re.compile(rule["pattern"])
            except re.error as error:
                raise ValueError(f"rule for '{path}' has an invalid pattern: {error}") from None


def validate(records, rules):
    """
    Check every record. Returns a list of violations, each a dict:
      {"record": <index>, "id": <record id if any>, "field": <path>, "problem": <text>}
    """
    violations = []
    fields = rules.get("fields", {})

    for index, record in enumerate(records):
        record_id = record.get("id") if isinstance(record, dict) else None
        if not isinstance(record, dict):
            violations.append({"record": index, "id": None, "field": "(record)",
                               "problem": "is not a JSON object"})
            continue
        for path, rule in fields.items():
            for problem in check_field(get_path(record, path), rule):
                violations.append({"record": index, "id": record_id,
                                   "field": path, "problem": problem})

    # Uniqueness is checked across all records, not one at a time.
    for path in rules.get("unique", []):
        first_seen = {}
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                continue
            value = get_path(record, path)
            if value is MISSING or value is None:
                continue
            if isinstance(value, str):
                key = value.lower()  # emails and usernames are case-insensitive
            elif isinstance(value, (list, dict)):
                key = json.dumps(value, sort_keys=True)  # lists and dicts cannot be dict keys
            else:
                key = value
            if key in first_seen:
                violations.append({"record": index, "id": record.get("id"), "field": path,
                                   "problem": f"duplicates record {first_seen[key]}"})
            else:
                first_seen[key] = index

    return violations


def load_records(url=None, file=None, timeout=10):
    """Fetch JSON from a URL or read it from a file. Must be a list of records."""
    if url:
        request = urllib.request.Request(url, headers={"User-Agent": "api-validator/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    else:
        with open(file, encoding="utf-8") as handle:
            data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of records")
    return data


def format_report(records, violations, source):
    """Build the human-readable report as a string."""
    bad_records = {v["record"] for v in violations}
    lines = [
        f"Validation report for {source}",
        f"  Records checked: {len(records)}",
        f"  Records passing: {len(records) - len(bad_records)}",
        f"  Records failing: {len(bad_records)}",
        f"  Total problems:  {len(violations)}",
    ]

    if violations:
        # Group by field so the reader sees which rule is breaking most often.
        by_field = {}
        for v in violations:
            by_field.setdefault(v["field"], []).append(v)
        lines.append("")
        lines.append("Problems by field:")
        for field, items in sorted(by_field.items(), key=lambda kv: -len(kv[1])):
            lines.append(f"  {field} ({len(items)})")
            for v in items:
                label = f"id {v['id']}" if v["id"] is not None else f"record {v['record']}"
                lines.append(f"    - {label}: {field} {v['problem']}")
    else:
        lines.append("")
        lines.append("All records passed.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate API records against rules.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="REST endpoint that returns a JSON array")
    source.add_argument("--file", help="local JSON file containing an array")
    parser.add_argument("--rules", required=True, help="path to the rules JSON file")
    parser.add_argument("--json", action="store_true", help="print violations as JSON")
    args = parser.parse_args(argv)

    try:
        with open(args.rules, encoding="utf-8") as handle:
            rules = json.load(handle)
        check_rules(rules)
        records = load_records(url=args.url, file=args.file)
    except (OSError, ValueError) as error:  # network errors, bad files, and bad JSON
        print(f"Could not run validation: {error}", file=sys.stderr)
        return 2

    violations = validate(records, rules)
    if args.json:
        print(json.dumps({"checked": len(records), "violations": violations}, indent=2))
    else:
        print(format_report(records, violations, args.url or args.file))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
