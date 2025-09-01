from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time
import requests

# --- Simple in-process TTL cache ---
@dataclass
class CacheItem:
    value: Any
    expire_at: float

class TTLCache:
    def __init__(self, ttl_seconds: int = 600, max_size: int = 256):
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._store: Dict[str, CacheItem] = {}

    def get(self, key: str):
        it = self._store.get(key)
        if not it:
            return None
        if it.expire_at < time.time():
            self._store.pop(key, None)
            return None
        return it.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        if len(self._store) >= self.max_size:
            self._store.pop(next(iter(self._store)))
        t = ttl if ttl is not None else self.ttl
        self._store[key] = CacheItem(value=value, expire_at=time.time() + t)

# --- Weather client (Open-Meteo) ---
ZH_WC = {
    0: "晴", 1: "多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "小雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    95: "雷阵雨", 96: "雷阵雨", 99: "雷阵雨",
}

def _desc(code: int) -> str:
    return ZH_WC.get(int(code), "天气不明")

class WeatherClient:
    def __init__(self, lang: str = "zh", session: Optional[requests.Session] = None):
        self.lang = lang
        self.sess = session or requests.Session()
        self.geo_cache = TTLCache(ttl_seconds=7*24*3600)   # 城市解析缓存 7 天
        self.wx_cache  = TTLCache(ttl_seconds=10*60)       # 天气缓存 10 分钟
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            retry = Retry(total=2, backoff_factor=0.2, status_forcelist=[429,500,502,503,504])
            adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
            self.sess.mount("https://", adapter); self.sess.mount("http://", adapter)
        except Exception:
            pass

    def geocode(self, city: str) -> Optional[Dict[str, Any]]:
        city = (city or "").strip()
        if not city:
            return None
        key = f"geo:{self.lang}:{city}"
        cached = self.geo_cache.get(key)
        if cached:
            return cached
        try:
            r = self.sess.get("https://geocoding-api.open-meteo.com/v1/search",
                              params={"name": city, "count": 1, "language": self.lang, "format": "json"},
                              timeout=5)
            r.raise_for_status()
            res = r.json().get("results") or []
            if not res:
                return None
            item = res[0]
            out = {
                "name": item.get("name") or city,
                "country": item.get("country") or "",
                "lat": float(item["latitude"]),
                "lon": float(item["longitude"]),
                "timezone": item.get("timezone") or "auto",
            }
            self.geo_cache.set(key, out)
            return out
        except Exception:
            return None

    def fetch(self, city: str, hours: int = 6, days: int = 1) -> Optional[Dict[str, Any]]:
        city = (city or "").strip()
        if not city:
            return None
        g = self.geocode(city)
        if not g:
            return None
        key = f"wx:{g['lat']:.3f},{g['lon']:.3f}:{hours}:{days}"
        cached = self.wx_cache.get(key)
        if cached:
            return cached
        try:
            params = {
                "latitude": g["lat"],
                "longitude": g["lon"],
                "current_weather": True,
                "hourly": "temperature_2m,apparent_temperature,precipitation_probability,weathercode",
                "daily": "weathercode,temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "forecast_days": max(1, min(3, int(days))),
            }
            r = self.sess.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=6)
            r.raise_for_status()
            data = r.json()
            out = {"geo": g, "raw": data}
            self.wx_cache.set(key, out)
            return out
        except Exception:
            return None

    def bubble_text(self, city: str, hours: int = 3) -> Optional[str]:
        pack = self.fetch(city, hours=max(1, min(12, hours)), days=1)
        if not pack:
            return None
        g = pack["geo"]; data = pack["raw"]
        cw = data.get("current_weather") or {}
        temp = cw.get("temperature")
        wind = cw.get("windspeed")
        code = cw.get("weathercode")
        desc = _desc(int(code or 0))
        name = g.get("name") or city
        h = data.get("hourly") or {}
        temps = h.get("temperature_2m") or []
        times = h.get("time") or []
        next_vals = []
        if temps and times:
            try:
                cur_iso = cw.get("time")
                idx = times.index(cur_iso) if cur_iso in times else 0
            except Exception:
                idx = 0
            slice_vals = temps[idx+1: idx+1+hours]
            next_vals = [f"{int(round(v))}°" for v in slice_vals if isinstance(v,(int,float))]
        d = data.get("daily") or {}
        dmin = d.get("temperature_2m_min") or []
        tonight = None
        if dmin:
            try:
                tonight = f"{int(round(dmin[0]))}°"
            except Exception:
                tonight = None

        head = f"{name}：{desc} {int(round(temp))}°" if isinstance(temp,(int,float)) else f"{name}：{desc}"
        wind_part = f"，风速{int(round(wind))}km/h" if isinstance(wind,(int,float)) else ""
        tail = ""
        if next_vals:
            tail += f"；接下来{len(next_vals)}小时：{'、'.join(next_vals)}"
        if tonight:
            tail += f"；今天晚上最低气温{tonight}喔~"
        return head + wind_part + tail

_client_singleton: Optional[WeatherClient] = None

def _get_client() -> WeatherClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = WeatherClient()
    return _client_singleton

def by_city(city: str) -> Optional[str]:
    try:
        return _get_client().bubble_text(city, hours=3)
    except Exception:
        return None
