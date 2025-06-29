# custom_components/genesisenergy/const.py

from logging import Logger, getLogger
from typing import Final
from homeassistant.helpers.entity import EntityCategory
from .model import GenesisEnergyBinarySensorEntityDescription

LOGGER: Logger = getLogger(__package__)
DOMAIN: Final = "genesisenergy"
INTEGRATION_NAME: Final = "Genesis Energy"

PLATFORMS: Final = ["sensor"]

# --- Configuration ---
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
DEFAULT_SCAN_INTERVAL_HOURS: Final = 1

# --- API Data Keys for Coordinator ---
DATA_API_ELECTRICITY_USAGE: Final = "api_electricity_usage"
DATA_API_GAS_USAGE: Final = "api_gas_usage"
DATA_API_POWERSHOUT_INFO: Final = "api_powershout_info"
DATA_API_POWERSHOUT_BALANCE: Final = "api_powershout_balance"
DATA_API_POWERSHOUT_BOOKINGS: Final = "api_powershout_bookings"
DATA_API_POWERSHOUT_OFFERS: Final = "api_powershout_offers"
DATA_API_POWERSHOUT_EXPIRING: Final = "api_powershout_expiring"
DATA_API_BILLING_PLANS: Final = "api_billing_plans"
DATA_API_WIDGET_HERO: Final = "api_widget_hero"
DATA_API_WIDGET_BILLS: Final = "api_widget_bill_summary"
DATA_API_AGGREGATED_ELEC_BILL: Final = "api_aggregated_elec_bill"
DATA_API_WIDGET_PROPERTY_LIST: Final = "api_widget_property_list"
DATA_API_WIDGET_PROPERTY_SWITCHER: Final = "api_widget_property_switcher"
DATA_API_WIDGET_SIDEKICK: Final = "api_widget_sidekick"
DATA_API_WIDGET_DASHBOARD_POWERSHOUT: Final = "api_widget_dashboard_powershout"
DATA_API_WIDGET_ECO_TRACKER: Final = "api_widget_eco_tracker"
DATA_API_WIDGET_DASHBOARD_LIST: Final = "api_widget_dashboard_list"
DATA_API_WIDGET_ACTION_TILE_LIST: Final = "api_widget_action_tile_list"
DATA_API_NEXT_BEST_ACTION: Final = "api_next_best_action"
DATA_API_GENERATION_MIX: Final = "api_generation_mix" # <-- ADDED

# --- Statistic IDs for Energy Dashboard ---
STATISTIC_ID_ELECTRICITY_CONSUMPTION: Final = f"{DOMAIN}:electricity_consumption_daily"
STATISTIC_ID_ELECTRICITY_COST: Final = f"{DOMAIN}:electricity_cost_daily"
STATISTIC_ID_GAS_CONSUMPTION: Final = f"{DOMAIN}:gas_consumption_daily"
STATISTIC_ID_GAS_COST: Final = f"{DOMAIN}:gas_cost_daily"

# --- Sensor EntityDescription Keys ---
SENSOR_KEY_POWERSHOUT_ELIGIBLE: Final = "powershout_eligible"
SENSOR_KEY_POWERSHOUT_BALANCE: Final = "powershout_balance"
SENSOR_KEY_ACCOUNT_DETAILS: Final = "account_details"
SENSOR_KEY_GENERATION_MIX: Final = "generation_mix" # <-- ADDED

# --- NEW: Keys for Billing Sensors ---
SENSOR_KEY_BILL_ELEC_USED: Final = "bill_electricity_used"
SENSOR_KEY_BILL_GAS_USED: Final = "bill_gas_used"
SENSOR_KEY_BILL_TOTAL_USED: Final = "bill_total_used"
SENSOR_KEY_BILL_ESTIMATED_TOTAL: Final = "bill_estimated_total"
SENSOR_KEY_BILL_ESTIMATED_FUTURE: Final = "bill_estimated_future"


# --- Device Information ---
DEVICE_MANUFACTURER: Final = "Genesis Energy"
DEVICE_MODEL: Final = "Online Account"

# --- Service Related Constants ---
SERVICE_ADD_POWERSHOUT_BOOKING: Final = "add_powershout_booking"
ATTR_START_DATETIME: Final = "start_datetime"
ATTR_DURATION_HOURS: Final = "duration_hours"

SERVICE_BACKFILL_STATISTICS: Final = "backfill_statistics"
ATTR_DAYS_TO_FETCH: Final = "days_to_fetch"
ATTR_FUEL_TYPE: Final = "fuel_type"

SERVICE_FORCE_UPDATE: Final = "force_update"