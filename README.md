# IT Automation Scripts

[![CI](https://github.com/maxcamplese/it-automation-scripts/actions/workflows/ci.yml/badge.svg)](https://github.com/maxcamplese/it-automation-scripts/actions/workflows/ci.yml)

Small Bash and Python scripts for everyday IT support and systems work. They check a network connection, summarize Wi-Fi quality, validate API data against rules, and report on SaaS vendor uptime.

| Script | What it does | Language |
|---|---|---|
| [`scripts/net-check.sh`](scripts/net-check.sh) | Tests the network, router, internet, DNS, and HTTPS in order, then explains any failure in plain language | Bash |
| [`scripts/wifi-summary.sh`](scripts/wifi-summary.sh) | Reports signal, noise, band, and security for the current Wi-Fi connection, with a verdict on each | Bash (macOS) |
| [`scripts/api_validator.py`](scripts/api_validator.py) | Pulls records from a REST API and checks each one against rules in a JSON file (required fields, types, formats, uniqueness) | Python |
| [`scripts/uptime_report.py`](scripts/uptime_report.py) | Reads public status pages (Slack, GitHub, Atlassian, Cloudflare), writes a Markdown summary, and tracks uptime across runs | Python |

## Setup

Requirements: macOS or Linux, Bash, and Python 3.9 or newer. There are no third-party packages; everything uses the standard library.

```bash
git clone https://github.com/maxcamplese/it-automation-scripts.git
cd it-automation-scripts
chmod +x scripts/*.sh
```

## Usage

### net-check.sh

```bash
./scripts/net-check.sh            # plain-language report
./scripts/net-check.sh --details  # also shows gateway, resolved address, and DNS servers
NET_CHECK_DOMAIN=yourcompany.com ./scripts/net-check.sh   # test a specific domain
```

Sample output (IP addresses replaced): [`samples/net-check.txt`](samples/net-check.txt). A run against a domain that does not exist shows the failure path: [`samples/net-check-dns-failure.txt`](samples/net-check-dns-failure.txt).

```
  [PASS] This computer is connected to a network.
  [WARN] The router did not answer a ping.
         What this means: Many networks block ping on purpose. If the checks below pass, ignore this.
  [PASS] The internet is reachable.
  [PASS] Website names are being looked up correctly (DNS works).
  [PASS] Secure websites load.
```

### wifi-summary.sh

```bash
./scripts/wifi-summary.sh
```

Sample output: [`samples/wifi-summary.txt`](samples/wifi-summary.txt)

```
  Signal / noise: -51 dBm / -93 dBm

  Signal: strong. Video calls and large downloads should work well.
  Interference: low (SNR 42 dB).
  Band: 6 GHz. Fastest and least crowded, but shorter range through walls.
```

### api_validator.py

```bash
python3 scripts/api_validator.py \
  --url https://jsonplaceholder.typicode.com/users \
  --rules config/user_rules.json
```

The rules in [`config/user_rules.json`](config/user_rules.json) treat the data as a user directory about to be loaded into another system. The sample data is fake test data from JSONPlaceholder. A run against it finds that 9 of 10 phone numbers use inconsistent formats, which would break a clean sync: [`samples/api-validator.txt`](samples/api-validator.txt).

Add `--json` for machine-readable output, or use `--file saved.json` to validate a local file instead of a URL. The exit code is `1` if any record fails, so the script can gate a pipeline or scheduled job.

### uptime_report.py

```bash
python3 scripts/uptime_report.py
```

Each run appends to `output/uptime_history.csv` and writes `output/uptime-report.md`. Run it on a schedule (for example with `cron`) to build an uptime trend. To add a service, add an entry to [`config/status_pages.json`](config/status_pages.json). Sample: [`samples/uptime-report.md`](samples/uptime-report.md).

## Tests

```bash
python3 -m unittest discover tests
```

The tests use fixed sample data, so they need no network connection. They cover the Python scripts only.

On every push, [GitHub Actions](.github/workflows/ci.yml) runs the tests on Python 3.12 and 3.14, lints the Bash scripts with `shellcheck`, and does a smoke run of `net-check.sh` on Linux.

## Known Limitations

- **Bash scripts have no automated tests.** They were tested by hand on macOS. CI runs `net-check.sh` on Linux, but GitHub's runners block ping, so the Linux ping path is only partly exercised.
- **`wifi-summary.sh` is macOS only.** Newer macOS versions also hide the network name (SSID) unless Terminal has Location Services permission.
- **DNS check uses one domain at a time.** By default it tests `example.com`. Set `NET_CHECK_DOMAIN` to test a company domain. Internal-only names that need a VPN fail unless the VPN is connected.
- **Uptime is approximate.** `uptime_report.py` only knows what it saw when it ran. A 10-minute outage between hourly runs is missed. It is a trend, not an SLA measurement.
- **Two status page formats only.** The uptime report supports Atlassian Statuspage and Slack. Vendors with their own formats (Salesforce Trust, Workday) would each need a new parser.
- **python.org installs on macOS** may fail HTTPS requests with `CERTIFICATE_VERIFY_FAILED` until you run `Install Certificates.command` from the Python folder in Applications. Apple's built-in `/usr/bin/python3` works as is.

## License

MIT. See [LICENSE](LICENSE).
