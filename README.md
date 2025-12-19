# Home Assistant Checkmk Integration

A Home Assistant custom integration for monitoring Checkmk hosts and services.

## Features

- Host and service status sensors (OK/WARN/CRIT/UNKNOWN, UP/DOWN/UNREACH).
- Include/exclude filters for hosts and services with wildcard patterns.
- HTTPS or HTTP, custom port, optional SSL verification.
- Config flow UI with editable options.

## Installation

### HACS (custom repository)

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

Optional fields:
- Protocol (`http` or `https`)
- Port
- Verify SSL (disable for self-signed certs)
- Host include/exclude patterns
- Service include/exclude patterns
- Legacy service filter (optional)

Pattern format: space or comma separated, supports wildcards. Example: `*temp* *cpu*`.

## Entities

The integration creates:
- One sensor per host
- One sensor per service

States are text (status), not numeric values.

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
