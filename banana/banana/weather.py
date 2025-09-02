# weather.py  —— 极简版（仅保留常用信息）
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import time, requests

# --- 轻量缓存 ---
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
        if not it or it.expire_at < time.time():
            self._store.pop(key, None)
            return None
        return it.value

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        if len(self._store) >= self.max_size:
            self._store.pop(next(iter(self._store)))
        t = ttl if ttl is not None else self.ttl
        self._store[key] = CacheItem(value=value, expire_at=time.time() + t)

# --- 代码映射（只保留最常见）---
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
        self.geo_cache = TTLCache(ttl_seconds=7*24*3600)   # 城市 7 天
        self.wx_cache  = TTLCache(ttl_seconds=10*60)       # 天气 10 分钟
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
        if not city: return None
        key = f"geo:{self.lang}:{city}"
        if (c := self.geo_cache.get(key)): return c
        try:
            r = self.sess.get("https://geocoding-api.open-meteo.com/v1/search",
                              params={"name": city, "count": 1, "language": self.lang, "format": "json"},
                              timeout=5)
            r.raise_for_status()
            res = r.json().get("results") or []
            if not res: return None
            it = res[0]
            out = {
                "name": it.get("name") or city,
                "country": it.get("country") or "",
                "lat": float(it["latitude"]),
                "lon": float(it["longitude"]),
                "timezone": it.get("timezone") or "auto",
            }
            self.geo_cache.set(key, out)
            return out
        except Exception:
            return None

    def fetch(self, city: str) -> Optional[Dict[str, Any]]:
        """当前天气 + 今日高低温（最常用信息）"""
        city = (city or "").strip()
        if not city: return None
        g = self.geocode(city)
        if not g: return None
        key = f"wx:{g['lat']:.3f},{g['lon']:.3f}:basic"
        if (c := self.wx_cache.get(key)): return c
        try:
            params = {
                "latitude": g["lat"], "longitude": g["lon"], "timezone": "auto",
                "current_weather": True,
                "daily": "weathercode,temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
            }
            r = self.sess.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=6)
            r.raise_for_status()
            data = r.json()
            out = {"geo": g, "raw": data}
            self.wx_cache.set(key, out)
            return out
        except Exception:
            return None

    def bubble_text(self, city: str) -> Optional[str]:
        """极简一句话：城市 · 描述 当前气温°，风x km/h；今日 高°/低°"""
        pack = self.fetch(city)
        if not pack: return None
        g = pack["geo"]; data = pack["raw"]
        cw = data.get("current_weather") or {}
        d  = data.get("daily") or {}
        name = g.get("name") or city
        temp = cw.get("temperature"); wind = cw.get("windspeed")
        code = cw.get("weathercode"); desc = _desc(int(code or 0))
        try:
            tmax = d.get("temperature_2m_max", [None])[0]
            tmin = d.get("temperature_2m_min", [None])[0]
        except Exception:
            tmax = tmin = None
        head = f"{name} · {desc}"
        now  = f" {int(round(temp))}°" if isinstance(temp,(int,float)) else ""
        wtxt = f"，风 {int(round(wind))} km/h" if isinstance(wind,(int,float)) else ""
        rng  = f"；今日 {int(round(tmax))}°/{int(round(tmin))}°" if isinstance(tmax,(int,float)) and isinstance(tmin,(int,float)) else ""
        return head + now + wtxt + rng

# ---- 兼容旧 API ----
_client_singleton: Optional[WeatherClient] = None
def _get_client() -> WeatherClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = WeatherClient()
    return _client_singleton

def by_city(city: str) -> Optional[str]:
    try:
        return _get_client().bubble_text(city)
    except Exception:
        return None

def alert_summary(city: str) -> Optional[str]:
    # 简化后不再提供预警信息
    return None

def card_html(city: str, hours: int = 6) -> Optional[str]:
    # 简化后不再提供卡片
    return None
