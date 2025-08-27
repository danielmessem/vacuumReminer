# Vacuum Prompt one-shot package

## What it does
- Prompts daily on your dashboard to run Sophie.
- "No" sends the prompt to the bottom of the view.
- "Yes" starts the vacuum and hides the prompt.
- Tracks last run timestamp and lets you set the daily time.

## Install
1) Copy `config/packages/vacuum_prompt.yaml` into your Home Assistant `config/packages/` folder. Create the folder if missing and ensure `homeassistant: packages: !include_dir_named packages` is in configuration.yaml, or enable Packages in your setup.
2) Restart Home Assistant.
3) Create a new YAML dashboard:
   - Settings → Dashboards → Add Dashboard → choose *Start with an empty dashboard* → switch to *YAML mode* and point it to the included `dashboards/vacuum_prompt_dashboard.yaml` content (paste into Raw configuration editor), or save this file on disk and set the dashboard path accordingly.
4) Set a time in **Settings → Helpers → `vacuum_prompt_time`**.

Vacuum entity used: `vacuum.mijia_v2_c0e0_robot_cleaner`. Change if needed in the package file.
