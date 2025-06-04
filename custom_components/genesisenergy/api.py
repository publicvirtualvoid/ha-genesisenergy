# custom_components/genesisenergy/api.py

import aiohttp
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping 
import json
from urllib.parse import parse_qs

# Import custom exceptions
from .exceptions import CannotConnect, InvalidAuth

_LOGGER = logging.getLogger(__name__)

class GenesisEnergyApi:
    """API to interact with Genesis Energy services, with robust token management."""

    TOKEN_VALIDITY_BUFFER_MINUTES = 5 

    def __init__(self, email, password):
        self._client_id = "8e41676f-7601-4490-9786-85d74f387f47"
        self._redirect_uri = 'https://myaccount.genesisenergy.co.nz/auth/redirect'
        self._url_token_base = "https://auth.genesisenergy.co.nz/auth.genesisenergy.co.nz"
        self._url_data_base = "https://web-api.genesisenergy.co.nz/"
        self._p = "B2C_1A_signin"
        self._email = email
        self._password = password

        self._token = None
        self._refresh_token = None
        self._access_token_absolute_expiry_ts = 0.0
        self._refresh_token_absolute_expiry_ts = 0.0
        self._access_token_original_expires_in = 0
        self._refresh_token_original_expires_in = 0

    def get_setting_json(self, page: str) -> Mapping[str, Any] | None:
        for line in page.splitlines():
            if line.startswith("var SETTINGS = ") and line.endswith(";"):
                json_string = line.removeprefix("var SETTINGS = ").removesuffix(";")
                try: return json.loads(json_string)
                except json.JSONDecodeError as e: _LOGGER.error(f"JSONDecodeError: {e} in SETTINGS: {json_string}"); return None
        _LOGGER.warning("SETTINGS variable not found."); return None

    async def get_refresh_token(self): # Full 6-step login
        _LOGGER.info("Attempting full login to get new tokens (get_refresh_token)...")
        async with aiohttp.ClientSession() as session:
            try:
                # Step 1
                url_s1 = f"{self._url_token_base}/oauth2/v2.0/authorize"
                p_s1 = {'p': self._p, 'client_id': self._client_id, 'response_type': 'code', 'response_mode': 'query', 'scope': f'openid offline_access {self._client_id}', 'redirect_uri': self._redirect_uri}
                _LOGGER.debug(f"S1: GET {url_s1} P:{p_s1}")
                async with session.get(url_s1, params=p_s1) as r_s1:
                    txt_s1 = await r_s1.text(); _LOGGER.debug(f"S1 Status: {r_s1.status}")
                    r_s1.raise_for_status()
                sjson = self.get_setting_json(txt_s1)
                if not sjson: _LOGGER.error("S1: Failed to extract settings_json."); raise CannotConnect("Login S1 failed: no settings JSON")
                tid, csrf = sjson.get("transId"), sjson.get("csrf")
                if not tid or not csrf: _LOGGER.error(f"S1: Missing tid/csrf. tid:{tid} csrf:{bool(csrf)}"); raise CannotConnect(f"Login S1 failed: missing tid/csrf")

                # Step 2
                url_s2 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
                pay_s2 = {"request_type": "RESPONSE", "email": self._email}; hdr_s2 = {'X-CSRF-TOKEN': csrf}
                _LOGGER.debug(f"S2: POST {url_s2}")
                async with session.post(url_s2, headers=hdr_s2, data=pay_s2) as r_s2: 
                    _LOGGER.debug(f"S2 Status: {r_s2.status}")
                    r_s2.raise_for_status()

                # Step 3
                url_s3 = f"{self._url_token_base}/{self._p}/api/SelfAsserted/confirmed"
                p_s3 = {'csrf_token': csrf, 'tx': tid, 'p': self._p}
                _LOGGER.debug(f"S3: GET {url_s3}")
                async with session.get(url_s3, params=p_s3) as r_s3:
                    _LOGGER.debug(f"S3 Status: {r_s3.status}")
                    r_s3.raise_for_status()
                    if 'x-ms-cpim-csrf' in r_s3.cookies: csrf = r_s3.cookies['x-ms-cpim-csrf'].value; _LOGGER.debug(f"S3: Updated CSRF: {csrf[:20]}...")
                    else: _LOGGER.error("S3: CSRF cookie missing."); raise CannotConnect("Login S3 failed: CSRF cookie missing")
                
                # Step 4
                url_s4 = f"{self._url_token_base}/{self._p}/SelfAsserted?tx={tid}&p={self._p}"
                pay_s4 = {"request_type": "RESPONSE", "signInName": self._email, "password": self._password}; hdr_s4 = {'X-CSRF-TOKEN': csrf}
                _LOGGER.debug(f"S4: POST {url_s4}")
                async with session.post(url_s4, headers=hdr_s4, data=pay_s4) as r_s4: 
                    _LOGGER.debug(f"S4 Status: {r_s4.status}")
                    if r_s4.status != 200:
                        s4_text = await r_s4.text()
                        _LOGGER.error(f"S4: Password submission failed. Status: {r_s4.status}. Response: {s4_text[:500]}")
                        if "The username or password provided in the request are invalid" in s4_text:
                            _LOGGER.error("S4 indicates invalid username or password.")
                            raise InvalidAuth("Invalid username or password.")
                        r_s4.raise_for_status() # Raise for other non-200s
                    
                # Step 5
                url_s5 = f"{self._url_token_base}/{self._p}/api/CombinedSigninAndSignup/confirmed"
                p_s5 = {'rememberMe': 'false', 'csrf_token': csrf, 'tx': tid, 'p': self._p}
                _LOGGER.debug(f"S5: GET {url_s5} (no redirects)")
                async with session.get(url_s5, params=p_s5, allow_redirects=False) as r_s5:
                    _LOGGER.debug(f"S5 Status: {r_s5.status}") 
                    if r_s5.status != 302: _LOGGER.error(f"S5: Expected 302, got {r_s5.status}. Text: {await r_s5.text()}"); raise CannotConnect(f"Login S5 failed: status {r_s5.status}")
                    loc = r_s5.headers.get('Location', '')
                if not loc: _LOGGER.error("S5: No Location header."); raise CannotConnect("Login S5 failed: no location header")
                _LOGGER.debug(f"S5 Location: {loc[:100]}...")
                qpr = parse_qs(loc.split('?', 1)[1])
                if 'error' in qpr: _LOGGER.error(f"S5 Error: {qpr['error'][0]} - {qpr.get('error_description',[''])[0]}"); raise InvalidAuth(f"Login S5 error: {qpr['error'][0]}")
                if 'code' not in qpr: _LOGGER.error("S5: 'code' not in redirect."); raise CannotConnect("Login S5 failed: no auth code")
                code = qpr['code'][0]; _LOGGER.debug(f"S5 Auth Code: {code[:20]}...")

                # Step 6
                url_s6 = f"{self._url_token_base}/{self._p}/oauth2/v2.0/token"
                p_s6 = {'p': self._p, 'grant_type': 'authorization_code', 'client_id': self._client_id, 'scope': f'openid offline_access {self._client_id}', 'redirect_uri': self._redirect_uri, 'code': code}
                _LOGGER.debug(f"S6: GET {url_s6}")
                async with session.get(url_s6, params=p_s6) as r_s6:
                    _LOGGER.debug(f"S6 Status: {r_s6.status}")
                    if r_s6.status == 200:
                        data_s6 = await r_s6.json(); _LOGGER.debug(f"S6 JSON: {data_s6}")
                        self._token = data_s6.get('access_token')
                        self._refresh_token = data_s6.get('refresh_token')
                        
                        self._access_token_original_expires_in = int(data_s6.get('expires_in', 0))
                        self._refresh_token_original_expires_in = int(data_s6.get('refresh_token_expires_in', 0))

                        now_ts = datetime.now(timezone.utc).timestamp()
                        self._access_token_absolute_expiry_ts = (now_ts + self._access_token_original_expires_in) if self._access_token_original_expires_in > 0 else 0
                        self._refresh_token_absolute_expiry_ts = (now_ts + self._refresh_token_original_expires_in) if self._refresh_token_original_expires_in > 0 else 0
                        
                        if not self._token: _LOGGER.error("S6: access_token missing in response."); raise InvalidAuth("Login S6 failed: no access token")
                        _LOGGER.info(f"Full login successful. Access Token will expire around: {datetime.fromtimestamp(self._access_token_absolute_expiry_ts, timezone.utc).isoformat() if self._access_token_absolute_expiry_ts > 0 else 'N/A'}")
                        return True
                    else: _LOGGER.error(f"S6: Failed. Status {r_s6.status} Text: {await r_s6.text()}"); raise CannotConnect(f"Login S6 failed: status {r_s6.status}")
            except aiohttp.ClientError as e:
                _LOGGER.error(f"ClientError during full login: {e}", exc_info=True)
                raise CannotConnect(f"HTTP ClientError during login: {e}") from e
            except Exception as e: # Catch any other unexpected error from the above logic
                _LOGGER.error(f"Unexpected error during full login: {e}", exc_info=True)
                raise CannotConnect(f"Unexpected error in login process: {e}") from e
        
        _LOGGER.error("Exited client session unexpectedly in get_refresh_token (full login). Should not happen.")
        return False # Should be unreachable if try/except is comprehensive


    async def get_api_token(self): # Refresh grant using a refresh_token
        _LOGGER.info("Attempting to refresh access token using refresh_token (get_api_token)...")
        if not self._refresh_token:
            _LOGGER.error("No refresh token available to refresh access token.")
            return False

        payload = {
            "grant_type": "refresh_token", "client_id": self._client_id,
            "scope": f"openid offline_access {self._client_id}",
            "redirect_uri": self._redirect_uri, "refresh_token": self._refresh_token,
        }
        url = f"{self._url_token_base}/oauth2/v2.0/token?p={self._p}"
        log_payload = {k: (v if k != 'refresh_token' else '******') for k, v in payload.items()}
        _LOGGER.debug(f"Refreshing AT: POST {url} with data {log_payload}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=payload) as response:
                    _LOGGER.debug(f"Refresh AT Response Status: {response.status}")
                    response_json = await response.json() # Attempt to get JSON first for logging
                    _LOGGER.debug(f"Refresh AT Response JSON: {json.dumps(response_json, indent=2)}")

                    if response.status == 200:
                        self._token = response_json.get("access_token")
                        new_access_token_expires_in = response_json.get("expires_in")
                        
                        if self._token and new_access_token_expires_in is not None:
                            self._access_token_original_expires_in = int(new_access_token_expires_in)
                            now_ts = datetime.now(timezone.utc).timestamp()
                            self._access_token_absolute_expiry_ts = now_ts + self._access_token_original_expires_in
                            _LOGGER.info(f"AT refreshed successfully. New AT expires around: {datetime.fromtimestamp(self._access_token_absolute_expiry_ts, timezone.utc).isoformat()}")

                            new_refresh_token = response_json.get("refresh_token")
                            if new_refresh_token and new_refresh_token != self._refresh_token:
                                _LOGGER.info("Refresh token was rotated. Storing new refresh token.")
                                self._refresh_token = new_refresh_token
                                new_rt_expires_in = response_json.get("refresh_token_expires_in")
                                if new_rt_expires_in is not None:
                                    self._refresh_token_original_expires_in = int(new_rt_expires_in)
                                    self._refresh_token_absolute_expiry_ts = now_ts + self._refresh_token_original_expires_in
                                    _LOGGER.info(f"New RT expires around: {datetime.fromtimestamp(self._refresh_token_absolute_expiry_ts, timezone.utc).isoformat() if self._refresh_token_absolute_expiry_ts > 0 else 'N/A'}")
                            elif not new_refresh_token:
                                _LOGGER.debug("No new refresh token in response. Old refresh token continues to be used.")
                            return True
                        else:
                            _LOGGER.error("Access token or 'expires_in' missing in successful refresh response.")
                            self._token = None; self._access_token_absolute_expiry_ts = 0
                            return False
                    else:
                        _LOGGER.error(f"Failed to refresh access token. Status: {response.status}")
                        self._token = None; self._access_token_absolute_expiry_ts = 0
                        return False
        except aiohttp.ClientError as e:
            _LOGGER.error(f"HTTP ClientError during token refresh: {e}", exc_info=True)
            return False
        except json.JSONDecodeError as e:
            # This case should be rare if await response.json() is used carefully above.
            # The `await response.text()` would be needed here if we didn't get JSON first.
            _LOGGER.error(f"Failed to decode JSON from token refresh response: {e}", exc_info=True)
            return False
        return False


    async def _ensure_valid_token(self):
        _LOGGER.debug(
            f"_ensure_valid_token: Current AT absolute expiry TS: {self._access_token_absolute_expiry_ts} "
            f"(around {datetime.fromtimestamp(self._access_token_absolute_expiry_ts, timezone.utc).isoformat() if self._access_token_absolute_expiry_ts > 0 else 'N/A'})"
        )
        _LOGGER.debug(
             f"_ensure_valid_token: Current RT absolute expiry TS: {self._refresh_token_absolute_expiry_ts} "
            f"(around {datetime.fromtimestamp(self._refresh_token_absolute_expiry_ts, timezone.utc).isoformat() if self._refresh_token_absolute_expiry_ts > 0 else 'N/A'})"
        )
        current_time_utc_ts = datetime.now(timezone.utc).timestamp()
        buffer_seconds = self.TOKEN_VALIDITY_BUFFER_MINUTES * 60

        if self._token and self._access_token_absolute_expiry_ts > (current_time_utc_ts + buffer_seconds):
            _LOGGER.debug("_ensure_valid_token: Existing access token is still valid and usable.")
            return True

        _LOGGER.info("_ensure_valid_token: Access token missing, expired, or nearing expiry.")
        
        # Check refresh token validity. Use a larger buffer for RT to encourage full re-login if RT is old.
        # For example, if RT expires in 90 days, try to do a full re-login if it's within last 7 days of its life.
        refresh_token_buffer_seconds = buffer_seconds * 24 * 7 # 7 days buffer for RT
        if self._refresh_token and \
           (self._refresh_token_absolute_expiry_ts == 0 or # If expiry was never set, assume it's good to try once
            self._refresh_token_absolute_expiry_ts > (current_time_utc_ts + refresh_token_buffer_seconds)):
            
            _LOGGER.info("_ensure_valid_token: Refresh token seems valid, trying get_api_token (refresh grant).")
            if await self.get_api_token():
                if self._token and self._access_token_absolute_expiry_ts > (datetime.now(timezone.utc).timestamp() + buffer_seconds):
                    _LOGGER.info("_ensure_valid_token: Access token refresh via get_api_token successful.")
                    return True
                else:
                    _LOGGER.error("_ensure_valid_token: get_api_token seemed to succeed but new access token is immediately invalid or not set.")
            else:
                _LOGGER.warning("_ensure_valid_token: get_api_token (refresh grant) failed. Will attempt full re-login.")
        else:
            _LOGGER.info("_ensure_valid_token: Refresh token is missing or (near)expired. Will attempt full re-login directly.")

        _LOGGER.info("_ensure_valid_token: Proceeding to full re-login (get_refresh_token).")
        if await self.get_refresh_token(): 
            if self._token and self._access_token_absolute_expiry_ts > (datetime.now(timezone.utc).timestamp() + buffer_seconds):
                _LOGGER.info("_ensure_valid_token: Full re-login successful, new token obtained and valid.")
                return True
            else:
                _LOGGER.error("_ensure_valid_token: Full re-login completed, but new token is immediately invalid or missing.")
                self._token = None; self._access_token_absolute_expiry_ts = 0
                raise InvalidAuth("Token invalid after full re-login.") # Raise to be caught by coordinator
        else:
            _LOGGER.error("_ensure_valid_token: Full re-login failed.")
            self._token = None; self._access_token_absolute_expiry_ts = 0
            raise CannotConnect("Full re-login process failed.") # Raise to be caught by coordinator
        
        return False # Should be unreachable if exceptions are raised

    async def _make_api_call(self, method: str, endpoint: str, params: dict = None, json_payload: dict = None, description: str = "data"):
        _LOGGER.debug(f"Preparing to fetch {description}...")
        if not await self._ensure_valid_token():
            # _ensure_valid_token now raises exceptions, so this path might not be hit if it raises.
            # However, if it somehow returns False without raising, we'd hit this.
            _LOGGER.error(f"Token validation failed prior to fetching {description}. Aborting call.")
            raise CannotConnect(f"Token validation failed prior to fetching {description}") # Should be caught by coordinator

        headers = {"authorization": "Bearer " + self._token, "brand-id": "GENE"}
        url = f"{self._url_data_base}{endpoint}"
        
        log_params = f"Params: {params}" if params else f"JSON Payload: {json_payload}" if json_payload else "No body/params"
        _LOGGER.debug(f"Fetching {description}: {method.upper()} {url} with {log_params}")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=headers, params=params, json=json_payload) as response:
                    _LOGGER.debug(f"{description} API Response Status: {response.status}")
                    if response.status == 200:
                        data = await response.json()
                        _LOGGER.debug(f"{description} fetched successfully from API.")
                        return data
                    elif response.status == 401:
                        _LOGGER.error(f"Received 401 Unauthorized for {description}. Invalidating current token.")
                        self._token = None 
                        self._access_token_absolute_expiry_ts = 0 
                        raise InvalidAuth(f"Unauthorized access for {description}")
                    else:
                        message = await response.text()
                        _LOGGER.error(f"Could not fetch {description}. Status: {response.status}, Error: {message}")
                        raise CannotConnect(f"API error for {description}: {response.status} - {message}")
        except aiohttp.ClientError as e:
            _LOGGER.error(f"HTTP ClientError while fetching {description}: {e}", exc_info=True)
            raise CannotConnect(f"HTTP client error for {description}: {e}") from e
        except json.JSONDecodeError as e:
            # This error means the response wasn't valid JSON, even if status was 200 (unlikely but possible)
            _LOGGER.error(f"Failed to decode JSON from {description} response: {e}. Response text was logged if status != 200.", exc_info=True)
            raise CannotConnect(f"Invalid JSON from {description}: {e}") from e
        except Exception as e: # Catch-all for other unexpected errors during the API call itself
            _LOGGER.error(f"Unexpected error while fetching {description}: {e}", exc_info=True)
            raise CannotConnect(f"Unexpected API call error for {description}: {e}") from e


    async def get_energy_data(self):
        from_date = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        payload = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("POST", "/v2/private/electricity/site-usage", json_payload=payload, description="electricity usage")

    async def get_gas_data(self):
        from_date = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        params = {'startDate': from_date, 'endDate': to_date, 'intervalType': "HOURLY"}
        return await self._make_api_call("GET", "/v2/private/naturalgas/advanced/usage", params=params, description="gas usage")

    async def get_powershout_info(self):
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency", description="Power Shout base info")

    async def get_powershout_balance(self):
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/balance", description="Power Shout balance")

    async def get_powershout_bookings(self):
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/bookings", description="Power Shout bookings")

    async def get_powershout_offers(self):
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/offers", description="Power Shout offers")

    async def get_powershout_expiring_hours(self):
        return await self._make_api_call("GET", "/v2/private/powershoutcurrency/expiringHours", description="Power Shout expiring hours")