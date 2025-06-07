"""The Genesis Energy integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, PLATFORMS, CONF_EMAIL, CONF_PASSWORD
from .api import GenesisEnergyApi # For type hinting

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Genesis Energy from a config entry."""
    _LOGGER.debug(f"Setting up Genesis Energy entry: {entry.entry_id} ({entry.title})")
    
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    
    # Create a single API instance for this config entry.
    # Sensors will use this instance.
    session = async_get_clientsession(hass)
    api_instance = GenesisEnergyApi(email, password, session)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api_instance,
        "email_username": email.split('@')[0] if '@' in email else email # For unique IDs
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Add a listener to close the API session when the entry is unloaded.
    async def _close_api_on_unload():
        _LOGGER.debug(f"Closing API session for entry {entry.entry_id} on unload.")
        await api_instance.close() # Call the close method on your API instance

    entry.async_on_unload(_close_api_on_unload)
    
    _LOGGER.info(f"Genesis Energy setup complete for {email}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug(f"Unloading Genesis Energy entry: {entry.entry_id} ({entry.title})")
    
    # The api.close() is handled by the listener set in async_setup_entry.
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
            if not hass.data[DOMAIN]: # If no more entries for this domain
                hass.data.pop(DOMAIN) # Clean up domain data if empty
        _LOGGER.info(f"Genesis Energy entry unloaded: {entry.title}")
    else:
        _LOGGER.error(f"Failed to unload platforms for Genesis Energy entry: {entry.title}")
        
    return unload_ok