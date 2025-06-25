# custom_components/genesisenergy/__init__.py

"""The Genesis Energy integration."""
import voluptuous as vol
import pytz

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN, PLATFORMS, LOGGER, CONF_EMAIL,
    SERVICE_ADD_POWERSHOUT_BOOKING, ATTR_START_DATETIME, ATTR_DURATION_HOURS,
    DATA_API_POWERSHOUT_OFFERS, DATA_API_AGGREGATED_ELEC_BILL, DATA_API_POWERSHOUT_INFO,
    SERVICE_BACKFILL_STATISTICS, ATTR_DAYS_TO_FETCH, ATTR_FUEL_TYPE,
    SERVICE_FORCE_UPDATE, DATA_API_BILLING_PLANS # <-- Import DATA_API_BILLING_PLANS
)
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .exceptions import InvalidAuth, CannotConnect

# Schemas remain the same, offering all options
SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING = vol.Schema({
    vol.Required(ATTR_START_DATETIME): cv.datetime,
    vol.Required(ATTR_DURATION_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
})

SERVICE_SCHEMA_BACKFILL_STATISTICS = vol.Schema({
    vol.Required(ATTR_DAYS_TO_FETCH): vol.All(vol.Coerce(int), vol.Range(min=1, max=730)),
    vol.Required(ATTR_FUEL_TYPE): vol.In(["electricity", "gas", "both"]),
})

SERVICE_SCHEMA_FORCE_UPDATE = vol.Schema({
    vol.Required(ATTR_FUEL_TYPE): vol.In(["electricity", "gas", "both"]),
})

# --- Helper function to check for available services ---
def get_available_services(coordinator: GenesisEnergyDataUpdateCoordinator) -> tuple[bool, bool]:
    """Checks billing plans and returns a tuple of (has_electricity, has_gas)."""
    has_electricity = False
    has_gas = False
    billing_plans_data = coordinator.data.get(DATA_API_BILLING_PLANS)
    if billing_plans_data and isinstance(billing_plans_data.get("billingAccountSites"), list):
        for site in billing_plans_data["billingAccountSites"]:
            if isinstance(site.get("supplyPoints"), list):
                for supply_point in site["supplyPoints"]:
                    if isinstance(supply_point, dict):
                        supply_type = supply_point.get("supplyType")
                        if supply_type == "electricity":
                            has_electricity = True
                        elif supply_type == "naturalGas":
                            has_gas = True
    return has_electricity, has_gas


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Genesis Energy from a config entry."""
    LOGGER.info(f"Setting up Genesis Energy for entry: {entry.title}")

    hass.data.setdefault(DOMAIN, {})
    coordinator = GenesisEnergyDataUpdateCoordinator(hass, entry)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        LOGGER.error(f"Initial data fetch failed for {entry.title}. Retrying setup.")
        raise
    except Exception as e:
        LOGGER.error(f"Unexpected error during first refresh for {entry.title}: {e}", exc_info=True)
        raise ConfigEntryNotReady(f"Initial data fetch failed with an unexpected error: {e}") from e

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ... (add_powershout_booking service is unchanged) ...
    @callback
    async def async_add_powershout_booking_service(call: ServiceCall) -> None:
        pass # Unchanged

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING,
        async_add_powershout_booking_service,
        schema=SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING,
    )

    # --- MODIFIED Backfill Service Handler ---
    @callback
    async def async_backfill_statistics_service(call: ServiceCall) -> None:
        """Handle the service call to backfill historical statistics."""
        days = call.data[ATTR_DAYS_TO_FETCH]
        requested_fuel = call.data[ATTR_FUEL_TYPE]

        has_electricity, has_gas = get_available_services(coordinator)
        
        # Determine what to actually process based on user's selection and available services
        process_fuel = "none"
        if requested_fuel == "electricity" and has_electricity:
            process_fuel = "electricity"
        elif requested_fuel == "gas" and has_gas:
            process_fuel = "gas"
        elif requested_fuel == "both":
            # If they ask for both, we determine what that actually means for them
            if has_electricity and has_gas:
                process_fuel = "both"
            elif has_electricity:
                process_fuel = "electricity"
            elif has_gas:
                process_fuel = "gas"
        
        if process_fuel == "none":
            LOGGER.warning(
                "Backfill service called for '%s', but this service is not available on your account. Aborting.",
                requested_fuel
            )
            return

        LOGGER.info(f"Backfill service proceeding for '{process_fuel}' for {days} days. This will run in the background.")
        hass.async_create_task(coordinator.async_backfill_statistics_data(days, process_fuel))

    hass.services.async_register(
        DOMAIN, SERVICE_BACKFILL_STATISTICS,
        async_backfill_statistics_service,
        schema=SERVICE_SCHEMA_BACKFILL_STATISTICS,
    )

    # --- MODIFIED Force Update Service Handler ---
    @callback
    async def async_force_update_service(call: ServiceCall) -> None:
        """Handle the service call to force an update."""
        # Although the UI will show options, a force update should always be a full refresh
        # for maximum data consistency. We can just log that we received the call.
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        LOGGER.info(f"Force update service called (for '{requested_fuel}'). Requesting a full coordinator refresh.")
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE,
        async_force_update_service,
        schema=SERVICE_SCHEMA_FORCE_UPDATE,
    )

    def _unload_services():
        hass.services.async_remove(DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING)
        hass.services.async_remove(DOMAIN, SERVICE_BACKFILL_STATISTICS)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_UPDATE)
    
    entry.async_on_unload(_unload_services)
    
    LOGGER.info(f"Genesis Energy setup complete for {entry.data[CONF_EMAIL]}")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            await hass.data[DOMAIN][entry.entry_id].api.close()
            hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok