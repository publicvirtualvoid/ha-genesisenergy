"""Sensor platform for Genesis Energy (Back to Basics + Power Shout + Account Details)."""

import logging
from datetime import timedelta, datetime, timezone
import pytz
from typing import Any, Mapping, Awaitable
from collections.abc import Callable 
import json 
import asyncio 

from homeassistant.components.sensor import (
    SensorEntity, 
    SensorEntityDescription,
    SensorStateClass 
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import PlatformNotReady # Ensure this is imported
from homeassistant.util import dt as dt_util


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
    SENSOR_KEY_POWERSHOUT_ELIGIBLE, 
    SENSOR_KEY_POWERSHOUT_BALANCE,
    SENSOR_KEY_ACCOUNT_DETAILS, 
)
from .api import GenesisEnergyApi 
from .exceptions import InvalidAuth, CannotConnect


_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> bool: # Ensure return type is bool
    _LOGGER.debug(f"Sensor platform: Setting up sensors for Genesis Energy entry: {entry.entry_id} ('{entry.title}')")
    
    # Ensure domain_data and api are correctly fetched or raise appropriately
    try:
        domain_data = hass.data[DOMAIN][entry.entry_id]
        api: GenesisEnergyApi = domain_data["api"]
        email_username: str = domain_data["email_username"]
    except KeyError as e:
        _LOGGER.error(f"Sensor platform: Critical data missing from hass.data for entry {entry.entry_id}: {e}")
        # This should ideally not happen if __init__.py setup was successful
        return False # Indicate failure to set up this platform


    device_unique_id_part = f"{DOMAIN}_{email_username}"
    _LOGGER.debug(f"Sensor platform: Using email_username: '{email_username}' for device/entity unique ID parts.")
    
    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_unique_id_part)},
        name=f"{INTEGRATION_NAME} ({email_username})", 
        manufacturer=DEVICE_MANUFACTURER,
        model=DEVICE_MODEL,
    )

    # API check is already done in __init__.py's async_setup_entry. 
    # If we reach here, the token should be valid initially.
    # However, a quick re-check or relying on individual sensor updates to handle API errors is also an option.
    # For now, we assume __init__.py handled the critical initial auth.

    sensors_to_add = []
    try:
        sensors_to_add.append(GenesisEnergyUsageSensor(api, SENSOR_TYPE_ELECTRICITY, device_info, email_username))
        sensors_to_add.append(GenesisEnergyUsageSensor(api, SENSOR_TYPE_GAS, device_info, email_username))
        sensors_to_add.append(PowerShoutEligibilitySensor(api, device_info, email_username))
        sensors_to_add.append(PowerShoutBalanceSensor(api, device_info, email_username))
        sensors_to_add.append(GenesisEnergyAccountSensor(api, device_info, email_username)) 
    except Exception as e:
        _LOGGER.error(f"Sensor platform: Error during sensor instantiation for entry '{entry.title}': {e}", exc_info=True)
        return False # Indicate failure

    if sensors_to_add:
        _LOGGER.debug(f"Sensor platform: Attempting to add {len(sensors_to_add)} sensors for entry '{entry.title}'. Update_before_add=True.")
        async_add_entities(sensors_to_add, update_before_add=True)
        _LOGGER.info(f"Sensor platform: Finished attempting to add {len(sensors_to_add)} Genesis Energy sensors for account '{email_username}' (Entry: '{entry.title}').")
    else:
        _LOGGER.warning(f"Sensor platform: No sensors were prepared to be added for entry '{entry.title}'.")

    return True # Explicitly return True if setup reaches this point successfully


