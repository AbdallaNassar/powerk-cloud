# Api.kt parses org.json explicitly by wire key; no model reflection or name-based
# deserialization is used, so model classes need no keep rules.
# AGP keeps manifest activities, widget receivers and TileService entry points.
# RemoteViews invokes Android framework setters only (no custom reflected methods).
