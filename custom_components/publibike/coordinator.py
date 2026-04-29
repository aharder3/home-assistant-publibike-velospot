"""Data coordinator for PubliBike / Velospot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import html
import logging
from math import asin, cos, radians, sin, sqrt
import re
from typing import Any

import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    API_ALL_STATIONS,
    API_PARTNER_STATIONS,
    API_STATION_DETAIL,
    API_STATIONS,
    ATTR_API_MODE,
    ATTR_BATTERY_FILTER_AVAILABLE,
    ATTR_BIKE_LIST,
    ATTR_EBIKE_DETAIL_LIST,
    ATTR_BIKE_DETAIL_LIST,
    ATTR_API_LIMITATION,
    ATTR_AVAILABLE_REASON,
    ATTR_VEHICLE_ID_AVAILABLE,
    ATTR_BATTERY_PERCENT_AVAILABLE,
    ATTR_BATTERY_PERCENT_ESTIMATE,
    ATTR_BATTERY_PERCENT_ESTIMATED,
    ATTR_BIKE_TABLE,
    ATTR_CONFIGURED_CITY,
    ATTR_DISTANCE_AIR_M,
    ATTR_EBIKE_BATTERY_LEVELS,
    ATTR_EBIKE_TABLE,
    ATTR_EBIKE_TABLE_MARKDOWN,
    ATTR_EBIKES_OVER_THRESHOLD,
    ATTR_GEOCODE_SOURCE,
    ATTR_KM_POTENTIAL,
    ATTR_EBIKE_RANGE_KM,
    ATTR_EBIKE_RANGE_AVAILABLE,
    ATTR_EBIKES_OVER_RANGE,
    ATTR_MIN_EBIKE_RANGE_KM,
    ATTR_RANGE_SOURCE,
    ATTR_LAST_UPDATE,
    ATTR_MIN_EBIKE_BATTERY,
    ATTR_RAW_STATION_COUNT,
    ATTR_SOURCE_ENDPOINT,
    ATTR_UPDATE_INTERVAL,
    ATTR_VEHICLE_DETAILS_AVAILABLE,
    ATTR_VEHICLE_DETAIL_SOURCE,
    ATTR_VEHICLE_TABLE,
    ATTR_VEHICLE_TABLE_MARKDOWN,
    ATTR_BIKE_TABLE_MARKDOWN,
    ATTR_VEHICLE_LIST_NOTE,
    ATTR_WALKING_DISTANCE_ESTIMATE_M,
    ATTR_WALKING_TIME_ESTIMATE_MIN,
    GEOCODE_URL,
    CONF_ADDRESS,
    CONF_CITY,
    CONF_LATITUDE,
    CONF_LOCATION_NAME,
    CONF_LONGITUDE,
    CONF_MIN_EBIKE_BATTERY,
    CONF_REFERENCE_TYPE,
    CONF_STATION_ID,
    CONF_UPDATE_INTERVAL,
    DEFAULT_MIN_EBIKE_BATTERY,
    DEFAULT_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MIN_UPDATE_INTERVAL,
    REFERENCE_TYPE_ADDRESS,
    REFERENCE_TYPE_STATION,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PubliBikeStationData:
    """Parsed station data."""

    station: dict[str, Any]
    total_bikes: int
    ebikes: int
    normal_bikes: int
    free_spaces: int | None
    status: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class PubliBikeLocationData:
    """Configured reference location."""

    name: str
    reference_type: str
    latitude: float | None
    longitude: float | None
    city: str | None
    address: str | None
    selected_station: PubliBikeStationData | None
    meta: dict[str, Any]


@dataclass(frozen=True)
class PubliBikeNearestStationData:
    """Nearest station matching a vehicle condition."""

    station_data: PubliBikeStationData
    distance_air_m: int
    walking_distance_estimate_m: int
    walking_time_estimate_min: int
    range_filter_available: bool
    min_range: int
    warning: str | None = None


@dataclass(frozen=True)
class PubliBikeData:
    """Full integration update data."""

    location: PubliBikeLocationData
    nearest_ebike: PubliBikeNearestStationData | None
    nearest_bike: PubliBikeNearestStationData | None
    nearest_available: PubliBikeNearestStationData | None
    all_station_count: int
    meta: dict[str, Any]


def _as_int(value: Any, default: int = 0) -> int:
    """Convert a value to int safely."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    """Convert a value to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    """Return a compact string."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_city_from_address(address: Any, station_name: Any = None) -> str:
    """Extract a city from the Velospot address field."""
    address_text = _clean_text(address)
    if address_text:
        parts = [part.strip() for part in address_text.split(",") if part.strip()]
        candidates = parts[:-1] if len(parts) >= 2 else parts
        for candidate in reversed(candidates):
            candidate = re.sub(r"\b(CH-)?\d{4}\b", "", candidate, count=1).strip(" -")
            candidate = re.sub(
                r"\b(Schweiz|Suisse|Svizzera|Switzerland)\b",
                "",
                candidate,
                flags=re.IGNORECASE,
            ).strip(" -")
            if candidate:
                return candidate

    name_text = _clean_text(station_name)
    if " - " in name_text:
        parts = [part.strip() for part in name_text.split(" - ") if part.strip()]
        if len(parts) >= 2:
            return parts[-2]

    return "Unbekannt"


def _station_name(station: dict[str, Any]) -> str:
    """Return station name."""
    return _clean_text(station.get("name") or station.get("station_name") or f"Station {station.get('id')}")


def station_label(station: dict[str, Any], include_city: bool = False) -> str:
    """Build a readable station label from normalized or raw station data."""
    name = _station_name(station)
    address = station.get("address") or station.get("station_address")
    city = station.get("city")
    station_number = station.get("stationNumber") or station.get("station_number")

    label = name
    if address:
        label = f"{label} ({_clean_text(address)})"
    elif include_city and city:
        label = f"{_clean_text(city)} - {label}"

    if station_number:
        label = f"{label} · Nr. {station_number}"

    return label


def _type_name(vehicle: dict[str, Any]) -> str:
    """Return the vehicle type name."""
    vehicle_type = vehicle.get("type") or {}
    return str(vehicle_type.get("name") or vehicle.get("vehicle_type") or vehicle.get("type_name") or "").lower()


def _is_ebike(vehicle: dict[str, Any]) -> bool:
    """Detect e-bikes robustly from available API fields."""
    if vehicle.get("ebike_battery_level") is not None or vehicle.get("battery_percent") is not None:
        return True
    type_name = _type_name(vehicle)
    return "e-bike" in type_name or "ebike" in type_name or "electric" in type_name or "elektro" in type_name


def _vehicle_id(vehicle: dict[str, Any]) -> str | None:
    """Return vehicle id if the API exposes one."""
    for key in ("id", "bike_id", "vehicle_id", "name", "number"):
        value = vehicle.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _battery_value(vehicle: dict[str, Any]) -> int | None:
    """Return a normalized battery percentage if available."""
    for key in ("ebike_battery_level", "battery_percent", "battery", "charge"):
        value = vehicle.get(key)
        if value is None:
            continue
        battery = _as_int(value, -1)
        if 0 <= battery <= 100:
            return battery
    return None


def _strip_html(value: Any) -> str:
    """Strip HTML tags and normalize whitespace."""
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    return _clean_text(text)


def _km_potential_lower_km(value: Any) -> int | None:
    """Return conservative lower-bound range from Velospot Km-Potenzial."""
    text = _clean_text(value)
    if not text:
        return None
    numbers = re.findall(r"\d+", text)
    if not numbers:
        return None
    lower_bound = _as_int(numbers[0], -1)
    if lower_bound < 0:
        return None
    return lower_bound


def _vehicle_range_km(vehicle: dict[str, Any]) -> tuple[int | None, str | None]:
    """Return (e-bike range lower bound in km, source)."""
    km_value = _km_potential_lower_km(vehicle.get(ATTR_KM_POTENTIAL))
    if km_value is not None:
        return km_value, "velospot Km-Potenzial"
    return None, None


def _battery_value_or_estimate(vehicle: dict[str, Any]) -> tuple[int | None, bool]:
    """Return battery percentage if old API exposes it. Not used for range filtering."""
    value = _battery_value(vehicle)
    return (value, False) if value is not None else (None, False)


def _parse_velospot_detail_vehicles(render_html: str) -> list[dict[str, Any]]:
    """Parse vehicle IDs and Km-Potenzial from the public Velospot detail HTML."""
    if not render_html:
        return []

    vehicles: list[dict[str, Any]] = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", render_html, flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.IGNORECASE | re.DOTALL)
        if not cells:
            continue

        vehicle_id = _strip_html(cells[0])
        if not vehicle_id or vehicle_id.lower() in {"velo id", "id"}:
            continue

        km_potential = _strip_html(cells[1]) if len(cells) > 1 else ""
        is_ebike = bool(km_potential)
        vehicle: dict[str, Any] = {
            "id": vehicle_id,
            "name": vehicle_id,
            "type": {"name": "E-Bike" if is_ebike else "Bike"},
        }
        if km_potential:
            vehicle[ATTR_KM_POTENTIAL] = km_potential
            range_km = _km_potential_lower_km(km_potential)
            if range_km is not None:
                vehicle[ATTR_EBIKE_RANGE_KM] = range_km
                vehicle[ATTR_RANGE_SOURCE] = "velospot Km-Potenzial"
        vehicles.append(vehicle)

    return vehicles


async def _enrich_velospot_station_detail(session: Any, station: dict[str, Any]) -> dict[str, Any]:
    """Fetch Velospot detailsRoute and attach parsed vehicles when available."""
    details_route = station.get("details_route") or station.get("detailsRoute")
    if not details_route:
        return station

    try:
        payload = await _fetch_json(session, str(details_route))
    except Exception:  # noqa: BLE001
        return station

    render_html = ""
    if isinstance(payload, dict):
        render_html = str(payload.get("renderHtml") or payload.get("render_html") or "")
    elif isinstance(payload, str):
        render_html = payload

    vehicles = _parse_velospot_detail_vehicles(render_html)
    if not vehicles:
        return station

    enriched = dict(station)
    enriched["vehicles"] = vehicles
    enriched["source_api"] = "velospot_details_route"
    enriched[ATTR_VEHICLE_DETAIL_SOURCE] = "velospot detailsRoute"
    return enriched


def _ebike_range_levels(station: dict[str, Any]) -> list[int]:
    """Return known e-bike range lower bounds in km from vehicle details."""
    vehicles = station.get("vehicles") or station.get("bikes") or []
    levels: list[int] = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict) or not _is_ebike(vehicle):
            continue
        range_km, _source = _vehicle_range_km(vehicle)
        if range_km is not None:
            levels.append(range_km)
    return levels


def _ebike_battery_levels(station: dict[str, Any]) -> list[int]:
    """Backward compatible alias; from v16 this returns range lower bounds in km."""
    return _ebike_range_levels(station)

def _normalize_velospot_station(station: dict[str, Any]) -> dict[str, Any]:
    """Normalize the new Velospot station structure to stable keys."""
    normalized = dict(station)
    normalized["id"] = str(station.get("station_id") or station.get("stationNumber") or station.get("station_name"))
    normalized["name"] = station.get("station_name")
    normalized["address"] = station.get("station_address")
    normalized["city"] = _extract_city_from_address(station.get("station_address"), station.get("station_name"))
    normalized["latitude"] = _as_float(station.get("lat"))
    normalized["longitude"] = _as_float(station.get("lng"))
    normalized["network_name"] = "Velospot / PubliBike"
    normalized["station_number"] = station.get("stationNumber")
    normalized["details_route"] = station.get("detailsRoute")
    normalized["map_icon"] = station.get("mapIcon")
    normalized["source_api"] = "velospot_all_stations"
    return normalized


def _normalize_old_publibike_station(station: dict[str, Any]) -> dict[str, Any]:
    """Normalize the old PubliBike station structure."""
    normalized = dict(station)
    normalized["id"] = str(station.get("id"))
    network = station.get("network") or {}
    normalized["network_name"] = network.get("name") or "PubliBike"
    normalized["city"] = station.get("city") or _extract_city_from_address(station.get("address"), station.get("name"))
    normalized["latitude"] = station.get("latitude")
    normalized["longitude"] = station.get("longitude")
    normalized["source_api"] = "old_publibike"
    return normalized


def _extract_station_lists(payload: Any) -> list[dict[str, Any]]:
    """Extract and normalize stations from the new all-stations endpoint."""
    stations: list[dict[str, Any]] = []

    if not isinstance(payload, dict):
        return stations

    publibike_payload = payload.get("publibike") or {}
    if isinstance(publibike_payload, dict):
        for station in publibike_payload.get("stations") or []:
            if isinstance(station, dict):
                stations.append(_normalize_old_publibike_station(station))

    velospot_payload = payload.get("velospot") or {}
    if isinstance(velospot_payload, dict):
        for station in velospot_payload.get("responseData") or []:
            if isinstance(station, dict):
                stations.append(_normalize_velospot_station(station))

    return stations


def _distance_m(lat1: float | None, lon1: float | None, lat2: float | None, lon2: float | None) -> int | None:
    """Calculate distance in meters using the haversine formula."""
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None

    earth_radius_m = 6371000
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    c = 2 * asin(sqrt(a))
    return int(round(earth_radius_m * c))


def _walking_estimates(distance_air_m: int) -> tuple[int, int]:
    """Return rough walking distance/time estimates from air-line distance."""
    walking_distance_m = int(round(distance_air_m * 1.25))
    # 4.8 km/h = 80 m/min.
    walking_time_min = max(1, int(round(walking_distance_m / 80)))
    return walking_distance_m, walking_time_min


def parse_station_data(station: dict[str, Any], meta: dict[str, Any] | None = None) -> PubliBikeStationData:
    """Parse a station response from either the new Velospot or old PubliBike API."""
    if "totalBike" in station or "totalElectricalBike" in station or "totalNonElectricalBike" in station:
        total_bikes = _as_int(station.get("totalBike"), 0)
        ebikes = _as_int(station.get("totalElectricalBike"), 0)
        normal_bikes = _as_int(station.get("totalNonElectricalBike"), max(total_bikes - ebikes, 0))
        free_spaces = None

        icon = str(station.get("mapIcon") or "").lower()
        if total_bikes > 0:
            status = "Bikes verfügbar"
        elif "available" in icon:
            status = "Station verfügbar, keine Bikes"
        else:
            status = "Keine Bikes verfügbar"
    else:
        vehicles = station.get("vehicles") or station.get("bikes") or []
        total_bikes = len(vehicles)
        ebikes = sum(1 for vehicle in vehicles if isinstance(vehicle, dict) and _is_ebike(vehicle))
        normal_bikes = max(total_bikes - ebikes, 0)

        capacity = station.get("capacity")
        capacity_int = _as_int(capacity, -1)
        free_spaces = max(capacity_int - total_bikes, 0) if capacity_int >= 0 else None

        state = station.get("state") or {}
        status = str(state.get("name") or station.get("status") or "Unknown")

    parsed_meta = dict(meta or {})
    parsed_meta[ATTR_LAST_UPDATE] = dt_util.utcnow().isoformat()
    parsed_meta[ATTR_EBIKE_BATTERY_LEVELS] = _ebike_range_levels(station)  # legacy attr: now range lower bounds in km
    parsed_meta[ATTR_EBIKE_RANGE_KM] = parsed_meta[ATTR_EBIKE_BATTERY_LEVELS]
    parsed_meta[ATTR_BATTERY_FILTER_AVAILABLE] = bool(parsed_meta[ATTR_EBIKE_RANGE_KM])
    parsed_meta[ATTR_EBIKE_RANGE_AVAILABLE] = bool(parsed_meta[ATTR_EBIKE_RANGE_KM])
    parsed_meta[ATTR_VEHICLE_DETAILS_AVAILABLE] = bool(station.get("vehicles") or station.get("bikes"))
    parsed_meta[ATTR_EBIKES_OVER_THRESHOLD] = sum(
        1
        for level in parsed_meta[ATTR_EBIKE_RANGE_KM]
        if level >= _as_int(parsed_meta.get(ATTR_MIN_EBIKE_BATTERY), DEFAULT_MIN_EBIKE_BATTERY)
    )
    parsed_meta[ATTR_EBIKES_OVER_RANGE] = parsed_meta[ATTR_EBIKES_OVER_THRESHOLD]
    parsed_meta[ATTR_MIN_EBIKE_RANGE_KM] = _as_int(parsed_meta.get(ATTR_MIN_EBIKE_BATTERY), DEFAULT_MIN_EBIKE_BATTERY)
    detail_lists = build_vehicle_detail_lists(station, total_bikes, ebikes, normal_bikes)
    parsed_meta[ATTR_BIKE_LIST] = detail_lists["all"]
    parsed_meta[ATTR_EBIKE_DETAIL_LIST] = detail_lists["ebikes"]
    parsed_meta[ATTR_BIKE_DETAIL_LIST] = detail_lists["bikes"]
    vehicle_tables = build_vehicle_tables(
        station,
        total_bikes,
        ebikes,
        normal_bikes,
        _as_int(parsed_meta.get(ATTR_MIN_EBIKE_BATTERY), DEFAULT_MIN_EBIKE_BATTERY),
    )
    parsed_meta[ATTR_VEHICLE_TABLE] = vehicle_tables["all"]
    parsed_meta[ATTR_EBIKE_TABLE] = vehicle_tables["ebikes"]
    parsed_meta[ATTR_BIKE_TABLE] = vehicle_tables["bikes"]
    parsed_meta[ATTR_VEHICLE_TABLE_MARKDOWN] = vehicle_tables["markdown"]
    parsed_meta[ATTR_EBIKE_TABLE_MARKDOWN] = vehicle_tables["ebike_markdown"]
    parsed_meta[ATTR_BIKE_TABLE_MARKDOWN] = vehicle_tables["bike_markdown"]
    parsed_meta[ATTR_VEHICLE_DETAIL_SOURCE] = vehicle_tables["source"]
    parsed_meta[ATTR_VEHICLE_LIST_NOTE] = vehicle_list_note(station)
    vehicles_for_meta = station.get("vehicles") or station.get("bikes") or []
    parsed_meta[ATTR_VEHICLE_ID_AVAILABLE] = bool(vehicles_for_meta) and any(
        isinstance(vehicle, dict) and _vehicle_id(vehicle) for vehicle in vehicles_for_meta
    )
    parsed_meta[ATTR_BATTERY_PERCENT_ESTIMATED] = bool(vehicles_for_meta) and any(
        isinstance(vehicle, dict) and vehicle.get(ATTR_BATTERY_PERCENT_ESTIMATED) for vehicle in vehicles_for_meta
    )
    parsed_meta[ATTR_BATTERY_PERCENT_AVAILABLE] = bool(vehicles_for_meta) and any(
        isinstance(vehicle, dict) and _is_ebike(vehicle) and _battery_value(vehicle) is not None for vehicle in vehicles_for_meta
    )
    if not parsed_meta[ATTR_VEHICLE_DETAILS_AVAILABLE]:
        parsed_meta[ATTR_API_LIMITATION] = (
            "Die Swagger-Doku der alten PubliBike-API beschreibt Einzelvelo-IDs und ebike_battery_level "
            "für /public/stations/{id} und /public/partner/stations. Diese alten Endpunkte liefern aktuell aber "
            "keine Stationen. Der aktuelle Velospot-Endpunkt liefert nur Summen pro Station "
            "(totalBike, totalElectricalBike, totalNonElectricalBike)."
        )

    return PubliBikeStationData(
        station=station,
        total_bikes=total_bikes,
        ebikes=ebikes,
        normal_bikes=normal_bikes,
        free_spaces=free_spaces,
        status=status,
        meta=parsed_meta,
    )


def build_vehicle_detail_lists(
    station: dict[str, Any],
    total_bikes: int | None = None,
    ebikes: int | None = None,
    normal_bikes: int | None = None,
) -> dict[str, list[str]]:
    """Return bike detail lists for the Home Assistant more-info popup."""
    vehicles = station.get("vehicles") or station.get("bikes") or []
    result_all: list[str] = []
    result_ebikes: list[str] = []
    result_bikes: list[str] = []

    if vehicles:
        for index, vehicle in enumerate(vehicles, start=1):
            if not isinstance(vehicle, dict):
                continue
            is_ebike = _is_ebike(vehicle)
            range_km, _range_source = _vehicle_range_km(vehicle)
            km_potential = vehicle.get(ATTR_KM_POTENTIAL)
            vehicle_id = _vehicle_id(vehicle) or "ID von API nicht verfügbar"
            if is_ebike:
                range_text = str(km_potential or (f"{range_km} km" if range_km is not None else "Reichweite unbekannt"))
                line = f"E-Bike {index}: ID {vehicle_id} · Reichweite {range_text}"
                result_ebikes.append(line)
            else:
                line = f"Bike {index}: ID {vehicle_id}"
                result_bikes.append(line)
            result_all.append(line)
        return {"all": result_all or ["Keine Bikes gemeldet"], "ebikes": result_ebikes, "bikes": result_bikes}

    total = total_bikes if total_bikes is not None else _as_int(station.get("totalBike"), 0)
    e_count = ebikes if ebikes is not None else _as_int(station.get("totalElectricalBike"), 0)
    n_count = normal_bikes if normal_bikes is not None else _as_int(station.get("totalNonElectricalBike"), max(total - e_count, 0))

    station_number = station.get("station_number") or station.get("stationNumber") or "unbekannt"
    if e_count > 0:
        line = (
            f"{e_count} E-Bike(s): Einzelvelo-ID und Reichweite werden nicht direkt in der Stationsübersicht geliefert "
            f"· Station Nr. {station_number}"
        )
        result_ebikes.append(line)
        result_all.append(line)
    if n_count > 0:
        line = f"{n_count} Bike(s): Einzelvelo-ID wird vom aktuellen Velospot-Endpunkt nicht geliefert · Station Nr. {station_number}"
        result_bikes.append(line)
        result_all.append(line)
    if not result_all:
        result_all.append("Keine Bikes gemeldet")
    return {"all": result_all, "ebikes": result_ebikes, "bikes": result_bikes}



def build_vehicle_tables(
    station: dict[str, Any],
    total_bikes: int | None = None,
    ebikes: int | None = None,
    normal_bikes: int | None = None,
    min_range: int | None = None,
) -> dict[str, Any]:
    """Build structured tables for Home Assistant attributes and dashboard markdown.

    Old PubliBike API: vehicles[] contains id/name/ebike_battery_level.
    New Velospot API: only totals per station are exposed, so the table is transparent
    and does not invent fake bike IDs or fake range values.
    """
    vehicles = station.get("vehicles") or station.get("bikes") or []
    min_range_int = _as_int(min_range, DEFAULT_MIN_EBIKE_BATTERY)
    rows_all: list[dict[str, Any]] = []
    rows_ebikes: list[dict[str, Any]] = []
    rows_bikes: list[dict[str, Any]] = []

    if vehicles:
        for index, vehicle in enumerate(vehicles, start=1):
            if not isinstance(vehicle, dict):
                continue
            is_ebike = _is_ebike(vehicle)
            range_km, range_source = _vehicle_range_km(vehicle)
            vehicle_id = _vehicle_id(vehicle)
            vehicle_name = vehicle.get("name") or vehicle.get("number") or vehicle_id
            km_potential = vehicle.get(ATTR_KM_POTENTIAL)
            if range_km is None:
                range_text: Any = "unbekannt" if is_ebike else "-"
            else:
                range_text = km_potential or f"{range_km} km"
            row = {
                "nr": index,
                "typ": "E-Bike" if is_ebike else "Bike",
                "id": vehicle_id or "nicht verfügbar",
                "name": str(vehicle_name) if vehicle_name not in (None, "") else "nicht verfügbar",
                "reichweite": range_text,
                "reichweite_km_min": range_km if range_km is not None else "",
                "reichweite_ok": bool(is_ebike and range_km is not None and range_km >= min_range_int) if is_ebike else True,
                "km_potential": km_potential or "",
                ATTR_EBIKE_RANGE_KM: range_km if range_km is not None else "",
                ATTR_RANGE_SOURCE: range_source or "",
                "akku_prozent": "-",
                "akku_ok": bool(is_ebike and range_km is not None and range_km >= min_range_int) if is_ebike else True,
                "api_quelle": "velospot detailsRoute" if station.get("source_api") == "velospot_details_route" else "api.publibike.ch vehicles[]",
            }
            rows_all.append(row)
            if is_ebike:
                rows_ebikes.append(row)
            else:
                rows_bikes.append(row)
        source = "Einzelvelo-Daten aus alter PubliBike vehicles[] API"
    else:
        total = total_bikes if total_bikes is not None else _as_int(station.get("totalBike"), 0)
        e_count = ebikes if ebikes is not None else _as_int(station.get("totalElectricalBike"), 0)
        n_count = normal_bikes if normal_bikes is not None else _as_int(station.get("totalNonElectricalBike"), max(total - e_count, 0))
        station_number = station.get("station_number") or station.get("stationNumber") or "unbekannt"
        station_id = station.get("id") or station.get("station_id") or "unbekannt"
        if e_count > 0:
            row = {
                "nr": 1,
                "typ": "E-Bike",
                "anzahl": e_count,
                "id": "nicht verfügbar",
                "name": "nicht verfügbar",
                "reichweite": "nicht verfügbar",
                "reichweite_km_min": "",
                "reichweite_ok": "nicht prüfbar",
                "akku_prozent": "-",
                "akku_ok": "nicht prüfbar",
                "station_id": station_id,
                "station_nr": station_number,
                "api_quelle": "rest.publibike.ch / Velospot Summen",
            }
            rows_all.append(row)
            rows_ebikes.append(row)
        if n_count > 0:
            row = {
                "nr": 2 if e_count > 0 else 1,
                "typ": "Bike",
                "anzahl": n_count,
                "id": "nicht verfügbar",
                "name": "nicht verfügbar",
                "reichweite": "-",
                "reichweite_km_min": "",
                "reichweite_ok": True,
                "akku_prozent": "-",
                "akku_ok": True,
                "station_id": station_id,
                "station_nr": station_number,
                "api_quelle": "rest.publibike.ch / Velospot Summen",
            }
            rows_all.append(row)
            rows_bikes.append(row)
        source = "Nur Summen aus neuer Velospot API; keine Einzelvelo-ID und keine Reichweite"

    def _compact_ebike_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return only the fields requested for the E-Bike table."""
        compact: list[dict[str, Any]] = []
        for row in rows:
            compact.append(
                {
                    "id": row.get("id") or row.get("name") or "nicht verfügbar",
                    "reichweite": row.get("reichweite") or row.get("km_potential") or "nicht verfügbar",
                }
            )
        return compact

    def _compact_bike_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return only the fields requested for the normal-bike table."""
        compact: list[dict[str, Any]] = []
        for row in rows:
            compact.append({"id": row.get("id") or row.get("name") or "nicht verfügbar"})
        return compact

    def _markdown_ebikes(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "Keine E-Bikes gemeldet."
        lines = ["| ID | Reichweite |", "|---|---:|"]
        for row in rows:
            lines.append(f"| {row.get('id', 'nicht verfügbar')} | {row.get('reichweite', 'nicht verfügbar')} |")
        return "\n".join(lines)

    def _markdown_bikes(rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "Keine normalen Bikes gemeldet."
        lines = ["| ID |", "|---|"]
        for row in rows:
            lines.append(f"| {row.get('id', 'nicht verfügbar')} |")
        return "\n".join(lines)

    compact_ebikes = _compact_ebike_rows(rows_ebikes)
    compact_bikes = _compact_bike_rows(rows_bikes)
    compact_all: list[dict[str, Any]] = []
    compact_all.extend({"typ": "E-Bike", **row} for row in compact_ebikes)
    compact_all.extend({"typ": "Bike", **row} for row in compact_bikes)

    return {
        "all": compact_all,
        "ebikes": compact_ebikes,
        "bikes": compact_bikes,
        "markdown": (_markdown_ebikes(compact_ebikes) + "\n\n" + _markdown_bikes(compact_bikes)).strip(),
        "ebike_markdown": _markdown_ebikes(compact_ebikes),
        "bike_markdown": _markdown_bikes(compact_bikes),
        "source": source,
    }

def build_bike_list_for_popup(
    station: dict[str, Any],
    total_bikes: int | None = None,
    ebikes: int | None = None,
    normal_bikes: int | None = None,
) -> list[str]:
    """Backward-compatible wrapper for compact bike list."""
    return build_vehicle_detail_lists(station, total_bikes, ebikes, normal_bikes)["all"]


def vehicle_list_note(station: dict[str, Any]) -> str:
    """Return a transparent note about vehicle detail availability."""
    if station.get("vehicles") or station.get("bikes"):
        return "Einzelne Fahrzeuge werden von der API geliefert. Reichweite wird als Km-Potenzial angezeigt, sofern vorhanden."
    return (
        "Die aktuelle Velospot-API liefert für diese Station nur Summen "
        "und keine echten Einzelvelo-/Reichweitenwerte. Die Liste ist deshalb aus den Summen erzeugt."
    )


def _station_matches(station: dict[str, Any], selected_id: str) -> bool:
    """Return true when a station matches the configured ID or station number."""
    return (
        str(station.get("id")) == selected_id
        or str(station.get("station_number")) == selected_id
        or str(station.get("stationNumber")) == selected_id
    )


def _has_ebike_over_threshold(station_data: PubliBikeStationData, min_range: int) -> tuple[bool, bool]:
    """Return (qualifies, range_filter_available)."""
    levels = _ebike_battery_levels(station_data.station)
    if levels:
        return any(level >= min_range for level in levels), True
    return station_data.ebikes > 0, False



def _availability_for_station(station_data: PubliBikeStationData, min_range: int) -> tuple[bool, bool, str | None, str]:
    """Return whether a station has a usable vehicle and the reason.

    The threshold is applied to e-bikes only when individual range values are
    available. Normal bikes always qualify when present.
    """
    levels = _ebike_battery_levels(station_data.station)
    has_normal = station_data.normal_bikes > 0

    if levels:
        charged = [level for level in levels if level >= min_range]
        if charged:
            return True, True, None, f"E-Bike >= {min_range} km Reichweite"
        if has_normal:
            return True, True, None, "Normales Bike verfügbar"
        return False, True, None, f"Kein E-Bike >= {min_range} km Reichweite"

    if has_normal:
        return True, False, None, "Normales Bike verfügbar"

    if station_data.ebikes > 0:
        warning = (
            "Die aktuelle Velospot-API liefert nur die Anzahl E-Bikes, aber keine einzelnen Reichweitenwerte. "
            f"Der Sensor zeigt deshalb eine Station mit E-Bike, nicht garantiert über {min_range} km Reichweite."
        )
        return True, False, warning, "E-Bike vorhanden, Reichweite nicht prüfbar"

    return False, False, None, "Keine Bikes verfügbar"

async def _find_nearest(
    session: Any,
    reference_lat: float | None,
    reference_lon: float | None,
    stations: list[dict[str, Any]],
    city: str | None,
    min_range: int,
    meta: dict[str, Any],
    mode: str,
) -> PubliBikeNearestStationData | None:
    """Find nearest station matching e-bike or normal-bike requirements."""
    if reference_lat is None or reference_lon is None:
        return None

    configured_city = _clean_text(city)
    raw_candidates: list[tuple[int, int, dict[str, Any]]] = []

    for station in stations:
        if configured_city and configured_city != "Alle Städte" and _clean_text(station.get("city")) != configured_city:
            continue

        distance_air = _distance_m(
            reference_lat,
            reference_lon,
            _as_float(station.get("latitude")),
            _as_float(station.get("longitude")),
        )
        if distance_air is None:
            continue

        parsed_fast = parse_station_data(station, meta)
        if mode == "ebike" and parsed_fast.ebikes <= 0:
            continue
        if mode == "bike" and parsed_fast.normal_bikes <= 0:
            continue
        if mode == "available" and parsed_fast.total_bikes <= 0:
            continue

        walking_distance, _walking_time = _walking_estimates(distance_air)
        raw_candidates.append((walking_distance, distance_air, station))

    raw_candidates.sort(key=lambda item: item[0])

    max_detail_checks = 25 if mode == "ebike" else 1

    for index, (walking_distance, distance_air, station) in enumerate(raw_candidates):
        enriched = station
        if index < max_detail_checks:
            enriched = await _enrich_velospot_station_detail(session, station)

        candidate = parse_station_data(enriched, meta)
        range_filter_available = False
        warning = None
        available_reason = None

        if mode == "ebike":
            qualifies, range_filter_available = _has_ebike_over_threshold(candidate, min_range)
            if not qualifies:
                continue
            available_reason = f"E-Bike >= {min_range} km" if range_filter_available else "E-Bike vorhanden, Reichweite nicht prüfbar"
            if not range_filter_available:
                warning = (
                    "Die aktuelle Velospot-API liefert hier keine einzelnen Reichweitenwerte. "
                    f"Ohne Detaildaten ist nicht garantiert, dass das E-Bike über {min_range} km Reichweite hat."
                )
            elif candidate.station.get("source_api") == "velospot_details_route":
                warning = (
                    "Velospot liefert Reichweite als Km-Potenzial. "
                    "Für den Filter wird konservativ der untere Km-Bereich verwendet."
                )
        elif mode == "bike":
            if candidate.normal_bikes <= 0:
                continue
            range_filter_available = bool(_ebike_battery_levels(candidate.station))
            available_reason = "Normales Bike verfügbar"
        else:
            qualifies, range_filter_available, warning, available_reason = _availability_for_station(candidate, min_range)
            if not qualifies:
                continue

        if available_reason:
            candidate = PubliBikeStationData(
                station=candidate.station,
                total_bikes=candidate.total_bikes,
                ebikes=candidate.ebikes,
                normal_bikes=candidate.normal_bikes,
                free_spaces=candidate.free_spaces,
                status=candidate.status,
                meta={**candidate.meta, ATTR_AVAILABLE_REASON: available_reason},
            )

        walking_distance, walking_time = _walking_estimates(distance_air)
        return PubliBikeNearestStationData(
            station_data=candidate,
            distance_air_m=distance_air,
            walking_distance_estimate_m=walking_distance,
            walking_time_estimate_min=walking_time,
            range_filter_available=range_filter_available,
            min_range=min_range,
            warning=warning,
        )

    return None


async def geocode_address(hass: HomeAssistant, address: str) -> dict[str, Any] | None:
    """Geocode a Swiss address with geo.admin.ch and return lat/lon."""
    session = async_get_clientsession(hass)
    params = {
        "searchText": address,
        "type": "locations",
        "origins": "address,zipcode,gg25",
        "limit": "1",
        "sr": "4326",
    }
    async with async_timeout.timeout(DEFAULT_TIMEOUT):
        response = await session.get(GEOCODE_URL, params=params, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = await response.json(content_type=None)

    results = payload.get("results") if isinstance(payload, dict) else None
    if not results:
        return None

    attrs = (results[0] or {}).get("attrs") or {}
    lat = attrs.get("lat") or attrs.get("latitude")
    lon = attrs.get("lon") or attrs.get("lng") or attrs.get("longitude")

    # GeoAdmin commonly returns x/y. With sr=4326, x is longitude and y is latitude.
    if lat is None or lon is None:
        x = _as_float(attrs.get("x"))
        y = _as_float(attrs.get("y"))
        if x is not None and y is not None:
            lon, lat = x, y

    lat_f = _as_float(lat)
    lon_f = _as_float(lon)
    if lat_f is None or lon_f is None:
        return None

    # Safety: if values look swapped for Switzerland, swap them.
    if 5 <= lat_f <= 11 and 45 <= lon_f <= 48:
        lat_f, lon_f = lon_f, lat_f

    label = attrs.get("label") or attrs.get("detail") or address
    return {
        "latitude": lat_f,
        "longitude": lon_f,
        "label": _clean_text(re.sub(r"<[^>]+>", "", str(label))),
        "source": "geo.admin.ch",
    }


async def _fetch_json(session: Any, url: str) -> Any:
    """Fetch JSON with timeout."""
    async with async_timeout.timeout(DEFAULT_TIMEOUT):
        response = await session.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        return await response.json(content_type=None)


async def _fetch_all_stations(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Fetch all station options for the config flow and coordinator."""
    session = async_get_clientsession(hass)

    try:
        payload = await _fetch_json(session, API_ALL_STATIONS)
        stations = _extract_station_lists(payload)
        if stations:
            return stations
    except Exception:  # noqa: BLE001
        pass

    try:
        payload = await _fetch_json(session, API_PARTNER_STATIONS)
        if isinstance(payload, dict):
            stations = [_normalize_old_publibike_station(s) for s in payload.get("stations") or [] if isinstance(s, dict)]
            if stations:
                return stations
    except Exception:  # noqa: BLE001
        pass

    try:
        payload = await _fetch_json(session, API_STATIONS)
        if isinstance(payload, list):
            return [_normalize_old_publibike_station(s) for s in payload if isinstance(s, dict)]
    except Exception:  # noqa: BLE001
        pass

    return []


