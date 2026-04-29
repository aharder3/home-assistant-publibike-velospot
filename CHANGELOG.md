# Changelog

## 0.19.0

### Added
- API status attribute `last_update` for reliable dashboard display of the last successful refresh.

### Changed
- Manual refresh now updates the API status entity timestamp even when the status remains `OK`.
- Refresh timestamp is limited to the diagnostic API status sensor to avoid excessive history changes on all bike sensors.

## 0.18.0

- Shortened entity names.
- Added short suggested entity IDs such as `sensor.publibike_zuhause_ebike_tabelle`.
- Removed duplicate `PubliBike <location> PubliBike ... <location>` style names.
- Kept E-Bike table compact: `ID` and `Reichweite` only.
- Kept Bike table compact: `ID` only.
- Added GitHub/HACS-ready repository files.

## 0.17.0

- Switched E-Bike filtering from battery percent to range in kilometres.
- Added separate E-Bike and Bike tables.
