"""Sensor platform for PubliBike / Velospot."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ADDRESS,
    ATTR_API_LIMITATION,
    ATTR_API_MODE,
    ATTR_AVAILABLE_REASON,
    ATTR_BATTERY_FILTER_AVAILABLE,
    ATTR_BATTERY_PERCENT_AVAILABLE,
    ATTR_BATTERY_PERCENT_ESTIMATED,
    ATTR_BIKE_TABLE,
    ATTR_BIKE_TABLE_MARKDOWN,
    ATTR_CAPACITY,
    ATTR_CITY,
    ATTR_CONFIGURED_CITY,
    ATTR_DETAILS_ROUTE,
    ATTR_DISTANCE_AIR_M,
    ATTR_EBIKE_BATTERY_LEVELS,
        ATTR_EBIKE_RANGE_KM,
        ATTR_EBIKE_RANGE_AVAILABLE,
        ATTR_EBIKES_OVER_RANGE,
        ATTR_MIN_EBIKE_RANGE_KM,
        ATTR_RANGE_SOURCE,
    ATTR_EBIKE_TABLE,
    ATTR_EBIKE_TABLE_MARKDOWN,
    ATTR_EBIKES,
    ATTR_EBIKES_OVER_THRESHOLD,
    ATTR_GEOCODE_SOURCE,
    ATTR_LAST_UPDATE,
    ATTR_LATITUDE,
    ATTR_LOCATION_NAME,
    ATTR_LONGITUDE,
    ATTR_MAP_ICON,
    ATTR_MIN_EBIKE_BATTERY,
    ATTR_MIN_EBIKE_RANGE_KM,
    ATTR_EBIKE_RANGE_KM,
    ATTR_EBIKE_RANGE_AVAILABLE,
    ATTR_EBIKES_OVER_RANGE,
    ATTR_RANGE_SOURCE,
    ATTR_NEAREST_STATION_TYPE,
    ATTR_NETWORK,
    ATTR_NORMAL_BIKES,
    ATTR_RAW_STATION_COUNT,
    ATTR_REFERENCE_TYPE,
    ATTR_SELECTED_STATION,
    ATTR_SOURCE,
    ATTR_SOURCE_ENDPOINT,
    ATTR_STATUS,
    ATTR_STATION_ID,
    ATTR_STATION_NAME,
    ATTR_STATION_NUMBER,
    ATTR_TOTAL_BIKES,
    ATTR_UPDATE_INTERVAL,
    ATTR_VEHICLE_DETAIL_SOURCE,
    ATTR_VEHICLE_DETAILS_AVAILABLE,
    ATTR_VEHICLE_ID_AVAILABLE,
    ATTR_VEHICLE_LIST_NOTE,
    ATTR_VEHICLE_TABLE,
    ATTR_VEHICLE_TABLE_MARKDOWN,
    ATTR_WARNING,
    ATTR_WALKING_DISTANCE_ESTIMATE_M,
    ATTR_WALKING_TIME_ESTIMATE_MIN,
    CONF_CITY,
    CONF_LOCATION_NAME,
    CONF_MIN_EBIKE_BATTERY,
    CONF_REFERENCE_TYPE,
    CONF_STATION_ID,
    DEFAULT_MIN_EBIKE_BATTERY,
    DOMAIN,
    REFERENCE_TYPE_ADDRESS,
    REFERENCE_TYPE_STATION,
)
from .coordinator import (
    PubliBikeData,
    PubliBikeDataUpdateCoordinator,
    PubliBikeNearestStationData,
    PubliBikeStationData,
)


@dataclass(frozen=True, kw_only=True)
class PubliBikeSensorEntityDescription(SensorEntityDescription):
    """Describes a PubliBike sensor."""

    value_fn: Callable[[PubliBikeData], Any]
    attributes_fn: Callable[[PubliBikeData], dict[str, Any]] | None = None


def _station_name(data: PubliBikeStationData) -> str:
    """Return station name."""
    return str(data.station.get("name") or data.station.get("station_name") or data.station.get("id") or "Unknown")


def _network_name(data: PubliBikeStationData) -> str | None:
    """Return network name."""
    if data.station.get("network_name"):
        return data.station.get("network_name")
    network = data.station.get("network") or {}
    return network.get("name")


def _base_station_attributes(data: PubliBikeStationData) -> dict[str, Any]:
    """Return common station attributes, including the vehicle table."""
    attrs = {
        ATTR_SOURCE: DOMAIN,
        ATTR_STATION_ID: data.station.get("id"),
        ATTR_STATION_NUMBER: data.station.get("station_number") or data.station.get("stationNumber"),
        ATTR_STATION_NAME: _station_name(data),
        ATTR_ADDRESS: data.station.get("address") or data.station.get("station_address"),
        ATTR_CITY: data.station.get("city"),
        ATTR_NETWORK: _network_name(data),
        ATTR_LATITUDE: data.station.get("latitude"),
        ATTR_LONGITUDE: data.station.get("longitude"),
        ATTR_CAPACITY: data.station.get("capacity"),
        ATTR_TOTAL_BIKES: data.total_bikes,
        ATTR_EBIKES: data.ebikes,
        ATTR_NORMAL_BIKES: data.normal_bikes,
        ATTR_STATUS: data.status,
        ATTR_AVAILABLE_REASON: data.meta.get(ATTR_AVAILABLE_REASON),
        ATTR_VEHICLE_TABLE: data.meta.get(ATTR_VEHICLE_TABLE),
        ATTR_EBIKE_TABLE: data.meta.get(ATTR_EBIKE_TABLE),
        ATTR_BIKE_TABLE: data.meta.get(ATTR_BIKE_TABLE),
        ATTR_EBIKE_TABLE_MARKDOWN: data.meta.get(ATTR_EBIKE_TABLE_MARKDOWN),
        ATTR_BIKE_TABLE_MARKDOWN: data.meta.get(ATTR_BIKE_TABLE_MARKDOWN),
        ATTR_VEHICLE_TABLE_MARKDOWN: data.meta.get(ATTR_VEHICLE_TABLE_MARKDOWN),
        ATTR_EBIKE_RANGE_KM: data.meta.get(ATTR_EBIKE_RANGE_KM),
        ATTR_EBIKE_RANGE_AVAILABLE: data.meta.get(ATTR_EBIKE_RANGE_AVAILABLE),
        ATTR_EBIKES_OVER_RANGE: data.meta.get(ATTR_EBIKES_OVER_RANGE),
        ATTR_EBIKE_BATTERY_LEVELS: data.meta.get(ATTR_EBIKE_BATTERY_LEVELS),
        ATTR_EBIKES_OVER_THRESHOLD: data.meta.get(ATTR_EBIKES_OVER_THRESHOLD),
        ATTR_BATTERY_FILTER_AVAILABLE: data.meta.get(ATTR_BATTERY_FILTER_AVAILABLE),
        ATTR_VEHICLE_DETAILS_AVAILABLE: data.meta.get(ATTR_VEHICLE_DETAILS_AVAILABLE),
        ATTR_VEHICLE_ID_AVAILABLE: data.meta.get(ATTR_VEHICLE_ID_AVAILABLE),
        ATTR_BATTERY_PERCENT_AVAILABLE: data.meta.get(ATTR_BATTERY_PERCENT_AVAILABLE),
        ATTR_BATTERY_PERCENT_ESTIMATED: data.meta.get(ATTR_BATTERY_PERCENT_ESTIMATED),
        ATTR_VEHICLE_DETAIL_SOURCE: data.meta.get(ATTR_VEHICLE_DETAIL_SOURCE),
        ATTR_API_LIMITATION: data.meta.get(ATTR_API_LIMITATION),
        ATTR_VEHICLE_LIST_NOTE: data.meta.get(ATTR_VEHICLE_LIST_NOTE),
        ATTR_DETAILS_ROUTE: data.station.get("details_route") or data.station.get("detailsRoute"),
        ATTR_MAP_ICON: data.station.get("map_icon") or data.station.get("mapIcon"),
        ATTR_API_MODE: data.meta.get(ATTR_API_MODE),
        ATTR_SOURCE_ENDPOINT: data.meta.get(ATTR_SOURCE_ENDPOINT),
        ATTR_RAW_STATION_COUNT: data.meta.get(ATTR_RAW_STATION_COUNT),
        ATTR_UPDATE_INTERVAL: data.meta.get(ATTR_UPDATE_INTERVAL),
    }
    return {key: value for key, value in attrs.items() if value not in (None, [], "")}


def _location_attributes(data: PubliBikeData) -> dict[str, Any]:
    """Attributes for the configured reference location."""
    attrs = {
        ATTR_SOURCE: DOMAIN,
        ATTR_LOCATION_NAME: data.location.name,
        ATTR_REFERENCE_TYPE: data.location.reference_type,
        ATTR_ADDRESS: data.location.address,
        ATTR_CONFIGURED_CITY: data.location.city,
        ATTR_LATITUDE: data.location.latitude,
        ATTR_LONGITUDE: data.location.longitude,
        ATTR_GEOCODE_SOURCE: data.location.meta.get(ATTR_GEOCODE_SOURCE),
        ATTR_SELECTED_STATION: _station_name(data.location.selected_station) if data.location.selected_station else None,
        ATTR_RAW_STATION_COUNT: data.all_station_count,
        ATTR_MIN_EBIKE_BATTERY: data.meta.get(ATTR_MIN_EBIKE_BATTERY),
        ATTR_MIN_EBIKE_RANGE_KM: data.meta.get(ATTR_MIN_EBIKE_RANGE_KM) or data.meta.get(ATTR_MIN_EBIKE_BATTERY),
        ATTR_UPDATE_INTERVAL: data.meta.get(ATTR_UPDATE_INTERVAL),
        ATTR_API_MODE: data.meta.get(ATTR_API_MODE),
        ATTR_SOURCE_ENDPOINT: data.meta.get(ATTR_SOURCE_ENDPOINT),
    }
    return {key: value for key, value in attrs.items() if value not in (None, [], "")}


def _compact_station_attributes_by_type(
    station_data: PubliBikeStationData,
    station_type: str,
    location_data: PubliBikeData | None = None,
) -> dict[str, Any]:
    """Return compact attributes for the separated e-bike/bike entities.

    E-bike tables intentionally expose only ID and range. Normal-bike tables
    intentionally expose only ID, so the more-info popup stays readable.
    """
    attrs: dict[str, Any] = {
        ATTR_SOURCE: DOMAIN,
        ATTR_STATION_ID: station_data.station.get("id"),
        ATTR_STATION_NUMBER: station_data.station.get("station_number") or station_data.station.get("stationNumber"),
        ATTR_STATION_NAME: _station_name(station_data),
        ATTR_ADDRESS: station_data.station.get("address") or station_data.station.get("station_address"),
        ATTR_CITY: station_data.station.get("city"),
        ATTR_LATITUDE: station_data.station.get("latitude"),
        ATTR_LONGITUDE: station_data.station.get("longitude"),
        ATTR_NEAREST_STATION_TYPE: station_type,
        ATTR_VEHICLE_DETAIL_SOURCE: station_data.meta.get(ATTR_VEHICLE_DETAIL_SOURCE),
        ATTR_VEHICLE_DETAILS_AVAILABLE: station_data.meta.get(ATTR_VEHICLE_DETAILS_AVAILABLE),
        ATTR_VEHICLE_ID_AVAILABLE: station_data.meta.get(ATTR_VEHICLE_ID_AVAILABLE),
        ATTR_VEHICLE_LIST_NOTE: station_data.meta.get(ATTR_VEHICLE_LIST_NOTE),
        ATTR_DETAILS_ROUTE: station_data.station.get("details_route") or station_data.station.get("detailsRoute"),
        ATTR_API_LIMITATION: station_data.meta.get(ATTR_API_LIMITATION),
    }

    if location_data is not None:
        attrs[ATTR_LOCATION_NAME] = location_data.location.name
        attrs[ATTR_CONFIGURED_CITY] = location_data.location.city

    if station_type == "ebike":
        attrs[ATTR_EBIKES] = station_data.ebikes
        attrs[ATTR_MIN_EBIKE_RANGE_KM] = station_data.meta.get(ATTR_MIN_EBIKE_RANGE_KM)
        attrs[ATTR_EBIKE_RANGE_AVAILABLE] = station_data.meta.get(ATTR_EBIKE_RANGE_AVAILABLE)
        attrs[ATTR_EBIKES_OVER_RANGE] = station_data.meta.get(ATTR_EBIKES_OVER_RANGE)
        attrs[ATTR_EBIKE_TABLE] = station_data.meta.get(ATTR_EBIKE_TABLE)
        attrs[ATTR_EBIKE_TABLE_MARKDOWN] = station_data.meta.get(ATTR_EBIKE_TABLE_MARKDOWN)
    else:
        attrs[ATTR_NORMAL_BIKES] = station_data.normal_bikes
        attrs[ATTR_BIKE_TABLE] = station_data.meta.get(ATTR_BIKE_TABLE)
        attrs[ATTR_BIKE_TABLE_MARKDOWN] = station_data.meta.get(ATTR_BIKE_TABLE_MARKDOWN)

    return {key: value for key, value in attrs.items() if value not in (None, [], "")}


def _selected_station(data: PubliBikeData) -> PubliBikeStationData | None:
    """Return configured station if this entry tracks a station."""
    return data.location.selected_station


def _table_station(data: PubliBikeData) -> PubliBikeStationData | None:
    """Return the station used by the table sensor."""
    if data.location.selected_station is not None:
        return data.location.selected_station
    if data.nearest_available is not None:
        return data.nearest_available.station_data
    return None


def _selected_station_attributes(data: PubliBikeData) -> dict[str, Any]:
    """Attributes for selected station sensors."""
    station = _selected_station(data)
    if station is None:
        return _location_attributes(data)
    attrs = _base_station_attributes(station)
    attrs[ATTR_CONFIGURED_CITY] = data.location.city
    attrs["all_station_count"] = data.all_station_count
    return attrs


def _selected_station_name(data: PubliBikeData) -> str:
    """Return selected station name."""
    station = _selected_station(data)
    return data.location.name if station is None else _station_name(station)


def _nearest_available_name(data: PubliBikeData) -> str:
    """Return nearest usable station name."""
    if data.nearest_available is None:
        return "Keine Station gefunden"
    return _station_name(data.nearest_available.station_data)


def _nearest_available_attributes(data: PubliBikeData) -> dict[str, Any]:
    """Attributes for nearest usable station sensor."""
    nearest = data.nearest_available
    if nearest is None:
        return {
            ATTR_SOURCE: DOMAIN,
            ATTR_LOCATION_NAME: data.location.name,
            ATTR_CONFIGURED_CITY: data.location.city,
            ATTR_MIN_EBIKE_BATTERY: data.meta.get(ATTR_MIN_EBIKE_BATTERY),
        ATTR_MIN_EBIKE_RANGE_KM: data.meta.get(ATTR_MIN_EBIKE_RANGE_KM) or data.meta.get(ATTR_MIN_EBIKE_BATTERY),
            ATTR_STATUS: "Keine passende Station gefunden",
            ATTR_WARNING: "Keine Station mit E-Bike oder normalem Bike gefunden.",
        }

    attrs = _base_station_attributes(nearest.station_data)
    attrs.update(
        {
            ATTR_LOCATION_NAME: data.location.name,
            ATTR_CONFIGURED_CITY: data.location.city,
            ATTR_DISTANCE_AIR_M: nearest.distance_air_m,
            ATTR_WALKING_DISTANCE_ESTIMATE_M: nearest.walking_distance_estimate_m,
            ATTR_WALKING_TIME_ESTIMATE_MIN: nearest.walking_time_estimate_min,
            ATTR_MIN_EBIKE_BATTERY: nearest.min_range,
                ATTR_MIN_EBIKE_RANGE_KM: nearest.min_range,
            ATTR_BATTERY_FILTER_AVAILABLE: nearest.range_filter_available,
                ATTR_EBIKE_RANGE_AVAILABLE: nearest.range_filter_available,
            ATTR_WARNING: nearest.warning,
        }
    )
    return {key: value for key, value in attrs.items() if value not in (None, [], "")}


def _nearest_by_type(data: PubliBikeData, station_type: str) -> PubliBikeNearestStationData | None:
    """Return nearest station data by requested type."""
    if station_type == "ebike":
        return data.nearest_ebike
    if station_type == "bike":
        return data.nearest_bike
    return data.nearest_available


def _nearest_name_by_type(station_type: str) -> Callable[[PubliBikeData], str]:
    """Return value function for nearest station name."""
    def _value(data: PubliBikeData) -> str:
        nearest = _nearest_by_type(data, station_type)
        if nearest is None:
            return "Keine Station gefunden"
        return _station_name(nearest.station_data)
    return _value


def _nearest_distance_by_type(station_type: str) -> Callable[[PubliBikeData], Any]:
    """Return value function for walking distance."""
    def _value(data: PubliBikeData) -> Any:
        nearest = _nearest_by_type(data, station_type)
        if nearest is None:
            return None
        return nearest.walking_distance_estimate_m
    return _value


def _nearest_count_by_type(station_type: str) -> Callable[[PubliBikeData], Any]:
    """Return value function for bike count."""
    def _value(data: PubliBikeData) -> Any:
        nearest = _nearest_by_type(data, station_type)
        if nearest is None:
            return None
        if station_type == "ebike":
            return nearest.station_data.ebikes
        if station_type == "bike":
            return nearest.station_data.normal_bikes
        return nearest.station_data.total_bikes
    return _value


def _nearest_attrs_by_type(station_type: str) -> Callable[[PubliBikeData], dict[str, Any]]:
    """Return attributes for nearest e-bike or normal-bike station."""
    def _attributes(data: PubliBikeData) -> dict[str, Any]:
        nearest = _nearest_by_type(data, station_type)
        label = "E-Bike" if station_type == "ebike" else "Bike"
        if nearest is None:
            return {
                ATTR_SOURCE: DOMAIN,
                ATTR_LOCATION_NAME: data.location.name,
                ATTR_CONFIGURED_CITY: data.location.city,
                ATTR_NEAREST_STATION_TYPE: station_type,
                ATTR_MIN_EBIKE_BATTERY: data.meta.get(ATTR_MIN_EBIKE_BATTERY),
        ATTR_MIN_EBIKE_RANGE_KM: data.meta.get(ATTR_MIN_EBIKE_RANGE_KM) or data.meta.get(ATTR_MIN_EBIKE_BATTERY),
                ATTR_STATUS: f"Keine passende {label}-Station gefunden",
            }

        attrs = _compact_station_attributes_by_type(nearest.station_data, station_type, data)
        attrs.update(
            {
                ATTR_DISTANCE_AIR_M: nearest.distance_air_m,
                ATTR_WALKING_DISTANCE_ESTIMATE_M: nearest.walking_distance_estimate_m,
                ATTR_WALKING_TIME_ESTIMATE_MIN: nearest.walking_time_estimate_min,
                ATTR_MIN_EBIKE_BATTERY: nearest.min_range,
                ATTR_MIN_EBIKE_RANGE_KM: nearest.min_range,
                ATTR_BATTERY_FILTER_AVAILABLE: nearest.range_filter_available,
                ATTR_EBIKE_RANGE_AVAILABLE: nearest.range_filter_available,
                ATTR_WARNING: nearest.warning,
            }
        )
        return {key: value for key, value in attrs.items() if value not in (None, [], "")}
    return _attributes


def _selected_count_by_type(station_type: str) -> Callable[[PubliBikeData], Any]:
    """Return selected station count for e-bikes or normal bikes."""
    def _value(data: PubliBikeData) -> Any:
        station = _selected_station(data)
        if station is None:
            return None
        return station.ebikes if station_type == "ebike" else station.normal_bikes
    return _value


def _selected_attrs_by_type(station_type: str) -> Callable[[PubliBikeData], dict[str, Any]]:
    """Return selected station attributes filtered by type."""
    def _attributes(data: PubliBikeData) -> dict[str, Any]:
        station = _selected_station(data)
        if station is None:
            return _location_attributes(data)
        attrs = _compact_station_attributes_by_type(station, station_type, data)
        attrs[ATTR_CONFIGURED_CITY] = data.location.city
        return attrs
    return _attributes


def _table_station_by_type(data: PubliBikeData, station_type: str) -> PubliBikeStationData | None:
    """Return station for e-bike or normal-bike table."""
    selected = _selected_station(data)
    if selected is not None:
        return selected
    nearest = _nearest_by_type(data, station_type)
    return nearest.station_data if nearest is not None else None


def _table_state_by_type(station_type: str) -> Callable[[PubliBikeData], str]:
    """State for separated e-bike/bike table sensor."""
    def _value(data: PubliBikeData) -> str:
        station = _table_station_by_type(data, station_type)
        if station is None:
            return "Keine Station"
        if station_type == "ebike":
            return f"{station.ebikes} E-Bikes"
        return f"{station.normal_bikes} Bikes"
    return _value


def _table_attrs_by_type(station_type: str) -> Callable[[PubliBikeData], dict[str, Any]]:
    """Attributes for separated e-bike/bike table sensor."""
    def _attributes(data: PubliBikeData) -> dict[str, Any]:
        station = _table_station_by_type(data, station_type)
        if station is None:
            return _location_attributes(data)
        attrs = _compact_station_attributes_by_type(station, station_type, data)
        nearest = _nearest_by_type(data, station_type) if data.location.selected_station is None else None
        if nearest is not None:
            attrs[ATTR_DISTANCE_AIR_M] = nearest.distance_air_m
            attrs[ATTR_WALKING_DISTANCE_ESTIMATE_M] = nearest.walking_distance_estimate_m
            attrs[ATTR_WALKING_TIME_ESTIMATE_MIN] = nearest.walking_time_estimate_min
            attrs[ATTR_MIN_EBIKE_RANGE_KM] = nearest.min_range
            attrs[ATTR_WARNING] = nearest.warning
        return {key: value for key, value in attrs.items() if value not in (None, [], "")}
    return _attributes



def _vehicle_table_state(data: PubliBikeData) -> str:
    """State for the compact table entity."""
    station = _table_station(data)
    if station is None:
        return "Keine Station"
    return f"{station.total_bikes} Bikes"


def _vehicle_table_attributes(data: PubliBikeData) -> dict[str, Any]:
    """Attributes for the vehicle table entity."""
    station = _table_station(data)
    if station is None:
        return _location_attributes(data)
    attrs = _base_station_attributes(station)
    attrs[ATTR_LOCATION_NAME] = data.location.name
    attrs[ATTR_CONFIGURED_CITY] = data.location.city
    if data.nearest_available and station is data.nearest_available.station_data:
        attrs[ATTR_DISTANCE_AIR_M] = data.nearest_available.distance_air_m
        attrs[ATTR_WALKING_DISTANCE_ESTIMATE_M] = data.nearest_available.walking_distance_estimate_m
        attrs[ATTR_WALKING_TIME_ESTIMATE_MIN] = data.nearest_available.walking_time_estimate_min
        attrs[ATTR_WARNING] = data.nearest_available.warning
    return {key: value for key, value in attrs.items() if value not in (None, [], "")}


def _api_status_attributes(data: PubliBikeData) -> dict[str, Any]:
    """Attributes for the API status sensor."""
    attrs = _location_attributes(data)
    attrs[ATTR_LAST_UPDATE] = data.location.meta.get(ATTR_LAST_UPDATE) or data.meta.get(ATTR_LAST_UPDATE)
    return {key: value for key, value in attrs.items() if value not in (None, [], "")}


ADDRESS_SENSORS: tuple[PubliBikeSensorEntityDescription, ...] = (
    PubliBikeSensorEntityDescription(
        key="location",
        translation_key="location",
        name="Standort",
        icon="mdi:map-marker-radius",
        value_fn=lambda data: data.location.name,
        attributes_fn=_location_attributes,
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_ebike_station",
        translation_key="nearest_ebike_station",
        name="Nächstes E-Bike",
        icon="mdi:bicycle-electric",
        value_fn=_nearest_name_by_type("ebike"),
        attributes_fn=_nearest_attrs_by_type("ebike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_ebike_distance",
        translation_key="nearest_ebike_distance",
        name="E-Bike Entfernung",
        icon="mdi:walk",
        native_unit_of_measurement="m",
        value_fn=_nearest_distance_by_type("ebike"),
        attributes_fn=_nearest_attrs_by_type("ebike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_ebike_count",
        translation_key="nearest_ebike_count",
        name="E-Bikes",
        icon="mdi:bicycle-electric",
        native_unit_of_measurement="Bikes",
        value_fn=_nearest_count_by_type("ebike"),
        attributes_fn=_nearest_attrs_by_type("ebike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_ebike_table",
        translation_key="nearest_ebike_table",
        name="E-Bike Tabelle",
        icon="mdi:table",
        value_fn=_table_state_by_type("ebike"),
        attributes_fn=_table_attrs_by_type("ebike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_bike_station",
        translation_key="nearest_bike_station",
        name="Nächstes Bike",
        icon="mdi:bicycle",
        value_fn=_nearest_name_by_type("bike"),
        attributes_fn=_nearest_attrs_by_type("bike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_bike_distance",
        translation_key="nearest_bike_distance",
        name="Bike Entfernung",
        icon="mdi:walk",
        native_unit_of_measurement="m",
        value_fn=_nearest_distance_by_type("bike"),
        attributes_fn=_nearest_attrs_by_type("bike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_bike_count",
        translation_key="nearest_bike_count",
        name="Normale Bikes",
        icon="mdi:bicycle",
        native_unit_of_measurement="Bikes",
        value_fn=_nearest_count_by_type("bike"),
        attributes_fn=_nearest_attrs_by_type("bike"),
    ),
    PubliBikeSensorEntityDescription(
        key="nearest_bike_table",
        translation_key="nearest_bike_table",
        name="Bike Tabelle",
        icon="mdi:table",
        value_fn=_table_state_by_type("bike"),
        attributes_fn=_table_attrs_by_type("bike"),
    ),
    PubliBikeSensorEntityDescription(
        key="api_status",
        translation_key="api_status",
        name="API Status",
        icon="mdi:api",
        value_fn=lambda data: "OK",
        attributes_fn=_api_status_attributes,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


STATION_SENSORS: tuple[PubliBikeSensorEntityDescription, ...] = (
    PubliBikeSensorEntityDescription(
        key="station",
        translation_key="station",
        name="Station",
        icon="mdi:map-marker",
        value_fn=_selected_station_name,
        attributes_fn=_selected_station_attributes,
    ),
    PubliBikeSensorEntityDescription(
        key="selected_ebikes",
        translation_key="selected_ebikes",
        name="E-Bikes",
        icon="mdi:bicycle-electric",
        native_unit_of_measurement="Bikes",
        value_fn=_selected_count_by_type("ebike"),
        attributes_fn=_selected_attrs_by_type("ebike"),
    ),
    PubliBikeSensorEntityDescription(
        key="selected_ebike_table",
        translation_key="selected_ebike_table",
        name="E-Bike Tabelle",
        icon="mdi:table",
        value_fn=_table_state_by_type("ebike"),
        attributes_fn=_table_attrs_by_type("ebike"),
    ),
    PubliBikeSensorEntityDescription(
        key="selected_bikes",
        translation_key="selected_bikes",
        name="Normale Bikes",
        icon="mdi:bicycle",
        native_unit_of_measurement="Bikes",
        value_fn=_selected_count_by_type("bike"),
        attributes_fn=_selected_attrs_by_type("bike"),
    ),
    PubliBikeSensorEntityDescription(
        key="selected_bike_table",
        translation_key="selected_bike_table",
        name="Bike Tabelle",
        icon="mdi:table",
        value_fn=_table_state_by_type("bike"),
        attributes_fn=_table_attrs_by_type("bike"),
    ),
    PubliBikeSensorEntityDescription(
        key="api_status",
        translation_key="api_status",
        name="API Status",
        icon="mdi:api",
        value_fn=lambda data: "OK",
        attributes_fn=_api_status_attributes,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _sensor_descriptions_for_entry(entry: ConfigEntry) -> tuple[PubliBikeSensorEntityDescription, ...]:
    """Return only useful sensors for this tracking mode."""
    reference_type = entry.options.get(CONF_REFERENCE_TYPE, entry.data.get(CONF_REFERENCE_TYPE, REFERENCE_TYPE_STATION))
    if reference_type == REFERENCE_TYPE_ADDRESS:
        return ADDRESS_SENSORS
    return STATION_SENSORS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PubliBike sensors from a config entry."""
    coordinator: PubliBikeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        PubliBikeSensor(coordinator, entry, description)
        for description in _sensor_descriptions_for_entry(entry)
    )