async def fetch_station_catalog(hass: HomeAssistant) -> dict[str, dict[str, str]]:
    """Return station options grouped by city."""
    stations = await _fetch_all_stations(hass)
    catalog: dict[str, dict[str, str]] = {}
    for station in stations:
        station_id = station.get("id")
        if station_id is None:
            continue
        city = _clean_text(station.get("city") or "Unbekannt")
        catalog.setdefault(city, {})[str(station_id)] = station_label(station)

    return {
        city: dict(sorted(stations_for_city.items(), key=lambda item: item[1].lower()))
        for city, stations_for_city in sorted(catalog.items(), key=lambda item: item[0].lower())
    }


class PubliBikeDataUpdateCoordinator(DataUpdateCoordinator[PubliBikeData]):
    """Class to manage fetching PubliBike station data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        self.entry = entry
        self.session = async_get_clientsession(hass)
        interval = entry.options.get(CONF_UPDATE_INTERVAL, entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        interval = max(_as_int(interval, DEFAULT_UPDATE_INTERVAL), MIN_UPDATE_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=interval),
        )

    @property
    def update_seconds(self) -> int:
        """Return update interval in seconds."""
        interval = self.entry.options.get(CONF_UPDATE_INTERVAL, self.entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))
        return max(_as_int(interval, DEFAULT_UPDATE_INTERVAL), MIN_UPDATE_INTERVAL)

    @property
    def reference_type(self) -> str:
        """Return reference type."""
        return str(self.entry.options.get(CONF_REFERENCE_TYPE, self.entry.data.get(CONF_REFERENCE_TYPE, REFERENCE_TYPE_STATION)))

    @property
    def city(self) -> str | None:
        """Return selected city filter."""
        return self.entry.options.get(CONF_CITY, self.entry.data.get(CONF_CITY))

    @property
    def min_ebike_battery(self) -> int:
        """Return minimum e-bike range threshold."""
        value = self.entry.options.get(
            CONF_MIN_EBIKE_BATTERY,
            self.entry.data.get(CONF_MIN_EBIKE_BATTERY, DEFAULT_MIN_EBIKE_BATTERY),
        )
        return max(0, min(_as_int(value, DEFAULT_MIN_EBIKE_BATTERY), 200))

    async def _async_update_data(self) -> PubliBikeData:
        """Update data via new PubliBike / Velospot API, with old fallbacks."""
        errors: list[str] = []
        min_range = self.min_ebike_battery
        interval = self.update_seconds
        # DataUpdateCoordinator reads the interval when scheduled. Keep it in sync after options changes/reload.
        self.update_interval = timedelta(seconds=interval)

        try:
            payload = await _fetch_json(self.session, API_ALL_STATIONS)
            stations = _extract_station_lists(payload)
            meta = {
                ATTR_API_MODE: "new_all_stations",
                ATTR_SOURCE_ENDPOINT: API_ALL_STATIONS,
                ATTR_RAW_STATION_COUNT: len(stations),
                ATTR_MIN_EBIKE_BATTERY: min_range, ATTR_MIN_EBIKE_RANGE_KM: min_range,
                ATTR_UPDATE_INTERVAL: interval,
                ATTR_LAST_UPDATE: dt_util.utcnow().isoformat(),
            }
            if stations:
                location = await self._build_location(stations, meta)
                nearest_ebike = await _find_nearest(
                    self.session,
                    location.latitude,
                    location.longitude,
                    stations,
                    self.city,
                    min_range,
                    meta,
                    "ebike",
                )
                nearest_bike = await _find_nearest(
                    self.session,
                    location.latitude,
                    location.longitude,
                    stations,
                    self.city,
                    min_range,
                    meta,
                    "bike",
                )
                nearest_available = await _find_nearest(
                    self.session,
                    location.latitude,
                    location.longitude,
                    stations,
                    self.city,
                    min_range,
                    meta,
                    "available",
                )
                return PubliBikeData(
                    location=location,
                    nearest_ebike=nearest_ebike,
                    nearest_bike=nearest_bike,
                    nearest_available=nearest_available,
                    all_station_count=len(stations),
                    meta=meta,
                )
            errors.append("new_all_stations: no stations returned")
        except Exception as err:  # noqa: BLE001
            errors.append(f"new_all_stations: {err}")

        # Old fallback: all stations including vehicles.
        try:
            payload = await _fetch_json(self.session, API_PARTNER_STATIONS)
            raw_stations = payload.get("stations", []) if isinstance(payload, dict) else []
            stations = [_normalize_old_publibike_station(station) for station in raw_stations if isinstance(station, dict)]
            meta = {
                ATTR_API_MODE: "old_partner_stations_fallback",
                ATTR_SOURCE_ENDPOINT: API_PARTNER_STATIONS,
                ATTR_RAW_STATION_COUNT: len(stations),
                ATTR_MIN_EBIKE_BATTERY: min_range, ATTR_MIN_EBIKE_RANGE_KM: min_range,
                ATTR_UPDATE_INTERVAL: interval,
                ATTR_LAST_UPDATE: dt_util.utcnow().isoformat(),
            }
            if stations:
                location = await self._build_location(stations, meta)
                nearest_ebike = await _find_nearest(self.session, location.latitude, location.longitude, stations, self.city, min_range, meta, "ebike")
                nearest_bike = await _find_nearest(self.session, location.latitude, location.longitude, stations, self.city, min_range, meta, "bike")
                nearest_available = await _find_nearest(self.session, location.latitude, location.longitude, stations, self.city, min_range, meta, "available")
                return PubliBikeData(location=location, nearest_ebike=nearest_ebike, nearest_bike=nearest_bike, nearest_available=nearest_available, all_station_count=len(stations), meta=meta)
            errors.append("old_partner_stations: no stations returned")
        except Exception as err:  # noqa: BLE001
            errors.append(f"old_partner_stations: {err}")

        # Old detail fallback only for selected old station entries.
        if self.reference_type == REFERENCE_TYPE_STATION:
            station_id = str(self.entry.options.get(CONF_STATION_ID, self.entry.data.get(CONF_STATION_ID, "")))
            detail_url = API_STATION_DETAIL.format(station_id=station_id)
            try:
                station = await _fetch_json(self.session, detail_url)
                if isinstance(station, dict) and station.get("id"):
                    meta = {
                        ATTR_API_MODE: "old_station_detail_fallback",
                        ATTR_SOURCE_ENDPOINT: detail_url,
                        ATTR_RAW_STATION_COUNT: 1,
                        ATTR_MIN_EBIKE_BATTERY: min_range, ATTR_MIN_EBIKE_RANGE_KM: min_range,
                        ATTR_UPDATE_INTERVAL: interval,
                        ATTR_LAST_UPDATE: dt_util.utcnow().isoformat(),
                    }
                    parsed = parse_station_data(_normalize_old_publibike_station(station), meta)
                    location = PubliBikeLocationData(
                        name=_station_name(parsed.station),
                        reference_type=REFERENCE_TYPE_STATION,
                        latitude=_as_float(parsed.station.get("latitude")),
                        longitude=_as_float(parsed.station.get("longitude")),
                        city=parsed.station.get("city"),
                        address=parsed.station.get("address"),
                        selected_station=parsed,
                        meta={**meta, ATTR_LAST_UPDATE: dt_util.utcnow().isoformat()},
                    )
                    return PubliBikeData(location=location, nearest_ebike=None, nearest_bike=None, nearest_available=None, all_station_count=1, meta=meta)
                errors.append("old_station_detail: response is empty or invalid")
            except Exception as err:  # noqa: BLE001
                errors.append(f"old_station_detail: {err}")

        raise UpdateFailed("PubliBike update failed: " + " | ".join(errors))

    async def _build_location(self, stations: list[dict[str, Any]], meta: dict[str, Any]) -> PubliBikeLocationData:
        """Build the configured reference location from station or address/coordinates."""
        reference_type = self.reference_type
        city = self.city
        location_name = self.entry.options.get(CONF_LOCATION_NAME, self.entry.data.get(CONF_LOCATION_NAME))
        address = self.entry.options.get(CONF_ADDRESS, self.entry.data.get(CONF_ADDRESS))
        geocode_source = self.entry.options.get(ATTR_GEOCODE_SOURCE, self.entry.data.get(ATTR_GEOCODE_SOURCE))

        if reference_type == REFERENCE_TYPE_STATION:
            station_id = str(self.entry.options.get(CONF_STATION_ID, self.entry.data.get(CONF_STATION_ID, "")))
            for station in stations:
                if _station_matches(station, station_id):
                    station = await _enrich_velospot_station_detail(self.session, station)
                    selected = parse_station_data(station, meta)
                    return PubliBikeLocationData(
                        name=location_name or _station_name(station),
                        reference_type=REFERENCE_TYPE_STATION,
                        latitude=_as_float(station.get("latitude")),
                        longitude=_as_float(station.get("longitude")),
                        city=station.get("city") or city,
                        address=station.get("address"),
                        selected_station=selected,
                        meta={**meta, ATTR_GEOCODE_SOURCE: geocode_source, ATTR_LAST_UPDATE: dt_util.utcnow().isoformat()},
                    )
            raise UpdateFailed(f"configured station not found: {station_id}")

        lat = _as_float(self.entry.options.get(CONF_LATITUDE, self.entry.data.get(CONF_LATITUDE)))
        lon = _as_float(self.entry.options.get(CONF_LONGITUDE, self.entry.data.get(CONF_LONGITUDE)))
        return PubliBikeLocationData(
            name=location_name or address or "PubliBike Standort",
            reference_type=REFERENCE_TYPE_ADDRESS,
            latitude=lat,
            longitude=lon,
            city=city,
            address=address,
            selected_station=None,
            meta={**meta, ATTR_GEOCODE_SOURCE: geocode_source, ATTR_LAST_UPDATE: dt_util.utcnow().isoformat()},
        )
