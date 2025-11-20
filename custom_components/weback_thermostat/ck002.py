from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    UnitOfTemperature,
    ATTR_TEMPERATURE,
)


class Ck002Thermostat(ClimateEntity):
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
    _attr_preset_modes = ['Manual', 'Automatic']
    _attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.PRESET_MODE |
            ClimateEntityFeature.TURN_OFF |
            ClimateEntityFeature.TURN_ON
    )
    _attr_has_entity_name = True

    def __init__(self, api, data):
        self.api = api
        self.status = data['thing_status']
        self.subtype = data['sub_type']
        self.thing_name = data['thing_name']
        self._attr_name = data['thing_nickname']

    @property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode."""
        if self.status.get('working_status') != 'on':
            return HVACMode.OFF
        if self.status.get('mode') == 'auto':
            return HVACMode.AUTO
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        return HVACAction.HEATING if self.status['working_status'] == 'on' else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return self.status['air_tem'] / 10

    @property
    def target_temperature(self) -> float | None:
        return self.status['set_tem'] / 2

    @property
    def temperature_unit(self) -> str:
        return UnitOfTemperature.CELSIUS

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        if self.status.get('mode') == 'auto':
            return 'Automatic'
        return 'Manual'

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == HVACMode.OFF:
            await self.api.device_control(self.subtype, self.thing_name, {"working_status": "off"})
        else:
            payload = {"working_status": "on"}
            if hvac_mode == HVACMode.AUTO:
                payload["mode"] = "auto"
            elif hvac_mode == HVACMode.HEAT:
                payload["mode"] = "manual"
            await self.api.device_control(self.subtype, self.thing_name, payload)

        await self.async_update_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        mode = 'auto' if preset_mode == 'Automatic' else 'manual'
        await self.api.device_control(self.subtype, self.thing_name, {"mode": mode})
        await self.async_update_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return

        # Device uses 2x scaling for temperature based on read logic
        val = int(temperature * 2)
        await self.api.device_control(self.subtype, self.thing_name, {"set_tem": val})
        await self.async_update_ha_state()

    async def async_update(self):
        self.status = await self.api.user_thing_info_get(self.sub_type, self.thing_name)