ENTITY_OBJECT_ID_SUFFIXES: dict[str, str] = {
    "location": "standort",
    "station": "station",
    "nearest_ebike_station": "naechstes_ebike",
    "nearest_ebike_distance": "ebike_entfernung",
    "nearest_ebike_count": "ebikes",
    "nearest_ebike_table": "ebike_tabelle",
    "nearest_bike_station": "naechstes_bike",
    "nearest_bike_distance": "bike_entfernung",
    "nearest_bike_count": "normale_bikes",
    "nearest_bike_table": "bike_tabelle",
    "selected_ebikes": "ebikes",
    "selected_ebike_table": "ebike_tabelle",
    "selected_bikes": "normale_bikes",
    "selected_bike_table": "bike_tabelle",
    "api_status": "api_status",
}


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


def _short_entity_name(name: str) -> str:
    """Remove old duplicated PubliBike prefixes from entity names."""
    if name.startswith("PubliBike "):
        return name.removeprefix("PubliBike ")
    return name


class PubliBikeSensor(CoordinatorEntity[PubliBikeDataUpdateCoordinator], SensorEntity):
    """PubliBike sensor."""

    entity_description: PubliBikeSensorEntityDescription

    _unrecorded_attributes = frozenset({
        ATTR_VEHICLE_TABLE,
        ATTR_EBIKE_TABLE,
        ATTR_BIKE_TABLE,
        ATTR_VEHICLE_TABLE_MARKDOWN,
        ATTR_EBIKE_TABLE_MARKDOWN,
        ATTR_BIKE_TABLE_MARKDOWN,
        ATTR_EBIKE_BATTERY_LEVELS,
        ATTR_EBIKE_RANGE_KM,
        ATTR_EBIKE_RANGE_AVAILABLE,
        ATTR_EBIKES_OVER_RANGE,
        ATTR_MIN_EBIKE_RANGE_KM,
        ATTR_RANGE_SOURCE,
        ATTR_EBIKES_OVER_THRESHOLD,
        ATTR_BATTERY_FILTER_AVAILABLE,
        ATTR_VEHICLE_DETAILS_AVAILABLE,
        ATTR_VEHICLE_ID_AVAILABLE,
        ATTR_BATTERY_PERCENT_AVAILABLE,
        ATTR_BATTERY_PERCENT_ESTIMATED,
        ATTR_API_LIMITATION,
        ATTR_VEHICLE_LIST_NOTE,
        ATTR_VEHICLE_DETAIL_SOURCE,
        ATTR_RAW_STATION_COUNT,
        ATTR_LAST_UPDATE,
        ATTR_TOTAL_BIKES,
        ATTR_EBIKES,
        ATTR_NORMAL_BIKES,
        ATTR_STATUS,
    })

    def __init__(
        self,
        coordinator: PubliBikeDataUpdateCoordinator,
        entry: ConfigEntry,
        description: PubliBikeSensorEntityDescription,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_force_update = description.key == "api_status"
        location_name = entry.options.get(
            CONF_LOCATION_NAME,
            entry.data.get(CONF_LOCATION_NAME, "PubliBike"),
        )
        suffix = ENTITY_OBJECT_ID_SUFFIXES.get(description.key, description.key)
        self._attr_suggested_object_id = f"publibike_{_slug_entity(str(location_name))}_{suffix}"

    @property
    def name(self) -> str:
        """Return short sensor name."""
        base = self.entity_description.name or self.entity_description.key
        return _short_entity_name(str(base))

    @property
    def native_value(self) -> Any:
        """Return sensor state."""
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        if self.coordinator.data is None or self.entity_description.attributes_fn is None:
            return {}
        return self.entity_description.attributes_fn(self.coordinator.data)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

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
