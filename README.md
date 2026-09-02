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

- Wildcard: `*qsv*`, `CPU*`, or `Filesystem*`
- Regular expression: `re:^STR-QSV-[1-3]$` or `re:^(CPU|Memory)$`

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
