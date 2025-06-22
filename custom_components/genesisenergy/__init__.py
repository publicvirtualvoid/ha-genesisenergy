"""The Genesis Energy integration."""
import logging
import voluptuous as vol
from datetime import datetime, timedelta 
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.exceptions import ConfigEntryNotReady 

import pytz 

from .const import (
    DOMAIN, 
    PLATFORMS, 
    CONF_EMAIL, 
    CONF_PASSWORD,
    SERVICE_ADD_POWERSHOUT_BOOKING,
    ATTR_START_DATETIME,
    ATTR_DURATION_HOURS,
    SENSOR_KEY_POWERSHOUT_BALANCE,
    SENSOR_KEY_POWERSHOUT_ELIGIBLE,
    SENSOR_KEY_ACCOUNT_DETAILS,
    STORED_KEY_LOYALTY_ACCOUNT_ID,
    STORED_KEY_SUPPLY_AGREEMENT_ID,
    STORED_KEY_SUPPLY_POINT_ID,
)
from .api import GenesisEnergyApi 
from .exceptions import InvalidAuth, CannotConnect

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING = vol.Schema(
    {
        vol.Required(ATTR_START_DATETIME): cv.datetime, 
        vol.Required(ATTR_DURATION_HOURS): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)), 
    }
)

