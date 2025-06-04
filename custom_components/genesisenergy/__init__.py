"""The Genesis Energy integration."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import GenesisEnergyApi
from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_EMAIL,
    CONF_PASSWORD,
    DEFAULT_SCAN_INTERVAL_SECONDS, # Use the seconds version
    DATA_API_RESPONSE_ELECTRICITY_USAGE,
    DATA_API_RESPONSE_GAS_USAGE,
    DATA_API_RESPONSE_POWERSHOUT_INFO,
    DATA_API_RESPONSE_POWERSHOUT_BALANCE,
    DATA_API_RESPONSE_POWERSHOUT_BOOKINGS,
    DATA_API_RESPONSE_POWERSHOUT_OFFERS,
    DATA_API_RESPONSE_POWERSHOUT_EXPIRING,
)
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Genesis Energy from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    api = GenesisEnergyApi(email, password)

    async def async_update_data():
        """Fetch data from API endpoint. This is the 'update_method' for the coordinator."""
        _LOGGER.debug("Coordinator: Starting data update cycle.")
        try:
            # The _ensure_valid_token method in api.py will be called internally
            # by the first _make_api_call if tokens are needed/expired.
            # Subsequent _make_api_call invocations in this same update cycle
            # should reuse the token if it's still valid.
            
            data_fetches = {
                DATA_API_RESPONSE_ELECTRICITY_USAGE: api.get_energy_data(),
                DATA_API_RESPONSE_GAS_USAGE: api.get_gas_data(),
                DATA_API_RESPONSE_POWERSHOUT_INFO: api.get_powershout_info(),
                DATA_API_RESPONSE_POWERSHOUT_BALANCE: api.get_powershout_balance(),
                DATA_API_RESPONSE_POWERSHOUT_BOOKINGS: api.get_powershout_bookings(),
                DATA_API_RESPONSE_POWERSHOUT_OFFERS: api.get_powershout_offers(),
                DATA_API_RESPONSE_POWERSHOUT_EXPIRING: api.get_powershout_expiring_hours(),
            }

            results = {}
            for key, task_coro in data_fetches.items():
                _LOGGER.debug(f"Coordinator: Fetching {key}")
                try:
                    results[key] = await task_coro
                except (InvalidAuth, CannotConnect) as err: # Catch specific errors per call
                    _LOGGER.warning(f"Coordinator: Failed to fetch {key}: {err}. Storing None.")
                    results[key] = None # Store None if a specific endpoint fails
                except Exception as err: # Catch other unexpected errors per call
                    _LOGGER.error(f"Coordinator: Unexpected error fetching {key}: {err}", exc_info=True)
                    results[key] = None # Store None
            
            _LOGGER.debug(f"Coordinator: Data fetch cycle complete. Data keys received: {list(results.keys())}")
            return results

        except InvalidAuth as err: # This would typically be raised by _ensure_valid_token if login fails
            _LOGGER.error("Authentication error during coordinator update (likely login failure): %s", err)
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except CannotConnect as err: # This could be raised by _ensure_valid_token or _make_api_call
            _LOGGER.error("Connection error during coordinator update: %s", err)
            raise UpdateFailed(f"Failed to connect to Genesis API: {err}") from err
        except Exception as err: # Catch-all for truly unexpected issues in the update_data structure
            _LOGGER.error("Unexpected error structure in coordinator update: %s", err, exc_info=True)
            raise UpdateFailed(f"Unexpected error during Genesis data fetch: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_SECONDS),
    )

    # Perform the first refresh.
    # ConfigEntryAuthFailed and UpdateFailed will be handled by Home Assistant.
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api, 
        "coordinator": coordinator,
        "email_username": email.split('@')[0] if '@' in email else email # For device naming
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok