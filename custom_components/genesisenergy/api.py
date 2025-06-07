"""Genesis Energy API Client (Adapted from v0.0.2 with improved token logic)."""

import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import json
from urllib.parse import parse_qs

from .exceptions import CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

class GenesisEnergyApi:
    """API to interact with Genesis Energy services."""

    TOKEN_VALIDITY_BUFFER_MINUTES = 5

    def __init__(self, email: str, password: str, session: aiohttp.ClientSession | None = None) -> None:
        """Initialise the API."""
        self._client_id = "8e41676f-7601-4490-9786-85d74f387f47"
        self._redirect_uri = 'https://myaccount.genesisenergy.co.nz/auth/redirect'
        self._url_token_base = "https://auth.genesisenergy.co.nz/auth.genesisenergy.co.nz"
        self._url_data_base = "https://web-api.genesisenergy.co.nz/"
        self._p = "B2C_1A_signin"

        self._email = email
        self._password = password

        self._token: str | None = None
        self._refresh_token: str | None = None 
        self._access_token_absolute_expiry_ts: float = 0.0
        self._refresh_token_absolute_expiry_ts: float = 0.0

        self._shared_session = session is not None
        self._session = session

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._shared_session = False 
        return self._session
    
    async def close(self) -> None:
        """Close the session if we own it."""
        if self._session and not self._shared_session and not self._session.closed:
            await self._session.close()
            _LOGGER.debug("Owned API session closed.")
        self._session = None

    def _get_setting_json(self, page: str) -> Mapping[str, Any] | None:
        for line in page.splitlines():
            if line.startswith("var SETTINGS = ") and line.endswith(";"):
                json_string = line.removeprefix("var SETTINGS = ").removesuffix(";")
                try:
                    return json.loads(json_string)
                except json.JSONDecodeError as e:
                    _LOGGER.error(f"Failed to decode SETTINGS JSON: {e}")
                    return None
        _LOGGER.warning("SETTINGS variable not found in page content.")
        return None

    async def _perform_full_login(self) -> bool:
        _LOGGER.info("Attempting full login to get new tokens...")
        session = await self._get_session()
        try:
            # Step 1
            url_s1 = f"{self._url_token_base}/oauth2/v2.0/authorize"; p_s1 = {'p': self._p, 'client_id': self._client_id, 'response_type': 'code', 'response_mode': 'query', 'scope': f'openid offline_access {self._client_id}', 'redirect_uri': self._redirect_uri}
            async with session.get(url_s1, params=p_s1) as r_s1:
                txt_s1 = await r_s1.text(); r_s1.raise_for_status()
            sjson = self._get_setting_json(txt_s1)
            if not sjson: raise CannotConnect("Login S1: no settings_json")
            tid, csrf = sjson.get("transId"), sjson.get("csrf")
            if not tid or not csrf: raise CannotConnect("Login S1: no tid/csrf")
            # Step 2
            url_s2 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"; pay_s2 = {"request_type": "RESPONSE", "email": self._email}; hdr_s2 = {'X-CSRF-TOKEN': csrf}
            async with session.post(url_s2, headers=hdr_s2, data=pay_s2) as r_s2: r_s2.raise_for_status()
            # Step 3
            url_s3 = f"{self._url_token_base}/{self._p}/api/SelfAsserted/confirmed"; p_s3 = {'csrf_token': csrf, 'tx': tid, 'p': self._p}
            async with session.get(url_s3, params=p_s3) as r_s3:
                r_s3.raise_for_status()
                if 'x-ms-cpim-csrf' in r_s3.cookies: csrf = r_s3.cookies['x-ms-cpim-csrf'].value
                else: raise CannotConnect("Login S3: CSRF cookie missing")
            # Step 4
            url_s4 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"; pay_s4 = {"request_type": "RESPONSE", "signInName": self._email, "password": self._password}; hdr_s4 = {'X-CSRF-TOKEN': csrf}
            async with session.post(url_s4, headers=hdr_s4, data=pay_s4) as r_s4:
                if r_s4.status != 200:
                    s4_text = await r_s4.text()
                    if "The username or password provided in the request are invalid" in s4_text:
                        raise InvalidAuth("Invalid username or password.")
                    r_s4.raise_for_status()
            # Step 5
            url_s5 = f"{self._url_token_base}/{self._p}/api/CombinedSigninAndSignup/confirmed"; p_s5 = {'rememberMe': 'false', 'csrf_token': csrf, 'tx': tid, 'p': self._p}
            async with session.get(url_s5, params=p_s5, allow_redirects=False) as r_s5:
                if r_s5.status != 302: raise CannotConnect(f"Login S5: status {r_s5.status}")
                loc = r_s5.headers.get('Location', '')
            if not loc: raise CannotConnect("Login S5: no location header")
            qpr = parse_qs(loc.split('?', 1)[1])
            if 'error' in qpr: raise InvalidAuth(f"Login S5 error: {qpr['error'][0]}")
            if 'code' not in qpr: raise CannotConnect("Login S5: no auth code")
            code = qpr['code'][0]
            # Step 6
            url_s6 = f"{self._url_token_base}/{self._p}/oauth2/v2.0/token"; p_s6 = {'p': self._p, 'grant_type': 'authorization_code', 'client_id': self._client_id, 'scope': f'openid offline_access {self._client_id}', 'redirect_uri': self._redirect_uri, 'code': code}
            async with session.get(url_s6, params=p_s6) as r_s6:
                if r_s6.status == 200:
                    data_s6 = await r_s6.json()
                    self._token = data_s6.get('access_token')
                    self._refresh_token = data_s6.get('refresh_token') 
                    expires_in = data_s6.get('expires_in', 0)
                    rt_expires_in = data_s6.get('refresh_token_expires_in', 0) 
                    now_ts = datetime.now(timezone.utc).timestamp()
                    self._access_token_absolute_expiry_ts = (now_ts + int(expires_in)) if expires_in else 0
                    self._refresh_token_absolute_expiry_ts = (now_ts + int(rt_expires_in)) if rt_expires_in else 0
                    if not self._token: raise InvalidAuth("Login S6: no access token")
                    _LOGGER.info("Full login successful.")
                    return True
                else:
                    raise CannotConnect(f"Login S6: status {r_s6.status}, Text: {await r_s6.text()}")
        except aiohttp.ClientError as e:
            _LOGGER.error(f"ClientError during login: {e}", exc_info=True)
            raise CannotConnect(f"HTTP ClientError during login: {e}") from e
        except (InvalidAuth, CannotConnect): raise
        except Exception as e:
            _LOGGER.error(f"Unexpected error during login: {e}", exc_info=True)
            raise CannotConnect(f"Unexpected error in login: {e}") from e
        return False

    async def _refresh_access_token(self) -> bool:
        _LOGGER.info("Attempting to refresh access token...")
        if not self._refresh_token:
            _LOGGER.warning("No refresh token available to refresh access token.")
            return False

        session = await self._get_session()
        payload = {
            "grant_type": "refresh_token", "client_id": self._client_id,
            "scope": f"openid offline_access {self._client_id}",
            "redirect_uri": self._redirect_uri, "refresh_token": self._refresh_token,
        }
        url = f"{self._url_token_base}/oauth2/v2.0/token?p={self._p}"
        try:
            async with session.post(url, data=payload) as response:
                _LOGGER.debug(f"Refresh Token API Response Status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    self._token = data.get("access_token")
                    new_expires_in = data.get("expires_in")
                    if self._token and new_expires_in is not None:
                        now_ts = datetime.now(timezone.utc).timestamp()
                        self._access_token_absolute_expiry_ts = now_ts + int(new_expires_in)
                        _LOGGER.info("Access token refreshed successfully.")
                        new_rt = data.get("refresh_token")
                        if new_rt and new_rt != self._refresh_token:
                            self._refresh_token = new_rt
                            new_rt_expires_in = data.get("refresh_token_expires_in")
                            if new_rt_expires_in is not None:
                                self._refresh_token_absolute_expiry_ts = now_ts + int(new_rt_expires_in)
                            _LOGGER.info("Refresh token was rotated.")
                        return True
                    _LOGGER.error("Access token or expires_in missing in refresh response.")
                    return False
                else:
                    _LOGGER.error(f"Failed to refresh access token (Status: {response.status}). Text: {await response.text()}")
                    if response.status in [400, 401]: 
                        self._refresh_token = None 
                        self._refresh_token_absolute_expiry_ts = 0
                    return False
        except (aiohttp.ClientError, json.JSONDecodeError) as e:
            _LOGGER.error(f"Error during token refresh: {e}", exc_info=True)
            return False
        return False

    async def _ensure_valid_token(self) -> None:
        current_time_utc_ts = datetime.now(timezone.utc).timestamp()
        buffer = self.TOKEN_VALIDITY_BUFFER_MINUTES * 60

        if self._token and self._access_token_absolute_expiry_ts > (current_time_utc_ts + buffer):
            return 

        _LOGGER.info("Access token expired or needs refresh/login.")
        if self._refresh_token and \
           (self._refresh_token_absolute_expiry_ts == 0 or \
            self._refresh_token_absolute_expiry_ts > current_time_utc_ts):
            if await self._refresh_access_token():
                if self._token and self._access_token_absolute_expiry_ts > (current_time_utc_ts + buffer):
                    return 
                _LOGGER.warning("Token refresh attempt made, but new AT is not valid.")
            else:
                _LOGGER.warning("Token refresh failed. Attempting full login.")
        
        if not await self._perform_full_login(): # Should raise on failure
             raise CannotConnect("Full login failed unexpectedly (should have raised).")
        
        if not (self._token and self._access_token_absolute_expiry_ts > (current_time_utc_ts + buffer)):
            raise InvalidAuth("Token invalid immediately after full re-login.")

    async def _make_api_call(self, method: str, endpoint: str, params: dict | None = None, json_payload: dict | None = None, description: str = "data") -> Any:
        await self._ensure_valid_token()
        session = await self._get_session()
        headers = {"authorization": "Bearer " + str(self._token), "brand-id": "GENE"}
        url = f"{self._url_data_base}{endpoint}"
        _LOGGER.debug(f"API Call: {method} {url} (Params: {params}, JSON: {json_payload})")
        try:
            async with session.request(method, url, headers=headers, params=params, json=json_payload) as response:
                _LOGGER.debug(f"API Response Status for {description}: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    return data
                elif response.status == 401:
                    self._token = None; self._access_token_absolute_expiry_ts = 0 
                    raise InvalidAuth(f"Unauthorized (401) for {description}")
                else:
                    raise CannotConnect(f"API error for {description}: {response.status} - {await response.text()}")
        except aiohttp.ClientError as e:
            raise CannotConnect(f"HTTP client error for {description}: {e}") from e
        except json.JSONDecodeError as e:
            raise CannotConnect(f"Invalid JSON from {description}: {e}") from e

    async def get_energy_data(self) -> Any:
        from_date = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        payload = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("POST", "/v2/private/electricity/site-usage", json_payload=payload, description="electricity usage")

    async def get_gas_data(self) -> Any:
        from_date = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        params = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description="gas usage")

    # --- Power Shout API Methods ---
    async def get_powershout_info(self) -> Any:
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency", description="Power Shout info")

    async def get_powershout_balance(self) -> Any:
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/balance", description="Power Shout balance")

    async def get_powershout_bookings(self) -> Any:
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/bookings", description="Power Shout bookings")

    async def get_powershout_offers(self) -> Any:
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/offers", description="Power Shout offers")

    async def get_powershout_expiring_hours(self) -> Any:
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/expiringHours", description="Power Shout expiring hours")