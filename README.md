# Genesis Energy Integration for Home Assistant

This is a custom component for Home Assistant to integrate with Genesis Energy (New Zealand). It allows you to track your electricity and gas consumption, view Power Shout details, and even book Power Shouts directly from Home Assistant.
Imports the last few days of hourly energy data & costs from Genesis Energy.
Imports Power Shout Balance, Accepted Offers and Active Offers count.

![Energy Useage PNG](/homeassistant-energy-graph.png "Energy Dashboard Reporting")

## Features

*   **Electricity and Gas Consumption Statistics:**
    *   Fetches hourly electricity and gas usage data.
    *   Pushes data to Home Assistant's long-term statistics, making it available for the Energy Dashboard (for electricity and gas consumption in kWh) and history graphs.
    *   Tracks daily costs for both electricity and gas (NZD).
*   **Power Shout Sensors:**
    *   **Eligibility:** Sensor to indicate if your account is currently eligible for Power Shout.
    *   **Balance:** Sensor showing your current Power Shout balance in hours.
    *   **Attributes:** The Power Shout Balance sensor includes additional attributes such as:
        *   Next booked Power Shout start and end times (if any).
        *   Number of upcoming bookings.
        *   Information on expiring Power Shout hours.
        *   Details on active and accepted Power Shout offers.
*   **Account Details Sensor:**
    *   A sensor that fetches various pieces of information from your Genesis Energy account dashboard widgets.
    *   Provides attributes with raw JSON data from endpoints like:
        *   Billing Plans (useful for account and supply point IDs)
        *   Property List / Switcher
        *   Hero Info
        *   Sidekick (estimated usage since last bill)
        *   Bill Summary
        *   Dashboard Power Shout display info
        *   Eco Tracker
        *   ...and more.
    *   This data can be used to create more specific template sensors in Home Assistant.
*   **Service to Book Power Shouts:**
    *   Provides a Home Assistant service (`genesisenergy.add_powershout_booking`) to book Power Shouts.
    *   Automatically attempts to fetch necessary account IDs (`loyaltyAccountId`, `supplyAgreementId`, `supplyPointId`).
    *   Requires `start_datetime` and `duration_hours` as input.
    *   Sends persistent notifications for booking success or failure.

## Installation

### Manual Installation

1.  Copy the `genesisenergy` folder from this repository into your Home Assistant `custom_components` folder.
    (Path: `<config_dir>/custom_components/genesisenergy/`)
2.  **Restart Home Assistant.**

## Configuration

After installation and restarting Home Assistant:

