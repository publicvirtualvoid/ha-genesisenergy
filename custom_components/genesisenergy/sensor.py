"""Sensor platform for Genesis Energy (Back to Basics + Power Shout)."""

import logging
from datetime import timedelta, datetime, timezone
import pytz
from typing import Any, Mapping
from collections.abc import Callable # For API method type hint

from homeassistant.components.sensor import (
    SensorEntity, 
    SensorEntityDescription,
    SensorStateClass # For Power Shout Balance
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import PlatformNotReady


from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.util import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

from .const import (
    DOMAIN, 
    INTEGRATION_NAME,
    SCAN_INTERVAL_SECONDS,
    SENSOR_TYPE_ELECTRICITY,
    SENSOR_TYPE_GAS,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    SENSOR_KEY_POWERSHOUT_ELIGIBLE, # Ensure these are defined in const.py
    SENSOR_KEY_POWERSHOUT_BALANCE,
)
from .api import GenesisEnergyApi 
from .exceptions import InvalidAuth, CannotConnect


_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.debug(f"Setting up sensors for Genesis Energy entry: {entry.entry_id}")
    
    domain_data = hass.data[DOMAIN][entry.entry_id]
    api: GenesisEnergyApi = domain_data["api"]
    email_username: str = domain_data["email_username"]
    device_unique_id_part = f"{DOMAIN}_{email_username}"
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_unique_id_part)},
        name=f"{INTEGRATION_NAME} ({email_username})", 
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
    )

    # Initial API check before adding any sensors
    try:
        _LOGGER.debug("Performing initial API check during sensor setup...")
        await api._ensure_valid_token()
        _LOGGER.debug("Initial API check successful.")
    except InvalidAuth as err:
        _LOGGER.error(f"Authentication failed during sensor setup: {err}")
        return 
    except CannotConnect as err:
        _LOGGER.error(f"Cannot connect to Genesis API during sensor setup: {err}")
        raise PlatformNotReady(f"Failed to connect to Genesis API: {err}") from err
    except Exception as err:
        _LOGGER.error(f"Unexpected error during sensor setup API check: {err}", exc_info=True)
        raise PlatformNotReady(f"Unexpected API error: {err}") from err

    sensors_to_add = [
        GenesisEnergyUsageSensor(api, SENSOR_TYPE_ELECTRICITY, device_info, email_username),
        GenesisEnergyUsageSensor(api, SENSOR_TYPE_GAS, device_info, email_username),
        PowerShoutEligibilitySensor(api, device_info, email_username),
        PowerShoutBalanceSensor(api, device_info, email_username),
    ]
    # Can add more PowerShout sensors here in the same pattern

    async_add_entities(sensors_to_add, update_before_add=True)
    _LOGGER.info(f"Added {len(sensors_to_add)} Genesis Energy sensors for account '{email_username}'.")


