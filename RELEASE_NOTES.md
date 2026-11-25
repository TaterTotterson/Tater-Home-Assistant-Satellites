# Tater Satellite 1.4.27

## What's changed

- **Dashboard layout fix:** Address Studio stopping with “Sections view needs sections” by giving the model an explicit view, section, and card schema with a complete Sections layout example.
- **Automatic nesting repair:** Move misplaced cards into the correct section structure without dropping cards, badges, or view options. Missing content still goes through model repair and validation.
- **Better design retries:** Give incomplete designs up to two repair attempts with the previous response, concrete layout examples, and validation feedback. Keep the existing overall timeout and entity validation checks.
- **Tater API guidance:** Document using **tater/base** or **tater/direct** for Studio. Tater's OpenAI-compatible API remains supported; switching to OpenAI's hosted API is not required.

Update through Marketplace or HACS, then restart Home Assistant. **No satellite firmware update or AI connection change is required.**

[Full changelog](https://github.com/TaterTotterson/Tater-Home-Assistant-Satellites/compare/v1.4.26...v1.4.27)