class GenesisEnergyUsageSensor(SensorEntity):
    """Representation of a Genesis Energy Usage Sensor that pushes statistics."""
    _attr_should_poll = True 

    def __init__(self, api: GenesisEnergyApi, sensor_type: str, device_info: DeviceInfo, account_label: str) -> None:
        self._api = api
        self._sensor_type = sensor_type
        self._account_label = account_label 
        self._attr_device_info = device_info
        
        fuel_name = sensor_type.capitalize()
        self._attr_name = f"{INTEGRATION_NAME} {fuel_name} Statistics Updater ({self._account_label})"
        self._attr_unique_id = f"{DOMAIN}_{self._account_label}_{sensor_type}_stats_updater"

        self._consumption_statistic_id = f"{DOMAIN}:{sensor_type}_consumption_daily"
        self._cost_statistic_id = f"{DOMAIN}:{sensor_type}_cost_daily"
        self._consumption_statistic_name = f"{INTEGRATION_NAME} {fuel_name} Consumption Daily"
        self._cost_statistic_name = f"{INTEGRATION_NAME} {fuel_name} Cost Daily"

        self._unit_of_measurement = "kWh"
        self._currency = "NZD"
        self._attr_native_value = None 
        self._attr_icon = "mdi:chart-line" if sensor_type == SENSOR_TYPE_ELECTRICITY else "mdi:chart-bell-curve-cumulative"
        _LOGGER.info(f"Initialized sensor: {self.name}, Unique ID: {self.unique_id}, Consumption Stat ID: {self._consumption_statistic_id}, Cost Stat ID: {self._cost_statistic_id}")

    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        try:
            if self._sensor_type == SENSOR_TYPE_ELECTRICITY:
                api_response_data = await self._api.get_energy_data()
            elif self._sensor_type == SENSOR_TYPE_GAS:
                api_response_data = await self._api.get_gas_data()
            else:
                _LOGGER.error(f"Unknown sensor type: {self._sensor_type} for {self.name}")
                self._attr_available = False
                return
            
            if not api_response_data:
                _LOGGER.warning(f"No data returned from API for {self.name}")
                # Sensor remains available but with old data if this happens after a successful first update
                return
            await self._async_process_statistics_data(api_response_data)
            self._attr_available = True 
        except InvalidAuth as e: 
            _LOGGER.error(f"API authentication error during update for {self.name}: {e}")
            self._attr_available = False 
        except CannotConnect as e: 
            _LOGGER.error(f"API connection error during update for {self.name}: {e}")
            self._attr_available = False 
        except Exception as e: 
            _LOGGER.error(f"Unexpected error during update for {self.name}: {e}", exc_info=True)
            self._attr_available = False


    async def _async_process_statistics_data(self, api_response_data: dict) -> None:
        _LOGGER.debug(f"{self.name}: Entered _async_process_statistics_data.")
        usage_data_raw = api_response_data.get('usage', [])
        
        if not isinstance(usage_data_raw, list) or not usage_data_raw:
            _LOGGER.info(f"{self.name}: No 'usage' entries or not a list in API response.")
            return

        try:
            valid_entries = [entry for entry in usage_data_raw if isinstance(entry, dict) and 'startDate' in entry]
            if not valid_entries:
                _LOGGER.info(f"{self.name}: No valid 'usage' entries with 'startDate' key.")
                return
            usage_data_sorted = sorted(valid_entries, key=lambda x: datetime.fromisoformat(x['startDate']))
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
                last_stat_point_utc_ts = last_kwh_stat_list[0]['start']
                if last_stat_point_utc_ts is not None:
                    last_stat_point_utc = datetime.fromtimestamp(last_stat_point_utc_ts, pytz.utc)
                    if last_stat_point_utc < first_start_date_utc_this_batch:
                         running_sum_kw = float(last_kwh_stat_list[0]["sum"])
                    else: 
                        last_stat_point_utc = None 
            
            last_cost_stats_map = await get_instance(self.hass).async_add_executor_job(get_last_statistics, self.hass, 1, self._cost_statistic_id, True, {"sum"})
            last_cost_stat_list = last_cost_stats_map.get(self._cost_statistic_id, [])
            if last_cost_stat_list and last_cost_stat_list[0].get("sum") is not None:
                cost_last_stat_point_utc_ts = last_cost_stat_list[0]['start']
                if cost_last_stat_point_utc_ts is not None:
                    cost_last_stat_point_utc_for_sum = datetime.fromtimestamp(cost_last_stat_point_utc_ts, pytz.utc) 
                    if cost_last_stat_point_utc_for_sum < first_start_date_utc_this_batch:
                        running_sum_cost_nzd = float(last_cost_stat_list[0]["sum"])
        except Exception as e: _LOGGER.error(f"{self.name}: Error fetching last stats: {e}. Sums from 0.", exc_info=True); running_sum_kw = 0.0; running_sum_cost_nzd = 0.0; last_stat_point_utc = None

        for entry in usage_data_sorted:
            try: 
                kw_val = float(entry['kw']); 
                cost_val = float(entry['costNZD']); 
                start_dt_utc = datetime.fromisoformat(entry['startDate']).astimezone(pytz.utc)
            except (KeyError, ValueError, TypeError) as e:
                _LOGGER.warning(f"{self.name}: Skipping invalid usage entry: {entry}, error: {e}")
                continue 
            if last_stat_point_utc and start_dt_utc <= last_stat_point_utc: 
                _LOGGER.debug(f"{self.name}: Skipping old stat point: {start_dt_utc} (last: {last_stat_point_utc})")
                continue
            running_sum_kw += kw_val; running_sum_cost_nzd += cost_val
            kw_statistics_list.append(StatisticData(start=start_dt_utc, state=round(kw_val, 2), sum=round(running_sum_kw, 2)))
            cost_statistics_list.append(StatisticData(start=start_dt_utc, state=round(cost_val, 2), sum=round(running_sum_cost_nzd, 2)))
        
        if kw_statistics_list:
            meta = StatisticMetaData(has_mean=False, has_sum=True, name=self._consumption_statistic_name, source=DOMAIN, statistic_id=self._consumption_statistic_id, unit_of_measurement=self._unit_of_measurement)
            try: async_add_external_statistics(self.hass, meta, kw_statistics_list); _LOGGER.info(f"{self.name}: Added {len(kw_statistics_list)} kWh stats for ID {self._consumption_statistic_id}.")
            except Exception as e: _LOGGER.error(f"{self.name}: Failed to save kWh stats for ID {self._consumption_statistic_id}: {e}", exc_info=True)
        else: _LOGGER.info(f"{self.name}: No new kWh stats to add for ID {self._consumption_statistic_id}.")
        if cost_statistics_list:
            meta = StatisticMetaData(has_mean=False, has_sum=True, name=self._cost_statistic_name, source=DOMAIN, statistic_id=self._cost_statistic_id, unit_of_measurement=self._currency)
            try: async_add_external_statistics(self.hass, meta, cost_statistics_list); _LOGGER.info(f"{self.name}: Added {len(cost_statistics_list)} NZD cost stats for ID {self._cost_statistic_id}.")
            except Exception as e: _LOGGER.error(f"{self.name}: Failed to save cost stats for ID {self._cost_statistic_id}: {e}", exc_info=True)
        else: _LOGGER.info(f"{self.name}: No new cost stats to add for ID {self._cost_statistic_id}.")