class GenesisEnergyUsageSensor(SensorEntity):
    """Representation of a Genesis Energy Usage Sensor that pushes statistics."""
    _attr_should_poll = True 

    def __init__(self, api: GenesisEnergyApi, sensor_type: str, device_info: DeviceInfo, account_label: str) -> None:
        self._api = api
        self._sensor_type = sensor_type
        self._account_label = account_label
        self._attr_device_info = device_info
        
        fuel_name = sensor_type.capitalize()
        self._attr_name = f"{INTEGRATION_NAME} {fuel_name} Statistics Updater"
        self._attr_unique_id = f"{DOMAIN}_{self._account_label}_{sensor_type}_stats_updater"

        self._consumption_statistic_id = f"{DOMAIN}:{self._account_label}_{sensor_type}_consumption_daily"
        self._cost_statistic_id = f"{DOMAIN}:{self._account_label}_{sensor_type}_cost_daily"
        self._consumption_statistic_name = f"{INTEGRATION_NAME} {fuel_name} ({self._account_label}) Consumption Daily"
        self._cost_statistic_name = f"{INTEGRATION_NAME} {fuel_name} ({self._account_label}) Cost Daily"

        self._unit_of_measurement = "kWh"
        self._currency = "NZD"
        self._attr_native_value = None 
        self._attr_icon = "mdi:chart-line" if sensor_type == SENSOR_TYPE_ELECTRICITY else "mdi:chart-bell-curve-cumulative"
        _LOGGER.info(f"Initialized sensor: {self.name}, Unique ID: {self.unique_id}, Stat ID: {self._consumption_statistic_id}")

    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        try:
            if self._sensor_type == SENSOR_TYPE_ELECTRICITY:
                api_response_data = await self._api.get_energy_data()
            elif self._sensor_type == SENSOR_TYPE_GAS:
                api_response_data = await self._api.get_gas_data()
            else:
                _LOGGER.error(f"Unknown sensor type: {self._sensor_type} for {self.name}")
                return
            
            if not api_response_data:
                _LOGGER.warning(f"No data returned from API for {self.name}")
                return
            await self._async_process_statistics_data(api_response_data)
        except (InvalidAuth, CannotConnect) as e: _LOGGER.error(f"API error during update for {self.name}: {e}")
        except Exception as e: _LOGGER.error(f"Unexpected error during update for {self.name}: {e}", exc_info=True)

    async def _async_process_statistics_data(self, api_response_data: dict) -> None:
        _LOGGER.debug(f"{self.name}: Entered _async_process_statistics_data.")
        usage_data_raw = api_response_data.get('usage', [])
        
        if not isinstance(usage_data_raw, list) or not usage_data_raw:
            _LOGGER.info(f"{self.name}: No 'usage' entries or not a list in API response.")
            return

        try:
            usage_data_sorted = sorted(usage_data_raw, key=lambda x: datetime.fromisoformat(x['startDate']))
        except (KeyError, ValueError, TypeError) as e:
            _LOGGER.error(f"{self.name}: Could not sort usageData: {e}. Skipping batch.", exc_info=True)
            return
        
        _LOGGER.debug(f"{self.name}: Processing {len(usage_data_sorted)} sorted usage entries.")
        running_sum_kw = 0.0; running_sum_cost_nzd = 0.0
        cost_statistics_list: list[StatisticData] = []; kw_statistics_list: list[StatisticData] = []
        first_start_date_utc_this_batch = datetime.fromisoformat(usage_data_sorted[0]['startDate']).astimezone(pytz.utc)
        last_stat_point_utc: datetime | None = None

        try:
            last_kwh_stats_map = await get_instance(self.hass).async_add_executor_job(get_last_statistics, self.hass, 1, self._consumption_statistic_id, True, {"sum"})
            last_kwh_stat_list = last_kwh_stats_map.get(self._consumption_statistic_id, [])
            if last_kwh_stat_list and last_kwh_stat_list[0].get("sum") is not None:
                last_stat_point_utc = datetime.fromtimestamp(last_kwh_stat_list[0]['start'], pytz.utc)
                if last_stat_point_utc < first_start_date_utc_this_batch: running_sum_kw = float(last_kwh_stat_list[0]["sum"])
            
            last_cost_stats_map = await get_instance(self.hass).async_add_executor_job(get_last_statistics, self.hass, 1, self._cost_statistic_id, True, {"sum"})
            last_cost_stat_list = last_cost_stats_map.get(self._cost_statistic_id, [])
            if last_cost_stat_list and last_cost_stat_list[0].get("sum") is not None:
                if last_stat_point_utc and last_stat_point_utc < first_start_date_utc_this_batch: running_sum_cost_nzd = float(last_cost_stat_list[0]["sum"])
        except Exception as e: _LOGGER.error(f"{self.name}: Error fetching last stats: {e}. Sums from 0.", exc_info=True); running_sum_kw = 0.0; running_sum_cost_nzd = 0.0; last_stat_point_utc = None

        for entry in usage_data_sorted:
            try: kw_val = float(entry['kw']); cost_val = float(entry['costNZD']); start_dt_utc = datetime.fromisoformat(entry['startDate']).astimezone(pytz.utc)
            except Exception: continue # Skip invalid entries
            if last_stat_point_utc and start_dt_utc <= last_stat_point_utc: continue
            running_sum_kw += kw_val; running_sum_cost_nzd += cost_val
            kw_statistics_list.append(StatisticData(start=start_dt_utc, state=round(kw_val, 2), sum=round(running_sum_kw, 2)))
            cost_statistics_list.append(StatisticData(start=start_dt_utc, state=round(cost_val, 2), sum=round(running_sum_cost_nzd, 2)))
        
        if kw_statistics_list:
            meta = StatisticMetaData(has_mean=False, has_sum=True, name=self._consumption_statistic_name, source=DOMAIN, statistic_id=self._consumption_statistic_id, unit_of_measurement=self._unit_of_measurement)
            try: async_add_external_statistics(self.hass, meta, kw_statistics_list); _LOGGER.info(f"{self.name}: Added {len(kw_statistics_list)} kWh stats.")
            except Exception as e: _LOGGER.error(f"{self.name}: Failed to save kWh stats: {e}", exc_info=True)
        else: _LOGGER.info(f"{self.name}: No new kWh stats to add.")
        if cost_statistics_list:
            meta = StatisticMetaData(has_mean=False, has_sum=True, name=self._cost_statistic_name, source=DOMAIN, statistic_id=self._cost_statistic_id, unit_of_measurement=self._currency)
            try: async_add_external_statistics(self.hass, meta, cost_statistics_list); _LOGGER.info(f"{self.name}: Added {len(cost_statistics_list)} NZD cost stats.")
            except Exception as e: _LOGGER.error(f"{self.name}: Failed to save cost stats: {e}", exc_info=True)
        else: _LOGGER.info(f"{self.name}: No new cost stats to add.")

