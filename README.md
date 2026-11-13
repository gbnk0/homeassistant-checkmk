# Checkmk

A Home Assistant custom integration for monitoring Checkmk hosts and services.

[![HACS Default](https://img.shields.io/badge/HACS-Default-orange.svg?style=flat-square)](https://www.hacs.xyz/)
[![Open your Home Assistant instance and add this integration repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=integration&owner=gbnk0&repository=homeassistant-checkmk)

## Features

- Host and service status sensors (OK/WARN/CRIT/UNKNOWN, UP/DOWN/UNREACH).
- Numeric metric sensors for graphing CPU, RAM, disks, temperatures, network
  traffic and any other performance data exposed by Checkmk.
- Four-page discovery assistant for hosts, services, and numeric metrics.
- Host, service, and metric filters with case-insensitive wildcards or regular expressions.
- HTTPS or HTTP, custom port, optional SSL verification.
- Config flow UI with editable options.

## Installation

### HACS (recommended)

Checkmk is available in the default HACS integration store. No custom repository is required.

1. Open HACS → Integrations.
2. Search for **Checkmk**, then select **Download**.
3. Restart Home Assistant.

### Manual

1. Copy `custom_components/homeassistant_checkmk` into your Home Assistant `config/custom_components`.
2. Restart Home Assistant.

## Configuration (UI)

Settings → Devices & Services → Add Integration → **Checkmk**.

Required fields:
- Host (Checkmk server)
- Site (Checkmk site name)
- Username
- Automation secret (API password)

The setup then connects to Checkmk and walks through four short pages:

1. Connection settings
2. Discovered hosts
3. Services found on the selected hosts
4. Numeric metrics found on the selected services

Optional fields:
- Protocol (`http` or `https`)
- Port
- Verify SSL (disable for self-signed certs)
- Host include/exclude patterns
- Service include/exclude patterns
- Metric include/exclude patterns

Patterns can complement the exact selections. They are separated by spaces,
commas, or lines and are case-insensitive:

- Wildcard: `my-server*`, `CPU*`, or `Filesystem*`
- Regular expression: `re:^my-server-[0-9]+$` or `re:^(CPU|Memory)$`

Exclusions always take priority. To change an existing installation, open
**Settings → Devices & services → Checkmk → Configure**. This
reloads discovery and lets you change the connection, hosts, services, metrics,
wildcards and regular expressions. Saving reloads the integration automatically.

## Entities

The integration creates:
- One sensor per host
- One status sensor per service
- One numeric sensor per Checkmk performance metric

Numeric metric sensors use Home Assistant's `measurement` state class so they
are recorded and graphable. Units such as `%`, bytes, seconds, watts and °C are
mapped to the corresponding Home Assistant device class. Checkmk warning,
critical, minimum and maximum values are exposed as entity attributes when
available.

Metrics named `power_w` are recognized as power measurements in watts even when
Checkmk omits the unit from its performance data. Select their services and
metrics in the configuration assistant to import them.

## Troubleshooting

- 401/403: verify username and automation secret in Checkmk.
- SSL errors: disable Verify SSL or fix the certificate chain.
- Missing services: check your include/exclude patterns.
- Enable debug logs:

```yaml
logger:
  default: warning
  logs:
    custom_components.homeassistant_checkmk: debug
```

## HACS

This integration is available from the default HACS repository.

## Releases and versions

Stable versions are published as GitHub Releases from semantic Git tags named
`vMAJOR.MINOR.PATCH` (for example, `v0.2.0`). The integration manifest uses the
same version without the leading `v`. HACS installs and upgrades from the latest
GitHub Release rather than directly from the default branch.


## Host discovery and read-only accounts

Setup and options first use the configured-host collection to preserve existing
host selections. If that collection is empty or returns HTTP 403, discovery
tries the monitoring host collection (`GET /domain-types/host/collections/all`).
This allows automation users with monitoring visibility, including Guest users,
to discover hosts without granting access to Setup. Neither request modifies
Checkmk. The existing service collection POST is also a read-only query.

The monitoring response uses the host name as `id`; names under `extensions`
are also accepted. Existing identifiers, filters and stored configuration are
unchanged. No visible hosts produces a specific error with visibility guidance.
Malformed collections produce an invalid-response error and a log entry naming
the endpoint and reason. Logs omit API credentials and response bodies.

Checkmk has deprecated the monitoring host and service endpoints; migration to
replacement APIs is outside this fix. Configured-host discovery continues to
work without calling the monitoring host endpoint when it returns hosts.

## Running tests

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests
```

Discovery tests mock HTTP requests and use minimal Home Assistant form stubs.
They cover the empty configured-host / 24 monitoring-host regression, existing
host discovery, service and metric parsing, permissions, malformed responses,
empty results, safe logging, and setup/options error mapping. They do not replace
a live Checkmk and Home Assistant integration test.
