
from __future__ import annotations
from typing import Optional
import requests

class Weather:
    @staticmethod
    def by_city(city: str) -> Optional[str]:
        city = (city or "").strip()
        if not city:
            return None
        try:
            g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                             params={"name": city, "count": 1, "language": "zh", "format": "json"}, timeout=5)
            g.raise_for_status()
            items = g.json().get("results") or []
            if not items:
                return None
            lat, lon = items[0]["latitude"], items[0]["longitude"]
            w = requests.get("https://api.open-meteo.com/v1/forecast",
                             params={"latitude": lat, "longitude": lon, "current_weather": True,
                                     "hourly": "temperature_2m", "timezone": "auto", "forecast_days": 1},
                             timeout=5)
            w.raise_for_status()
            data = w.json().get("current_weather", {})
            temp, ws, code = data.get("temperature"), data.get("windspeed"), data.get("weathercode")
            mapping = {0:"晴",1:"多云",2:"多云",3:"阴",45:"雾",48:"雾",51:"小雨",61:"小雨",63:"中雨",65:"大雨",
                       71:"小雪",73:"中雪",75:"大雪",95:"雷阵雨"}
            desc = mapping.get(int(code or 0), "天气不明")
            if temp is not None:
                return f"{city} 天气：{desc}，{temp:.0f}°C，风速{ws:.0f} km/h"
        except Exception:
            return None
        return None