# --- Power Shout Sensor Base Class (Optional, or individual classes) ---
class GenesisEnergyPowerShoutSensorBase(SensorEntity):
    """Base for Power Shout sensors."""
    _attr_should_poll = True

    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str, 
                 entity_key: str, name_suffix: str, icon: str | None = None, 
                 unit: str | None = None, state_class: SensorStateClass | None = None):
        self._api = api
        self._attr_device_info = device_info
        self._account_label = account_label # Used for unique ID

        self._attr_name = f"{INTEGRATION_NAME} Power Shout {name_suffix}"
        self._attr_unique_id = f"{DOMAIN}_{account_label}_powershout_{entity_key}"
        if icon: self._attr_icon = icon
        if unit: self._attr_native_unit_of_measurement = unit
        if state_class: self._attr_state_class = state_class
        
        self._attr_native_value = None
        self._extra_attributes: dict[str, Any] = {}
        _LOGGER.info(f"Initialized sensor: {self.name}, Unique ID: {self.unique_id}")

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return self._extra_attributes if self._extra_attributes else None

    # Child classes will implement async_update and call their specific API method

class PowerShoutEligibilitySensor(GenesisEnergyPowerShoutSensorBase):
    """Sensor for Power Shout eligibility."""
    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str):
        super().__init__(api, device_info, account_label, 
                         SENSOR_KEY_POWERSHOUT_ELIGIBLE, "Eligible", "mdi:lightning-bolt-outline")

    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        try:
            data = await self._api.get_powershout_info()
            if data and isinstance(data, dict):
                self._attr_native_value = data.get("isEligible")
                # Potentially add other attributes from ps_info to self._extra_attributes
                self._extra_attributes = {"last_api_response": "info_ok"} # Example
            else:
                self._attr_native_value = None
                _LOGGER.warning(f"No/invalid data from get_powershout_info for {self.name}")
        except (InvalidAuth, CannotConnect) as e: _LOGGER.error(f"API error for {self.name}: {e}")
        except Exception as e: _LOGGER.error(f"Unexpected error for {self.name}: {e}", exc_info=True)


