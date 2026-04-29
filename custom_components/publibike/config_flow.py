"""Config flow for PubliBike."""

from __future__ import annotations

from typing import Any
import re

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    ATTR_GEOCODE_SOURCE,
    CONF_ADDRESS,
    CONF_CITY,
    CONF_LATITUDE,
    CONF_LOCATION_NAME,
    CONF_LONGITUDE,
    CONF_MIN_EBIKE_BATTERY,
    CONF_REFERENCE_TYPE,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_UPDATE_INTERVAL,
    DEFAULT_CITY,
    DEFAULT_MIN_EBIKE_BATTERY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
    REFERENCE_TYPE_ADDRESS,
    REFERENCE_TYPE_STATION,
)
from .coordinator import fetch_station_catalog, geocode_address


REFERENCE_OPTIONS = {
    REFERENCE_TYPE_STATION: "Station auswählen",
    REFERENCE_TYPE_ADDRESS: "Adresse / Koordinaten eingeben",
}


def _default_city(cities: list[str], preferred: str | None = None) -> str | None:
    """Return a sensible default city."""
    if preferred and preferred in cities:
        return preferred
    for candidate in (DEFAULT_CITY, "Zurich", "Bern", "Basel"):
        if candidate in cities:
            return candidate
    return cities[0] if cities else None


def _slug(value: str) -> str:
    """Create a compact identifier."""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:80] or "location"


class PubliBikeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PubliBike."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize flow."""
        self._catalog: dict[str, dict[str, str]] = {}
        self._selected_city: str | None = None
        self._reference_type: str | None = None

    async def _async_load_catalog(self) -> None:
        """Load stations grouped by city once per flow."""
        if not self._catalog:
            self._catalog = await fetch_station_catalog(self.hass)

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """First step: select city and reference type."""
        errors: dict[str, str] = {}
        await self._async_load_catalog()

        if not self._catalog:
            errors["base"] = "no_stations_from_api"
            schema = vol.Schema({})
            return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

        cities = list(self._catalog)
        if "Alle Städte" not in cities:
            cities = ["Alle Städte", *cities]

        if user_input is not None:
            self._selected_city = str(user_input[CONF_CITY])
            self._reference_type = str(user_input[CONF_REFERENCE_TYPE])
            if self._reference_type == REFERENCE_TYPE_ADDRESS:
                return await self.async_step_address()
            return await self.async_step_station()

        default_city = _default_city(cities)
        schema = vol.Schema(
            {
                vol.Required(CONF_CITY, default=default_city): vol.In(cities),
                vol.Required(CONF_REFERENCE_TYPE, default=REFERENCE_TYPE_STATION): vol.In(REFERENCE_OPTIONS),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_station(self, user_input: dict[str, Any] | None = None):
        """Second step: select station and update settings."""
        errors: dict[str, str] = {}
        await self._async_load_catalog()

        if not self._selected_city:
            return await self.async_step_user()

        if self._selected_city == "Alle Städte":
            station_options: dict[str, str] = {}
            for city, stations in self._catalog.items():
                for station_id, label in stations.items():
                    station_options[station_id] = f"{city} - {label}"
            station_options = dict(sorted(station_options.items(), key=lambda item: item[1].lower()))
        else:
            station_options = self._catalog.get(self._selected_city, {})

        if not station_options:
            errors["base"] = "no_stations_for_city"
            schema = vol.Schema({})
            return self.async_show_form(step_id="station", data_schema=schema, errors=errors)

        if user_input is not None:
            station_id = str(user_input[CONF_STATION_ID])
            station_name = station_options.get(station_id, f"Station {station_id}")
            location_name = str(user_input.get(CONF_LOCATION_NAME) or station_name)
            update_interval = max(int(user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)), MIN_UPDATE_INTERVAL)
            min_ebike_battery = max(0, min(int(user_input.get(CONF_MIN_EBIKE_BATTERY, DEFAULT_MIN_EBIKE_BATTERY)), 200))

            await self.async_set_unique_id(f"publibike_station_{station_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=location_name,
                data={
                    CONF_REFERENCE_TYPE: REFERENCE_TYPE_STATION,
                    CONF_LOCATION_NAME: location_name,
                    CONF_CITY: self._selected_city,
                    CONF_STATION_ID: station_id,
                    CONF_STATION_NAME: station_name,
                    CONF_UPDATE_INTERVAL: update_interval,
                    CONF_MIN_EBIKE_BATTERY: min_ebike_battery,
                },
            )

        default_station = next(iter(station_options))
        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID, default=default_station): vol.In(station_options),
                vol.Optional(CONF_LOCATION_NAME, default=""): str,
                vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)
                ),
                vol.Required(CONF_MIN_EBIKE_BATTERY, default=DEFAULT_MIN_EBIKE_BATTERY): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=200)
                ),
            }
        )
        return self.async_show_form(step_id="station", data_schema=schema, errors=errors)

    async def async_step_address(self, user_input: dict[str, Any] | None = None):
        """Second step for address/coordinate based tracking."""
        errors: dict[str, str] = {}
        if not self._selected_city:
            return await self.async_step_user()

        if user_input is not None:
            location_name = str(user_input.get(CONF_LOCATION_NAME) or "PubliBike Standort")
            address = str(user_input.get(CONF_ADDRESS) or "").strip()
            lat_raw = user_input.get(CONF_LATITUDE)
            lon_raw = user_input.get(CONF_LONGITUDE)
            lat = float(lat_raw) if lat_raw not in (None, "") else None
            lon = float(lon_raw) if lon_raw not in (None, "") else None
            geocode_source = None

            if lat is None or lon is None:
                if not address:
                    errors["base"] = "address_or_coordinates_required"
                else:
                    geocoded = await geocode_address(self.hass, address)
                    if geocoded is None:
                        errors["base"] = "address_not_found"
                    else:
                        lat = float(geocoded["latitude"])
                        lon = float(geocoded["longitude"])
                        geocode_source = geocoded.get("source")
                        if location_name == "PubliBike Standort":
                            location_name = str(geocoded.get("label") or address)

            if not errors:
                update_interval = max(int(user_input.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)), MIN_UPDATE_INTERVAL)
                min_ebike_battery = max(0, min(int(user_input.get(CONF_MIN_EBIKE_BATTERY, DEFAULT_MIN_EBIKE_BATTERY)), 200))
                unique_base = address or f"{lat:.6f}_{lon:.6f}"
                await self.async_set_unique_id(f"publibike_location_{_slug(location_name)}_{_slug(unique_base)}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=location_name,
                    data={
                        CONF_REFERENCE_TYPE: REFERENCE_TYPE_ADDRESS,
                        CONF_LOCATION_NAME: location_name,
                        CONF_CITY: self._selected_city,
                        CONF_ADDRESS: address,
                        CONF_LATITUDE: lat,
                        CONF_LONGITUDE: lon,
                        ATTR_GEOCODE_SOURCE: geocode_source,
                        CONF_UPDATE_INTERVAL: update_interval,
                        CONF_MIN_EBIKE_BATTERY: min_ebike_battery,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_LOCATION_NAME, default="Zuhause"): str,
                vol.Optional(CONF_ADDRESS, default=""): str,
                vol.Optional(CONF_LATITUDE, default=""): str,
                vol.Optional(CONF_LONGITUDE, default=""): str,
                vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)
                ),
                vol.Required(CONF_MIN_EBIKE_BATTERY, default=DEFAULT_MIN_EBIKE_BATTERY): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=200)
                ),
            }
        )
        return self.async_show_form(step_id="address", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return PubliBikeOptionsFlow(config_entry)


class PubliBikeOptionsFlow(config_entries.OptionsFlow):
    """Handle PubliBike options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Options: update refresh interval and e-bike battery threshold."""
        current_interval = self.config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        current_min_battery = self.config_entry.options.get(
            CONF_MIN_EBIKE_BATTERY,
            self.config_entry.data.get(CONF_MIN_EBIKE_BATTERY, DEFAULT_MIN_EBIKE_BATTERY),
        )

        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_UPDATE_INTERVAL: max(int(user_input[CONF_UPDATE_INTERVAL]), MIN_UPDATE_INTERVAL),
                    CONF_MIN_EBIKE_BATTERY: max(0, min(int(user_input[CONF_MIN_EBIKE_BATTERY]), 200)),
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current_interval): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL)
                ),
                vol.Required(CONF_MIN_EBIKE_BATTERY, default=current_min_battery): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=200)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
