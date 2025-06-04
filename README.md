# Genesis Energy integration for Home Assistant

View your energy usage from Genesis Energy (NZ) in homeassistant.

## Data

Imports the last few days of hourly energy data & costs from Genesis Energy.

![Energy Useage PNG](/homeassistant-energy-graph.png "Energy Dashboard Reporting")

## Getting started

You will need to have an existing Genesis Energy account.

## Installation

Once installed, simply set-up from the `Devices and services` area.
The first field is the username and the next field is the password for your Genesis Energy account.

Add "energy_consumption_daily" into Energy Dashboard for energy reporting.
Then choose "Use an entity tracking the total costs" and select "genesisenergy energy_cost_daily" to add the cost statistic.

### Manually

Copy all files in the custom*components/genesisenergy folder to your Home Assistant folder \_config/custom_components/genesisenergy*.

## Known issues

## Future enhancements

Your support is welcomed.

- fix/add labels for user integration config flow

## Acknowledgements

This integration is not supported / endorsed by, nor affiliated with, Genesis Energy.
