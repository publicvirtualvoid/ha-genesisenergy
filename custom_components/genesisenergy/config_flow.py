"""Config flow for Genesis Energy integration."""

import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession


from .api import GenesisEnergyApi
from .const import DOMAIN, INTEGRATION_NAME
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)

class GenesisEnergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Genesis Energy."""
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            # Use email as unique_id to prevent duplicate entries for the same account
            await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = GenesisEnergyApi(user_input[CONF_EMAIL], user_input[CONF_PASSWORD], session)
            try:
                # Test authentication by attempting a login
                await api._ensure_valid_token() 
                _LOGGER.info("Config flow: Authentication successful.")
                return self.async_create_entry(title=INTEGRATION_NAME, data=user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception during config flow.")
                errors["base"] = "unknown"
            # No need to explicitly close session if it's managed by HA (async_get_clientsession)
            # but if api.close() was implemented to handle shared sessions, call it.
            # await api.close() # Only if api.close() is smart about shared sessions

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }),
            errors=errors,
        )