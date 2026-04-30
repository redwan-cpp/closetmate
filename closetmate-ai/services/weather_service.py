"""
Weather service for ClosetMate AI.

Uses Open-Meteo (https://open-meteo.com/) — completely FREE, no API key needed.
Also uses Nominatim geocoding to turn city names into lat/lon.

Functions:
  get_weather_by_coords(lat, lon)   → WeatherData
  get_weather_by_city(city_name)    → WeatherData
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional
import urllib.request
import urllib.parse
import json

log = logging.getLogger(__name__)


@dataclass
class WeatherData:
    city:           str
    country:        str
    temperature:    float   # °C
    feels_like:     float   # °C
    humidity:       int     # %
    wind_speed:     float   # km/h
    condition:      str     # "Clear", "Cloudy", "Rain", etc.
    condition_icon: str     # emoji
    uv_index:       float
    is_day:         bool


def _emoji_for_condition(wmo_code: int, is_day: bool) -> tuple[str, str]:
    """Map WMO weather code to human label + emoji."""
    # https://open-meteo.com/en/docs#weathervariables
    if wmo_code == 0:
        return ("Clear sky", "☀️" if is_day else "🌙")
    elif wmo_code in (1, 2):
        return ("Partly cloudy", "⛅")
    elif wmo_code == 3:
        return ("Overcast", "☁️")
    elif wmo_code in (45, 48):
        return ("Foggy", "🌫️")
    elif wmo_code in (51, 53, 55):
        return ("Drizzle", "🌦️")
    elif wmo_code in (61, 63, 65):
        return ("Rain", "🌧️")
    elif wmo_code in (71, 73, 75, 77):
        return ("Snow", "❄️")
    elif wmo_code in (80, 81, 82):
        return ("Rain showers", "🌧️")
    elif wmo_code in (85, 86):
        return ("Snow showers", "🌨️")
    elif wmo_code in (95, 96, 99):
        return ("Thunderstorm", "⛈️")
    else:
        return ("Unknown", "🌡️")


def _http_get_json(url: str, timeout: int = 8) -> dict:
    """Simple synchronous HTTP GET returning parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "ClosetMate/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def get_weather_by_coords(lat: float, lon: float, city_hint: str = "") -> WeatherData:
    """
    Fetch current weather for a lat/lon coordinate using Open-Meteo.
    """
    params = {
        "latitude":           lat,
        "longitude":          lon,
        "current":            ",".join([
            "temperature_2m",
            "apparent_temperature",
            "relative_humidity_2m",
            "wind_speed_10m",
            "weather_code",
            "is_day",
            "uv_index",
        ]),
        "wind_speed_unit":    "kmh",
        "timezone":           "auto",
    }
    qs = urllib.parse.urlencode(params)
    url = f"https://api.open-meteo.com/v1/forecast?{qs}"
    log.info("Fetching weather: %s", url)

    data = _http_get_json(url)
    curr = data.get("current", {})

    wmo         = int(curr.get("weather_code", 0))
    is_day      = bool(curr.get("is_day", 1))
    condition, icon = _emoji_for_condition(wmo, is_day)

    return WeatherData(
        city=city_hint or f"{lat:.2f},{lon:.2f}",
        country="",
        temperature=float(curr.get("temperature_2m", 22)),
        feels_like=float(curr.get("apparent_temperature", 22)),
        humidity=int(curr.get("relative_humidity_2m", 60)),
        wind_speed=float(curr.get("wind_speed_10m", 0)),
        condition=condition,
        condition_icon=icon,
        uv_index=float(curr.get("uv_index", 0)),
        is_day=is_day,
    )


def get_weather_by_city(city_name: str) -> Optional[WeatherData]:
    """
    Geocode city_name with Nominatim, then fetch weather from Open-Meteo.
    Returns None if the city can't be found.
    """
    # Step 1: Geocode
    geo_params = urllib.parse.urlencode({
        "q":      city_name,
        "format": "json",
        "limit":  1,
    })
    geo_url = f"https://nominatim.openstreetmap.org/search?{geo_params}"
    log.info("Geocoding city: %s", city_name)

    try:
        geo_data = _http_get_json(geo_url)
    except Exception as exc:
        log.warning("Geocoding failed for %r: %s", city_name, exc)
        return None

    if not geo_data:
        log.warning("No geocoding result for city: %r", city_name)
        return None

    lat = float(geo_data[0]["lat"])
    lon = float(geo_data[0]["lon"])
    display_name = geo_data[0].get("display_name", city_name).split(",")[0]

    # Step 2: Weather
    try:
        return get_weather_by_coords(lat, lon, city_hint=display_name)
    except Exception as exc:
        log.warning("Weather fetch failed for %r (%.4f, %.4f): %s", city_name, lat, lon, exc)
        return None


def weather_to_context_string(w: WeatherData, environment: str) -> str:
    """
    Format WeatherData into a concise context string for the AI prompt.
    environment: "indoor" | "outdoor" | "both"
    """
    lines = [
        f"📍 Location: {w.city}",
        f"{w.condition_icon} Weather: {w.condition}",
        f"🌡️ Temperature: {w.temperature:.0f}°C (feels like {w.feels_like:.0f}°C)",
        f"💧 Humidity: {w.humidity}%",
        f"💨 Wind: {w.wind_speed:.0f} km/h",
    ]

    if w.uv_index >= 6:
        lines.append(f"☀️ UV Index: {w.uv_index:.0f} (High — sun protection advised)")
    elif w.uv_index >= 3:
        lines.append(f"🌤️ UV Index: {w.uv_index:.0f} (Moderate)")

    lines.append(f"🏠 Environment: {environment}")

    # Smart advisories
    advisories = []
    if w.temperature >= 35:
        advisories.append("extreme heat — ultra-lightweight & breathable fabrics only")
    elif w.temperature >= 30:
        advisories.append("hot — lightweight cotton, linen, chiffon preferred")
    elif w.temperature >= 20:
        advisories.append("warm & comfortable — most fabrics work")
    elif w.temperature >= 10:
        advisories.append("cool — consider light layering")
    elif w.temperature >= 0:
        advisories.append("cold — warm layers essential (wool, fleece)")
    else:
        advisories.append("very cold — heavy insulation required")

    if w.humidity >= 85:
        advisories.append("very humid/rainy — avoid white & light fabrics, prefer quick-dry")
    elif w.humidity >= 70:
        advisories.append("humid — breathable fabrics strongly preferred")

    if environment == "outdoor":
        if "Rain" in w.condition or "Drizzle" in w.condition or "Shower" in w.condition:
            advisories.append("RAIN — waterproof or rain-resistant layer recommended")
        if "Thunderstorm" in w.condition:
            advisories.append("STORM — indoor alternative strongly advised")
        if w.uv_index >= 6:
            advisories.append("high UV — cover-up fabrics or sun protection layer recommended")
        if w.wind_speed >= 30:
            advisories.append("windy — avoid loose/billowy fabrics")
    elif environment == "indoor":
        advisories.append("indoor setting — comfort & style balance; ignore wind/rain")

    if advisories:
        lines.append("⚠️ Style Advisories: " + "; ".join(advisories))

    return "\n".join(lines)
