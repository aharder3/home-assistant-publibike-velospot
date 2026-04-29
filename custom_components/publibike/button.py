"""Button platform for PubliBike / Velospot."""

from __future__ import annotations

from dataclasses import dataclass
import re

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CITY,
    CONF_LOCATION_NAME,
    CONF_MIN_EBIKE_BATTERY,
    CONF_REFERENCE_TYPE,
    CONF_STATION_ID,
    DEFAULT_MIN_EBIKE_BATTERY,
    DOMAIN,
)
from .coordinator import PubliBikeDataUpdateCoordinator


@dataclass(frozen=True, kw_only=True)
class PubliBikeButtonEntityDescription(ButtonEntityDescription):
    """Describes a PubliBike button."""


BUTTONS: tuple[PubliBikeButtonEntityDescription, ...] = (
    PubliBikeButtonEntityDescription(
        key="refresh",
        translation_key="refresh",
        name="Aktualisieren",
        icon="mdi:refresh",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PubliBike buttons from a config entry."""
    coordinator: PubliBikeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(PubliBikeRefreshButton(coordinator, entry, description) for description in BUTTONS)



def _slug_entity(value: str) -> str:
    """Return a compact Home Assistant object-id-safe slug."""
    value = value.lower().strip()
    value = (
        value.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("é", "e")
        .replace("è", "e")
        .replace("à", "a")
    )
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")[:50] or "standort"


class PubliBikeRefreshButton(CoordinatorEntity[PubliBikeDataUpdateCoordinator], ButtonEntity):
    """Manual refresh button."""

    entity_description: PubliBikeButtonEntityDescription

    def __init__(
        self,
        coordinator: PubliBikeDataUpdateCoordinator,
        entry: ConfigEntry,
        description: PubliBikeButtonEntityDescription,
    ) -> None:
        """Initialize button."""
        super().__init__(coordinator)
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        location_name = entry.options.get(
            CONF_LOCATION_NAME,
            entry.data.get(CONF_LOCATION_NAME, "PubliBike"),
        )
        self._attr_suggested_object_id = f"publibike_{_slug_entity(str(location_name))}_aktualisieren"

    @property
    def name(self) -> str:
        """Return short button name."""
        return self.entity_description.name or "Aktualisieren"

    async def async_press(self) -> None:
        """Trigger an immediate refresh."""
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        location_name = self.entry.options.get(
            CONF_LOCATION_NAME,
            self.entry.data.get(CONF_LOCATION_NAME, "PubliBike"),
        )
        city = self.entry.options.get(CONF_CITY, self.entry.data.get(CONF_CITY, ""))
        min_battery = self.entry.options.get(
            CONF_MIN_EBIKE_BATTERY,
            self.entry.data.get(CONF_MIN_EBIKE_BATTERY, DEFAULT_MIN_EBIKE_BATTERY),
        )
        reference_type = self.entry.options.get(CONF_REFERENCE_TYPE, self.entry.data.get(CONF_REFERENCE_TYPE, ""))
        device_id = self.entry.data.get(CONF_STATION_ID) or self.entry.entry_id
        return DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            name=f"PubliBike {location_name}",
            manufacturer="PubliBike / Velospot",
            model=f"{reference_type} · {city} · E-Bike >= {min_battery} km",
        )
