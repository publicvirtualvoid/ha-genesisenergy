"""Constants for the Genesis Energy integration."""

from homeassistant.const import Platform

DOMAIN = "genesisenergy"
INTEGRATION_NAME = "Genesis Energy"

PLATFORMS = [
    Platform.SENSOR,
]

# Configuration keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# Default update interval for sensors
DEFAULT_SCAN_INTERVAL_MINUTES = 4 # 4 hours
SCAN_INTERVAL_SECONDS = DEFAULT_SCAN_INTERVAL_MINUTES * 60

# --- Sensor Types / Keys for Statistics Sensors ---
SENSOR_TYPE_ELECTRICITY = "electricity"
SENSOR_TYPE_GAS = "gas"

# --- API Data Keys (conceptual, for clarity in sensor code) ---
API_DATA_KEY_POWERSHOUT_INFO = "powershout_info" 
API_DATA_KEY_POWERSHOUT_BALANCE = "powershout_balance"
API_DATA_KEY_POWERSHOUT_BOOKINGS = "powershout_bookings"
API_DATA_KEY_POWERSHOUT_OFFERS = "powershout_offers" 
API_DATA_KEY_POWERSHOUT_EXPIRING = "powershout_expiring"


# --- Sensor EntityDescription Keys for Power Shout sensors ---
SENSOR_KEY_POWERSHOUT_ELIGIBLE = "powershout_eligible"
SENSOR_KEY_POWERSHOUT_BALANCE = "powershout_balance"
SENSOR_KEY_ACCOUNT_DETAILS = "account_details" 

# --- Device Information ---
DEVICE_MANUFACTURER = "Genesis Energy"
DEVICE_MODEL = "Online Account Data"

# --- Service Related Constants ---
SERVICE_ADD_POWERSHOUT_BOOKING = "add_powershout_booking"
ATTR_START_DATETIME = "start_datetime" 
ATTR_DURATION_HOURS = "duration_hours"

# --- Data keys for storing fetched IDs ---
STORED_KEY_LOYALTY_ACCOUNT_ID = "loyalty_account_id"
STORED_KEY_SUPPLY_AGREEMENT_ID = "supply_agreement_id"
STORED_KEY_SUPPLY_POINT_ID = "supply_point_id"