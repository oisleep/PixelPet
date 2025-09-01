
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import time
import requests

# --- Simple in-process TTL cache -------------------------------------------------
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
            # drop an arbitrary element
            self._store.pop(next(iter(self._store)))
        t = ttl if ttl is not None else self.ttl
        self._store[key] = CacheItem(value=value, expire_at=time.time() + t)

# --- Weather client (Open-Meteo, no API key) ------------------------------------
ZH_WC = {
    0: "晴", 1: "多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "小雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    95: "雷阵雨", 96: "雷阵雨", 99: "雷阵雨",
}

SEV_RANK = {"red": 3, "orange": 2, "yellow": 1, "unknown": 0}
SEV_ZH = {"red": "红色", "orange": "橙色", "yellow": "黄色", "unknown": "未知"}

def _desc(code: int) -> str:
    return ZH_WC.get(int(code), "天气不明")

class WeatherClient:
    def __init__(self, lang: str = "zh", session: Optional[requests.Session] = None):
        self.lang = lang
        self.sess = session or requests.Session()
        self.geo_cache = TTLCache(ttl_seconds=7*24*3600)   # 城市解析缓存 7 天
        self.wx_cache  = TTLCache(ttl_seconds=10*60)       # 天气缓存 10 分钟
        self.wr_cache  = TTLCache(ttl_seconds=5*60)        # 预警缓存 5 分钟

        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            retry = Retry(total=2, backoff_factor=0.2, status_forcelist=[429,500,502,503,504])
            adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
            self.sess.mount("https://", adapter); self.sess.mount("http://", adapter)
        except Exception:
            pass

    # ---------- Geocoding (cached) ----------
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

    # ---------- Fetch current + short-term forecast (cached) ----------
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

    # ---------- Weather warnings (cached) ----------
    def alerts(self, city: str) -> List[Dict[str, Any]]:
        """Return a list of normalized alerts; empty if none/unsupported region."""
        g = self.geocode(city)
        if not g:
            return []
        key = f"wr:{g['lat']:.3f},{g['lon']:.3f}"
        cached = self.wr_cache.get(key)
        if cached is not None:
            return cached
        alerts: List[Dict[str, Any]] = []
        try:
            r = self.sess.get("https://api.open-meteo.com/v1/warnings",
                              params={"latitude": g["lat"], "longitude": g["lon"], "timezone": "auto"},
                              timeout=6)
            if r.ok:
                js = r.json()
                items = js.get("warnings") or js.get("alerts") or []
                for it in items:
                    event = it.get("event") or it.get("headline") or it.get("title") or "天气预警"
                    level = (it.get("level") or it.get("severity") or "unknown").lower()
                    severity_rank = {"red":3, "orange":2, "yellow":1}.get(level, 0)
                    start = it.get("start") or it.get("effective") or it.get("onset")
                    end   = it.get("end")   or it.get("expires")  or it.get("until")
                    alerts.append({
                        "event": str(event),
                        "level": level if level in ("red","orange","yellow") else "unknown",
                        "rank": severity_rank,
                        "start": start, "end": end,
                        "description": it.get("description") or it.get("instruction") or "",
                        "source": it.get("source") or it.get("provider") or "",
                        "region": it.get("region") or it.get("region_name") or "",
                    })
        except Exception:
            pass
        alerts.sort(key=lambda a: a.get("rank", 0), reverse=True)
        self.wr_cache.set(key, alerts)
        return alerts

    # ---------- Compact bubble text ----------
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
        # hourly next N temps
        h = data.get("hourly") or {}
        temps = h.get("temperature_2m") or []
        times = h.get("time") or []
        pops  = h.get("precipitation_probability") or []
        next_temps, next_pops = [], []
        if temps and times:
            try:
                cur_iso = cw.get("time")
                idx = times.index(cur_iso) if cur_iso in times else 0
            except Exception:
                idx = 0
            slice_t = temps[idx+1: idx+1+hours]
            slice_p = pops[idx+1: idx+1+hours] if pops else []
            next_temps = [f"{int(round(v))}°" for v in slice_t if isinstance(v,(int,float))]
            if slice_p:
                next_pops = [f"{int(round(p))}%" for p in slice_p]
        d = data.get("daily") or {}
        dmin = d.get("temperature_2m_min") or []
        tonight = None
        if dmin:
            try:
                tonight = f"{int(round(dmin[0]))}°"
            except Exception:
                tonight = None

        head = f"{name}：{desc} {int(round(temp))}°" if isinstance(temp,(int,float)) else f"{name}：{desc}"
        wind_part = f"，风{int(round(wind))}km/h" if isinstance(wind,(int,float)) else ""
        tail = ""
        if next_temps:
            tail += f"；接下来{len(next_temps)}小时：{'、'.join(next_temps)}"
        if next_pops:
            tail += f"（降水{'、'.join(next_pops)}）"
        if tonight:
            tail += f"；今夜最低{tonight}"
        return head + wind_part + tail

    # ---------- Fancy HTML card ----------
    def card_html(self, city: str, hours: int = 6) -> Optional[str]:
        hours = max(1, min(12, int(hours)))
        pack = self.fetch(city, hours=hours, days=1)
        if not pack:
            return None
        g = pack["geo"]; data = pack["raw"]; cw = data.get("current_weather") or {}
        name = g.get("name") or city
        temp = cw.get("temperature"); wind = cw.get("windspeed"); code = cw.get("weathercode")
        desc = _desc(int(code or 0))
        # next hours temps & pops
        h = data.get("hourly") or {}
        temps = h.get("temperature_2m") or []
        times = h.get("time") or []
        pops  = h.get("precipitation_probability") or []
        idx = 0
        try:
            cur_iso = cw.get("time")
            idx = times.index(cur_iso) if cur_iso in times else 0
        except Exception:
            idx = 0
        next_t = temps[idx+1: idx+1+hours]
        next_p = pops[idx+1: idx+1+hours] if pops else []
        blocks = "▁▂▃▄▅▆▇"
        if next_t:
            mn, mx = min(next_t), max(next_t)
            rng = max(1.0, mx - mn)
            bars = [blocks[min(len(blocks)-1, int((t-mn)/rng * (len(blocks)-1)))] for t in next_t]
        else:
            bars = []
        t_line = " ".join(f"{int(round(t))}°" for t in next_t) if next_t else "—"
        p_line = " ".join(f"{int(round(p))}%" for p in next_p) if next_p else "—"
        bar_line = " ".join(bars) if bars else ""

        alerts = self.alerts(city)
        alert_html = ""
        if alerts:
            top = alerts[0]
            sev = top.get("level","unknown")
            sev_zh = SEV_ZH.get(sev,"未知")
            ev = top.get("event","天气预警")
            until = (top.get("end") or "")[:16].replace("T"," ")
            alert_html = f"""
            <div style="margin-top:6px;padding:6px 8px;border-radius:8px;background:rgba(255,87,51,0.12);
                        border:1px solid rgba(255,87,51,0.35);color:#8a1f11;">
              ⚠️ <b>{sev_zh}{ev}</b>
              <span style="opacity:.85"> {('至 ' + until) if until else ''}</span>
            </div>
            """

        html = f"""
        <div style="font-size:13px; line-height:1.45; color:#4c3b05; min-width:220px;">
          <div style="font-weight:700; font-size:15px; margin-bottom:2px;">{name} · {desc} {int(round(temp)) if isinstance(temp,(int,float)) else ''}°</div>
          <div style="opacity:.9; margin-bottom:6px;">风 {int(round(wind)) if isinstance(wind,(int,float)) else '—'} km/h</div>
          <div style="display:block; margin:4px 0 2px 0;"><span style="opacity:.8;">未来{hours}小时</span></div>
          <div style="font-family:monospace; white-space:nowrap;">{t_line}</div>
          {"<div style='opacity:.7; font-family:monospace;'>" + p_line + "</div>" if next_p else ""}
          {"<div style='opacity:.8;'>" + bar_line + "</div>" if bar_line else ""}
          {alert_html}
        </div>
        """
        return html

# ---------- Backward-compatible simple API ----------
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

def alert_summary(city: str) -> Optional[str]:
    try:
        alerts = _get_client().alerts(city)
        if not alerts:
            return None
        top = alerts[0]
        sev = top.get("level","unknown")
        sev_zh = {"red":"红色","orange":"橙色","yellow":"黄色"}.get(sev, "未知")
        ev = top.get("event","天气预警")
        until = (top.get("end") or "")[:16].replace("T"," ")
        core = f"{sev_zh}{ev}"
        return f"⚠️ {core}" + (f"（至 {until}）" if until else "")
    except Exception:
        return None

def card_html(city: str, hours: int = 6) -> Optional[str]:
    try:
        return _get_client().card_html(city, hours=hours)
    except Exception:
        return None