class GenesisEnergyPowerShoutSensorBase(SensorEntity):
    """Base for Power Shout sensors."""
    _attr_should_poll = True

    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str, 
                 entity_key: str, name_suffix: str, icon: str | None = None, 
                 unit: str | None = None, state_class: SensorStateClass | None = None):
        self._api = api
        self._attr_device_info = device_info
        self._account_label = account_label 

        self._attr_name = f"{INTEGRATION_NAME} Power Shout {name_suffix} ({account_label})" 
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


class PowerShoutEligibilitySensor(GenesisEnergyPowerShoutSensorBase):
    """Sensor for Power Shout eligibility."""
    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str):
        super().__init__(api, device_info, account_label, 
                         SENSOR_KEY_POWERSHOUT_ELIGIBLE, "Eligible", "mdi:lightning-bolt-outline")

    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        self._attr_native_value = None 
        self._extra_attributes = {}
        try:
            balance_data = await self._api.get_powershout_balance() 
            _LOGGER.debug(f"{self.name}: Raw get_powershout_balance for eligibility: {balance_data}")

            if balance_data and isinstance(balance_data, dict):
                balance_value_raw = balance_data.get("balance")
                if balance_value_raw is not None:
                    try:
                        balance_value = float(balance_value_raw)
                        self._attr_native_value = balance_value > 0
                        self._extra_attributes["balance_used_for_eligibility"] = balance_value
                        self._extra_attributes["raw_balance_response"] = str(balance_data) 
                    except (ValueError, TypeError):
                        _LOGGER.warning(f"{self.name}: Invalid balance value for eligibility: {balance_value_raw}")
                else:
                    _LOGGER.warning(f"{self.name}: 'balance' key missing in response for eligibility.")
                    self._extra_attributes["raw_balance_response"] = str(balance_data)
            else:
                _LOGGER.warning(f"No/invalid data from get_powershout_balance for eligibility for {self.name}. Response: {balance_data}")
            self._attr_available = True
        except InvalidAuth as e: 
            _LOGGER.error(f"API authentication error for {self.name}: {e}")
            self._attr_available = False
        except CannotConnect as e: 
            _LOGGER.error(f"API connection error for {self.name}: {e}")
            self._attr_available = False
        except Exception as e: 
            _LOGGER.error(f"Unexpected error for {self.name}: {e}", exc_info=True)
            self._attr_available = False


