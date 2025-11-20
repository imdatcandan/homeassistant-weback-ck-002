"""
Weback API class
"""
import asyncio
import configparser
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

import httpx

_LOGGER = logging.getLogger(__name__)

# API Answer
SUCCESS_OK = "success"
SERVICE_ERROR = "ServiceErrorException"
USER_NOT_EXIST = "UserNotExist"  # nosec B105
PASSWORD_NOK = "PasswordInvalid"  # nosec B105

# API
AUTH_URL = "https://user.grit-cloud.com/prod/oauth"
N_RETRY = 8
HTTP_TIMEOUT = 5

# ROOT DIR
CREDS_FILE = "wb_creds"
COMPONENT_DIR = os.path.dirname(os.path.abspath(__file__))


class WebackApi:
    """
    WeBack API
    Handle connection with OAuth server to get WSS credentials
    """

    def __init__(self, user, password, region, country="en", app="WeBack", client_id="yugong_app", api_version="1.0"):
        _LOGGER.debug("WebackApi __init__")

        # HTTP Oauth required param
        self.user = user
        self.password = password
        self.region = region
        self.app = app
        self.country = country
        self.client_id = client_id
        self.api_version = api_version

        # API auth & connection param
        self.jwt_token = None
        self.region_name = None
        self.wss_url = None
        self.api_url = None
        self.token_duration = 0
        self.token_exp = None

    async def login(self) -> bool:
        """
        Login to WebBack platform
        """
        # Checking if there is cached token and is still valid
        if self.verify_cached_creds():
            return True

        params = {
            "json": {
                "payload": {
                    "opt": "login",
                    "pwd": hashlib.md5(
                        self.password.encode()
                    ).hexdigest(),  # nosec B324
                },
                "header": {
                    "language": self.country,
                    "app_name": self.app,
                    "calling_code": "00" + self.region,
                    "api_version": self.api_version,
                    "account": self.user,
                    "client_id": self.client_id,
                },
            }
        }

        resp = await self.send_http(AUTH_URL, **params)

        if resp is None:
            _LOGGER.error(
                "WebackApi login failed, server sent an empty answer, "
                "please check repo's README.md about WeBack's discontinuation service"
            )
            return False

        result_msg = resp.get("msg")

        if result_msg == SUCCESS_OK:
            # Login OK
            self.jwt_token = resp["data"]["jwt_token"]
            self.region_name = resp["data"]["region_name"]
            self.wss_url = resp["data"]["wss_url"]
            self.api_url = resp["data"]["api_url"]
            self.token_duration = resp["data"]["expired_time"] - 60

            # Calculate token expiration
            now_date = datetime.today()
            self.token_exp = now_date + timedelta(seconds=self.token_duration)
            _LOGGER.debug("WebackApi login successful")

            self.save_token_file()
            return True
        if result_msg == SERVICE_ERROR:
            # Wrong APP
            _LOGGER.error(
                "WebackApi login failed, application is not recognized, "
                "please check repo's README.md about WeBack's discontinuation service"
            )
            return False
        if result_msg == USER_NOT_EXIST:
            # User NOK
            _LOGGER.error(
                "WebackApi login failed, user does not exist "
                "please check repo's README.md about WeBack's discontinuation service"
            )
            return False
        if result_msg == PASSWORD_NOK:
            # Password NOK
            _LOGGER.error("WebackApi login failed, wrong password")
            return False
        # Login NOK
        _LOGGER.error("WebackApi can't login (reason is: %s)", result_msg)
        return False

    def verify_cached_creds(self):
        """
        Check if cached creds are not outdated
        """
        creds_data = self.get_token_file()
        if "weback_token" in creds_data:
            weback_token = creds_data["weback_token"]
            if self.check_token_is_valid(
                weback_token.get("token_exp")
            ) and self.user == weback_token.get("user"):
                # Valid creds to use, loading it
                self.jwt_token = weback_token.get("jwt_token")
                self.region_name = weback_token.get("region_name")
                self.wss_url = weback_token.get("wss_url")
                self.api_url = weback_token.get("api_url")
                self.token_exp = weback_token.get("token_exp")
                _LOGGER.debug("WebackApi use cached creds.")
                return True
        _LOGGER.debug("WebackApi has no or invalid cached creds, renew it...")
        return False

    @staticmethod
    def get_token_file() -> dict:
        """
        Open token file and get all data.
        """
        creds_data = {}
        try:
            config = configparser.ConfigParser()
            config.read(os.path.join(COMPONENT_DIR, CREDS_FILE))
            creds_data = config._sections
        except Exception as get_err:
            _LOGGER.debug(
                "WebackApi not found or invalid weback creds file error=%s", get_err
            )
        return creds_data

    def save_token_file(self):
        """
        Save token file with all information
        """
        try:
            config = configparser.ConfigParser()
            config.add_section("weback_token")
            config.set("weback_token", "user", str(self.user))
            config.set("weback_token", "jwt_token", str(self.jwt_token))
            config.set("weback_token", "token_exp", str(self.token_exp))
            config.set("weback_token", "api_url", str(self.api_url))
            config.set("weback_token", "wss_url", str(self.wss_url))
            config.set("weback_token", "region_name", str(self.region_name))
            with open(
                os.path.join(COMPONENT_DIR, CREDS_FILE), "w", encoding="utf-8"
            ) as configfile:
                config.write(configfile)
            _LOGGER.debug("WebackApi saved new creds")
        except Exception as excpt_msg:
            _LOGGER.debug("WebackApi failed to saved new creds details=%s", excpt_msg)

    @staticmethod
    def check_token_is_valid(token) -> bool:
        """
        Check if token validity is still OK or not
        """
        _LOGGER.debug("WebackApi checking token validity : %s", token)
        try:
            now_date = datetime.today() - timedelta(minutes=15)
            dt_token = datetime.strptime(str(token), "%Y-%m-%d %H:%M:%S.%f")
            if now_date < dt_token:
                _LOGGER.debug("WebackApi token is valid")
                return True
        except Exception as excpt_token:
            _LOGGER.debug("WebackApi failed to check token : %s", excpt_token)
        _LOGGER.debug("WebackApi token not valid")
        return False

    async def get_things_list(self):
        """
        Get robot things list registered from Weback server
        """
        resp = await self.make_api_call('user_thing_list_get')
        return resp["thing_list"]

    async def user_thing_info_get(self, sub_type, thing_name):
        """
        Get info about a thing.

        Example:
        thing = await api.get_things_list()[0]
        api.user_thing_info_get(thing['sub_type'], thing['thing_name'])
        """
        return await self.make_api_call('user_thing_info_get', sub_type=sub_type, thing_name=thing_name)

    async def set_thing_status(self, sub_type, thing_name, parameters):
        """
        Set status of the thing
        """
        return await self.make_api_call(
            'thing_control',
            sub_type=sub_type,
            thing_name=thing_name,
            parameters=parameters
        )

    async def make_api_call(self, opt, **fields):
        # re-login if the token is expired.
        await self.login()
        fields["opt"] = opt
        params = {
            "json": fields,
            "headers": {"Token": self.jwt_token, "Region": self.region_name},
        }
        resp = await self.send_http(self.api_url, **params)
        if resp["msg"] == SUCCESS_OK:
            return resp["data"]

        # Note: At the time of writing, the API still returns success for invalid
        # inputs.
        raise Exception('Failed to ' + opt, resp)

    @staticmethod
    async def send_http(url, **params):
        """
        Send HTTP request
        """
        _LOGGER.debug("Send HTTP request Url=%s Params=%s", url, params)
        timeout = httpx.Timeout(HTTP_TIMEOUT, connect=15.0)
        for attempt in range(N_RETRY):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    req = await client.post(url, **params)
                    if req.status_code == 200:
                        # Server status OK
                        _LOGGER.debug("WebackApi : Send HTTP OK, return=200")
                        _LOGGER.debug("WebackApi : HTTP data received = %s", req.json())
                        return req.json()
                    # Server status NOK
                    _LOGGER.warning(
                        "WebackApi : Bad server response (status code=%s) retry... (%s/%s)",
                        req.status_code,
                        attempt,
                        N_RETRY,
                    )
            except httpx.RequestError as http_excpt:
                _LOGGER.debug(
                    "Send HTTP exception details=%s retry... (%s/%s)",
                    http_excpt,
                    attempt,
                    N_RETRY,
                )
        _LOGGER.error(
            "WebackApi : HTTP error after %s retry please check repo's "
            "README.md about WeBack's discontinuation service",
            N_RETRY,
        )
        return {"msg": "error", "details": f"Failed after {N_RETRY} retry"}
