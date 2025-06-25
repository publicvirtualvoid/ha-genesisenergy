# Genesis Energy Integration for Home Assistant

This is a custom component for Home Assistant to integrate with Genesis Energy (New Zealand). It fetches your hourly electricity and gas consumption, costs, Power Shout details, and other account information, making it available within Home Assistant.

This integration is built by reverse-engineering the Genesis Energy web portal and is not officially supported by Genesis. It may break if Genesis changes their website or APIs.

![Energy Useage PNG](/homeassistant-energy-graph.png "Energy Dashboard Reporting")

## Features

*   **Energy Dashboard Integration:**
    *   Creates long-term statistics for **Electricity Consumption (kWh)** and **Gas Consumption (kWh)**, ready to be added to your Home Assistant Energy Dashboard.
    *   Also creates statistics for daily **Electricity Cost (NZD)** and **Gas Cost (NZD)** for detailed tracking.
*   **Power Shout Sensors:**
    *   **Eligibility:** A binary sensor to know if you're eligible for Power Shout.
    *   **Balance:** A sensor showing your current Power Shout balance in hours.
    *   **Attributes:** Includes details on upcoming bookings, active offers, and expiring hours.
*   **Billing Cycle Sensors:**
    *   Provides sensors for costs within your current billing cycle, powered by the "Sidekick" widget on the Genesis website.
    *   Includes sensors for: `Electricity Used ($)`, `Gas Used ($)`, `Total Used ($)`, `Estimated Total Bill ($)`, and `Estimated Future Use ($)`. Perfect for creating custom dashboards and gauges.
*   **Detailed Account Sensor:**
    *   A single `sensor.genesis_energy_account_details` entity with a wealth of information in its attributes, including your billing plans, account IDs, and raw data from various dashboard widgets.
*   **Powerful Services:**
    *   `genesisenergy.add_powershout_booking`: Book your Power Shouts directly from automations or scripts.
    *   `genesisenergy.backfill_statistics`: A powerful tool to import historical usage data into Home Assistant.
    *   `genesisenergy.force_update`: Trigger an immediate data refresh outside of the normal schedule.

### Manual Installation

1.  Copy the `genesisenergy` folder from this repository into your Home Assistant `custom_components` folder.
    (Path: `<config_dir>/custom_components/genesisenergy/`)
2.  **Restart Home Assistant.**

## Configuration

1.  Go to **Settings > Devices & Services**.
2.  Click **+ ADD INTEGRATION** and search for "Genesis Energy".
3.  Enter your Genesis Energy **Email** and **Password**. These are the same credentials you use for the [Genesis Energy My Account portal](https://myaccount.genesisenergy.co.nz/).
4.  Click **SUBMIT**. The integration will set up a device and all associated sensors.

## Services

This integration provides three powerful services to manage your account.

### Service: `genesisenergy.backfill_statistics`

This service allows you to import historical usage data into Home Assistant. It's perfect for populating your Energy Dashboard with a large amount of history right after you first install the integration.

| Field             | Description                                                                 | Example          |
| ----------------- | --------------------------------------------------------------------------- | ---------------- |
| `days_to_fetch`   | **Required.** The total number of past days of data to retrieve.            | `365`            |
| `fuel_type`       | **Required.** Which fuel type to backfill.                                  | `electricity`    |
|                   | Options: `electricity`, `gas`, `both`                                       |                  |

**How It Works (Important!)**

This service is designed to be **safe** and **non-destructive**. It will only add data for periods where **no data currently exists** in your Home Assistant database.

*   **On a Clean Install:** When you first add the integration, your database is empty. You can run this service with a large number of days (e.g., `365`) to import a full year of history. This will work perfectly.

*   **After Data is Imported:** Once statistics exist, the service's behavior changes. It will fetch the historical data you request, but it will **only import points that are newer than the newest point already in your database.** This is a safety feature to prevent the "negative number" bug and avoid corrupting your existing history.

**What This Means for You:**

*   **The backfill service is most effective when run once, right after a clean installation.** Decide how much history you want (e.g., 90, 180, 365 days) and run it then.
*   The service **cannot** be used to "fix" or "re-import" data for a period that has already been recorded. Its primary purpose is to fill in the past from where your data currently ends.
*   If you have a gap or corrupted data from a previous version, you must fix it manually using **Developer Tools > Statistics**. The current version of this integration will prevent new corruption from occurring.


### Service: `genesisenergy.add_powershout_booking`

This service lets you book Power Shouts from automations.

| Field             | Description                                                                 | Example                    |
| ----------------- | --------------------------------------------------------------------------- | -------------------------- |
| `start_datetime`  | **Required.** The date and time for the Power Shout to begin (in your local timezone). | `"2025-07-20 19:00:00"`    |
| `duration_hours`  | **Required.** The duration in hours (e.g., 1, 2, 3).                        | `2`                        |

### Service: `genesisenergy.force_update`

This service triggers an immediate data refresh for all sensors. It has no parameters.

## Troubleshooting

*   **Authentication Errors (InvalidAuth):** Double-check your Genesis Energy email and password.
*   **Connection Errors (CannotConnect):** Ensure your Home Assistant instance has internet connectivity and that `auth.genesisenergy.co.nz` is not blocked by a firewall or ad-blocker (like Pi-hole).
*   **"Negative Number" in Energy Dashboard:** This indicates corrupted historical data. This was caused by a bug in earlier versions of this component.
    *   **To Fix:** Go to **Developer Tools > Statistics**, find the `genesisenergy:gas_consumption_daily` or `genesisenergy:electricity_consumption_daily` statistic, and find the first data point with a bad value. Click the "target" icon to manually adjust the `sum` to be correct based on the previous hour's value. You may need to do this for a few consecutive hours to fix the chain. The current version of the integration will prevent this from happening again.

## Debugging

To enable debug logging, add the following to your `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.genesisenergy: debug