class PowerShoutBalanceSensor(GenesisEnergyPowerShoutSensorBase):
    """Sensor for Power Shout balance."""
    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str):
        super().__init__(api, device_info, account_label, 
                         SENSOR_KEY_POWERSHOUT_BALANCE, "Balance", "mdi:timer-sand", 
                         "hr", SensorStateClass.MEASUREMENT)
        self._ps_bookings_data: dict | list | None = None 
        self._ps_offers_data: dict | list | None = None
        self._ps_expiring_data: dict | list | None = None

    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        
        current_balance_value = None
        
        try:
            balance_data = await self._api.get_powershout_balance()
            _LOGGER.debug(f"{self.name}: Raw get_powershout_balance response: {balance_data}")
            if balance_data and isinstance(balance_data, dict):
                bal_val_raw = balance_data.get("balance")
                if bal_val_raw is not None:
                    try:
                        current_balance_value = float(bal_val_raw)
                    except (ValueError, TypeError):
                        _LOGGER.warning(f"{self.name}: Invalid PS balance value: {bal_val_raw}, type: {type(bal_val_raw)}")
                else:
                    _LOGGER.debug(f"{self.name}: 'balance' key missing in response or is None.")
            else:
                _LOGGER.warning(f"No valid data or not a dict from get_powershout_balance for {self.name}. Response: {balance_data}")
            self._attr_native_value = current_balance_value 
            self._attr_available = True 
        except InvalidAuth as e: 
            _LOGGER.error(f"API authentication error fetching balance for {self.name}: {e}")
            self._attr_available = False
            return 
        except CannotConnect as e: 
            _LOGGER.error(f"API connection error fetching balance for {self.name}: {e}")
            self._attr_available = False
            return 
        except Exception as e: 
            _LOGGER.error(f"Unexpected error fetching/parsing balance for {self.name}: {e}", exc_info=True)
            self._attr_available = False 
            
        temp_extra_attrs = self._extra_attributes.copy() 

        attribute_tasks = {
            "bookings": self._api.get_powershout_bookings(),
            "offers": self._api.get_powershout_offers(),
            "expiring": self._api.get_powershout_expiring_hours(),
        }
        
        results = await asyncio.gather(
            *(task for task in attribute_tasks.values()), 
            return_exceptions=True 
        )

        results_map = dict(zip(attribute_tasks.keys(), results))

        if isinstance(results_map.get("bookings"), Exception) or results_map.get("bookings") is None:
            _LOGGER.warning(f"Failed to fetch bookings attribute for {self.name}: {results_map.get('bookings')}")
            self._ps_bookings_data = None
        else:
            self._ps_bookings_data = results_map.get("bookings")
            _LOGGER.debug(f"{self.name}: Raw get_powershout_bookings response: {self._ps_bookings_data}")

        if isinstance(results_map.get("offers"), Exception) or results_map.get("offers") is None:
            _LOGGER.warning(f"Failed to fetch offers attribute for {self.name}: {results_map.get('offers')}")
            self._ps_offers_data = None
        else:
            self._ps_offers_data = results_map.get("offers")
            _LOGGER.debug(f"{self.name}: Raw get_powershout_offers response: {self._ps_offers_data}")

        if isinstance(results_map.get("expiring"), Exception) or results_map.get("expiring") is None:
            _LOGGER.warning(f"Failed to fetch expiring hours attribute for {self.name}: {results_map.get('expiring')}")
            self._ps_expiring_data = None
        else:
            self._ps_expiring_data = results_map.get("expiring")
            _LOGGER.debug(f"{self.name}: Raw get_powershout_expiring_hours response: {self._ps_expiring_data}")
        
        self._update_extra_attributes(temp_extra_attrs) 
        self._extra_attributes = temp_extra_attrs 


    def _update_extra_attributes(self, attrs: dict[str, Any]) -> None: 
        keys_to_clear = [
            "accepted_offers_count", "active_offers_count", "active_offer_names",
            "expiring_hours_message", "expiring_hours_tooltip",
            "next_booking_start", "next_booking_end", "next_booking_duration_hrs",
            "upcoming_bookings_count"
        ]
        for key in keys_to_clear:
            attrs.pop(key, None)

        if self._ps_offers_data and isinstance(self._ps_offers_data, dict):
            accepted_offers = self._ps_offers_data.get("acceptedOffers", [])
            active_offers = self._ps_offers_data.get("activeOffers", [])
            
            attrs["accepted_offers_count"] = len(accepted_offers) if isinstance(accepted_offers, list) else 0
            attrs["active_offers_count"] = len(active_offers) if isinstance(active_offers, list) else 0
            
            if isinstance(active_offers, list):
                active_names = [
                    o.get("name") for o in active_offers if isinstance(o, dict) and o.get("name")
                ]
                if active_names:
                    attrs["active_offer_names"] = active_names
        else:
            _LOGGER.debug(f"{self.name}: No _ps_offers_data or not a dict for attributes. Data: {self._ps_offers_data}")

        if self._ps_expiring_data and isinstance(self._ps_expiring_data, dict):
            exp_msg = self._ps_expiring_data.get("expiringHoursMessage")
            if isinstance(exp_msg, dict):
                title = exp_msg.get("title")
                if title: 
                    attrs["expiring_hours_message"] = title
            
            tooltip = self._ps_expiring_data.get("messageTooltip")
            if tooltip:
                attrs["expiring_hours_tooltip"] = tooltip
        else:
            _LOGGER.debug(f"{self.name}: No _ps_expiring_data or not a dict for attributes. Data: {self._ps_expiring_data}")

        if self._ps_bookings_data and isinstance(self._ps_bookings_data, dict): 
            now_utc = datetime.now(timezone.utc)
            upcoming = []
            bookings_list = self._ps_bookings_data.get("bookings", []) 
            
            if isinstance(bookings_list, list):
                for booking in bookings_list:
                    if not isinstance(booking, dict): 
                        _LOGGER.debug(f"{self.name}: Booking item is not a dict: {booking}")
                        continue
                    try:
                        start_dt_str = booking.get("startDate")
                        if not start_dt_str or not isinstance(start_dt_str, str): 
                            _LOGGER.debug(f"{self.name}: Booking missing or invalid startDate: {booking}")
                            continue

                        start_dt = datetime.fromisoformat(start_dt_str).astimezone(timezone.utc)
                        
                        if start_dt > now_utc:
                            current_booking_data: dict[str, Any] = {"start": start_dt.isoformat()}
                            if end_date_str := booking.get("endDate"):
                                current_booking_data["end"] = end_date_str 
                            if (duration_raw := booking.get("duration")) is not None:
                                try: current_booking_data["duration_hrs"] = float(duration_raw)
                                except (ValueError, TypeError): _LOGGER.warning(f"{self.name}: Invalid duration value: {duration_raw}")
                            upcoming.append(current_booking_data)
                    except ValueError as ve:
                        _LOGGER.warning(f"{self.name}: Error parsing booking data item {booking}: {ve}")
                    except Exception as e:
                        _LOGGER.error(f"{self.name}: Unexpected error processing booking item {booking}: {e}", exc_info=True)
            else:
                _LOGGER.debug(f"{self.name}: 'bookings' key not a list or missing in _ps_bookings_data. Data: {self._ps_bookings_data}")
            
            if upcoming:
                upcoming.sort(key=lambda b_item: b_item["start"])
                attrs["next_booking_start"] = upcoming[0]["start"]
                if "end" in upcoming[0]: attrs["next_booking_end"] = upcoming[0]["end"]
                if "duration_hrs" in upcoming[0]: attrs["next_booking_duration_hrs"] = upcoming[0]["duration_hrs"]
                attrs["upcoming_bookings_count"] = len(upcoming)
        else:
            _LOGGER.debug(f"{self.name}: No _ps_bookings_data or not a dict for attributes. Data: {self._ps_bookings_data}")
        