async def fetch_and_store_booking_ids(hass: HomeAssistant, entry: ConfigEntry, api: GenesisEnergyApi) -> bool:
    """Fetch and store Power Shout booking related IDs."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug(f"Attempting to fetch and store booking IDs for {entry.title}")

    entry_data.pop(STORED_KEY_LOYALTY_ACCOUNT_ID, None)
    entry_data.pop(STORED_KEY_SUPPLY_AGREEMENT_ID, None)
    entry_data.pop(STORED_KEY_SUPPLY_POINT_ID, None)

    loyalty_account_id = None
    supply_agreement_id = None
    supply_point_id = None 

    all_ids_found_perfectly = False

    try:
        # 1. Get Loyalty Account ID from offers
        _LOGGER.debug(f"Fetching powershout_offers for {STORED_KEY_LOYALTY_ACCOUNT_ID}")
        offers_data = await api.get_powershout_offers()
        _LOGGER.debug(f"Raw powershout_offers response: {offers_data}")
        if offers_data and isinstance(offers_data.get("acceptedOffers"), list) and offers_data["acceptedOffers"]:
            first_offer = offers_data["acceptedOffers"][0]
            if isinstance(first_offer.get("loyaltyAccount"), dict):
                loyalty_account_id = first_offer["loyaltyAccount"].get("id")
                _LOGGER.debug(f"Derived {STORED_KEY_LOYALTY_ACCOUNT_ID} from offers: {loyalty_account_id}")
        
        # 2. Get Supply Agreement ID and Electricity Supply Point ID from electricity_aggregated_bill_period
        _LOGGER.debug(f"Fetching electricity_aggregated_bill_period for {STORED_KEY_SUPPLY_AGREEMENT_ID} and {STORED_KEY_SUPPLY_POINT_ID}")
        to_date_str = datetime.now().strftime("%Y-%m-%d")
        from_date_str = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d") 
        
        agg_elec_data = await api.get_electricity_aggregated_bill_period(from_date_str, to_date_str)
        _LOGGER.debug(f"Raw electricity_aggregated_bill_period response: {agg_elec_data}")

        if agg_elec_data and isinstance(agg_elec_data, dict) and agg_elec_data: 
            current_sp_id = agg_elec_data.get("supplyPointId")
            if current_sp_id and current_sp_id.upper().startswith("ELECTRICITY-"):
                supply_point_id = current_sp_id
                _LOGGER.debug(f"Derived {STORED_KEY_SUPPLY_POINT_ID} from agg_elec_data: {supply_point_id}")
            
            current_sa_id = agg_elec_data.get("supplyAgreementId")
            if current_sa_id:
                supply_agreement_id = current_sa_id
                _LOGGER.debug(f"Derived {STORED_KEY_SUPPLY_AGREEMENT_ID} from agg_elec_data: {supply_agreement_id}")

            if not supply_point_id or not supply_agreement_id: 
                sp_array = agg_elec_data.get("supplyPoints")
                if isinstance(sp_array, list) and sp_array:
                    first_sp_in_array = sp_array[0]
                    if isinstance(first_sp_in_array, dict):
                        if not supply_point_id and first_sp_in_array.get("supplyPointId", "").upper().startswith("ELECTRICITY-"):
                            supply_point_id = first_sp_in_array.get("supplyPointId")
                            _LOGGER.debug(f"Derived {STORED_KEY_SUPPLY_POINT_ID} from agg_elec_data.supplyPoints[0]: {supply_point_id}")
                        if not supply_agreement_id:
                            supply_agreement_id = first_sp_in_array.get("supplyAgreementId")
                            _LOGGER.debug(f"Derived {STORED_KEY_SUPPLY_AGREEMENT_ID} from agg_elec_data.supplyPoints[0]: {supply_agreement_id}")
        else:
            _LOGGER.warning(f"electricity_aggregated_bill_period returned empty/invalid data for {entry.title}. Will try ps_info for SA/SP ID.")

        # 3. Fallback: Try get_powershout_info() if primary methods for SA/SP_ID failed or agg_elec_data was empty
        if not supply_agreement_id or not supply_point_id:
            _LOGGER.debug(f"SA_ID or SP_ID still missing. Fetching powershout_info as fallback.")
            ps_info_fallback = await api.get_powershout_info() 
            _LOGGER.debug(f"Raw powershout_info response (for SA/SP_ID fallback): {ps_info_fallback}")
            if ps_info_fallback and isinstance(ps_info_fallback, dict):
                if not loyalty_account_id: 
                     current_la_id = ps_info_fallback.get("loyaltyAccountId")
                     if current_la_id:
                         loyalty_account_id = current_la_id
                         _LOGGER.debug(f"Derived {STORED_KEY_LOYALTY_ACCOUNT_ID} from ps_info (fallback): {loyalty_account_id}")
                
                eligible_accounts = ps_info_fallback.get("eligibleBillingAccounts")
                if isinstance(eligible_accounts, list) and eligible_accounts:
                    first_account = eligible_accounts[0]
                    if isinstance(first_account, dict):
                        if not supply_agreement_id: 
                            current_sa_id_fb = first_account.get("id")
                            if current_sa_id_fb:
                                supply_agreement_id = current_sa_id_fb
                                _LOGGER.debug(f"Derived {STORED_KEY_SUPPLY_AGREEMENT_ID} from ps_info (fallback): {supply_agreement_id}")
                        
                        if not supply_point_id: 
                            billing_sites = first_account.get("billingAccountSites")
                            if isinstance(billing_sites, list) and billing_sites:
                                first_site = billing_sites[0] 
                                if isinstance(first_site, dict):
                                    supply_points_list = first_site.get("supplyPoints")
                                    if isinstance(supply_points_list, list):
                                        for sp_fb in supply_points_list:
                                            if isinstance(sp_fb, dict) and sp_fb.get("id", "").upper().startswith("ELECTRICITY-"):
                                                current_sp_id_fb = sp_fb.get("id")
                                                if current_sp_id_fb:
                                                    supply_point_id = current_sp_id_fb
                                                    _LOGGER.debug(f"Derived {STORED_KEY_SUPPLY_POINT_ID} from ps_info (fallback): {supply_point_id}")
                                                
                                                sp_supply_agreement_id_fb = sp_fb.get("supplyAgreementId")
                                                if sp_supply_agreement_id_fb and (not supply_agreement_id or sp_supply_agreement_id_fb == supply_agreement_id) :
                                                    supply_agreement_id = sp_supply_agreement_id_fb
                                                    _LOGGER.debug(f"Confirmed/updated {STORED_KEY_SUPPLY_AGREEMENT_ID} from ps_info supplyPoint (fallback): {supply_agreement_id}")
                                                break 
        
        _LOGGER.debug(f"After all primary/fallback ID fetches: LA_ID={loyalty_account_id}, SA_ID={supply_agreement_id}, SP_ID={supply_point_id}")
        
        if all([loyalty_account_id, supply_agreement_id, supply_point_id]):
            entry_data[STORED_KEY_LOYALTY_ACCOUNT_ID] = loyalty_account_id
            entry_data[STORED_KEY_SUPPLY_AGREEMENT_ID] = supply_agreement_id
            entry_data[STORED_KEY_SUPPLY_POINT_ID] = supply_point_id
            _LOGGER.info(f"Successfully stored booking IDs for {entry.title}: "
                         f"LA_ID: {loyalty_account_id}, SA_ID: {supply_agreement_id}, SP_ID: {supply_point_id}")
            all_ids_found_perfectly = True
        else:
            _LOGGER.error(f"Could not derive all necessary booking IDs for {entry.title}. "
                          f"Final derived: LA_ID: {loyalty_account_id}, SA_ID: {supply_agreement_id}, SP_ID: {supply_point_id}")
            all_ids_found_perfectly = False

    except InvalidAuth as e: 
        _LOGGER.error(f"Authentication error while fetching booking IDs for {entry.title}: {e}.")
        raise ConfigEntryNotReady(f"Authentication failed during ID fetch for {entry.title}: {e}") from e
    except CannotConnect as e:
        _LOGGER.error(f"Connection error while fetching booking IDs for {entry.title}: {e}")
        raise ConfigEntryNotReady(f"Connection error during ID fetch for {entry.title}: {e}") from e
    except Exception as e:
        _LOGGER.error(f"Generic error during fetch_and_store_booking_ids for {entry.title}: {e}", exc_info=True)
        all_ids_found_perfectly = False
    
    return all_ids_found_perfectly


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Genesis Energy from a config entry."""
    _LOGGER.debug(f"Setting up Genesis Energy entry: {entry.entry_id} ({entry.title})")
    
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    
    session = async_get_clientsession(hass)
    api_instance = GenesisEnergyApi(email, password, session)

    try:
        await api_instance._ensure_valid_token()
    except (InvalidAuth, CannotConnect) as err:
        _LOGGER.error(f"API authentication/connection failed during initial token validation for {entry.title}: {err}")
        raise ConfigEntryNotReady(f"API token validation failed for {entry.title}: {err}") from err
    except Exception as err: # Catch any other unexpected error from _ensure_valid_token
        _LOGGER.error(f"Unexpected API error during initial token validation for {entry.title}: {err}", exc_info=True)
        raise ConfigEntryNotReady(f"Unexpected API token validation error for {entry.title}: {err}") from err


    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api_instance,
        "email_username": email.split('@')[0] if '@' in email else email,
    }

    try:
        ids_fetched_on_setup = await fetch_and_store_booking_ids(hass, entry, api_instance)
        if not ids_fetched_on_setup:
            _LOGGER.warning(
                f"Initial fetch of all booking IDs failed for {entry.title}. "
                "The booking service might not work correctly until all IDs are available. "
                "Service calls will re-attempt ID fetching if needed."
            )
            # Do not raise ConfigEntryNotReady here if it was a parsing issue,
            # as sensors might still work. Auth/Connect errors within fetch_and_store_booking_ids will raise.
    except ConfigEntryNotReady: # Re-raise if fetch_and_store_booking_ids raised it
        raise
    except Exception as e: # Catch any other unexpected error from fetch_and_store_booking_ids
        _LOGGER.error(f"Unexpected error during initial fetch_and_store_booking_ids for {entry.title}: {e}", exc_info=True)
        # Allow platform setup to continue, but log the problem


    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception as e: # Catch any exception from platform setup
        _LOGGER.error(f"Error setting up platforms for {entry.title}: {e}", exc_info=True)
        # Depending on the error, HA might already handle it or we might want to raise ConfigEntryNotReady
        # For now, if platform setup fails, the integration load will likely fail anyway or be incomplete.
        return False # Signal failure to load

    async def _close_api_on_unload():
        _LOGGER.debug(f"Closing API session for entry {entry.entry_id} on unload.")
        await api_instance.close() 

    entry.async_on_unload(_close_api_on_unload)
    
    @callback
    async def async_add_powershout_booking_service(call: ServiceCall) -> None:
        """Handle the service call to add a Power Shout booking."""
        _LOGGER.debug(f"Service '{SERVICE_ADD_POWERSHOUT_BOOKING}' called with data: {call.data}")
        
        api = hass.data[DOMAIN][entry.entry_id]["api"]
        entry_data = hass.data[DOMAIN][entry.entry_id]
        email_user_part = entry_data["email_username"]

        start_datetime_naive = call.data[ATTR_START_DATETIME]
        duration = call.data[ATTR_DURATION_HOURS]

        try:
            nz_tz = pytz.timezone('Pacific/Auckland')
            if start_datetime_naive.tzinfo is None or start_datetime_naive.tzinfo.utcoffset(start_datetime_naive) is None:
                start_datetime_local_nz = nz_tz.localize(start_datetime_naive)
            else: 
                start_datetime_local_nz = start_datetime_naive.astimezone(nz_tz)
            _LOGGER.debug(f"Service call: Initial datetime: {start_datetime_naive}, Target NZ datetime for API: {start_datetime_local_nz}")
        except Exception as e:
            _LOGGER.error(f"Error processing start_datetime for Power Shout booking: {e}", exc_info=True)
            hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Invalid start_datetime format or timezone issue for '{entry.title}': {e}"})
            return
            
        start_date_str = start_datetime_local_nz.strftime("%Y-%m-%dT%H:%M:%S")

        loyalty_account_id = entry_data.get(STORED_KEY_LOYALTY_ACCOUNT_ID)
        supply_agreement_id = entry_data.get(STORED_KEY_SUPPLY_AGREEMENT_ID)
        supply_point_id = entry_data.get(STORED_KEY_SUPPLY_POINT_ID)

        if not all([loyalty_account_id, supply_agreement_id, supply_point_id]):
            _LOGGER.warning(f"Booking IDs not pre-fetched or incomplete for {entry.title}. Attempting to fetch now for service call.")
            try:
                if not await fetch_and_store_booking_ids(hass, entry, api):
                    _LOGGER.error(f"Failed to fetch necessary IDs for Power Shout booking for {entry.title} during service call.")
                    hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Could not fetch required account IDs for Power Shout booking for '{entry.title}'. Check debug logs."})
                    return
            except (InvalidAuth, CannotConnect) as e:
                 _LOGGER.error(f"API error during ID fetch for service call for {entry.title}: {e}")
                 hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"API error fetching IDs for '{entry.title}': {e}"})
                 return
            except Exception as e: # Catch any other unexpected error
                 _LOGGER.error(f"Unexpected error during ID fetch for service call {entry.title}: {e}", exc_info=True)
                 hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Unexpected error fetching IDs for '{entry.title}': {e}"})
                 return


            loyalty_account_id = entry_data.get(STORED_KEY_LOYALTY_ACCOUNT_ID)
            supply_agreement_id = entry_data.get(STORED_KEY_SUPPLY_AGREEMENT_ID)
            supply_point_id = entry_data.get(STORED_KEY_SUPPLY_POINT_ID)

        if not all([loyalty_account_id, supply_agreement_id, supply_point_id]):
            _LOGGER.error(f"Still missing required IDs after fetch attempt for {entry.title}. LA_ID: {loyalty_account_id}, SA_ID: {supply_agreement_id}, SP_ID: {supply_point_id}")
            hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Critically failed to get all IDs for Power Shout booking for '{entry.title}'. Check debug logs."})
            return

        _LOGGER.info(f"Calling API to book Power Shout for {entry.title}: Start: {start_date_str}, Duration: {duration}, LA_ID: {loyalty_account_id}, SA_ID: {supply_agreement_id}, SP_ID: {supply_point_id}")

        try:
            result = await api.add_powershout_booking(start_date_str=start_date_str, duration=duration, supply_agreement_id=supply_agreement_id, supply_point_id=supply_point_id, loyalty_account_id=loyalty_account_id)
            _LOGGER.info(f"Power Shout booking API call result for {entry.title}: {result}")
            
            success = False
            if isinstance(result, bool) and result is True: success = True
            elif isinstance(result, dict) and result.get("status") in [200, 201, 204]: success = True
            
            if success:
                _LOGGER.info(f"Power Shout successfully booked for {entry.title} at {start_date_str} for {duration} hour(s).")
                hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booked", "message": f"Power Shout booked for {entry.title} starting {start_date_str} for {duration} hour(s)."})
            else:
                api_response_details = str(result.get("text", result) if isinstance(result, dict) else result)
                _LOGGER.error(f"Power Shout booking failed for {entry.title}. API response: {api_response_details}")
                hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Booking failed for {entry.title}. API response: {api_response_details}"})

        except InvalidAuth as e:
            _LOGGER.error(f"Authentication failed while trying to book Power Shout for {entry.title}: {e}")
            hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Auth error for {entry.title}: {e}"})
        except CannotConnect as e:
            _LOGGER.error(f"Connection error while trying to book Power Shout for {entry.title}: {e}")
            hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Connection error for {entry.title}: {e}"})
        except Exception as e:
            _LOGGER.error(f"Unexpected error while booking Power Shout for {entry.title}: {e}", exc_info=True)
            hass.services.async_call("persistent_notification", "create", {"title": "Power Shout Booking Failed", "message": f"Unexpected error for {entry.title}: {e}"})

        ent_reg = er.async_get(hass)
        sensors_to_refresh = [
            f"{DOMAIN}_{email_user_part}_powershout_{SENSOR_KEY_POWERSHOUT_BALANCE}",
            f"{DOMAIN}_{email_user_part}_powershout_{SENSOR_KEY_POWERSHOUT_ELIGIBLE}",
            f"{DOMAIN}_{email_user_part}_{SENSOR_KEY_ACCOUNT_DETAILS}" 
        ]
        for sensor_unique_id_suffix in sensors_to_refresh:
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, sensor_unique_id_suffix)
            if entity_id:
                _LOGGER.debug(f"Requesting update for sensor: {entity_id}")
                hass.async_create_task(hass.services.async_call("homeassistant", "update_entity", {"entity_id": entity_id}, blocking=False))
    
    _LOGGER.debug(f"Registering service '{SERVICE_ADD_POWERSHOUT_BOOKING}' with schema: {SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING.schema}")
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_POWERSHOUT_BOOKING,
        async_add_powershout_booking_service,
        schema=SERVICE_SCHEMA_ADD_POWERSHOUT_BOOKING,
    )
    
    _LOGGER.info(f"Genesis Energy setup complete for {email}")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug(f"Unloading Genesis Energy entry: {entry.entry_id} ({entry.title})")
    
    hass.services.async_remove(DOMAIN, SERVICE_ADD_POWERSHOUT_BOOKING)
    
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            hass.data[DOMAIN].pop(entry.entry_id)
            if not hass.data[DOMAIN]: 
                hass.data.pop(DOMAIN) 
        _LOGGER.info(f"Genesis Energy entry unloaded: {entry.title}")
    else:
        _LOGGER.error(f"Failed to unload platforms for Genesis Energy entry: {entry.title}")
        
    return unload_ok