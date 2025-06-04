# custom_components/genesisenergy/sensor.py

import logging
from datetime import datetime, timezone
import pytz 
from collections.abc import Mapping
from typing import Any # For type hints

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, HomeAssistantError, callback 
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

# For statistics processing
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.util import get_instance
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)

from .const import (
    DOMAIN,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DATA_API_RESPONSE_ELECTRICITY_USAGE,
    DATA_API_RESPONSE_GAS_USAGE,
    DATA_API_RESPONSE_POWERSHOUT_INFO,
    DATA_API_RESPONSE_POWERSHOUT_BALANCE,
    DATA_API_RESPONSE_POWERSHOUT_BOOKINGS,
    DATA_API_RESPONSE_POWERSHOUT_OFFERS,
    DATA_API_RESPONSE_POWERSHOUT_EXPIRING,
    STATISTIC_ID_ELECTRICITY_CONSUMPTION,
    STATISTIC_ID_ELECTRICITY_COST,
    STATISTIC_ID_GAS_CONSUMPTION,
    STATISTIC_ID_GAS_COST,
    DEVICE_MANUFACTURER,
    DEVICE_MODEL,
    DEVICE_NAME_PREFIX,
    SENSOR_KEY_POWERSHOUT_ELIGIBLE,
    SENSOR_KEY_POWERSHOUT_BALANCE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Genesis Energy sensors from a config entry."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: DataUpdateCoordinator = entry_data["coordinator"]
    email_username: str = entry_data["email_username"]
    
    device_unique_id = f"{DOMAIN}_{email_username}" # Used for device and unique_id prefixes

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_unique_id)},
        name=f"{DEVICE_NAME_PREFIX} ({email_username})",
        manufacturer=DEVICE_MANUFACTURER,
        model=f"{DEVICE_MODEL} (Polls every {DEFAULT_SCAN_INTERVAL_HOURS}h)",
    )

    entities = []

    # Statistics-Pushing Sensors
    if coordinator.data and coordinator.data.get(DATA_API_RESPONSE_ELECTRICITY_USAGE) is not None:
        entities.append(GenesisEnergyStatisticsSensor(coordinator, device_info, "Electricity", DATA_API_RESPONSE_ELECTRICITY_USAGE, device_unique_id)) # ADDED device_unique_id
    if coordinator.data and coordinator.data.get(DATA_API_RESPONSE_GAS_USAGE) is not None:
        entities.append(GenesisEnergyStatisticsSensor(coordinator, device_info, "Gas", DATA_API_RESPONSE_GAS_USAGE, device_unique_id)) # ADDED device_unique_id

    # New Power Shout Sensors
    if coordinator.data and coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_INFO) is not None:
        entities.append(PowerShoutEligibilitySensor(coordinator, device_info, device_unique_id))
    if coordinator.data and coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_BALANCE) is not None:
        entities.append(PowerShoutBalanceSensor(coordinator, device_info, device_unique_id))
    
    async_add_entities(entities)


