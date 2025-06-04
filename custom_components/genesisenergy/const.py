"""Constants for the Genesis Energy integration."""

from homeassistant.const import Platform

DOMAIN = "genesisenergy"
SENSOR_NAME = "Genesis Energy" # Default title for ConfigEntry

PLATFORMS = [
    Platform.SENSOR,
]

# Configuration keys (from config_flow.py)
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# DataUpdateCoordinator update interval
DEFAULT_SCAN_INTERVAL_HOURS = 4 # Fetch data every 4 hours
DEFAULT_SCAN_INTERVAL_SECONDS = DEFAULT_SCAN_INTERVAL_HOURS * 3600

# --- Keys for data stored by the DataUpdateCoordinator ---
# These keys will be used to access specific pieces of data from coordinator.data
DATA_API_RESPONSE_ELECTRICITY_USAGE = "api_electricity_usage"
DATA_API_RESPONSE_GAS_USAGE = "api_gas_usage"
DATA_API_RESPONSE_POWERSHOUT_INFO = "api_powershout_info"
DATA_API_RESPONSE_POWERSHOUT_BALANCE = "api_powershout_balance"
DATA_API_RESPONSE_POWERSHOUT_BOOKINGS = "api_powershout_bookings"
DATA_API_RESPONSE_POWERSHOUT_OFFERS = "api_powershout_offers"
DATA_API_RESPONSE_POWERSHOUT_EXPIRING = "api_powershout_expiring_hours"

# --- Statistic IDs (used by GenesisEnergyStatisticsSensor) ---
# These are the IDs that will appear in HA's statistics database
STATISTIC_ID_ELECTRICITY_CONSUMPTION = f"{DOMAIN}:electricity_consumption_daily"
STATISTIC_ID_ELECTRICITY_COST = f"{DOMAIN}:electricity_cost_daily"
STATISTIC_ID_GAS_CONSUMPTION = f"{DOMAIN}:gas_consumption_daily"
STATISTIC_ID_GAS_COST = f"{DOMAIN}:gas_cost_daily"

# --- Sensor EntityDescription Keys (for new Power Shout sensors) ---
# These are used internally to generate unique_ids and sometimes entity_id suffixes
SENSOR_KEY_POWERSHOUT_ELIGIBLE = "powershout_eligible"
SENSOR_KEY_POWERSHOUT_BALANCE = "powershout_balance"
# Add more if you create more dedicated sensors, e.g.:
# SENSOR_KEY_POWERSHOUT_NEXT_BOOKING_START = "powershout_next_booking_start"
# SENSOR_KEY_POWERSHOUT_ACTIVE_OFFERS_COUNT = "powershout_active_offers_count"

# --- Device Information ---
DEVICE_MANUFACTURER = "Genesis Energy"
DEVICE_MODEL = "Online Account"
DEVICE_NAME_PREFIX = "Genesis Energy" # Will be like "Genesis Energy (your_email_userpart)"