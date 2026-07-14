# Home Assistant Checkmk Integration

A Home Assistant custom integration for monitoring Checkmk hosts and services.

## Features

- Host and service status sensors (OK/WARN/CRIT/UNKNOWN, UP/DOWN/UNREACH).
- Numeric metric sensors for graphing CPU, RAM, disks, temperatures, network
  traffic and any other performance data exposed by Checkmk.
- Discovery and multi-selection of hosts and services from the config flow.
- Include/exclude filters with case-insensitive wildcards or regular expressions.
- HTTPS or HTTP, custom port, optional SSL verification.
- Config flow UI with editable options.

## Installation

### HACS (custom repository)

Click the button below to add this repository in HACS:

[![Open your Home Assistant instance and add this integration repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?category=integration&owner=gbnk0&repository=homeassistant-checkmk)

1. HACS → Integrations → three dots → Custom repositories.
2. Add this repository URL, category: Integration.
3. Install, then restart Home Assistant.

### Manual

1. Copy `custom_components/homeassistant_checkmk` into your Home Assistant `config/custom_components`.
2. Restart Home Assistant.

## Configuration (UI)

Settings → Devices & Services → Add Integration → **Home Assistant Checkmk**.

Required fields:
- Host (Checkmk server)
- Site (Checkmk site name)
- Username
- Automation secret (API password)

The setup then connects to Checkmk and loads the available hosts. Select the
hosts you want, continue, then select the services found on those hosts.

Optional fields:
- Protocol (`http` or `https`)
- Port
- Verify SSL (disable for self-signed certs)
- Host include/exclude patterns
- Service include/exclude patterns

Patterns can complement the exact selections. They are separated by spaces,
commas, or lines and are case-insensitive:

- Wildcard: `*qsv*`, `CPU*`, or `Filesystem*`
- Regular expression: `re:^STR-QSV-[1-3]$` or `re:^(CPU|Memory)$`

Exclusions always take priority. To change an existing installation, open
**Settings → Devices & services → Home Assistant Checkmk → Configure**. This
reloads discovery and lets you change the connection, hosts, services, wildcards
and regular expressions. Saving reloads the integration automatically.

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

This repository is HACS-compatible as a custom integration.

## Releases and versions

Stable versions are published as GitHub Releases from semantic Git tags named
`vMAJOR.MINOR.PATCH` (for example, `v0.2.0`). The integration manifest uses the
same version without the leading `v`. HACS installs and upgrades from the latest
GitHub Release rather than directly from the default branch.