class GenesisEnergyStatisticsSensor(CoordinatorEntity, SensorEntity):
    """A sensor that processes statistics from coordinator data."""
    _attr_has_entity_name = True
    _attr_should_poll = False # Data is from coordinator

    def __init__(self, coordinator: DataUpdateCoordinator, device_info: DeviceInfo, fuel_type: str, data_key: str, device_unique_id: str):
        super().__init__(coordinator)
        self._fuel_type = fuel_type
        self._data_key = data_key
        self._attr_device_info = device_info
        
        self.entity_description = SensorEntityDescription(
            key=f"{fuel_type.lower()}_statistics_updater", # e.g., electricity_statistics_updater
            name=f"{fuel_type} Statistics Updater",
            icon="mdi:chart-line" if self._fuel_type == "Electricity" else "mdi:chart-bell-curve-cumulative",
        )
        self._attr_unique_id = f"{device_unique_id}_{self.entity_description.key}" 
        
        if fuel_type == "Electricity":
            self._consumption_statistic_id = STATISTIC_ID_ELECTRICITY_CONSUMPTION
            self._cost_statistic_id = STATISTIC_ID_ELECTRICITY_COST
        else: # Gas
            self._consumption_statistic_id = STATISTIC_ID_GAS_CONSUMPTION
            self._cost_statistic_id = STATISTIC_ID_GAS_COST
            
        self._consumption_statistic_name = f"Genesis {fuel_type} Consumption Daily"
        self._cost_statistic_name = f"Genesis {fuel_type} Cost Daily"
        
        self._unit_of_measurement = "kWh"
        self._currency = "NZD"
        _LOGGER.info(f"Initialized {self.name}")

    @property
    def state(self): # This sensor has no direct state shown in UI
        return None 

    @callback
    def _handle_coordinator_update(self) -> None:
        _LOGGER.debug(f"{self.name}: Coordinator update received.")
        if self.coordinator.data and self._data_key in self.coordinator.data:
            raw_api_response = self.coordinator.data[self._data_key]
            if raw_api_response and raw_api_response.get('usage'): # Ensure 'usage' key exists
                _LOGGER.debug(f"{self.name}: Scheduling statistics processing for {len(raw_api_response['usage'])} items.")
                self.hass.async_create_task(self.async_process_statistics_data(raw_api_response))
            else:
                _LOGGER.debug(f"{self.name}: No 'usage' data in coordinator for key {self._data_key}")
        else:
            _LOGGER.warning(f"{self.name}: Data key '{self._data_key}' not found in coordinator data or coordinator has no data.")
        # No need to call self.async_write_ha_state() if state is always None and no attributes change based on coordinator
        # However, if you add attributes that depend on coordinator data, call it.

    async def async_process_statistics_data(self, data):
        usageData = data.get('usage', [])
        if not isinstance(usageData, list) or not usageData:
            _LOGGER.warning(f"{self.name}: No 'usage' data array or invalid format, skipping statistics.")
            return

        _LOGGER.debug(f"{self.name}: Processing {len(usageData)} usage entries for statistics.")
        running_sum_kw = 0.0
        running_sum_costNZD = 0.0
        cost_statistics_list = []
        kw_statistics_list = []

        first_entry = usageData[0]
        if 'startDate' not in first_entry:
            _LOGGER.error(f"{self.name}: First entry missing 'startDate'. Data: {first_entry}")
            return
        try:
            first_start_date_api_tz = datetime.fromisoformat(first_entry['startDate'])
            first_start_date_utc = first_start_date_api_tz.astimezone(pytz.utc)
        except ValueError as e:
            _LOGGER.error(f"{self.name}: Could not parse 'startDate' {first_entry['startDate']}: {e}")
            return

        try:
            last_kwh_stats_data = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, self._consumption_statistic_id, True, {"sum"}
            )
            last_kwh_stat_entry = last_kwh_stats_data.get(self._consumption_statistic_id, [])
            if last_kwh_stat_entry and last_kwh_stat_entry[0]["sum"] is not None:
                stat_start_dt_utc = datetime.fromtimestamp(last_kwh_stat_entry[0]['start'], pytz.utc)
                if stat_start_dt_utc < first_start_date_utc:
                    running_sum_kw = float(last_kwh_stat_entry[0]["sum"])
                    _LOGGER.debug(f"{self.name}: Resuming kWh sum from: {running_sum_kw:.2f} (stat time: {stat_start_dt_utc})")
                else:
                    _LOGGER.debug(f"{self.name}: Latest kWh stat ({stat_start_dt_utc}) not before new data ({first_start_date_utc}). Sum from 0.")
            else:
                _LOGGER.debug(f"{self.name}: No previous kWh sum for {self._consumption_statistic_id}. Sum from 0.")

            last_cost_stats_data = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, self._cost_statistic_id, True, {"sum"}
            )
            last_cost_stat_entry = last_cost_stats_data.get(self._cost_statistic_id, [])
            if last_cost_stat_entry and last_cost_stat_entry[0]["sum"] is not None:
                stat_start_dt_utc = datetime.fromtimestamp(last_cost_stat_entry[0]['start'], pytz.utc)
                if stat_start_dt_utc < first_start_date_utc:
                    running_sum_costNZD = float(last_cost_stat_entry[0]["sum"])
                    _LOGGER.debug(f"{self.name}: Resuming NZD cost sum from: {running_sum_costNZD:.2f} (stat time: {stat_start_dt_utc})")
                else:
                     _LOGGER.debug(f"{self.name}: Latest NZD cost stat ({stat_start_dt_utc}) not before new data ({first_start_date_utc}). Sum from 0.")
            else:
                _LOGGER.debug(f"{self.name}: No previous NZD cost sum for {self._cost_statistic_id}. Sum from 0.")
        except Exception as e:
            _LOGGER.error(f"{self.name}: Error fetching last statistics: {e}", exc_info=True)
            running_sum_kw = 0.0; running_sum_costNZD = 0.0
        
        for entry in usageData:
            try:
                kw_val = float(entry['kw'])
                cost_val = float(entry['costNZD'])
                start_dt_aware = datetime.fromisoformat(entry['startDate'])
                start_dt_utc = start_dt_aware.astimezone(pytz.utc) # Ensure UTC for HA statistics
            except (KeyError, ValueError, TypeError) as e:
                _LOGGER.warning(f"{self.name}: Skipping invalid entry: {entry}. Error: {e}")
                continue

            running_sum_kw += kw_val
            running_sum_costNZD += cost_val
            cost_statistics_list.append(StatisticData(start=start_dt_utc, state=round(cost_val, 2), sum=round(running_sum_costNZD, 2)))
            kw_statistics_list.append(StatisticData(start=start_dt_utc, state=round(kw_val, 2), sum=round(running_sum_kw, 2)))
        
        if kw_statistics_list:
            kw_metadata = StatisticMetaData(
                has_mean=False, has_sum=True, name=self._consumption_statistic_name,
                source=DOMAIN, statistic_id=self._consumption_statistic_id, unit_of_measurement=self._unit_of_measurement,
            )
            try: async_add_external_statistics(self.hass, kw_metadata, kw_statistics_list)
            except (HomeAssistantError, ValueError) as e: _LOGGER.error(f"{self.name}: Failed to save kWh stats for {self._consumption_statistic_id}: {e}", exc_info=True)
        if cost_statistics_list:
            cost_metadata = StatisticMetaData(
                has_mean=False, has_sum=True, name=self._cost_statistic_name,
                source=DOMAIN, statistic_id=self._cost_statistic_id, unit_of_measurement=self._currency,
            )
            try: async_add_external_statistics(self.hass, cost_metadata, cost_statistics_list)
            except (HomeAssistantError, ValueError) as e: _LOGGER.error(f"{self.name}: Failed to save cost stats for {self._cost_statistic_id}: {e}", exc_info=True)


class PowerShoutEligibilitySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DataUpdateCoordinator, device_info: DeviceInfo, device_unique_id: str):
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self.entity_description = SensorEntityDescription(
            key=SENSOR_KEY_POWERSHOUT_ELIGIBLE, name="Power Shout Eligible", icon="mdi:lightning-bolt-outline",
        )
        self._attr_unique_id = f"{device_unique_id}_{self.entity_description.key}"
        _LOGGER.info(f"Initialized {self.name}")

    @property
    def native_value(self):
        if self.coordinator.data and (ps_info := self.coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_INFO)):
            return ps_info.get("isEligible")
        return None

class PowerShoutBalanceSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DataUpdateCoordinator, device_info: DeviceInfo, device_unique_id: str):
        super().__init__(coordinator)
        self._attr_device_info = device_info
        self.entity_description = SensorEntityDescription(
            key=SENSOR_KEY_POWERSHOUT_BALANCE, name="Power Shout Balance",
            native_unit_of_measurement="hr", icon="mdi:timer-sand", state_class=SensorStateClass.MEASUREMENT,
        )
        self._attr_unique_id = f"{device_unique_id}_{self.entity_description.key}"
        _LOGGER.info(f"Initialized {self.name}")

    @property
    def native_value(self):
        if self.coordinator.data and (ps_balance := self.coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_BALANCE)):
            if (balance_val := ps_balance.get("balance")) is not None:
                try: return float(balance_val)
                except (ValueError, TypeError): _LOGGER.warning(f"Invalid PS balance: {balance_val}"); return None
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = {}
        if not self.coordinator.data: return None

        if ps_offers := self.coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_OFFERS):
            attrs["accepted_offers_count"] = len(ps_offers.get("acceptedOffers", []))
            attrs["active_offers_count"] = len(ps_offers.get("activeOffers", []))
            if active_names := [o.get("name") for o in ps_offers.get("activeOffers", []) if o.get("name")]:
                attrs["active_offer_names"] = active_names

        if ps_expiring := self.coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_EXPIRING):
            if exp_msg := ps_expiring.get("expiringHoursMessage"):
                if title := exp_msg.get("title"): attrs["expiring_hours_message"] = title
            if tooltip := ps_expiring.get("messageTooltip"): attrs["expiring_hours_tooltip"] = tooltip
        
        if ps_bookings := self.coordinator.data.get(DATA_API_RESPONSE_POWERSHOUT_BOOKINGS):
            now_utc = datetime.now(timezone.utc)
            upcoming = []
            for booking in ps_bookings.get("bookings", []):
                try:
                    start_dt = datetime.fromisoformat(booking.get("startDate")).astimezone(timezone.utc)
                    if start_dt > now_utc:
                        upcoming.append({
                            "start": start_dt.isoformat(), "end": booking.get("endDate"),
                            "duration_hrs": booking.get("duration")
                        })
                except (ValueError, TypeError, AttributeError): 
                    _LOGGER.debug(f"Skipping booking with invalid startDate: {booking.get('startDate')}")
            
            if upcoming:
                upcoming.sort(key=lambda b: b["start"])
                attrs["next_booking_start"] = upcoming[0]["start"]
                attrs["next_booking_end"] = upcoming[0]["end"]
                attrs["next_booking_duration_hrs"] = upcoming[0].get("duration_hrs")
                attrs["upcoming_bookings_count"] = len(upcoming)
        
        return attrs if attrs else None