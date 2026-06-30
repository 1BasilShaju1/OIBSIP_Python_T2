

from __future__ import annotations

import dataclasses
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional, Tuple

try:
    import requests
    from requests.exceptions import ConnectionError as ReqConnectionError, Timeout as ReqTimeout
except ImportError:
    requests = None  
    ReqConnectionError = ReqTimeout = Exception 

# ─── Configuration ────────────────────────────────────────────────────────────
API_KEY      = os.getenv("OWM_API_KEY", "")      
OWM_BASE     = "https://api.openweathermap.org/data/2.5"
OWM_GEO_BASE = "https://api.openweathermap.org/geo/1.0"
DEFAULT_CITY = "Thrissur"

AQI_LABELS  = ("Good", "Fair", "Moderate", "Poor", "Very Poor")


_BEAUFORT = (
    (1,   "Calm"),          (5,   "Light Air"),      (11,  "Light Breeze"),
    (19,  "Gentle Breeze"), (28,  "Moderate Breeze"), (38,  "Fresh Breeze"),
    (49,  "Strong Breeze"), (61,  "Near Gale"),       (74,  "Gale"),
    (88,  "Strong Gale"),   (102, "Storm"),            (117, "Violent Storm"),
)
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# UV 
_UV_CATS = (
    "Low", "Low", "Low",
    "Moderate", "Moderate", "Moderate",
    "High", "High",
    "Very High", "Very High", "Very High",
    "Extreme",
)


_TIME_FMT = "%#H:%M" if sys.platform == "win32" else "%-H:%M"


# ─── Error handling 
class ErrorCode(Enum):
    NO_REQUESTS    = "no_requests"
    NO_API_KEY     = "no_api_key"
    INVALID_KEY    = "invalid_key"
    CITY_NOT_FOUND = "city_not_found"
    NETWORK        = "network"
    EMPTY_INPUT    = "empty_input"
    INVALID_INPUT  = "invalid_input"
    UNKNOWN        = "unknown"


class WeatherError(Exception):
    def __init__(self, code: ErrorCode, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code    = code
        self.message = message
        self.hint    = hint


# ─── Data classes 
@dataclass
class CityResult:
    name:    str
    country: str
    lat:     float
    lon:     float
    state:   str = ""

    def display(self) -> str:
        parts = [self.name]
        if self.state:
            parts.append(self.state)
        parts.append(self.country)
        return ", ".join(parts)

    def query(self) -> str:
        return f"{self.name},{self.country}"


@dataclass
class HourSlot:
    time:   str
    temp:   float
    kind:   str
    period: str = ""


@dataclass
class DayForecast:
    day:  str
    date: str
    low:  float
    high: float
    desc: str
    kind: str


@dataclass
class WeatherData:
    city:          str   = "Demo City"
    country:       str   = "IN"
    lat:           float = 0.0
    lon:           float = 0.0
    temp:          float = 28.0
    feels_like:    float = 35.0
    temp_min:      float = 26.0
    temp_max:      float = 32.0
    unit_symbol:   str   = "°C"
    description:   str   = "Partly Cloudy"
    kind:          str   = "partly"
    sunrise:       str   = "06:19"
    sunset:        str   = "18:42"
    day_length:    str   = "12h 23m"
    wind_speed:    float = 14.0
    wind_deg:      float = 225.0
    wind_unit:     str   = "km/h"
    humidity:      float = 78.0
    dew_point:     float = 23.0
    pressure:      float = 1005.0
    visibility:    float = 6.0
    cloud_cover:   float = 40.0
    uv_index:      float = 10.0
    aqi:           int   = 2
    precipitation: float = 30.0
    hourly:        List[HourSlot]    = field(default_factory=list)
    daily:         List[DayForecast] = field(default_factory=list)
    timestamp:     str   = ""
    local_time_hm: str   = ""   #
    status:        str   = ""


# ───  conversion functions 
def weather_kind(cid: int, icon: str = "") -> str:
    """Map an OWM condition id (and optional icon code) to an internal kind string."""
    if 200 <= cid < 300: return "storm"
    if 300 <= cid < 600: return "rain"
    if 600 <= cid < 700: return "snow"
    if 700 <= cid < 800: return "fog"
    if cid == 800:       return "moon" if icon.endswith("n") else "sun"
    if cid == 801:       return "partly"
    return "cloud"


def uv_category(index: float) -> str:
    return _UV_CATS[min(int(index), 11)]


def beaufort(kmh: float) -> str:
    for limit, label in _BEAUFORT:
        if kmh < limit:
            return label
    return "Hurricane"


def deg_to_compass(deg: float) -> str:
    return _COMPASS[int((deg + 22.5) / 45) % 8]


def visibility_label(km: float) -> str:
    if km > 10: return "Excellent"
    if km > 5:  return "Good"
    if km > 2:  return "Moderate"
    return "Poor"


def aqi_label(aqi: int) -> str:
    return AQI_LABELS[max(0, min(aqi - 1, 4))]


# Unit conversion
def ms_to_kmh(ms: float)  -> float: return ms * 3.6
def hpa_to_mmhg(hpa: float) -> int: return round(hpa * 0.750062)
def c_to_f(c: float)      -> float: return c * 9 / 5 + 32
def f_to_c(f: float)      -> float: return (f - 32) * 5 / 9
def kmh_to_mph(k: float)  -> float: return k * 0.621371
def mph_to_kmh(m: float)  -> float: return m / 0.621371


# ─── Validation
_CITY_RE    = re.compile(r"^[A-Za-z\u00C0-\u024F\u0400-\u04FF'\-\s,\.]{1,100}$")
_STRIP_PUNC = re.compile(r"^[^\w\u00C0-\u024F\u0400-\u04FF]+|[^\w\u00C0-\u024F\u0400-\u04FF]+$")
_HAS_LETTER = re.compile(r"[A-Za-z\u00C0-\u024F\u0400-\u04FF]")
_MULTI_WS   = re.compile(r"\s{2,}")

_ERR_EMPTY  = WeatherError(ErrorCode.EMPTY_INPUT, "City name cannot be empty.",
                            "Type a city name like 'Thrissur' or 'London'.")
_ERR_LONG   = WeatherError(ErrorCode.INVALID_INPUT, "City name too long (max 100 chars).")
_ERR_LETTER = WeatherError(ErrorCode.INVALID_INPUT, "Must contain at least one letter.")


def validate_city_input(raw: str) -> Tuple[bool, str, Optional[WeatherError]]:
    """
    Cleans and validates a raw city-name string.
    Returns (ok, cleaned_name, error_or_None).
    """
    s = raw.strip()
    if not s:
        return False, "", _ERR_EMPTY

   
    s = _STRIP_PUNC.sub("", s).strip()
    if not s:
        return False, "", _ERR_EMPTY

    if len(s) > 100:
        return False, "", _ERR_LONG

    cleaned = _MULTI_WS.sub(" ", s)

    if not _CITY_RE.match(cleaned):
        return False, "", WeatherError(
            ErrorCode.INVALID_INPUT,
            f"'{cleaned}' has invalid characters.",
            "Use letters, spaces, hyphens or apostrophes only.",
        )

    if not _HAS_LETTER.search(cleaned):
        return False, "", _ERR_LETTER

    return True, cleaned, None


# ─── City search ──────────────────────────────────────────────────────────────
def search_cities(query: str, limit: int = 8) -> List[CityResult]:
    """Geo-search via OWM. Returns up to *limit* de-duplicated CityResult objects."""
    ok, clean, err = validate_city_input(query)
    if not ok:
        raise err

    if requests is None:
        raise WeatherError(ErrorCode.NO_REQUESTS, "requests not installed.", "pip install requests")
    if not API_KEY:
        raise WeatherError(ErrorCode.NO_API_KEY, "OWM_API_KEY not set.")

    try:
        resp = requests.get(
            f"{OWM_GEO_BASE}/direct",
            params={"q": clean, "limit": max(1, min(limit, 10)), "appid": API_KEY},
            timeout=8,
        )
    except ReqTimeout:
        raise WeatherError(ErrorCode.NETWORK, "Search timed out.")
    except ReqConnectionError:
        raise WeatherError(ErrorCode.NETWORK, "No internet connection.")

    if resp.status_code == 401:
        raise WeatherError(ErrorCode.INVALID_KEY, "Invalid API key.")
    resp.raise_for_status()

    results: List[CityResult] = []
    seen: set = set()
    for item in resp.json():
        key = (
            item.get("name", "").lower(),
            item.get("country", "").lower(),
            round(item.get("lat", 0), 1),
            round(item.get("lon", 0), 1),
        )
        if key in seen:
            continue
        seen.add(key)
        results.append(CityResult(
            name    = item.get("name", ""),
            country = item.get("country", ""),
            state   = item.get("state", ""),
            lat     = item.get("lat", 0),
            lon     = item.get("lon", 0),
        ))
    return results


# ─── IP geolocation 
def get_location_by_ip() -> Optional[CityResult]:
    if requests is None:
        return None
    try:
        r = requests.get(
            "http://ip-api.com/json/",
            params={"fields": "status,city,regionName,countryCode,lat,lon"},
            timeout=5,
        )
        d = r.json()
        if d.get("status") != "success":
            return None
        return CityResult(
            name    = d.get("city", ""),
            country = d.get("countryCode", ""),
            state   = d.get("regionName", ""),
            lat     = d.get("lat", 0),
            lon     = d.get("lon", 0),
        )
    except Exception:
        return None


# ─── Unit converter 
class UnitConverter:
    """Converts a WeatherData snapshot between metric and imperial units."""

    @staticmethod
    def to_imperial(d: WeatherData) -> WeatherData:
        if d.unit_symbol == "°F":
            return d
        r1 = lambda v: round(c_to_f(v), 1)
        r2 = lambda v: round(kmh_to_mph(v), 1)
        return dataclasses.replace(
            d,
            temp=r1(d.temp), feels_like=r1(d.feels_like),
            temp_min=r1(d.temp_min), temp_max=r1(d.temp_max),
            dew_point=r1(d.dew_point), unit_symbol="°F",
            wind_speed=r2(d.wind_speed), wind_unit="mph",
            hourly=[dataclasses.replace(h, temp=r1(h.temp)) for h in d.hourly],
            daily =[dataclasses.replace(dy, low=r1(dy.low), high=r1(dy.high)) for dy in d.daily],
        )

    @staticmethod
    def to_metric(d: WeatherData) -> WeatherData:
        if d.unit_symbol == "°C":
            return d
        r1 = lambda v: round(f_to_c(v), 1)
        r2 = lambda v: round(mph_to_kmh(v), 1)
        return dataclasses.replace(
            d,
            temp=r1(d.temp), feels_like=r1(d.feels_like),
            temp_min=r1(d.temp_min), temp_max=r1(d.temp_max),
            dew_point=r1(d.dew_point), unit_symbol="°C",
            wind_speed=r2(d.wind_speed), wind_unit="km/h",
            hourly=[dataclasses.replace(h, temp=r1(h.temp)) for h in d.hourly],
            daily =[dataclasses.replace(dy, low=r1(dy.low), high=r1(dy.high)) for dy in d.daily],
        )

    @staticmethod
    def convert(d: WeatherData, target: str) -> WeatherData:
        if target == "imperial": return UnitConverter.to_imperial(d)
        if target == "metric":   return UnitConverter.to_metric(d)
        raise ValueError(f"Unknown unit target {target!r}")


# ─── Demo 
def _sample_data(unit: str = "metric") -> WeatherData:
    """Returns a static snapshot used when no API key is available."""
    metric = unit == "metric"
    sym    = "°C" if metric else "°F"
    wu     = "km/h" if metric else "mph"
    ct     = lambda v: v if metric else round(c_to_f(v))

    hourly = [
        HourSlot("20:30", ct(27), "cloud",  "EVENING"),
        HourSlot("23:30", ct(26), "cloud",  ""),
        HourSlot("02:30", ct(25), "rain",   "NIGHT"),
        HourSlot("05:30", ct(25), "rain",   ""),
        HourSlot("08:30", ct(27), "partly", "MORNING"),
        HourSlot("11:30", ct(30), "sun",    ""),
        HourSlot("14:30", ct(32), "sun",    "DAY"),
        HourSlot("17:30", ct(30), "partly", ""),
        HourSlot("20:30", ct(28), "cloud",  "EVENING"),
        HourSlot("23:30", ct(27), "rain",   ""),
        HourSlot("02:30", ct(26), "rain",   "NIGHT"),
        HourSlot("05:30", ct(26), "rain",   ""),
    ]
    daily = [
        DayForecast("Sun", "28 Jun", ct(25), ct(32), "Partly Cloudy", "partly"),
        DayForecast("Mon", "29 Jun", ct(25), ct(31), "Moderate Rain",  "rain"),
        DayForecast("Tue", "30 Jun", ct(24), ct(30), "Heavy Rain",     "rain"),
        DayForecast("Wed", "01 Jul", ct(24), ct(29), "Thunderstorm",   "storm"),
        DayForecast("Thu", "02 Jul", ct(25), ct(31), "Light Rain",     "rain"),
        DayForecast("Fri", "03 Jul", ct(25), ct(32), "Partly Cloudy", "partly"),
        DayForecast("Sat", "04 Jul", ct(26), ct(33), "Sunny",          "sun"),
    ]
    return WeatherData(
        city="Thrissur", country="IN", lat=10.5276, lon=76.2144,
        temp=ct(28), feels_like=ct(35), temp_min=ct(25), temp_max=ct(33),
        unit_symbol=sym, description="Partly Cloudy", kind="partly",
        sunrise="06:19", sunset="18:42", day_length="12h 23m",
        wind_speed=14 if metric else round(kmh_to_mph(14)),
        wind_deg=225.0, wind_unit=wu,
        humidity=78, dew_point=ct(23), pressure=1005,
        visibility=6.0, cloud_cover=40, uv_index=10.0,
        aqi=2, precipitation=30,
        hourly=hourly, daily=daily,
        timestamp=datetime.now().strftime("%d %b %Y  %I:%M %p"),
        local_time_hm=datetime.now().strftime("%H:%M"),
        status="DEMO — set OWM_API_KEY for live data",
    )


# ─── Internal helpers for fetch_weather ───────────────────────────────────────
def _make_tz(seconds: int) -> timezone:
    return timezone(timedelta(seconds=seconds))


def _build_hourly(fore_list: list, fore_tz: timezone) -> List[HourSlot]:
    """Extract up to 12 hourly slots from the OWM /forecast response."""
    # Period labels cycle every 2 slots (each slot = 3 h)
    period_map = {0: "EVENING", 2: "NIGHT", 4: "MORNING", 6: "DAY", 8: "EVENING", 10: "NIGHT"}
    slots: List[HourSlot] = []
    for idx, item in enumerate(fore_list[:12]):
        dt = datetime.fromtimestamp(item["dt"], tz=fore_tz)
        iw = item["weather"][0]
        slots.append(HourSlot(
            time   = dt.strftime(_TIME_FMT),
            temp   = round(item["main"]["temp"]),
            kind   = weather_kind(iw["id"], iw.get("icon", "")),
            period = period_map.get(idx, ""),
        ))
    return slots


def _build_daily(fore_list: list, fore_tz: timezone, unit: str,
                 fallback_fn) -> List[DayForecast]:
    """
    Group 3-hourly forecast slots into daily cards.
    Pads to 7 days using fallback_fn if OWM returned fewer.
    """
    grouped: dict = {}
    for item in fore_list:
        dt  = datetime.fromtimestamp(item["dt"], tz=fore_tz)
        key = dt.date().isoformat()
        iw  = item["weather"][0]
        bucket = grouped.setdefault(key, {
            "day":   dt.strftime("%a"),
            "date":  dt.strftime("%d %b"),
            "temps": [],
            "desc":  iw["description"].capitalize(),
            "kind":  weather_kind(iw["id"], iw.get("icon", "")),
        })
        bucket["temps"].append(item["main"]["temp"])

    daily = [
        DayForecast(
            day  = b["day"],
            date = b["date"],
            low  = round(min(b["temps"])),
            high = round(max(b["temps"])),
            desc = b["desc"],
            kind = b["kind"],
        )
        for b in list(grouped.values())[:7]
    ]

    if len(daily) < 7:
        daily.extend(fallback_fn(unit).daily[len(daily):7])
    return daily


# ─── Live API fetch ───────────────────────────────────────────────────────────
def fetch_weather(city: str, unit: str = "metric") -> WeatherData:
    """
    Fetch current conditions + forecast for *city*.
    Raises WeatherError on any failure.
    """
    ok, clean, err = validate_city_input(city)
    if not ok:
        raise err  # type: ignore[misc]

    if requests is None:
        raise WeatherError(ErrorCode.NO_REQUESTS, "requests not installed.", "pip install requests")
    if not API_KEY:
        raise WeatherError(ErrorCode.NO_API_KEY, "OWM_API_KEY not set.")

    sym = "°C" if unit == "metric" else "°F"
    wu  = "km/h" if unit == "metric" else "mph"

    # ── Current conditions ────────────────────────────────────────────────────
    try:
        cur_r = requests.get(
            f"{OWM_BASE}/weather",
            params={"q": clean, "appid": API_KEY, "units": unit},
            timeout=10,
        )
    except ReqTimeout:
        raise WeatherError(ErrorCode.NETWORK, "Request timed out.")
    except ReqConnectionError:
        raise WeatherError(ErrorCode.NETWORK, "No internet connection.")

    if cur_r.status_code == 401:
        raise WeatherError(ErrorCode.INVALID_KEY, "Invalid API key.")
    if cur_r.status_code == 404:
        raise WeatherError(ErrorCode.CITY_NOT_FOUND, f"'{clean}' not found.")
    cur_r.raise_for_status()
    cur = cur_r.json()

    # ── Forecast (best-effort; degrade gracefully) ────────────────────────────
    try:
        fore_r = requests.get(
            f"{OWM_BASE}/forecast",
            params={"q": clean, "appid": API_KEY, "units": unit, "cnt": 40},
            timeout=10,
        )
        fore_r.raise_for_status()
        fore = fore_r.json()
    except Exception:
        fore = {"list": [], "city": {}}

    # ── Parse shared fields ───────────────────────────────────────────────────
    tz_off  = cur.get("timezone", 0)
    tz      = _make_tz(tz_off)
    now     = datetime.now(tz=tz)
    w       = cur["weather"][0]
    wind    = cur.get("wind", {})
    spd_raw = wind.get("speed", 0)

    sr = datetime.fromtimestamp(cur["sys"]["sunrise"], tz=tz)
    ss = datetime.fromtimestamp(cur["sys"]["sunset"],  tz=tz)
    day_total_min = (ss - sr).seconds // 60
    dlh, dlm = divmod(day_total_min, 60)

    fore_list = fore.get("list", [])
    fore_tz   = _make_tz(fore.get("city", {}).get("timezone", tz_off))

    hourly = _build_hourly(fore_list, fore_tz)
    daily  = _build_daily(fore_list, fore_tz, unit, _sample_data)

    pop = round((fore_list[0].get("pop", 0) or 0) * 100) if fore_list else 0
    # Approximate dew point: temp_min - 2°  (good enough without one-call API)
    dew = round(cur["main"].get("temp_min", cur["main"]["temp"]) - 2)

    return WeatherData(
        city          = cur.get("name", clean),
        country       = cur.get("sys", {}).get("country", ""),
        lat           = cur.get("coord", {}).get("lat", 0),
        lon           = cur.get("coord", {}).get("lon", 0),
        temp          = round(cur["main"]["temp"]),
        feels_like    = round(cur["main"]["feels_like"]),
        temp_min      = round(cur["main"]["temp_min"]),
        temp_max      = round(cur["main"]["temp_max"]),
        unit_symbol   = sym,
        description   = w["description"].capitalize(),
        kind          = weather_kind(w["id"], w.get("icon", "")),
        sunrise       = sr.strftime(_TIME_FMT),
        sunset        = ss.strftime(_TIME_FMT),
        day_length    = f"{dlh}h {dlm:02d}m",
        wind_speed    = round(ms_to_kmh(spd_raw)) if unit == "metric" else round(spd_raw),
        wind_deg      = wind.get("deg", 0),
        wind_unit     = wu,
        humidity      = cur["main"]["humidity"],
        dew_point     = dew,
        pressure      = cur["main"]["pressure"],
        visibility    = round(cur.get("visibility", 6000) / 1000, 1),
        cloud_cover   = cur.get("clouds", {}).get("all", 0),
        uv_index      = 0.0,   # requires One Call API
        aqi           = 1,     # requires Air Pollution API
        precipitation = pop,
        hourly        = hourly,
        daily         = daily,
        timestamp     = now.strftime("%d %b %Y  %I:%M %p"),
        local_time_hm = now.strftime("%H:%M"),
        status        = "",
    )