class PowerShoutBalanceSensor(GenesisEnergyPowerShoutSensorBase):
    """Sensor for Power Shout balance."""
    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str):
        super().__init__(api, device_info, account_label, 
                         SENSOR_KEY_POWERSHOUT_BALANCE, "Balance", "mdi:timer-sand", 
                         "hr", SensorStateClass.MEASUREMENT)
        # For more complex attributes like bookings, offers
        self._ps_bookings_data: dict | None = None
        self._ps_offers_data: dict | None = None
        self._ps_expiring_data: dict | None = None


    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        # This sensor could fetch multiple related PS endpoints if desired,
        # to populate its value and attributes in one go.
        try:
            balance_data = await self._api.get_powershout_balance()
            if balance_data and isinstance(balance_data, dict):
                bal_val = balance_data.get("balance")
                try: self._attr_native_value = float(bal_val) if bal_val is not None else None
                except (ValueError, TypeError): self._attr_native_value = None; _LOGGER.warning(f"Invalid PS balance value: {bal_val}")
            else:
                self._attr_native_value = None
                _LOGGER.warning(f"No/invalid data from get_powershout_balance for {self.name}")

            # Fetch other data for attributes
            self._ps_bookings_data = await self._api.get_powershout_bookings()
            self._ps_offers_data = await self._api.get_powershout_offers()
            self._ps_expiring_data = await self._api.get_powershout_expiring_hours()
            
            self._update_extra_attributes()

        except (InvalidAuth, CannotConnect) as e: _LOGGER.error(f"API error for {self.name}: {e}")
        except Exception as e: _LOGGER.error(f"Unexpected error for {self.name}: {e}", exc_info=True)

    def _update_extra_attributes(self) -> None:
        """Helper to update extra_state_attributes from fetched PS data."""
        attrs: dict[str, Any] = {}
        if self._ps_offers_data and isinstance(self._ps_offers_data, dict):
            attrs["accepted_offers_count"] = len(self._ps_offers_data.get("acceptedOffers", []))
            attrs["active_offers_count"] = len(self._ps_offers_data.get("activeOffers", []))
            if active_names := [o.get("name") for o in self._ps_offers_data.get("activeOffers", []) if o.get("name")]:
                attrs["active_offer_names"] = active_names

        if self._ps_expiring_data and isinstance(self._ps_expiring_data, dict):
            if (exp_msg := self._ps_expiring_data.get("expiringHoursMessage")) and isinstance(exp_msg, dict):
                if title := exp_msg.get("title"): attrs["expiring_hours_message"] = title
            if tooltip := self._ps_expiring_data.get("messageTooltip"): attrs["expiring_hours_tooltip"] = tooltip
        
        if self._ps_bookings_data and isinstance(self._ps_bookings_data, dict):
            now_utc = datetime.now(timezone.utc)
            upcoming = []
            for booking in self._ps_bookings_data.get("bookings", []):
                if not isinstance(booking, dict): continue
                try:
                    start_dt_str = booking.get("startDate")
                    if not start_dt_str: continue
                    start_dt = datetime.fromisoformat(start_dt_str).astimezone(timezone.utc)
                    if start_dt > now_utc:
                        upcoming.append({
                            "start": start_dt.isoformat(), "end": booking.get("endDate"),
                            "duration_hrs": booking.get("duration")
                        })
                except Exception: pass # Ignore parsing errors for bookings
            
            if upcoming:
                upcoming.sort(key=lambda b: b["start"])
                attrs["next_booking_start"] = upcoming[0]["start"]
                attrs["next_booking_end"] = upcoming[0]["end"]
                attrs["next_booking_duration_hrs"] = upcoming[0].get("duration_hrs")
                attrs["upcoming_bookings_count"] = len(upcoming)
        self._extra_attributes = attrs