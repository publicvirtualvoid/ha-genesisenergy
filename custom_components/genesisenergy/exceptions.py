# custom_components/genesisenergy/exceptions.py

from homeassistant.exceptions import HomeAssistantError

class GenesisEnergyError(HomeAssistantError):
    """Base class for Genesis Energy integration errors."""
    pass

class CannotConnect(GenesisEnergyError):
    """Error to indicate we cannot connect."""
    pass

class InvalidAuth(GenesisEnergyError):
    """Error to indicate there is invalid auth."""
    pass