class GenesisEnergyAccountSensor(SensorEntity):
    """Sensor for various Genesis Energy account and widget data."""
    _attr_should_poll = True

    def __init__(self, api: GenesisEnergyApi, device_info: DeviceInfo, account_label: str):
        self._api = api
        self._attr_device_info = device_info
        self._account_label = account_label

        self._attr_name = f"{INTEGRATION_NAME} Account Details ({account_label})"
        self._attr_unique_id = f"{DOMAIN}_{account_label}_{SENSOR_KEY_ACCOUNT_DETAILS}"
        self._attr_icon = "mdi:account-details"
        
        self._attr_native_value = None 
        self._extra_attributes: dict[str, Any] = {}
        _LOGGER.info(f"Initialized sensor: {self.name}, Unique ID: {self.unique_id}")

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return {
            k: (json.dumps(v, indent=2) if isinstance(v, (dict, list)) else v)
            for k, v in self._extra_attributes.items()
        }

    async def async_update(self) -> None:
        _LOGGER.debug(f"Updating sensor: {self.name}")
        
        api_calls_to_make: dict[str, Awaitable[Any]] = {
            "powershout_account_info": self._api.get_powershout_info(),
            "billing_plans_info": self._api.get_billing_plans(), # Added this call
            "widget_property_list": self._api.get_widget_property_list(),
            "widget_property_switcher": self._api.get_widget_property_switcher(),
            "widget_hero_info": self._api.get_widget_hero_info(),
            "widget_sidekick": self._api.get_widget_sidekick(),
            "widget_bill_summary": self._api.get_widget_bill_summary(),
            "widget_dashboard_powershout_display": self._api.get_widget_dashboard_powershout(),
            "widget_eco_tracker": self._api.get_widget_eco_tracker(),
            "widget_dashboard_list": self._api.get_widget_dashboard_list(), 
            "widget_action_tile_list": self._api.get_widget_action_tile_list(),
            "next_best_action": self._api.get_next_best_action(),
            "powershout_bookings_attr": self._api.get_powershout_bookings(),
            "powershout_offers_attr": self._api.get_powershout_offers(),
            "powershout_expiring_hours_attr": self._api.get_powershout_expiring_hours(),
        }

        results = await asyncio.gather(
            *api_calls_to_make.values(), 
            return_exceptions=True
        )

        new_attributes: dict[str, Any] = {}
        any_call_succeeded = False
        auth_error_occurred = False

        for key, result in zip(api_calls_to_make.keys(), results):
            if isinstance(result, InvalidAuth):
                _LOGGER.error(f"API authentication error for {self.name} fetching {key}: {result}")
                new_attributes[key] = f"Auth Error: {result}"
                auth_error_occurred = True 
                break 
            elif isinstance(result, CannotConnect):
                _LOGGER.warning(f"API connection error for {self.name} fetching {key}: {result}")
                new_attributes[key] = f"Connection Error: {result}"
            elif isinstance(result, Exception):
                _LOGGER.error(f"Unexpected error for {self.name} fetching {key}: {result}", exc_info=result)
                new_attributes[key] = f"Unexpected Error: {result}"
            else: 
                new_attributes[key] = result if result is not None else "No data"
                # Consider an empty dict from API as "No data" for simplicity unless it's an error string
                if isinstance(result, dict) and not result:
                    new_attributes[key] = "No data (empty dict)"
                
                if not (isinstance(new_attributes[key], str) and "Error" in new_attributes[key]):
                    any_call_succeeded = True
        
        self._extra_attributes = new_attributes
        
        if auth_error_occurred:
            self._attr_available = False
            self._attr_native_value = "Auth Error"
        elif any_call_succeeded:
            self._attr_available = True
            self._attr_native_value = dt_util.utcnow().isoformat()
            if any(isinstance(v, str) and "Error" in str(v) for v in new_attributes.values()): # check str(v) for safety
                 _LOGGER.warning(f"{self.name}: Update completed with some errors fetching attributes, but sensor remains available.")
            else:
                _LOGGER.debug(f"{self.name}: Update successful.")
        else: 
            self._attr_available = False
            self._attr_native_value = "Update Failed"