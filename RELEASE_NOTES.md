# Tater Satellite 1.4.17

## What's changed

- **Automated integration validation.** HACS and Home Assistant hassfest now
  validate every push and pull request, with daily and manual checks available.
  All validation checks remain enabled.
- **Explicit UI-only setup.** Declare the integration's existing config-entry
  setup through Home Assistant's configuration schema, resolving the hassfest
  configuration warning.
- **Marketplace installation guidance.** Add the official Marketplace install
  button and voice-assistant category. Update installation and upgrade guidance
  for Home Assistant 2026.11 and newer, with HACS instructions for older versions.

Install the update through Marketplace or HACS, then restart Home Assistant.
Home Assistant 2026.6.0 remains the minimum supported version. No satellite
firmware update is required for these changes.

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.16...v1.4.17)
