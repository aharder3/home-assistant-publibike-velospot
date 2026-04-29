# PubliBike / Velospot for Home Assistant

Custom Home Assistant integration for PubliBike / Velospot stations in Switzerland.

This integration can track either:

- a fixed PubliBike/Velospot station, or
- a custom address/coordinate and the nearest usable station from there.

It uses the current public Velospot endpoint:

```text
https://rest.publibike.ch/v1/public/all/stations
```

If available, the integration also follows the station `detailsRoute` to read vehicle tables. On current Velospot station detail pages, E-Bikes expose `Velo ID` and `Km-Potenzial` rather than an exact battery percentage. The integration therefore filters E-Bikes by minimum range in kilometres.

## Features

- Select city/area first, then station or address/coordinates.
- Track multiple locations by adding the integration multiple times.
- Find the nearest station with an E-Bike above a configurable minimum range.
- Find the nearest station with a normal bike.
- Separate E-Bike and Bike entities.
- E-Bike table with only `ID` and `Reichweite`.
- Bike table with only `ID`.
- Configurable update interval.
- Manual refresh button.
- Short entity names and short suggested entity IDs.

## Typical entities

For an address/location named `Zuhause`, new installs should create short object IDs such as:

```text
sensor.publibike_zuhause_standort
sensor.publibike_zuhause_naechstes_ebike
sensor.publibike_zuhause_ebike_entfernung
sensor.publibike_zuhause_ebikes
sensor.publibike_zuhause_ebike_tabelle
sensor.publibike_zuhause_naechstes_bike
sensor.publibike_zuhause_bike_entfernung
sensor.publibike_zuhause_normale_bikes
sensor.publibike_zuhause_bike_tabelle
button.publibike_zuhause_aktualisieren
```

For a fixed station named `Bahnhofstrasse`:

```text
sensor.publibike_Bahnhofstrasse_station
sensor.publibike_Bahnhofstrasse_ebikes
sensor.publibike_Bahnhofstrasse_ebike_tabelle
sensor.publibike_Bahnhofstrasse_normale_bikes
sensor.publibike_Bahnhofstrasse_bike_tabelle
button.publibike_Bahnhofstrasse_aktualisieren
```

If you upgraded from an older test version and still see long duplicated entity IDs, remove the PubliBike integration from Home Assistant, restart Home Assistant, and add it again.

## HACS installation

1. Add this repository as a custom repository in HACS.
2. Category: `Integration`.
3. Install `PubliBike`.
4. Restart Home Assistant.
5. Add the integration under **Settings → Devices & services → Add integration → PubliBike**.

## Manual installation

Copy the component folder to Home Assistant:

```text
custom_components/publibike
```

Restart Home Assistant and add the integration from the UI.

## Notes about battery and range

The old PubliBike API documented battery percentage via `ebike_battery_level`, but the currently usable Velospot public endpoint mainly exposes range information through station detail pages. Therefore this integration uses `Km-Potenzial` / range in kilometres for filtering.

## Version

`0.18.0`
