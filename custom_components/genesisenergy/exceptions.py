"""Exceptions for the Genesis Energy integration."""

from homeassistant.exceptions import HomeAssistantError

class GenesisEnergyError(HomeAssistantError):
    """Base class for Genesis Energy integration errors."""
    pass

class CannotConnect(GenesisEnergyError):
    """Error to indicate we cannot connect to the API."""
    pass

class InvalidAuth(GenesisEnergyError):
    """Error to indicate there is invalid authentication."""
    pass