1.  Go to **Settings > Devices & Services**.
2.  Click the **+ ADD INTEGRATION** button in the bottom right.
3.  Search for "Genesis Energy" and select it.
4.  You will be prompted to enter your Genesis Energy **Email** and **Password**.
    *   These are the same credentials you use to log in to the [Genesis Energy My Account portal](https://myaccount.genesisenergy.co.nz/).
5.  Click **SUBMIT**.

The integration will attempt to log in and set up the devices and entities. If successful, you will see a device representing your Genesis Energy account, with associated sensors.

## Entities Provided

Once configured, the integration will create the following entities (entity IDs will be prefixed based on your account, typically using the part of your email before the '@'):

### Statistics Updater Sensors (Internal - Feed the Energy Dashboard & LTS)

*   `sensor.genesis_energy_electricity_statistics_updater_[your_account_label]`
*   `sensor.genesis_energy_gas_statistics_updater_[your_account_label]`
    *   These sensors don't have a visible state but are responsible for fetching hourly data and pushing it to Home Assistant's long-term statistics for:
        *   `genesisenergy:electricity_consumption_daily` (kWh)
        *   `genesisenergy:electricity_cost_daily` (NZD)
        *   `genesisenergy:gas_consumption_daily` (kWh)
        *   `genesisenergy:gas_cost_daily` (NZD)
    *   You can add `genesisenergy:electricity_consumption_daily` and `genesisenergy:gas_consumption_daily` to your Energy Dashboard configuration.

### Power Shout Sensors

*   **Power Shout Eligible:**
    *   Entity ID: `sensor.genesis_energy_power_shout_eligible_[your_account_label]`
    *   State: `true` or `false` indicating eligibility.
*   **Power Shout Balance:**
    *   Entity ID: `sensor.genesis_energy_power_shout_balance_[your_account_label]`
    *   State: Your current Power Shout balance in hours.
    *   Attributes: Contains details about bookings, offers, expiring hours, etc.

### Account Details Sensor

*   **Account Details:**
    *   Entity ID: `sensor.genesis_energy_account_details_[your_account_label]`
    *   State: Timestamp of the last successful update.
    *   Attributes: Contains various raw JSON data fetched from different Genesis dashboard widget APIs (e.g., `billing_plans_info`, `widget_bill_summary`, `widget_eco_tracker`, `powershout_account_info`, etc.). This data can be parsed using template sensors to extract specific values.

## Service: Book Power Shout

The integration provides a service to book Power Shouts.

*   **Service:** `genesisenergy.add_powershout_booking`
*   **Fields:**
    *   `start_datetime` (Required): The date and time for the Power Shout to begin. Provide this in your Home Assistant's local timezone.
        *   Example: `"2025-06-15 18:00:00"`
        *   UI: Uses a date/time picker.
    *   `duration_hours` (Required): The duration of the Power Shout in hours (typically 1 to 4).
        *   Example: `1`
        *   UI: Uses a number input/slider.

The service will automatically try to fetch the necessary `loyaltyAccountId`, `supplyAgreementId`, and electricity `supplyPointId` for your account.

### Example: Calling the Service in an Automation or Script

```yaml
action:
  - service: genesisenergy.add_powershout_booking
    data:
      start_datetime: "2025-07-01 19:30:00"
      duration_hours: 2
Use code with caution.
Markdown
Example: Using Input Helpers for a Dashboard UI
Create Input Helpers (via UI or configuration.yaml):
input_datetime:
  powershout_booking_start:
    name: Power Shout Booking Start
    has_date: true
    has_time: true

input_number:
  powershout_booking_duration:
    name: Power Shout Booking Duration
    initial: 1
    min: 1
    max: 4
    step: 1
    unit_of_measurement: "hr"
    mode: slider
Use code with caution.
Yaml
Create a Script (via UI or scripts.yaml):
genesis_book_selected_powershout:
  alias: Book Selected Genesis Power Shout
  sequence:
    - service: genesisenergy.add_powershout_booking
      data:
        start_datetime: "{{ states('input_datetime.powershout_booking_start') }}"
        duration_hours: "{{ states('input_number.powershout_booking_duration') | int }}"
  mode: single
  icon: mdi:calendar-flash
Use code with caution.
Yaml
Add the input_datetime.powershout_booking_start, input_number.powershout_booking_duration, and script.genesis_book_selected_powershout entities to your Lovelace dashboard.
Troubleshooting
"Failed to load integration" or NoneType errors:
Ensure you have restarted Home Assistant after installation/updates.
Check your Home Assistant logs for more detailed error messages from the custom_components.genesisenergy logger. Enable debug logging if necessary.
Authentication Errors (InvalidAuth):
Double-check your Genesis Energy email and password.
The API or login process may have changed.
Connection Errors (CannotConnect):
Ensure your Home Assistant instance has internet connectivity.
The Genesis Energy API might be temporarily unavailable.
"Update of sensor ... is taking over 10 seconds":
This can happen if the Genesis API is slow to respond. The integration attempts to fetch data concurrently where possible to mitigate this. The default scan interval for sensors is 4 hours.
Booking Service Fails to Find IDs:
The integration attempts to automatically discover your loyaltyAccountId, supplyAgreementId, and electricity supplyPointId. If this fails, the service call will not succeed. Check the debug logs for details on which IDs could not be found. The primary sources are /v2/private/billing/plans for supply IDs and /v2/private/powershoutcurrency/offers for loyalty ID.
Debugging
To enable debug logging, add the following to your configuration.yaml:
logger:
  default: info # or your current default
  logs:
    custom_components.genesisenergy: debug
    custom_components.genesisenergy.api: debug
Use code with caution.
Yaml
Then restart Home Assistant. This will provide more detailed logs to help diagnose issues.
Contributing
Contributions are welcome! If you find bugs or have improvements, please open an issue or submit a pull request.
Acknowledgements
This integration was developed by reverse-engineering the Genesis Energy web portal.
**Key things I've added/updated in this README draft:**

*   **Clear Disclaimer:** Emphasizing it's unofficial and API-dependent.
*   **Updated Features List:**
    *   Clarified what statistics are provided and their use in the Energy Dashboard.
    *   Detailed the Power Shout sensor attributes.
    *   Added the "Account Details Sensor" and its purpose.
    *   Described the "Service to Book Power Shouts" and its automatic ID fetching.
*   **Installation:** Added HACS custom repository instructions (standard practice for new HACS integrations not yet in the default store).
*   **Configuration:** Simple steps.
*   **Entities Provided:** More detailed breakdown.
    *   Explained the statistic IDs for the Energy Dashboard (`genesisenergy:electricity_consumption_daily`, etc.).
*   **Service Section:**
    *   Clearly defined the service name and its fields.
    *   Explicitly mentioned the `selector` types for better UI in Developer Tools.
    *   Provided examples for calling the service and using input helpers.
*   **Troubleshooting:** Added common issues and debugging steps.
*   **Debugging Section:** Standard instructions.

**Before you commit this to your GitHub:**

1.  **Review it carefully:** Make sure it accurately reflects the current state of your integration.
2.  **Update your HACS installation instructions:** If you decide to keep it as a custom repository for HACS, the instructions are good. If you plan to eventually get it into the HACS default store, those instructions would change later.
3.  **Placeholders:** I used `[your_account_label]` as a placeholder for entity IDs. You might want to clarify how that label is derived (e.g., "typically the part of your email before the '@' symbol").

This README should give users a much better understanding of what your integration does and how to use it! Let me know if you'd like any adjustments.