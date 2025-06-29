# custom_components/genesisenergy/__init__.py

"""The Genesis Energy integration."""
import voluptuous as vol
import pytz

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.components.persistent_notification import async_create

from .const import (
    DOMAIN, PLATFORMS, LOGGER, CONF_EMAIL,
    SERVICE_ADD_POWERSHOUT_BOOKING, ATTR_START_DATETIME, ATTR_DURATION_HOURS,
    DATA_API_POWERSHOUT_INFO, DATA_API_AGGREGATED_ELEC_BILL,
    SERVICE_BACKFILL_STATISTICS, ATTR_DAYS_TO_FETCH, ATTR_FUEL_TYPE,
    SERVICE_FORCE_UPDATE, DATA_API_BILLING_PLANS
)
from .coordinator import GenesisEnergyDataUpdateCoordinator
from .exceptions import CannotConnect, InvalidAuth

# Schemas remain the same
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

# ... (get_available_services and async_setup_entry boilerplate are unchanged) ...

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

    # --- REVISED Power Shout Booking Service ---
    @callback
    async def async_add_powershout_booking_service(call: ServiceCall) -> None:
        """Handle the service call to add a Power Shout booking."""
        start_dt_raw = call.data[ATTR_START_DATETIME]
        duration = call.data[ATTR_DURATION_HOURS]

        # --- MODIFICATION START ---
        # Floor the start time to the beginning of the hour.
        start_dt = start_dt_raw.replace(minute=0, second=0, microsecond=0)
        LOGGER.info(
            f"Power Shout booking requested for {start_dt_raw}. "
            f"Flooring to hour start time: {start_dt}"
        )
        # --- MODIFICATION END ---


        LOGGER.info(f"Attempting to book Power Shout for {duration} hour(s) starting at {start_dt}")

        ps_info = coordinator.data.get(DATA_API_POWERSHOUT_INFO)

        if not ps_info or not all(k in ps_info for k in ['supplyAgreementId', 'supplyPointId', 'loyaltyAccountId']):
            LOGGER.error("Could not book Power Shout: Missing required IDs. Please try again after the next update.")
            async_create(
                hass,
                "Could not book Power Shout: Required information is missing. Please wait a minute and try again.",
                title="Genesis Energy Power Shout Failed",
                notification_id="genesis_powershout_error"
            )
            return

        supply_agreement_id = ps_info['supplyAgreementId']
        supply_point_id = ps_info['supplyPointId']
        loyalty_account_id = ps_info['loyaltyAccountId']

        # Use the floored datetime for the API call
        start_date_str = start_dt.astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')

        try:
            success = await coordinator.api.add_powershout_booking(
                start_date_str=start_date_str,
                duration=duration,
                supply_agreement_id=supply_agreement_id,
                supply_point_id=supply_point_id,
                loyalty_account_id=loyalty_account_id
            )

            if success:
                LOGGER.info("Successfully booked Power Shout.")
                # --- MODIFICATION --- Use the floored time in the success message
                async_create(
                    hass,
                    f"Your {duration}-hour Power Shout starting at {start_dt.strftime('%-I:%M %p')} has been booked successfully.",
                    title="Genesis Energy Power Shout Booked",
                    notification_id="genesis_powershout_success"
                )
                await coordinator.async_request_refresh()
            else:
                LOGGER.error("Failed to book Power Shout. The API call was unsuccessful.")
                async_create(
                    hass,
                    "The Power Shout booking failed. The API reported an issue. Check logs for details.",
                    title="Genesis Energy Power Shout Failed",
                    notification_id="genesis_powershout_error"
                )

        except (CannotConnect, InvalidAuth) as e:
            LOGGER.error(f"Failed to book Power Shout due to an API error: {e}")
            async_create(
                hass, f"The Power Shout booking failed due to an API error: {e}",
                title="Genesis Energy Power Shout Failed", notification_id="genesis_powershout_error"
            )
        except Exception as e:
            LOGGER.exception("An unexpected error occurred while booking Power Shout.")
            async_create(
                hass, f"An unexpected error occurred: {e}",
                title="Genesis Energy Power Shout Failed", notification_id="genesis_powershout_error"
            )


    hass.services.async_register(
        DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING,
        async_add_powershout_booking_service,
        schema=SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING,
    )

    # --- Backfill Service Handler (Unchanged) ---
    @callback
    async def async_backfill_statistics_service(call: ServiceCall) -> None:
        """Handle the service call to backfill historical statistics."""
        days = call.data[ATTR_DAYS_TO_FETCH]
        requested_fuel = call.data[ATTR_FUEL_TYPE]

        has_electricity, has_gas = get_available_services(coordinator)
        
        process_fuel = "none"
        if requested_fuel == "electricity" and has_electricity:
            process_fuel = "electricity"
        elif requested_fuel == "gas" and has_gas:
            process_fuel = "gas"
        elif requested_fuel == "both":
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

    # --- Force Update Service Handler (Unchanged) ---
    @callback
    async def async_force_update_service(call: ServiceCall) -> None:
        """Handle the service call to force an update."""
        requested_fuel = call.data[ATTR_FUEL_TYPE]
        LOGGER.info(f"Force update service called (for '{requested_fuel}'). Requesting a full coordinator refresh.")
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_FORCE_UPDATE,
        async_force_update_service,
        schema=SERVICE_SCHEMA_FORCE_UPDATE,
    )
    
    # ... (Service unloading and final setup are unchanged) ...
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