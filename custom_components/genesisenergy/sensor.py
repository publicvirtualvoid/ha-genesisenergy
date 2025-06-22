# custom_components/genesisenergy/sensor.py
import logging
from datetime import datetime
import pytz
from functools import partial
from typing import Any, Mapping
import json

from homeassistant.components.sensor import (
    SensorEntity, SensorEntityDescription, SensorStateClass, SensorDeviceClass
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics, get_last_statistics

from .const import (
    DOMAIN, LOGGER, DATA_API_ELECTRICITY_USAGE, DATA_API_GAS_USAGE, DATA_API_POWERSHOUT_INFO,
    DATA_API_POWERSHOUT_BALANCE, DATA_API_POWERSHOUT_BOOKINGS, DATA_API_POWERSHOUT_OFFERS,
    DATA_API_POWERSHOUT_EXPIRING, DATA_API_BILLING_PLANS, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS,
    STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST,
    STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST, SENSOR_KEY_POWERSHOUT_ELIGIBLE,
    SENSOR_KEY_POWERSHOUT_BALANCE, SENSOR_KEY_ACCOUNT_DETAILS,
    DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER,
    DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT,
    DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST,
    DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION,
    SENSOR_KEY_BILL_ELEC_USED, SENSOR_KEY_BILL_GAS_USED, SENSOR_KEY_BILL_TOTAL_USED,
    SENSOR_KEY_BILL_ESTIMATED_TOTAL, SENSOR_KEY_BILL_ESTIMATED_FUTURE
)
from .coordinator import GenesisEnergyDataUpdateCoordinator

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GenesisEnergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    entities = []
    has_electricity, has_gas = False, False
    billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
    if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
        for site in billing_plans_data["billingAccountSites"]:
            if isinstance(site.get("supplyPoints"), list):
                for supply_point in site["supplyPoints"]:
                    if isinstance(supply_point, dict):
                        supply_type = supply_point.get("supplyType")
                        if supply_type == "electricity": has_electricity = True
                        elif supply_type == "naturalGas": has_gas = True
    
    if has_electricity: entities.append(GenesisEnergyStatisticsSensor(coordinator, "Electricity"))
    if has_gas: entities.append(GenesisEnergyStatisticsSensor(coordinator, "Gas"))

    entities.extend([
        PowerShoutEligibilitySensor(coordinator),
        PowerShoutBalanceSensor(coordinator),
        GenesisEnergyAccountSensor(coordinator)
    ])
    
    if coordinator.data.get(DATA_API_WIDGET_SIDEKICK):
        LOGGER.info("Sidekick widget data found. Adding billing sensors.")
        entities.append(TotalUsedSensor(coordinator))
        entities.append(EstimatedTotalSensor(coordinator))
        entities.append(EstimatedFutureUseSensor(coordinator))
        if has_electricity: entities.append(ElectricityUsedSensor(coordinator))
        if has_gas: entities.append(GasUsedSensor(coordinator))
    else:
        LOGGER.warning("Sidekick widget data not found. Skipping billing sensors.")
    
    async_add_entities(entities)

class GenesisEnergyStatisticsSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True; _attr_should_poll = False
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, fuel_type: str):
        super().__init__(coordinator)
        self._fuel_type = fuel_type
        self._data_key = DATA_API_ELECTRICITY_USAGE if fuel_type == "Electricity" else DATA_API_GAS_USAGE
        self._attr_device_info = coordinator.device_info
        self.entity_description = SensorEntityDescription(key=f"{fuel_type.lower()}_statistics_updater", name=f"{fuel_type.capitalize()} Statistics Updater", icon="mdi:chart-line" if self._fuel_type == "Electricity" else "mdi:chart-bell-curve-cumulative")
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
        if self._fuel_type == "Electricity":
            self._consumption_statistic_id, self._cost_statistic_id = STATISTIC_ID_ELECTRICITY_CONSUMPTION, STATISTIC_ID_ELECTRICITY_COST
        else:
            self._consumption_statistic_id, self._cost_statistic_id = STATISTIC_ID_GAS_CONSUMPTION, STATISTIC_ID_GAS_COST
        self._consumption_statistic_name, self._cost_statistic_name = f"Genesis {fuel_type} Consumption Daily", f"Genesis {fuel_type} Cost Daily"
        self._unit, self._currency, self._processed_data_hash = "kWh", "NZD", None
    @property
    def native_value(self) -> str:
        if self.coordinator.data and (api_data := self.coordinator.data.get(self._data_key)) and api_data.get("usage"): return "ok"
        elif self.coordinator.last_update_success: return "no_data"
        return "error"
    @callback
    def _handle_coordinator_update(self) -> None:
        if not self.coordinator.last_update_success: self.async_write_ha_state(); return
        if api_data := self.coordinator.data.get(self._data_key):
            if raw_usage_list := api_data.get('usage'):
                if isinstance(raw_usage_list, list) and raw_usage_list:
                    current_hash = (len(raw_usage_list), raw_usage_list[0].get('startDate'), raw_usage_list[-1].get('startDate'))
                    if self._processed_data_hash != current_hash:
                        self.hass.async_create_task(self.async_process_statistics_data(list(raw_usage_list)))
                        self._processed_data_hash = current_hash
        self.async_write_ha_state()
    async def async_process_statistics_data(self, usage_data: list):
        if not usage_data: return
        try: sorted_usage_data = sorted(usage_data, key=lambda x: x['startDate'])
        except (KeyError, TypeError): return
        async def _process_one_statistic(statistic_id: str, stat_name: str, unit: str, value_key: str):
            def _get_last_stats_at_time(): return get_last_statistics(self.hass, 1, statistic_id, True, {"sum"}, end_time=datetime.fromisoformat(sorted_usage_data[0]['startDate']).astimezone(pytz.utc))
            last_stat_list = await get_instance(self.hass).async_add_executor_job(_get_last_stats_at_time)
            last_stat = last_stat_list.get(statistic_id, [{}])[0]; running_sum = float(last_stat.get('sum', 0.0))
            stats_to_add = []
            for entry in sorted_usage_data:
                try:
                    value = float(entry[value_key])
                    start_dt_utc = datetime.fromisoformat(entry['startDate']).astimezone(pytz.utc)
                except (KeyError, ValueError, TypeError): continue
                running_sum += round(value, 3); stats_to_add.append(StatisticData(start=start_dt_utc, state=round(value, 2), sum=round(running_sum, 3)))
            if stats_to_add:
                meta = StatisticMetaData(has_mean=False, has_sum=True, name=stat_name, source=DOMAIN, statistic_id=statistic_id, unit_of_measurement=unit)
                async_add_external_statistics(self.hass, meta, stats_to_add)
        await _process_one_statistic(self._consumption_statistic_id, self._consumption_statistic_name, self._unit, 'kw')
        await _process_one_statistic(self._cost_statistic_id, self._cost_statistic_name, self._currency, 'costNZD')

class GenesisBillSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "NZD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_icon = "mdi:cash"
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator, desc: SensorEntityDescription):
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_device_info = coordinator.device_info
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{desc.key}"
    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data and self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK) is not None

class ElectricityUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_ELEC_USED, name="Genesis Bill - Electricity Used", state_class=SensorStateClass.TOTAL)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        for supply in sidekick_data.get('supplyTypesArea', {}).get('supplyTypes', []):
            if supply.get('type') == 'electricity':
                try: return float(supply.get('value'))
                except (ValueError, TypeError): return None
        return 0.0

class GasUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_GAS_USED, name="Genesis Bill - Gas Used", state_class=SensorStateClass.TOTAL)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        for supply in sidekick_data.get('supplyTypesArea', {}).get('supplyTypes', []):
            if supply.get('type') == 'naturalGas':
                try: return float(supply.get('value'))
                except (ValueError, TypeError): return None
        return 0.0

class TotalUsedSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        # --- FIX: State class should be TOTAL ---
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_TOTAL_USED, name="Genesis Bill - Total Used", state_class=SensorStateClass.TOTAL)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        if (value := sidekick_data.get('titleArea', {}).get('value')) is not None:
            try: return float(value)
            except (ValueError, TypeError): return None
        return None

class EstimatedTotalSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        # --- FIX: State class should be None ---
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_TOTAL, name="Genesis Bill - Estimated Total", state_class=None)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        title = sidekick_data.get('billArea', {}).get('title')
        if title and '$' in title:
            try: return float(title.split('$')[1])
            except (ValueError, IndexError): return None
        return None

class EstimatedFutureUseSensor(GenesisBillSensor):
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        # --- FIX: State class should be None ---
        description = SensorEntityDescription(key=SENSOR_KEY_BILL_ESTIMATED_FUTURE, name="Genesis Bill - Estimated Future Use", state_class=None)
        super().__init__(coordinator, description)
    @property
    def native_value(self) -> float | None:
        sidekick_data = self.coordinator.data.get(DATA_API_WIDGET_SIDEKICK, {})
        estimated_val, used_val = 0.0, 0.0
        title = sidekick_data.get('billArea', {}).get('title')
        if title and '$' in title:
            try: estimated_val = float(title.split('$')[1])
            except (ValueError, IndexError): pass
        if (value := sidekick_data.get('titleArea', {}).get('value')) is not None:
            try: used_val = float(value)
            except (ValueError, TypeError): pass
        future_use = estimated_val - used_val
        return round(future_use, 2) if future_use >= 0 else 0.0

class PowerShoutEligibilitySensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator); self._attr_device_info = coordinator.device_info; self.entity_description = SensorEntityDescription(key=SENSOR_KEY_POWERSHOUT_ELIGIBLE, name="Power Shout Eligible", icon="mdi:lightning-bolt-outline"); self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self):
        if ps_info := self.coordinator.data.get(DATA_API_POWERSHOUT_INFO): return ps_info.get("isEligible")
        return None
class PowerShoutBalanceSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator); self._attr_device_info = coordinator.device_info; self.entity_description = SensorEntityDescription(key=SENSOR_KEY_POWERSHOUT_BALANCE, name="Power Shout Balance", native_unit_of_measurement="hr", icon="mdi:timer-sand", state_class=SensorStateClass.MEASUREMENT); self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self):
        if ps_balance := self.coordinator.data.get(DATA_API_POWERSHOUT_BALANCE):
            if (val := ps_balance.get("balance")) is not None:
                try: return float(val)
                except (ValueError, TypeError): return None
        return None
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        attrs = {};
        if not self.coordinator.data: return None
        if offers := self.coordinator.data.get(DATA_API_POWERSHOUT_OFFERS, {}): attrs["active_offers_count"] = len(offers.get("activeOffers", []))
        if expiring := self.coordinator.data.get(DATA_API_POWERSHOUT_EXPIRING, {}):
            if msg := expiring.get("expiringHoursMessage", {}): attrs["expiring_hours_message"] = msg.get("title")
        if bookings := self.coordinator.data.get(DATA_API_POWERSHOUT_BOOKINGS, {}):
            upcoming = [b for b in bookings.get("bookings", []) if isinstance(b, dict) and datetime.fromisoformat(b.get("startDate")).astimezone(pytz.utc) > dt_util.utcnow()]
            if upcoming: upcoming.sort(key=lambda b: b["start"]); attrs["next_booking_start"] = upcoming[0].get("startDate")
        return attrs
class GenesisEnergyAccountSensor(CoordinatorEntity[GenesisEnergyDataUpdateCoordinator], SensorEntity):
    _attr_has_entity_name = True
    def __init__(self, coordinator: GenesisEnergyDataUpdateCoordinator):
        super().__init__(coordinator); self._attr_device_info = coordinator.device_info; self.entity_description = SensorEntityDescription(key=SENSOR_KEY_ACCOUNT_DETAILS, name="Account Details", icon="mdi:account-details"); self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self.entity_description.key}"
    @property
    def native_value(self) -> str: return dt_util.utcnow().isoformat() if self.coordinator.last_update_success else "error"
    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        if not self.coordinator.data: return None
        attribute_keys = [DATA_API_BILLING_PLANS, DATA_API_WIDGET_HERO, DATA_API_WIDGET_BILLS, DATA_API_WIDGET_PROPERTY_LIST, DATA_API_WIDGET_PROPERTY_SWITCHER, DATA_API_WIDGET_SIDEKICK, DATA_API_WIDGET_DASHBOARD_POWERSHOUT, DATA_API_WIDGET_ECO_TRACKER, DATA_API_WIDGET_DASHBOARD_LIST, DATA_API_WIDGET_ACTION_TILE_LIST, DATA_API_NEXT_BEST_ACTION]
        attrs = {}; [attrs.update({key.replace("api_", ""): data}) for key in attribute_keys if (data := self.coordinator.data.get(key)) is not None]
        return {k: (json.dumps(v, indent=2) if isinstance(v, (dict, list)) else v) for k, v in attrs.items()}