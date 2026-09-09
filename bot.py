# BUSINESS + TAXIPARK UNIFIED PASSIVE INCOME — exact Business-style collector

# RESSELL FIXED FINAL — 2026-08-25
# Fixes: iOS/Telegram long-hold R-Farm pointer cancellation; Avito /state NameError.
# unified_bot.py - ПОЛНЫЙ СЕРВЕР + ТЕЛЕГРАМ БОТ ДЛЯ RESELL TYCOON
# Улучшенный интерфейс: страницы меню, разделение по категориям
# Все функции сохранены (гонки, скины, аукцион, трейдинг, таксопарк, разбор поставок, друзья, рефералы и т.д.)

import asyncio
import threading
import sqlite3
import json
import random
import hashlib
import base64
import hmac
import time as time_module
import re
import asyncio
import aiohttp
import random
import time
import json
import traceback
import threading
import uuid
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime
from html import escape
from typing import Optional, Dict, Any, List, Tuple
from pydantic import BaseModel
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message, InlineQueryResultArticle, InputTextMessageContent
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo, ReplyKeyboardRemove
from aiogram.enums import ButtonStyle
from collections import defaultdict, deque
from datetime import datetime, timedelta

# ==================== ROBUST TYCOON DATA HELPERS ====================
def _safe_json_list(raw, default=None):
    default = [] if default is None else default
    if isinstance(raw, list): return list(raw)
    if raw is None: return list(default)
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return list(value) if isinstance(value, list) else list(default)
        except Exception:
            return list(default)
    return list(default)

def _safe_taxopark(raw):
    """Normalize Taxopark state without dropping accounting fields."""
    if isinstance(raw, dict):
        value = dict(raw)
    elif isinstance(raw, str):
        try:
            x = json.loads(raw)
            value = dict(x) if isinstance(x, dict) else {}
        except Exception:
            value = {}
    else:
        value = {}

    level = str(value.get("level") or "none")
    cars = value.get("cars") if isinstance(value.get("cars"), list) else []
    indices = value.get("car_instance_indices") if isinstance(value.get("car_instance_indices"), list) else []
    clean = []
    for x in indices:
        try:
            clean.append(int(x))
        except (TypeError, ValueError):
            pass

    try:
        service = int(value.get("last_service_at") or 0)
    except (TypeError, ValueError):
        service = 0
    try:
        collect = int(value.get("last_collect_at") or 0)
    except (TypeError, ValueError):
        collect = 0
    try:
        carry = max(0, int(value.get("pending_carry") or 0))
    except (TypeError, ValueError):
        carry = 0

    return {
        "level": level,
        "cars": [str(x) for x in cars],
        "car_instance_indices": clean,
        "last_service_at": service,
        "last_collect_at": collect,
        "pending_carry": carry,
    }

def _safe_car_stats(raw, count, now=None):
    now=int(now or time_module.time()); items=raw if isinstance(raw,list) else []
    out=[]
    for i in range(int(count or 0)):
        v=items[i] if i<len(items) else {}
        if isinstance(v,dict): d=dict(v)
        elif isinstance(v,str):
            try: x=json.loads(v); d=dict(x) if isinstance(x,dict) else {}
            except Exception: d={}
        else: d={}
        try:m=max(0.0,float(d.get("mileage",0) or 0))
        except (TypeError,ValueError):m=0.0
        try:w=max(0.0,min(100.0,float(d.get("wear",0) or 0)))
        except (TypeError,ValueError):w=0.0
        try:inc=max(0,int(d.get("total_income",0) or 0))
        except (TypeError,ValueError):inc=0
        try:u=int(d.get("updated_at") or now)
        except (TypeError,ValueError):u=now
        d.update({"mileage":m,"wear":w,"total_income":inc,"updated_at":u})
        out.append(d)
    return out

def _accrue_taxi_stats(stats, owned, park_indices, now, income_multiplier=1.0):
    """Server-authoritative, restart-safe taxi wear/income accrual.

    line_started_at + *_before form an immutable baseline for the current line
    stint. Wear and mileage advance only while the car is working; at 100%
    wear the car is broken and stops generating income until repaired.
    """
    now=int(now); park=set(int(x) for x in (park_indices or [])); changed=False
    for idx in park:
        if idx<0 or idx>=len(owned) or idx>=len(stats): continue
        car=next((c for c in CARS if c.get("id")==owned[idx]),None)
        if not car: continue
        st=stats[idx] if isinstance(stats[idx],dict) else {}
        try: wear=float(st.get("wear",0) or 0)
        except Exception: wear=0.0
        try: mileage=float(st.get("mileage",0) or 0)
        except Exception: mileage=0.0
        try: income=int(st.get("total_income",0) or 0)
        except Exception: income=0
        try: started=int(st.get("line_started_at") or 0)
        except Exception: started=0
        if not started:
            try: started=int(st.get("updated_at") or now)
            except Exception: started=now
            st["line_started_at"]=started
            st["wear_before"]=wear
            st["mileage_before"]=mileage
            st["income_before"]=income
            changed=True
        try: base_wear=float(st.get("wear_before",wear) or 0)
        except Exception: base_wear=wear
        try: base_mileage=float(st.get("mileage_before",mileage) or 0)
        except Exception: base_mileage=mileage
        try: base_income=int(st.get("income_before",income) or 0)
        except Exception: base_income=income
        elapsed=max(0.0,(now-started)/3600.0)
        rate=_taxi_wear_per_hour(int(car.get("price",0) or 0))
        hourly=int(car.get("income_per_hour",0) or 0)*float(income_multiplier or 1.0)
        break_after_hours=max(0.0,(100.0-base_wear)/rate) if rate>0 else 0.0
        working_hours=min(elapsed,break_after_hours)
        new_wear=min(100.0,base_wear+working_hours*rate)
        new_mileage=base_mileage+working_hours*22.0
        new_income=base_income+int(working_hours*hourly)
        if abs(float(st.get("wear",0) or 0)-new_wear)>0.0001 or abs(float(st.get("mileage",0) or 0)-new_mileage)>0.05 or int(st.get("total_income",0) or 0)!=new_income:
            changed=True
        st.update({"wear":round(new_wear,4),"mileage":round(new_mileage,2),"total_income":new_income,"updated_at":now})
        stats[idx]=st
    return changed

# --- Настройки для генерации краш-точки ---
# Вероятность того, что множитель не улетит далеко
CRASH_BASE = 0.9

# ==================== ЭПОХИ RESell ====================
# Прогресс эпохи строится на общей заработанной прибыли (total_earned).
# Порог и награды легко менять здесь, не трогая клиент.
RESELL_EPOCHS = [
    {"id": 1, "name": "Trading Era · 01", "threshold": 1_000_000, "reward": 50_000, "reward_label": "50 000₽", "title": "ПЕРВЫЙ ОБОРОТ"},
    {"id": 2, "name": "Market Era · 02", "threshold": 5_000_000, "reward": 150_000, "reward_label": "150 000₽", "title": "ВЫХОД НА РЫНОК"},
    {"id": 3, "name": "Trader Era · 03", "threshold": 15_000_000, "reward": 500_000, "reward_label": "500 000₽", "title": "УВЕРЕННЫЙ ТРЕЙДЕР"},
    {"id": 4, "name": "Empire Era · 04", "threshold": 40_000_000, "reward": 2_000_000, "reward_label": "2 000 000₽", "title": "ИМПЕРИЯ RESELL"},
    {"id": 5, "name": "Capital Era · 05", "threshold": 100_000_000, "reward": 7_500_000, "reward_label": "7 500 000₽", "title": "КАПИТАЛ И ВЛИЯНИЕ"},
    {"id": 6, "name": "Core Era · 06", "threshold": 250_000_000, "reward": 25_000_000, "reward_label": "25 000 000₽", "title": "ЯДРО R-GAME"},
    {"id": 7, "name": "Global Era · 07", "threshold": 600_000_000, "reward": 75_000_000, "reward_label": "75 000 000₽", "title": "ГЛОБАЛЬНЫЙ ИГРОК"},
    {"id": 8, "name": "Legend Era · 08", "threshold": 1_500_000_000, "reward": 200_000_000, "reward_label": "200 000 000₽", "title": "ЛЕГЕНДА RESELL"},
]

def _cosmetic_unlocked_era_from_total_earned(total_earned:int)->int:
    earned=max(0,int(total_earned or 0))
    completed=sum(1 for e in RESELL_EPOCHS if earned>=int(e.get("threshold",0) or 0))
    return max(1,min(8,completed+1))


# ==================== WEBAPP HOLD GAME + UPGRADES ====================
HOLD_DURATION_SECONDS = 30
HOLD_COOLDOWN_SECONDS = 24 * 60 * 60
HOLD_REWARD_MIN = 10_000
HOLD_REWARD_MAX = 100_000
HOLD_BASE_REWARD = 10_000
HOLD_RANDOM_MIN_SECONDS = HOLD_DURATION_SECONDS
HOLD_RANDOM_MAX_SECONDS = HOLD_DURATION_SECONDS

# ==================== RESSELL R-HOLD CUSTOMIZATION ====================
RHOLD_BUTTON_SKINS = []
for _era in range(1,9):
    RHOLD_BUTTON_SKINS.extend([
        {"id": f"era{_era}_core", "name": f"ERA {_era} · CORE", "kind": "era", "era": _era, "price": 0, "accent": ["#b7ff6a","#8cff9a","#f1ff7a"][_era % 3], "bg": "linear-gradient(145deg,#111711,#090b09)", "border": "rgba(183,255,106,.50)", "glow": "rgba(183,255,106,.28)", "symbol": "R"},
        {"id": f"era{_era}_pulse", "name": f"ERA {_era} · PULSE", "kind": "era", "era": _era, "price": 0, "accent": ["#c7ff8a","#ffffff","#a8ffcf"][_era % 3], "bg": "radial-gradient(circle at 50% 45%,rgba(183,255,106,.22),rgba(10,14,10,.96) 68%)", "border": "rgba(255,255,255,.34)", "glow": "rgba(183,255,106,.38)", "symbol": "R"},
        {"id": f"era{_era}_grid", "name": f"ERA {_era} · GRID", "kind": "era", "era": _era, "price": 0, "accent": ["#b7ff6a","#d8ffb4","#92ffc8"][_era % 3], "bg": "linear-gradient(135deg,#171717 0%,#0a0a0a 55%,rgba(183,255,106,.12) 100%)", "border": "rgba(183,255,106,.38)", "glow": "rgba(183,255,106,.24)", "symbol": "R"},
    ])
RHOLD_BUTTON_SKINS.extend([
    {"id": "premium5m", "name": "BLACK LABEL", "kind": "premium", "min_balance": 5_000_000, "price": 5_000_000, "accent": "#ffffff", "bg": "linear-gradient(145deg,#171717,#050505)", "border": "rgba(255,255,255,.62)", "glow": "rgba(255,255,255,.18)", "symbol": "R"},
    {"id": "premium25m", "name": "CHROME VAULT", "kind": "premium", "min_balance": 25_000_000, "price": 25_000_000, "accent": "#eaffd9", "bg": "linear-gradient(135deg,#0d0d0d,#252525,#0a0a0a)", "border": "rgba(220,255,190,.58)", "glow": "rgba(220,255,190,.26)", "symbol": "R"},
    {"id": "network10", "name": "NETWORK 10", "kind": "network", "min_friends": 10, "price": 0, "accent": "#b7ff6a", "bg": "linear-gradient(145deg,#111a12,#081008 72%)", "border": "rgba(183,255,106,.74)", "glow": "rgba(183,255,106,.34)", "symbol": "R"},
])

# ---------------- V28: NEW RHOLD COLLECTION ----------------
# Keep the legacy ids above for database compatibility, but move the shop to a
# completely new visual collection. Every new button also carries a persistent
# reward multiplier which is locked into the hold session at start.
for _legacy in RHOLD_BUTTON_SKINS:
    _legacy.setdefault("legacy", True)

RHOLD_BUTTON_SKINS.extend([
    {"id":"v28_base_signal","name":"BASE SIGNAL","kind":"rhold","slot":"rhold","tier":"START","min_sales":0,"price":0,"reward_multiplier":1.0,"accent":"#9aa4ff","bg":"radial-gradient(circle at 50% 30%,rgba(154,164,255,.22),transparent 32%),linear-gradient(145deg,#10131f,#08090e 60%,#171c32)","border":"rgba(154,164,255,.62)","glow":"rgba(154,164,255,.38)","symbol":"R","decoration":"BASE"},
    {"id":"v28_4_prism","name":"PRISM DRIVE","kind":"rhold","slot":"rhold","tier":"4.0","min_sales":10,"price":1_500_000,"reward_multiplier":1.35,"accent":"#a98bff","bg":"radial-gradient(circle at 28% 20%,rgba(169,139,255,.42),transparent 28%),linear-gradient(145deg,#1a1228,#09080e 62%,#22153b)","border":"rgba(177,145,255,.75)","glow":"rgba(169,139,255,.55)","symbol":"R","decoration":"PRISM"},
    {"id":"v28_4_cyan","name":"CYBER TIDE","kind":"rhold","slot":"rhold","tier":"4.0","min_sales":10,"price":2_000_000,"reward_multiplier":1.50,"accent":"#5cf1ff","bg":"radial-gradient(circle at 72% 28%,rgba(92,241,255,.35),transparent 28%),linear-gradient(145deg,#061a20,#071012 60%,#0a2730)","border":"rgba(92,241,255,.76)","glow":"rgba(92,241,255,.52)","symbol":"R","decoration":"WAVE"},
    {"id":"v28_4_amber","name":"AMBER CORE","kind":"rhold","slot":"rhold","tier":"4.0","min_sales":10,"price":2_500_000,"reward_multiplier":1.75,"accent":"#ffc857","bg":"radial-gradient(circle at 50% 20%,rgba(255,200,87,.34),transparent 30%),linear-gradient(145deg,#24170a,#0d0a05 58%,#3a2409)","border":"rgba(255,200,87,.78)","glow":"rgba(255,200,87,.52)","symbol":"R","decoration":"CORE"},
    {"id":"v28_45_neon","name":"NEON VECTOR","kind":"rhold","slot":"rhold","tier":"4.5","min_sales":25,"price":7_500_000,"reward_multiplier":2.0,"accent":"#6cffb1","bg":"radial-gradient(circle at 20% 70%,rgba(108,255,177,.36),transparent 28%),linear-gradient(135deg,#081d16,#07100d 58%,#103426)","border":"rgba(108,255,177,.8)","glow":"rgba(108,255,177,.58)","symbol":"R","decoration":"VECTOR"},
    {"id":"v28_45_ultra","name":"ULTRA BLUE","kind":"rhold","slot":"rhold","tier":"4.5","min_sales":25,"price":10_000_000,"reward_multiplier":2.25,"accent":"#7ea7ff","bg":"radial-gradient(circle at 78% 20%,rgba(126,167,255,.38),transparent 30%),linear-gradient(145deg,#0c1730,#080b14 58%,#172752)","border":"rgba(126,167,255,.82)","glow":"rgba(126,167,255,.58)","symbol":"R","decoration":"ULTRA"},
    {"id":"v28_45_magenta","name":"MAGENTA FLUX","kind":"rhold","slot":"rhold","tier":"4.5","min_sales":25,"price":14_000_000,"reward_multiplier":2.5,"accent":"#ff74d9","bg":"radial-gradient(circle at 26% 25%,rgba(255,116,217,.38),transparent 29%),linear-gradient(145deg,#241025,#0e090f 58%,#351535)","border":"rgba(255,116,217,.82)","glow":"rgba(255,116,217,.58)","symbol":"R","decoration":"FLUX"},
    {"id":"v28_5_gold","name":"GOLD STANDARD","kind":"rhold","slot":"rhold","tier":"5.0","min_sales":50,"price":25_000_000,"reward_multiplier":3.0,"accent":"#ffe36c","bg":"radial-gradient(circle at 50% 17%,rgba(255,227,108,.42),transparent 30%),linear-gradient(145deg,#2a2008,#0e0b04 58%,#40300a)","border":"rgba(255,227,108,.88)","glow":"rgba(255,227,108,.62)","symbol":"R","decoration":"GOLD"},
    {"id":"v28_5_ruby","name":"RUBY VECTOR","kind":"rhold","slot":"rhold","tier":"5.0","min_sales":50,"price":40_000_000,"reward_multiplier":3.5,"accent":"#ff657b","bg":"radial-gradient(circle at 75% 22%,rgba(255,101,123,.4),transparent 31%),linear-gradient(145deg,#2b0d12,#0e0708 60%,#45141d)","border":"rgba(255,101,123,.86)","glow":"rgba(255,101,123,.6)","symbol":"R","decoration":"RUBY"},
    {"id":"v28_5_aurora","name":"AURORA PRIME","kind":"rhold","slot":"rhold","tier":"5.0","min_sales":50,"price":60_000_000,"reward_multiplier":4.0,"accent":"#83fff0","bg":"radial-gradient(circle at 20% 25%,rgba(131,255,240,.34),transparent 27%),radial-gradient(circle at 80% 72%,rgba(144,117,255,.28),transparent 28%),linear-gradient(145deg,#081b1a,#080c11 58%,#17132a)","border":"rgba(131,255,240,.88)","glow":"rgba(131,255,240,.62)","symbol":"R","decoration":"AURORA"},
    {"id":"v28_l_chrome","name":"CHROME CROWN","kind":"rhold","slot":"rhold","tier":"LEGEND","min_sales":100,"price":90_000_000,"reward_multiplier":5.0,"accent":"#f4f7ff","bg":"radial-gradient(circle at 50% 16%,rgba(244,247,255,.30),transparent 27%),linear-gradient(145deg,#22262d,#07090c 56%,#3a414e)","border":"rgba(244,247,255,.9)","glow":"rgba(210,224,255,.62)","symbol":"R","decoration":"CHROME"},
    {"id":"v28_l_emerald","name":"EMERALD DYNASTY","kind":"rhold","slot":"rhold","tier":"LEGEND","min_sales":100,"price":150_000_000,"reward_multiplier":6.0,"accent":"#75ffb4","bg":"radial-gradient(circle at 68% 24%,rgba(117,255,180,.4),transparent 31%),linear-gradient(145deg,#062016,#070d0b 58%,#103f2a)","border":"rgba(117,255,180,.92)","glow":"rgba(117,255,180,.65)","symbol":"R","decoration":"DYNASTY"},
    {"id":"v28_l_nebula","name":"NEBULA OVERDRIVE","kind":"rhold","slot":"rhold","tier":"LEGEND","min_sales":100,"price":250_000_000,"reward_multiplier":8.0,"accent":"#d8b6ff","bg":"radial-gradient(circle at 18% 24%,rgba(216,182,255,.38),transparent 28%),radial-gradient(circle at 82% 70%,rgba(92,241,255,.28),transparent 30%),linear-gradient(145deg,#130e24,#08090f 54%,#22153a)","border":"rgba(216,182,255,.94)","glow":"rgba(216,182,255,.68)","symbol":"R","decoration":"NEBULA"},
])

# Make every visible V28 profile cosmetic explicitly communicate its public slot.
for _item in RHOLD_BUTTON_SKINS:
    if _item.get("kind")=="nick_glow": _item.setdefault("display_scope","Ник в профиле, друзьях и лидерборде")
    elif _item.get("kind")=="avatar_frame": _item.setdefault("display_scope","Рамка вокруг R в профиле, друзьях и лидерборде")
    elif _item.get("kind")=="profile_badge": _item.setdefault("display_scope","Префикс рядом с ником в профиле, друзьях и лидерборде")

# ===== RESSELL PROFILE CUSTOMIZATION =====
# Additional cosmetics are unlocked by Avito seller level (sales count).
# The existing R-HOLD catalog remains intact.
RHOLD_BUTTON_SKINS.extend([
    {"id":"nick_lime","name":"NEON LIME","kind":"nick_glow","slot":"nick","min_sales":10,"price":1_500_000,
     "accent":"#b7ff6a","glow":"rgba(183,255,106,.72)"},
    {"id":"nick_ice","name":"ICE SIGNAL","kind":"nick_glow","slot":"nick","min_sales":25,"price":7_500_000,
     "accent":"#dfffe5","glow":"rgba(176,255,216,.72)"},
    {"id":"nick_vault","name":"VAULT WHITE","kind":"nick_glow","slot":"nick","min_sales":50,"price":25_000_000,
     "accent":"#ffffff","glow":"rgba(255,255,255,.60)"},
    {"id":"avatar_frame_lime","name":"LIME FRAME","kind":"avatar_frame","slot":"avatar","min_sales":10,"price":2_000_000,
     "accent":"#b7ff6a","glow":"rgba(183,255,106,.65)"},
    {"id":"avatar_frame_chrome","name":"CHROME FRAME","kind":"avatar_frame","slot":"avatar","min_sales":25,"price":10_000_000,
     "accent":"#d9e6df","glow":"rgba(214,239,226,.60)"},
    {"id":"avatar_frame_onyx","name":"ONYX FRAME","kind":"avatar_frame","slot":"avatar","min_sales":50,"price":35_000_000,
     "accent":"#ffffff","glow":"rgba(255,255,255,.52)"},
    {"id":"badge_verified","name":"ПРОВЕРЕННЫЙ","kind":"profile_badge","slot":"badge","min_sales":10,"price":1_000_000,
     "accent":"#b7ff6a","glow":"rgba(183,255,106,.58)"},
    {"id":"badge_pro","name":"PRO DEALER","kind":"profile_badge","slot":"badge","min_sales":25,"price":5_000_000,
     "accent":"#dfffe5","glow":"rgba(214,255,232,.58)"},
    {"id":"badge_legend","name":"LEGEND DEALER","kind":"profile_badge","slot":"badge","min_sales":50,"price":20_000_000,
     "accent":"#ffffff","glow":"rgba(255,255,255,.55)"},
])


RHOLD_STAR_PRODUCTS = {
    "v28_4_cyan": {"stars": 150, "title":"CYBER TIDE", "description":"Эксклюзивный R-HOLD стиль RESSELL · 1.50× награды"},
    "v28_5_gold": {"stars": 350, "title":"GOLD STANDARD", "description":"Эксклюзивный R-HOLD стиль RESSELL · 3.00× награды"},
    "v28_l_nebula": {"stars": 750, "title":"NEBULA OVERDRIVE", "description":"Эксклюзивный R-HOLD стиль RESSELL · 8.00× награды"},
}

# V33 customization rule: all current non-legacy cosmetics unlock by RESSELL Era;
# exactly three flagship R-HOLD buttons are Telegram Stars exclusives.
_RHOLD_STAR_IDS = set(RHOLD_STAR_PRODUCTS)
for _item in RHOLD_BUTTON_SKINS:
    if _item.get("id") in _RHOLD_STAR_IDS:
        _item["unlock_method"] = "stars"
        _item["stars_price"] = int(RHOLD_STAR_PRODUCTS[_item["id"]]["stars"])
        _item["unlock_era"] = 1
    elif not _item.get("legacy"):
        kind = str(_item.get("kind") or "")
        if kind == "rhold":
            tier = str(_item.get("tier") or "START").upper()
            _item["unlock_era"] = {"START":1,"4.0":2,"4.5":3,"5.0":4,"LEGEND":5}.get(tier,1)
        elif kind in {"nick_glow","avatar_frame","profile_badge"}:
            ms=int(_item.get("min_sales",0) or 0)
            _item["unlock_era"] = 2 if ms<=10 else 3 if ms<=25 else 4
        else:
            _item.setdefault("unlock_era", 1)
        _item["unlock_method"] = "era"
        _item["price"] = 0

# ==================== RESSELL MARKET HUB ====================
# These are intentionally not duplicates of Business / Auto / R-HOLD. They are
# prestige, collection and Night Club sinks that turn excess cash into visible
# progression.
RESSELL_EMPIRE_CATALOG = [
    {"id":"empire_office","name":"PRIVATE OFFICE","label":"ЛИЧНЫЙ ОФИС","price":25_000_000,"tier":1,"description":"Первое настоящее пространство владельца RESSELL.","accent":"#b7ff6a"},
    {"id":"empire_hq","name":"RESSELL HQ","label":"ШТАБ-КВАРТИРА","price":100_000_000,"tier":2,"description":"Премиальный штаб с видом на весь твой капитал.","accent":"#a9c4ff"},
    {"id":"empire_tower","name":"RESSELL TOWER","label":"НЕБОСКРЁБ","price":500_000_000,"tier":3,"description":"Финальный уровень империи. Один экран — весь статус игрока.","accent":"#ffe16c"},
]

RESSELL_COLLECTIBLE_CATALOG = [
    {"id":"collect_black_card","name":"BLACK CARD","price":7_500_000,"rarity":"RARE","description":"Чёрная карта члена закрытого круга RESSELL.","accent":"#f3f6ff"},
    {"id":"collect_midnight_key","name":"MIDNIGHT KEY","price":15_000_000,"rarity":"EPIC","description":"Коллекционный ключ от ночной экономики RESSELL.","accent":"#ae9cff"},
    {"id":"collect_chrome_chip","name":"CHROME CHIP","price":40_000_000,"rarity":"MYTHIC","description":"Редкий знак крупного капитала.","accent":"#dfffe9"},
    {"id":"collect_neon_token","name":"NEON TOKEN","price":75_000_000,"rarity":"MYTHIC","description":"Лимитированный жетон из закрытой коллекции.","accent":"#67f6ff"},
    {"id":"collect_sovereign_seal","name":"SOVEREIGN SEAL","price":150_000_000,"rarity":"LEGEND","description":"Коллекционный знак владельца собственной империи.","accent":"#ffe36c"},
    {"id":"collect_nightfall","name":"NIGHTFALL","price":300_000_000,"rarity":"LEGEND","description":"Самый редкий предмет Black Market этой ротации.","accent":"#ff86d5"},
]

RESSELL_BLACK_MARKET_POOL = [
    {"id":"bm_shadow_case","name":"SHADOW CASE","price":12_000_000,"rarity":"RARE","description":"Опечатанный футляр из ночного рынка.","accent":"#9ba9ff"},
    {"id":"bm_neon_sign","name":"NEON SIGN","price":25_000_000,"rarity":"EPIC","description":"Лимитированный световой объект для твоей коллекции.","accent":"#66f7c7"},
    {"id":"bm_black_chip","name":"BLACK CHIP","price":50_000_000,"rarity":"EPIC","description":"Коллекционный чип крупных игроков.","accent":"#f2f4ff"},
    {"id":"bm_vault_key","name":"VAULT KEY","price":90_000_000,"rarity":"MYTHIC","description":"Редкий ключ, выдаваемый только во время ротации.","accent":"#a98bff"},
    {"id":"bm_diamond_pass","name":"DIAMOND PASS","price":180_000_000,"rarity":"LEGEND","description":"Лимитированный пропуск закрытого клуба.","accent":"#a7ffe0"},
    {"id":"bm_afterdark","name":"AFTERDARK","price":350_000_000,"rarity":"LEGEND","description":"Ультраредкий collectible ночной экономики.","accent":"#ff8bcf"},
    {"id":"bm_crown","name":"BLACK CROWN","price":600_000_000,"rarity":"ICON","description":"Главный предмет текущей ротации.","accent":"#ffe56c"},
    {"id":"bm_zero","name":"ZERO HOUR","price":1_000_000_000,"rarity":"ICON","description":"Коллекционный символ максимального капитала.","accent":"#e8efff"},
]

RESSELL_COLLECTOR_CARS = [
    {"id":"collector_lexus_lfa","name":"LEXUS LFA · NIGHT RUN","price":120_000_000,"rarity":"MYTHIC","description":"Коллекционная машина для личного гаража. Не участвует в таксопарке.","accent":"#8ff7ff"},
    {"id":"collector_porsche_gt","name":"PORSCHE 911 GT3 RS · RS","price":180_000_000,"rarity":"MYTHIC","description":"Редкий дорожный collectible для статуса владельца.","accent":"#ffffff"},
    {"id":"collector_mercedes_one","name":"AMG ONE · BLACK","price":350_000_000,"rarity":"LEGEND","description":"Эксклюзивная коллекционная машина RESSELL.","accent":"#a98bff"},
    {"id":"collector_mclaren_speedtail","name":"McLAREN SPEEDTAIL · X","price":550_000_000,"rarity":"LEGEND","description":"Лимитированная машина для коллекционного гаража.","accent":"#ff8ed7"},
    {"id":"collector_buggati_chiron","name":"BUGATTI CHIRON · NOIR","price":900_000_000,"rarity":"ICON","description":"Верхний уровень коллекционного гаража RESSELL.","accent":"#ffe36c"},
]

RESSELL_DROP_CATALOG = [
    {"id":"drop_elite","name":"RESSELL ELITE DROP","price":25_000_000,"reward_asset":"collect_black_card","reward_value":7_500_000,"description":"Гарантированный предмет коллекции без случайного денежного убытка.","accent":"#b7ff6a"},
    {"id":"drop_mythic","name":"RESSELL MYTHIC DROP","price":100_000_000,"reward_asset":"collect_chrome_chip","reward_value":40_000_000,"description":"Гарантированно добавляет редкий мифический collectible в коллекцию.","accent":"#7df6ff"},
    {"id":"drop_legend","name":"RESSELL LEGEND DROP","price":300_000_000,"reward_asset":"collect_sovereign_seal","reward_value":150_000_000,"description":"Гарантированный легендарный collectible для Зала славы.","accent":"#ffe36c"},
]


NIGHT_CLUB_LEVELS = [
    {"level":1,"name":"AFTERDARK ROOM","price":50_000_000,"income_per_hour":6_000,"capacity":40,"reputation":8,"description":"Закрытый лаунж для своих."},
    {"level":2,"name":"NEON LOUNGE","price":150_000_000,"income_per_hour":20_000,"capacity":90,"reputation":18,"description":"Большой ночной зал и постоянный поток гостей."},
    {"level":3,"name":"NIGHT DISTRICT","price":500_000_000,"income_per_hour":70_000,"capacity":220,"reputation":38,"description":"Главная ночная точка города."},
    {"level":4,"name":"BLACK PALACE","price":1_500_000_000,"income_per_hour":240_000,"capacity":500,"reputation":80,"description":"Легендарный ночной дворец RESSELL."},
]

NIGHT_CLUB_STYLES = [
    {"id":"afterdark","name":"AFTERDARK","accent":"#b7ff6a","price":0},
    {"id":"violet","name":"VIOLET ROOM","accent":"#b59cff","price":25_000_000},
    {"id":"ice","name":"ICE CLUB","accent":"#7df6ff","price":60_000_000},
    {"id":"gold","name":"GOLD ROOM","accent":"#ffe36c","price":150_000_000},
]

def _rhold_skin_catalog_map():
    return {x["id"]: x for x in RHOLD_BUTTON_SKINS}

REFERRAL_DIRECT_REWARD = 250_000
REFERRAL_INVITEE_BONUS = 250_000
REFERRAL_BASE_PASSIVE_PERCENT = 1.0
REFERRAL_PASSIVE_STEP_PERCENT = 0.25
REFERRAL_PASSIVE_MAX_PERCENT = 10.0
# Compatibility alias: never let a referral-only change break unrelated sync paths.
REFERRAL_PASSIVE_PERCENT = REFERRAL_BASE_PASSIVE_PERCENT
REFERRAL_MIN_ACCOUNT_AGE_SECONDS = 10*60
REFERRAL_MIN_UNIQUE_ACTIONS = 3
REFERRAL_MIN_ACTIVITY_SPAN_SECONDS = 120
REFERRAL_SUSPICIOUS_PAIR_THRESHOLD = 70
REFERRAL_AUTO_BAN_RISK = 90
REFERRAL_AUTO_BAN_SUSPICIOUS_PAIRS = 3
REFERRAL_RAPID_LINK_LIMIT_1H = 8
REFERRAL_RAPID_LINK_LIMIT_24H = 20
REFERRAL_BOOST_TIERS = [(0,1.0),(1,1.5),(5,2.0),(10,3.0),(15,4.0),(25,5.0),(50,7.0),(75,8.5),(100,10.0)]
_REFERRAL_MILESTONE_TITLES = {
    5: "ПЕРВЫЙ КРУГ", 10: "ВЕРБОВЩИК", 15: "КАПИТАН СЕТИ", 20: "АРХИТЕКТОР",
    25: "МАГНАТ", 30: "ИМПЕРАТОР", 35: "ТИТАН", 40: "ЛЕГЕНДА",
    50: "ИМПЕРАТОР RESSELL", 75: "АРХИТЕКТОР ЭКОНОМИКИ", 100: "ВЛАДЫКА СЕТИ",
}
REFERRAL_MILESTONES = [
    {"target": target,
     "reward": 50_000 * (target // 5) * (2 * (target // 5) + 1),
     "title": _REFERRAL_MILESTONE_TITLES.get(target, f"УРОВЕНЬ {target // 5}")}
    for target in range(5, 101, 5)
]

def get_referral_passive_percent(active_count: int) -> float:
    """Base 1%, +0.25 percentage point per active referral, capped at 10%."""
    count = max(0, int(active_count or 0))
    return min(REFERRAL_PASSIVE_MAX_PERCENT, REFERRAL_BASE_PASSIVE_PERCENT + count * REFERRAL_PASSIVE_STEP_PERCENT)

def get_referral_boost_multiplier(player_id: int) -> float:
    try:
        player=get_player_data(int(player_id)); tg_id=int((player or {}).get("tg_id") or 0)
        if not tg_id: return 1.0
        conn=get_db(); row=conn.execute("SELECT COUNT(*) AS c FROM referral_relations r JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? AND r.reward_paid=1 AND COALESCE(p.is_banned,0)=0",(tg_id,)).fetchone(); conn.close()
        active=int(row["c"] if row else 0); value=1.0
        for target,mult in REFERRAL_BOOST_TIERS:
            if active>=target: value=mult
            else: break
        return value
    except Exception: return 1.0

def get_referral_title(active: int) -> str:
    title="НОВИЧОК"
    for m in REFERRAL_MILESTONES:
        if active>=m["target"]: title=m["title"]
        else: break
    return title

def boost_referral_income(amount: int, player_id: int) -> int:
    amount=int(amount or 0)
    return int(amount*get_referral_boost_multiplier(player_id)) if amount>0 else amount

UPGRADE_CARDS = {
    # Значительно более сильная окупаемость: улучшения должны ощущаться как реальный экономический рычаг.
    "traffic": {"name": "Трафик", "icon": "📣", "description": "Больше покупателей и выше шанс закрыть выгодную продажу.", "income_per_level": 6_000, "hold_bonus_per_level": 1_250, "costs": [100_000,250_000,600_000,1_300_000,2_800_000,6_000_000,12_000_000,25_000_000]},
    "automation": {"name": "Автоматизация", "icon": "⚙️", "description": "Сокращает потери и усиливает стабильный пассив.", "income_per_level": 12_000, "hold_bonus_per_level": 1_750, "costs": [250_000,600_000,1_400_000,3_000_000,6_500_000,14_000_000,30_000_000,60_000_000]},
    "warehouse": {"name": "Склад", "icon": "📦", "description": "Увеличивает оборот товаров и доход от реселла.", "income_per_level": 22_000, "hold_bonus_per_level": 2_500, "costs": [500_000,1_200_000,2_800_000,6_000_000,13_000_000,28_000_000,60_000_000,125_000_000]},
    "marketing": {"name": "Маркетинг", "icon": "🚀", "description": "Разгоняет поток клиентов и общую доходность.", "income_per_level": 45_000, "hold_bonus_per_level": 3_500, "costs": [1_000_000,2_500_000,6_000_000,13_000_000,28_000_000,60_000_000,125_000_000,250_000_000]},
    "resell_core": {"name": "Resell Core", "icon": "R", "description": "Ядро R-GAME: прямой бонус к фарму и ускорение пассивной экономики.", "income_per_level": 75_000, "hold_bonus_per_level": 7_500, "costs": [2_000_000,5_000_000,12_000_000,30_000_000,70_000_000,150_000_000]},
}

def get_epoch_state(player: Dict[str, Any]) -> Dict[str, Any]:
    total_earned = max(0, int(player.get("total_earned", 0) or 0))
    try:
        claimed = set(int(x) for x in json.loads(player.get("epoch_claimed", "[]") or "[]"))
    except Exception:
        claimed = set()
    # Эпохи проходят строго последовательно: пока текущая награда не забрана,
    # следующая не может визуально «перепрыгнуть» поверх неё.
    current_index = next((i for i, e in enumerate(RESELL_EPOCHS) if e["id"] not in claimed), len(RESELL_EPOCHS))
    if current_index >= len(RESELL_EPOCHS):
        current = RESELL_EPOCHS[-1]
        previous_threshold = RESELL_EPOCHS[-2]["threshold"]
        progress = 100.0
        claimable_epochs = []
    else:
        current = RESELL_EPOCHS[current_index]
        previous_threshold = RESELL_EPOCHS[current_index - 1]["threshold"] if current_index else 0
        span = max(1, current["threshold"] - previous_threshold)
        progress = min(100.0, max(0.0, (total_earned - previous_threshold) / span * 100.0))
        claimable_epochs = [current["id"]] if total_earned >= current["threshold"] else []
    completed_ids = [e["id"] for e in RESELL_EPOCHS if total_earned >= e["threshold"]]
    claimable_reward = int(current["reward"]) if claimable_epochs else 0
    return {
        "epochs": RESELL_EPOCHS,
        "current_epoch": current["id"],
        "current_name": current["name"],
        "current_title": current["title"],
        "current_threshold": current["threshold"],
        "previous_threshold": previous_threshold,
        "progress": round(progress, 2),
        "total_earned": total_earned,
        "completed_ids": completed_ids,
        "claimed_ids": sorted(claimed),
        "claimable_reward": claimable_reward,
        "claimable_epochs": claimable_epochs,
        "next_reward": current["reward_label"] if current_index < len(RESELL_EPOCHS) else "Все награды получены",
        "next_reward_value": int(current["reward"]) if current_index < len(RESELL_EPOCHS) else 0,
    }


# ==================== FSM СОСТОЯНИЯ (РАЗДЕЛЬНЫЕ) ====================
class Form(StatesGroup):
    waiting_for_chat_price = State()
    waiting_for_description = State()
    waiting_for_auction_price = State()
    waiting_for_nickname = State()
    waiting_for_shopname = State()
    waiting_for_transfer_amount = State()
    waiting_for_transfer_nickname = State()
    waiting_for_notifications = State()
    waiting_for_transfer_to_friend = State()
    waiting_for_deposit_amount = State()
    waiting_for_loan_amount = State()
    # Новые раздельные состояния (вместо waiting_for_custom_amount)
    waiting_for_trade_amount = State()      # для трейдинга
    waiting_for_loan_repayment = State()    # для погашения кредита
    waiting_for_auction_bid = State()   
    waiting_for_stock_quantity = State() 

class GameState(StatesGroup):
    playing = State()
    writing_description = State()
    writing_nickname = State()
    writing_shopname = State()
    racing = State()

# ==================== БЕЗОПАСНЫЙ ОТВЕТ НА CALLBACK ====================
async def safe_callback_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Отвечает на callback, игнорируя ошибку 'query too old'"""
    try:
        if text:
            await callback.answer(text, show_alert=show_alert)
        else:
            await callback.answer()
    except Exception:
        pass

# ==================== КОНФИГ ====================
import os

API_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("API_TOKEN")
# Backward-compatible aliases: deployments may expose any of these names.
BOT_TOKEN = API_TOKEN
BOT_USERNAME = os.getenv("BOT_USERNAME", "buygame61_bot")
ADMIN_ID = int(os.getenv("ADMIN_ID", "1475910449"))
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "44T1K17IVDLA0VU1")
DB_PATH = "game.db"
BASE_WEBAPP_URL = "https://ruslangodunov66-alt.github.io/resellcrash/" # Корневой путь вашего репозитория
URL_ROULETTE = f"{BASE_WEBAPP_URL}roulette.html"
URL_SLOTS = f"{BASE_WEBAPP_URL}slots.html"
URL_CRASH = f"{BASE_WEBAPP_URL}crash.html"
URL_MINES = f"{BASE_WEBAPP_URL}mines.html"
URL_BLACKJACK = f"{BASE_WEBAPP_URL}blackjack.html"
URL_CASINO = f"{BASE_WEBAPP_URL}casino.html"
URL_TRADING = f"{BASE_WEBAPP_URL}trading.html"
URL_RESELL = f"{BASE_WEBAPP_URL}resell.html"
# ==================== RCOIN / TON CONFIG ====================
RCOIN_SYMBOL = os.getenv("RCOIN_SYMBOL", "RCOIN")
RCOIN_POINTS_PER_TOKEN = max(1, int(os.getenv("RCOIN_POINTS_PER_TOKEN", "1000000")))
RCOIN_DECIMALS = max(0, min(9, int(os.getenv("RCOIN_DECIMALS", "9"))))
RCOIN_NETWORK = os.getenv("RCOIN_NETWORK", "testnet").strip().lower() or "testnet"
RCOIN_JETTON_MASTER = os.getenv("RCOIN_JETTON_MASTER", "").strip()
TON_CONNECT_MANIFEST_URL = os.getenv("TON_CONNECT_MANIFEST_URL", f"{BASE_WEBAPP_URL.rstrip('/')}/tonconnect-manifest.json")
TON_CONNECT_APP_DOMAIN = os.getenv("TON_CONNECT_APP_DOMAIN", "ruslangodunov66-alt.github.io").strip().lower()
RCOIN_TESTNET_ONLY = RCOIN_NETWORK != "mainnet"


def save_players():
    """Заглушка для совместимости со старым кодом. Данные сохраняются через SQLite."""
    pass

# ==================== БАЗОВЫЕ ДАННЫЕ ====================
CATEGORIES = ["👖 Джинсы", "👕 Худи", "🧥 Куртки", "👟 Кроссы", "🎒 Аксессуары"]

BASE_ITEMS = [
    {"cat": "👖 Джинсы", "name": "Levi's 501 Vintage", "base_price": 2000},
    {"cat": "👖 Джинсы", "name": "Carhartt WIP Denim", "base_price": 3500},
    {"cat": "👕 Худи", "name": "Adidas Originals Hoodie", "base_price": 2500},
    {"cat": "👕 Худи", "name": "Nike ACG Fleece", "base_price": 3000},
    {"cat": "🧥 Куртки", "name": "The North Face Nuptse", "base_price": 5000},
    {"cat": "🧥 Куртки", "name": "Alpha Industries MA-1", "base_price": 4000},
    {"cat": "👟 Кроссы", "name": "Nike Air Max 90", "base_price": 3500},
    {"cat": "👟 Кроссы", "name": "Adidas Samba OG", "base_price": 2800},
]

SUPPLIER_ITEM_RARITIES = {
    "обычный": {"name": "Обычный", "color": "⬜", "price_mult_min": 0.8, "price_mult_max": 1.3, "chance": 55},
    "редкий": {"name": "Редкий", "color": "🟦", "price_mult_min": 1.5, "price_mult_max": 2.5, "chance": 25},
    "эпический": {"name": "Эпический", "color": "🟪", "price_mult_min": 2.5, "price_mult_max": 5.0, "chance": 12},
    "легендарный": {"name": "Легендарный", "color": "🟨", "price_mult_min": 5.0, "price_mult_max": 12.0, "chance": 6},
    "мифический": {"name": "Мифический", "color": "🟥", "price_mult_min": 10.0, "price_mult_max": 30.0, "chance": 2},
}

SKINS = [
    {"id": "default", "name": "Новичок", "price": 0, "rarity": "обычный", "sales_required": 0, "emoji": "👶", "description": "Базовый скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDHGn4w7w3AAGnzzdBPwI4mNZEgoIjsAACzhhrG8bbwEsN1TBcMS6PhwEAAwIAA3kAAzsE"},
    {"id": "hustler", "name": "Темщик", "price": 0, "rarity": "обычный", "sales_required": 5, "emoji": "😎", "description": "⭐ Продано 5 товаров.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDLGn4xLrV_G5vUn9b0lfZbRt9uSNpAAIjE2sbRxXIS2ta2c2uvaRDAQADAgADeQADOwQ"},
    {"id": "boss", "name": "Мажор", "price": 0, "rarity": "обычный", "sales_required": 15, "emoji": "🕴", "description": "🏅 Продано 15 товаров.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDIGn4w8SxLumhkkue8rlTXiUqetBaAALQGGsbxtvAS3sUKevJKpGYAQADAgADeQADOwQ"},
    {"id": "coffee", "name": "Кофейный барыга", "price": 25000, "rarity": "редкий", "sales_required": 0, "emoji": "💻", "description": "Редкий скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDImn4w8m4lmlm6AYS1kBkt8Dx7ZyXAAL9GGsbxtvAS_vggWeGPBAgAQADAgADeQADOwQ"},
    {"id": "cyber", "name": "Кибер-барыга", "price": 80000, "rarity": "эпический", "sales_required": 0, "emoji": "🤖", "description": "Эпический скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDxWn45SvUS8m2sFIRTRarzV3ylymgAAJGFGsbRxXISwzuA4OGtBJyAQADAgADeQADOwQ"},
    {"id": "casual", "name": "Кэжуал барыга", "price": 5000, "rarity": "обычный", "sales_required": 0, "emoji": "👕", "description": "Обычный скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDyWn45lfPG9qMGWwqqtVvghaY-OpXAAJPFGsbRxXIS30JjvcuwnwHAQADAgADeQADOwQ"},
    {"id": "cyberpunk", "name": "Барыга-киберпанк", "price": 120000, "rarity": "эпический", "sales_required": 0, "emoji": "🦾", "description": "Эпический скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDy2n45wzQNDGj-mZOhvUo3ToyI8MVAAJTFGsbRxXIS-Qrt13FcYnwAQADAgADeQADOwQ"},
    {"id": "legend", "name": "Бог товарки", "price": 500000, "rarity": "легендарный", "sales_required": 0, "emoji": "👑", "description": "Легендарный скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDJGn4w8wheVk6HY-7qpII5w8hQ4lyAAL_GGsbxtvAS2S7TonuV3alAQADAgADeQADOwQ"},
    {"id": "oldmoney", "name": "Олд мани барыга", "price": 180000, "rarity": "эпический", "sales_required": 0, "emoji": "🎩", "description": "Эпический скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAIDzWn457hhlWHg6jBASBq0EcTDmWEpAAJUFGsbRxXIS1Xa-QcoURaAAQADAgADeQADOwQ"},
    {"id": "bazaar", "name": "Базарный барыга", "price": 35000, "rarity": "редкий", "sales_required": 0, "emoji": "🗣", "description": "Редкий скин.", "limited": False, "max_count": 0, "image_url": "AgACAgIAAxkBAAID0Wn46ouAFjuzjq1yQyOG4FahoM-CAAJlFGsbRxXIS-9X56WNZeVnAQADAgADeQADOwQ"},
    {"id": "creator", "name": "Создатель", "price": 0, "rarity": "мифический", "sales_required": 0, "emoji": "💎", "description": "💎 МИФИЧЕСКИЙ СКИН.", "limited": True, "max_count": 3, "image_url": "AgACAgIAAxkBAAIDz2n46ShGgxc6Z-mfB73cEzOvS74oAAJjFGsbRxXIS67XdFNB5viXAQADAgADeQADOwQ"},
    {"id": "henri", "name": "Анри Жерар", "price": 0, "rarity": "мифический", "sales_required": 0, "emoji": "🎩", "description": "Легендарный скин Анри Жерар.", "limited": True, "max_count": 1, "image_url": "AgACAgIAAxkBAAIyF2p3fVS8MBTXboVQ39GgKu1luBcAA-oZaxuTQ7lLXGVOyujf2JYBAAMCAAN5AAM9BA"},
]

CARS = [
    # Эконом (economy)
    {"id": "zhiguli", "name": "🚗 ВАЗ-2106 Жигули", "price": 15000, "speed_bonus": 10, "income_per_hour": 50, "rarity": "обычный", "category": "economy", "image_url": "AgACAgIAAxkBAAIKH2n7eaZvhsyGLQOFcU8fmz7BKgWhAAIkGGsbH9_QS0gOkG0ns94lAQADAgADeQADOwQ"},
    {"id": "granta", "name": "🚙 Лада Гранта", "price": 35000, "speed_bonus": 15, "income_per_hour": 120, "rarity": "обычный", "category": "economy", "image_url": "AgACAgIAAxkBAAIKJWn7e2SPU9Y3sbCRzOFO9-nf5Dw5AAIlGGsbH9_QSzJxHsxEUqGUAQADAgADeQADOwQ"},
    
    # Средний (medium)
    {"id": "cclass", "name": "🚘 Mercedes C-Class 2014", "price": 160000, "speed_bonus": 35, "income_per_hour": 600, "rarity": "эпический", "category": "medium", "image_url": "AgACAgIAAxkBAAIKLWn7e3QVhA8tYDpJPzpERwRtMdF3AAIpGGsbH9_QS4t1p3Bhq0TwAQADAgADeQADOwQ"},
    {"id": "mustang", "name": "🏎 Ford Mustang Кабриолет", "price": 120000, "speed_bonus": 30, "income_per_hour": 450, "rarity": "редкий", "category": "medium", "image_url": "AgACAgIAAxkBAAIKK2n7e3Ca7ti-KAq0As2CCsNvasMbAAIoGGsbH9_QS6URKdMbGfwQAQADAgADeQADOwQ"},
    {"id": "w140", "name": "🚘 Mercedes W140", "price": 90000, "speed_bonus": 28, "income_per_hour": 350, "rarity": "редкий", "category": "medium", "image_url": "AgACAgIAAxkBAAIKJ2n7e2jABfB9rbxFh3g5wJsAAUj0CgACJhhrGx_f0Eto1dm5lBmv_AEAAwIAA3kAAzsE"},
    {"id": "bmwm4", "name": "🏎 BMW M4", "price": 180000, "speed_bonus": 45, "income_per_hour": 700, "rarity": "эпический", "category": "medium", "image_url": "AgACAgIAAxkBAAIKKWn7e2wl9oHh_U4ygjOmTNZ-nAmfAAInGGsbH9_QS07bjw42tsNqAQADAgADeQADOwQ"},
    {"id": "challenger", "name": "🏎 Dodge Challenger", "price": 300000, "speed_bonus": 55, "income_per_hour": 1200, "rarity": "легендарный", "category": "medium", "image_url": "AgACAgIAAxkBAAIKNWn7e5kR4aOlGwVlwdhsbw5fvc_CAAItGGsbH9_QS6hSbI8YfnInAQADAgADeQADOwQ"},
    {"id": "ramtrx", "name": "🛻 Dodge Ram TRX", "price": 350000, "speed_bonus": 60, "income_per_hour": 1400, "rarity": "легендарный", "category": "medium", "image_url": "AgACAgIAAxkBAAIKM2n7e5NrhSVVTc2wUcRsOaBUHDoKAAIsGGsbH9_QS7sNrOC98FMGAQADAgADeQADOwQ"},
    {"id": "bmwm5", "name": "🏎 BMW M5 F90", "price": 450000, "speed_bonus": 70, "income_per_hour": 1800, "rarity": "легендарный", "category": "medium", "image_url": "AgACAgIAAxkBAAIKL2n7e3dRS58kxBJIwMbQyfhgSbXHAAIqGGsbH9_QS4JTxjSqqMS3AQADAgADeQADOwQ"},
    
    # Люкс (luxury)
    {"id": "sclass", "name": "🚘 Mercedes S-Class", "price": 650000, "speed_bonus": 75, "income_per_hour": 2600, "rarity": "легендарный", "category": "luxury", "image_url": "AgACAgIAAxkBAAIKMWn7e46bcc2IvFRWXnL99PAMfahNAAIrGGsbH9_QS8WFReLP1qWmAQADAgADeQADOwQ"},
    {"id": "bmwx7", "name": "🚙 BMW X7", "price": 850000, "speed_bonus": 70, "income_per_hour": 3400, "rarity": "легендарный", "category": "luxury", "image_url": "AgACAgIAAxkBAAIKOWn7e6XgOfa0orm4ZHTXA7BEWqDoAAIvGGsbH9_QS633taC4w8RrAQADAgADeQADOwQ"},
    {"id": "rollsroyce", "name": "👑 Rolls-Royce Phantom", "price": 1800000, "speed_bonus": 95, "income_per_hour": 7200, "rarity": "мифический", "category": "luxury", "image_url": "AgACAgIAAxkBAAIKN2n7e6AqWY0zFZGO2P9f4hsCdk8bAAIuGGsbH9_QSzUrOdo8uXGlAQADAgADeQADOwQ"},
    {"id": "aventador", "name": "🏎 Lamborghini Aventador", "price": 5000000, "speed_bonus": 98, "income_per_hour": 20000, "rarity": "мифический", "category": "luxury", "image_url": "AgACAgIAAxkBAAIKPGn7f2Rs5K3TIz7TUtspqjTQ5WweAAJaE2sbhKXhSz4-e1I_GY--AQADAgADeQADOwQ"},
    {"id": "brabus", "name": "👑 Brabus Mansory", "price": 20000000, "speed_bonus": 99, "income_per_hour": 80000, "rarity": "мифический", "category": "luxury", "image_url": "AgACAgIAAxkBAAIKPmn7f3zPq6X1RER7yHfJKjbkukAgAAJbE2sbhKXhS9npCM9WIdMXAQADAgADeQADOwQ"},
]

HOUSES = [
    {"id":"room","name":"🏚 Комната в общаге","price":0,"income_bonus":0,"description":"Бесплатное жильё. Не является источником пассивного дохода.","image_url":"AgACAgIAAxkBAAIYY2oTU26AUdnboAxd2xOOoa02oIo7AAL3ImsbWuiYSKh9uXShrqquAQADAgADeQADOwQ"},
    {"id":"flat","name":"🏢 Квартира","price":10000,"income_bonus":0,"income_per_hour":100,"description":"Недвижимость для статуса. Пассивного дохода не приносит.","image_url":"AgACAgIAAxkBAAIBeGn3hGvVcFktYFQJP-YNnKti48v1AAKYGWsbUNy4SzN3yqU-dPZwAQADAgADeQADOwQ"},
    {"id":"house","name":"🏠 Одноэтажный дом","price":35000,"income_bonus":0,"income_per_hour":350,"description":"Дом с гаражом. Пассивного дохода не приносит.","image_url":"AgACAgIAAxkBAAIBemn3hKeq-IxdQ6l6j7sD10pQPbHAAKUGGsbaAW5S4jG5ecluTqMAQADAgADeQADOwQ"},
    {"id":"villa","name":"🏰 Богатая вилла","price":100000,"income_bonus":0,"income_per_hour":900,"description":"Вилла с бассейном. Пассивного дохода не приносит.","image_url":"AgACAgIAAxkBAAIBfGn3hME0a5rsH1wos1Qyy1AhsYAnAAKVGGsbaAW5SzyFR-E8--65AQADAgADeQADOwQ"},
    {"id":"yacht","name":"🛥 Яхта","price":250000,"income_bonus":0,"income_per_hour":2500,"description":"Яхта у причала. Пассивного дохода не приносит.","image_url":"AgACAgIAAxkBAAIBfmn3hNlqZXeSCAxLTetoN0kJMG4RAAKWGGsbaAW5SxNdXNthpgjFAQADAgADeQADOwQ"},
    {"id":"skyscraper","name":"🏙 Небоскрёб","price":3000000,"income_bonus":0,"income_per_hour":8000,"description":"Статусный актив. Пассивного дохода не приносит.","image_url":"AgACAgIAAxkBAAIOGGn80IpHo9UQDHb2EhlAp6cOqCp8AAItF2sb59XpS_EAAVDuV6ZpTwEAAwIAA3kAAzsE"},
]

SHOP_LEVELS = [
    {"id": "none", "name": "Нет магазина", "price": 0, "income_per_hour": 0},
    {"id": "stall", "name": "🛍 Лавка на рынке", "price": 5000, "income_per_hour": 100},
    {"id": "container", "name": "📦 Контейнер на Садоводе", "price": 15000, "income_per_hour": 300},
    {"id": "small_shop", "name": "🏬 Маленький магазин одежды", "price": 50000, "income_per_hour": 800},
    {"id": "store", "name": "🏪 Магазин в ТЦ", "price": 150000, "income_per_hour": 2000},
    {"id": "brand_shop", "name": "👔 Брендовый магазин одежды", "price": 500000, "income_per_hour": 5000},
    {"id": "boutique", "name": "👑 Бутик в центре", "price": 1500000, "income_per_hour": 15000},
]

# V33: расширенная единая линейка Business. Это именно новые бизнесы, а не дубли
# уже существующих Auto/Taxi/Real Estate разделов.
SHOP_LEVELS.extend([
    {"id": "concept_store", "name": "✨ Concept Store", "price": 5000000, "income_per_hour": 45000},
    {"id": "flagship_center", "name": "🏙 Flagship Center", "price": 15000000, "income_per_hour": 140000},
    {"id": "resell_gallery", "name": "🖼 RESSELL Gallery", "price": 50000000, "income_per_hour": 500000},
    {"id": "city_plaza", "name": "🏢 City Plaza", "price": 150000000, "income_per_hour": 1600000},
    {"id": "resell_campus", "name": "🏙 RESSELL Campus", "price": 500000000, "income_per_hour": 5500000},
    {"id": "metroplex", "name": "🌆 RESSELL Metroplex", "price": 1500000000, "income_per_hour": 20000000},
])

TAXOPARK_LEVELS = [
    {"id": "none", "name": "Нет таксопарка", "price": 0, "slots": 0, "income_per_car": 0},
    {"id": "small", "name": "🚕 Маленький таксопарк", "price": 500000, "slots": 3, "income_per_car": 5000},
    {"id": "medium", "name": "🚖 Средний таксопарк", "price": 2000000, "slots": 7, "income_per_car": 8000},
    {"id": "large", "name": "🚗 Крупный таксопарк", "price": 10000000, "slots": 15, "income_per_car": 12000},
    {"id": "elite", "name": "👑 Элитный таксопарк", "price": 50000000, "slots": 30, "income_per_car": 20000},
]

# Долгосрочная экономика: новые покупки требуют заметно большего капитала.
# Уже купленные активы не переоцениваются в БД, чтобы не ломать коллекции игроков.
for _car in CARS:
    mult = 3 if _car.get("category") == "medium" else (5 if _car.get("category") == "luxury" else 1.5)
    _car["price"] = int(_car["price"] * mult)
for _house in HOUSES:
    if _house.get("price", 0) > 0: _house["price"] = int(_house["price"] * 3)
for _shop in SHOP_LEVELS:
    if _shop.get("price", 0) > 0: _shop["price"] = int(_shop["price"] * 4)
for _taxi in TAXOPARK_LEVELS:
    if _taxi.get("price", 0) > 0: _taxi["price"] = int(_taxi["price"] * 3)

CLIENT_TYPES = {
    "normal": {
        "max_rounds": 5,
        "phrases": {
            "greet": ["Здравствуйте!", "Добрый день!", "Приветствую!"],
            "state_reaction": ["Какое состояние у {item}?", "Состояние хорошее?", "Какой процент износа?"],
            "delivery_reaction": ["А доставка есть?", "Как быстро отправите?", "Можете доставить?"],
            "reason_reaction": ["Почему продаёте?", "С чем связана продажа?", "Что-то не так с товаром?"],
            "agree": ["Хорошо, беру за {price}₽!", "Договорились, {price}₽ устраивает.", "Ладно, забираю за {price}₽."],
            "decline": ["Извините, передумал.", "Дорого, ищу другое.", "Не убедили, отказ."],
            "wait": ["Подумаю ещё.", "Напишу позже.", "Сомневаюсь."]
        },
        "persuasion_bonus": 0
    },
    "skeptic": {
        "max_rounds": 5,
        "phrases": {
            "greet": ["Почему так дорого? {price}₽ — многовато.", "Цена высоковата для этого товара.", "Можете сделать скидку? {price}₽ дорого."],
            "state_reaction": ["А состояние какое?", "Есть дефекты?", "Как давно в использовании?"],
            "delivery_reaction": ["Доставка за ваш счёт?", "Когда сможете отправить?", "Самовывоз возможен?"],
            "reason_reaction": ["Зачем продаёте?", "Что-то с ним не так?", "Почему избавляетесь?"],
            "agree": ["Ладно, убедили, беру за {price}₽.", "Ну хорошо, {price}₽ идёт.", "Забираю по вашей цене."],
            "decline": ["Нет, всё равно дорого.", "Не убедили, отказ.", "Ищу другое предложение."],
            "wait": ["Подумаю.", "Сомневаюсь.", "Напишу позже."]
        },
        "persuasion_bonus": 30
    },
    "trader": {
        "max_rounds": 3,
        "phrases": {
            "greet": ["Здравствуйте! {item} — {price}₽? Давайте {offer}₽.", "Привет! Могу предложить {offer}₽ за {item}.", "Добрый день! {offer}₽ — моя цена."],
            "counter": ["Нет, всё равно дорого. {new_offer}₽?", "Подниму до {new_offer}₽. Это предел.", "Могу добавить только {new_offer}₽, идёт?"],
            "agree": ["Ладно, беру за {price}₽.", "Хорошо, давай по вашей цене.", "Уговорили, {price}₽."],
            "decline": ["Нет, не пойдёт.", "Дорого, отказываюсь.", "Не договорились, удачи."],
            "wait": ["Подумаю...", "Ну, не знаю.", "Посмотрю ещё варианты."]
        },
        "persuasion_bonus": 0
    }
}

# ==================== 60 ПЛАНОВЫХ СЦЕНАРИЕВ ДИАЛОГОВ ====================
_DIALOGUE_TOPICS=[
("Оригинальность","Привет! Подскажи, товар точно оригинальный?","Есть фото бирки или серийника?","Где покупал и остался ли чек?","Хочу понять происхождение перед покупкой."),
("Состояние","Здравствуйте! Насколько хорошо сохранился товар?","Есть потёртости или следы носки?","Что по скрытым дефектам?","Причина продажи тоже важна."),
("Размер","Привет! Мне нравится модель. Размер точно соответствует?","Замер по длине и ширине можешь дать?","Если размер не подойдёт, получится вернуть?","Покупаю для себя, поэтому хочу попасть точно."),
("Срочная покупка","Добрый день! Мне нужен такой товар прямо сейчас.","Сможешь отправить сегодня?","Как быстро упакуешь и отдашь в доставку?","Если всё быстро, готов закрыть сделку сегодня."),
("Подарок","Привет! Беру в подарок, поэтому внешний вид критичен.","Упаковка сохранилась?","Можешь сделать аккуратные фото перед отправкой?","Не хочу получить подарок с сюрпризами."),
("Торг","Здравствуйте! Цена вижу, но бюджет немного ниже.","Насколько готов двигаться по цене?","Если беру сегодня, будет скидка?","Давайте найдём середину."),
("Сравнение","Привет! Сравниваю несколько таких объявлений.","Чем твой вариант лучше остальных?","Есть ли у тебя аргумент за эту цену?","Хочу понять, за что переплачиваю."),
("Доставка","Добрый день! Мне важна нормальная доставка.","Есть отправка СДЭКом или через пункт выдачи?","Кто оплачивает доставку и упаковку?","Хочу избежать лишних расходов."),
("Комплект","Привет! Комплект полностью укомплектован?","Все аксессуары и документы на месте?","Ничего отдельно не продавалось?","Для меня комплектность сильно влияет на цену."),
("Редкость","Здравствуйте! Модель нечастая, интересно забрать её себе.","Когда ты её покупал?","Насколько часто такая модель встречается у тебя на рынке?","Если редкость подтвердится, готов обсуждать цену."),
("Бренд","Привет! Я хорошо знаю этот бренд, поэтому придираюсь к деталям.","Какая конкретно версия модели?","Есть бирки, артикул и подтверждение размера?","Хочу исключить сомнения перед оплатой."),
("Коллекционер","Добрый день! Я собираю такие вещи в коллекцию.","Есть история покупки?","Сохранились ли редкие детали из оригинального комплекта?","Если всё сходится, заберу без долгих раздумий."),
]
CLIENT_DIALOGUES=[]
_DIALOGUE_STYLES=[
("спокойный","Расскажи чуть подробнее — я не тороплюсь.","Понял, это уже выглядит убедительно.","Если уступишь немного, можем закрыть сделку."),
("проверка","Окей, хочу сначала убедиться, что всё честно.","Хорошо, ответы совпадают с объявлением.","Последний вопрос — и решаем по цене."),
("рациональный","Смотрю на цену и состояние одновременно.","Аргументы по товару мне подходят.","Давай теперь сверим итоговую сумму."),
("быстрый","Я уже почти решил брать, нужен один короткий ответ.","Отлично, это то, что хотел услышать.","Если по цене сойдёмся — забираю."),
("настойчивый","Я буду задавать вопросы, потому что не люблю сюрпризы.","Хорошо, теперь картина яснее.","Осталось только договориться о деньгах."),
]
for ti,(topic,g,q2,q3,q4) in enumerate(_DIALOGUE_TOPICS):
    for vi,(style,p1,p2,p3) in enumerate(_DIALOGUE_STYLES):
        CLIENT_DIALOGUES.append({"id":f"dlg_{ti+1:02d}_{vi+1}","title":f"{topic} · {style}","client_type":["normal","skeptic","normal","trader","skeptic"][vi],"phases":[g,q2,q3,q4,p1,p2,p3],"final_prompt":"Хорошо, с информацией разобрался. Теперь давай окончательно по цене.","final_agree":"Отлично, договорились. Я забираю товар по {price}₽.","final_decline":"Нет, при такой цене не готов. Спасибо за ответы, но пропущу."})
assert len(CLIENT_DIALOGUES)==60

TRADING_ASSETS = {
    "BTC": {"name": "Bitcoin",   "coin_id": "bitcoin",  "min_bet": 100,  "max_bet": 10000, "color": "🟠", "base_price": 50000, "volatility": 0.05},
    "ETH": {"name": "Ethereum",  "coin_id": "ethereum", "min_bet": 50,   "max_bet": 5000,  "color": "🔵", "base_price": 3000,  "volatility": 0.06},
    "SOL": {"name": "Solana",    "coin_id": "solana",   "min_bet": 10,   "max_bet": 2000,  "color": "🟣", "base_price": 150,   "volatility": 0.08},
    "DOGE": {"name": "Dogecoin", "coin_id": "dogecoin", "min_bet": 5,    "max_bet": 1000,  "color": "🟡", "base_price": 0.15,  "volatility": 0.10},
}

JOBS = [
    {"id": "flyers", "name": "📦 Расклейка объявлений", "duration": 60, "reward": 200, "emoji": "📦"},
    {"id": "delivery", "name": "🚗 Доставка заказов", "duration": 120, "reward": 500, "emoji": "🚗"},
    {"id": "freelance", "name": "💻 Фриланс (дизайн)", "duration": 300, "reward": 1200, "emoji": "💻"},
]

# Дополнить MARKET_EVENTS
MARKET_EVENTS = [
    {"text": "📰 Хайп на джинсы!", "cat": "👖 Джинсы", "mult": 1.5},
    {"text": "📰 Куртки в цене!", "cat": "🧥 Куртки", "mult": 1.4},
    {"text": "📰 Кроссовки в тренде!", "cat": "👟 Кроссы", "mult": 1.5},
    {"text": "📰 Джинсы падают.", "cat": "👖 Джинсы", "mult": 0.6},
    {"text": "🌧 Дождливая погода – продажи дождевиков и курток растут!", "cat": "🧥 Куртки", "mult": 1.3},
    {"text": "🌧 Ливень – зонты и дождевики раскупают!", "cat": "🎒 Аксессуары", "mult": 1.5},
    {"text": "❄ Сильный снегопад – тёплые куртки и шапки в дефиците!", "cat": "🧥 Куртки", "mult": 1.5},
    {"text": "☀️ Аномальная жара – спрос на футболки и кепки зашкаливает!", "cat": "👕 Худи", "mult": 1.6},
    {"text": "☀️ Жаркое лето – кроссовки и сандалии на пике!", "cat": "👟 Кроссы", "mult": 1.4},
    {"text": "🍂 Осенний сезон – продажи джинсов и худи выросли!", "cat": "👖 Джинсы", "mult": 1.3},
    {"text": "❄️ Зимний фронт – тёплая одежда дорожает, спрос на куртки растёт!", "cat": "🧥 Куртки", "mult": 1.45},
    {"text": "🌨 Слякоть – продажи кроссовок просели, аксессуары для улицы в плюсе!", "cat": "🎒 Аксессуары", "mult": 1.25},
    {"text": "🌬 Сильный ветер – люди чаще покупают практичные аксессуары для улицы!", "cat": "🎒 Аксессуары", "mult": 1.28},
    {"text": "🧊 Гололёд – рынок одежды осторожный, быстрая продажа даётся сложнее!", "cat": "👟 Кроссы", "mult": 0.72},
    {"text": "❄️ Зимняя распродажа – пуховики уходят по завышенным ценам!", "cat": "🧥 Куртки", "mult": 1.6},
    {"text": "🔄 Обновление Авито – комиссия снижена на 20%!", "cat": None, "mult": 1.2, "global": True},
]

# ==================== ДОСТИЖЕНИЯ И КВЕСТЫ ====================
ACHIEVEMENTS = {
    "millionaire": {
        "name": "💰 Миллионер",
        "description": "Заработать 1 000 000₽ общей прибыли",
        "target": 1_000_000,
        "reward_money": 100_000,
        "reward_skin": None  # можно указать id скина
    },
    "tycoon": {
        "name": "👑 Торговый магнат",
        "description": "Купить 10 магазинов",
        "target": 10,
        "reward_money": 150_000,
    },
    "car_lover": {
        "name": "🏎 Автолюбитель",
        "description": "Купить 5 автомобилей",
        "target": 5,
        "reward_money": 50_000,
    },
    "seller": {
        "name": "📦 Торговый поток",
        "description": "Продать 100 товаров",
        "target": 100,
        "reward_money": 75_000,
    },
    "shop_lover": {
        "name": "🏪 Коллекционер магазинов",
        "description": "Купить все типы магазинов (по 1шт)",
        "target": len([s for s in SHOP_LEVELS if s["id"] != "none"]),
        "reward_money": 200_000,
    },
}

# Ежедневные задания
DAILY_QUESTS = {
    "farm_once": {
        "name": "⚡ R-Фарм",
        "description": "Полностью завершить один цикл R-Фарма",
        "target": 1,
        "reward_money": 15_000,
    },
    "sell_3": {
        "name": "📦 Продавец дня",
        "description": "Продать 3 товара",
        "target": 3,
        "reward_money": 5_000,
    },
    "sell_10": {
        "name": "📦 Массовый продавец",
        "description": "Продать 10 товаров",
        "target": 10,
        "reward_money": 12_000,
    },
    "earn_50k": {
        "name": "💰 Прибыльный день",
        "description": "Заработать 50 000₽ за день (продажи + пассивный доход)",
        "target": 50_000,
        "reward_money": 10_000,
    },
    "earn_200k": {
        "name": "💎 Большая прибыль",
        "description": "Заработать 200 000₽ за день",
        "target": 200_000,
        "reward_money": 25_000,
    },
    "buy_shop": {
        "name": "🏪 Инвестор",
        "description": "Купить любой магазин",
        "target": 1,
        "reward_money": 7_500,
    },
    "buy_car": {
        "name": "🚗 Автомобилист",
        "description": "Купить автомобиль",
        "target": 1,
        "reward_money": 5_000,
    },
    "win_race": {
        "name": "🏆 Гоночная победа",
        "description": "Выиграть гонку",
        "target": 1,
        "reward_money": 10_000,
    },
    "supply_unpack": {
        "name": "📦 Разбор поставки",
        "description": "Разобрать поставку (10 кликов)",
        "target": 1,
        "reward_money": 5_000,
    },
    "collect_passive_10k": {
        "name": "💤 Пассивный доход",
        "description": "Получить 10 000₽ пассивного дохода за день",
        "target": 10_000,
        "reward_money": 10_000,
    },
    "collect_passive_50k": {
        "name": "💤 Пассивный магнат",
        "description": "Получить 50 000₽ пассивного дохода за день",
        "target": 50_000,
        "reward_money": 20_000,
    },
    "visit_casino": {
        "name": "🎰 Игрок в казино",
        "description": "Сыграть 3 игры в казино",
        "target": 3,
        "reward_money": 5_000,
    },
    "win_casino": {
        "name": "💰 Удача в казино",
        "description": "Выиграть 10 000₽ в казино за день",
        "target": 10_000,
        "reward_money": 8_000,
    },
}


# Три постоянных квеста WebApp: прогресс не сбрасывается.
PERMANENT_QUESTS = {
    "resell_veteran": {"name": "🛍 Ветеран RESELL", "description": "Совершить 25 продаж", "target": 25, "reward_money": 25_000, "metric": "total_sales"},
    "capital_builder": {"name": "💎 Строитель капитала", "description": "Заработать 500 000₽ общей прибыли", "target": 500_000, "reward_money": 50_000, "metric": "total_earned"},
    "shop_empire": {"name": "🏪 Империя магазинов", "description": "Владеть 3 магазинами одновременно", "target": 3, "reward_money": 75_000, "metric": "shops_count"},
}

DAILY_ROTATION_SIZE = 5

def get_rotating_daily_quest_ids(day=None):
    """Детерминированная ротация пяти ежедневных заданий; новый набор открывается в 12:00."""
    if day is None:
        now = datetime.now()
        day = now.date() if now.hour >= 12 else (now - timedelta(days=1)).date()
    ids = list(DAILY_QUESTS.keys())
    rng = random.Random(day.toordinal())
    rng.shuffle(ids)
    return ids[:min(DAILY_ROTATION_SIZE, len(ids))]


def _daily_reset_label(now=None):
    now = now or datetime.now()
    target = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    return target.strftime('%Y-%m-%d %H:%M:%S')

TRADING_ITEMS = {
    "👖 Джинсы": {"name": "Джинсы", "base_price": 500, "volatility": 0.15},
    "👕 Футболки": {"name": "Футболки", "base_price": 300, "volatility": 0.12},
    "🧥 Куртки": {"name": "Куртки", "base_price": 800, "volatility": 0.18},
    "👟 Кроссовки": {"name": "Кроссовки", "base_price": 600, "volatility": 0.20},
    "🧢 Кепки": {"name": "Кепки", "base_price": 200, "volatility": 0.10},
}

MINING_RIGS = {
    "small": {"name": "🖥 Малая ферма", "price": 250000, "daily_income": 20000},
    "medium": {"name": "🖥🖥 Средняя ферма", "price": 1000000, "daily_income": 60000},
    "large": {"name": "🖥🖥🖥 Крупная ферма", "price": 6000000, "daily_income": 300000},
}

# ==================== ГЛОБАЛЬНЫЕ ХРАНИЛИЩА ====================
active_races = {}
active_chats = {}
chats_lock = asyncio.Lock()
published_items = {}
published_lock = asyncio.Lock()
races_lock = asyncio.Lock()
db_lock = asyncio.Lock()
sold_items = {}
supplier_stock = {"items_by_player": {}, "last_update_by_player": {}}
trading_prices = {}          # {asset: {"price": float, "trend": float, "history": deque(maxlen=5)}}
completed_sales = []  # list of dict: {"seller_id": int, "buyer_id": int, "item_name": str, "price": int, "date": str}
trading_lock = asyncio.Lock()
bet_history = defaultdict(list)   # {user_id: [{"asset", "direction", "bet", "result", "profit", "time"}]}
auction_items = []
auction_lock = asyncio.Lock()
supply_drop = {}
side_jobs = {}
side_jobs_lock = asyncio.Lock()
active_bets = {}   # {bet_id: {...}}
pending_inviter = {}  # legacy compatibility; persistent referral_pending is authoritative
last_bot_message = {}
pending_messages = defaultdict(list)
supplier_lock = asyncio.Lock()
supply_drop_lock = asyncio.Lock()
active_mines_games = {}      # {user_id: game_data}
player_luck = {}
crash_active_bets = {}  # {player_id: {"amount": int, "crash_point": float, "timestamp": float}}
crash_active_bets = {}
pending_deposits = {}  # {user_id: amount}

async def update_balance(player_id: int, delta: int):
    """Увеличивает или уменьшает balance на delta. delta может быть отрицательным."""
    if delta == 0:
        return
    async with db_lock:
        player = await run_sync_db(get_player_data, player_id)
        if not player:
            return
        new_balance = player.get("balance", 0) + delta
        if new_balance < 0:
            new_balance = 0
        await run_sync_db(update_player_data, player_id, {"balance": new_balance})

async def run_sync_db(func, *args, **kwargs):
    # Блокировку навешиваем ТОЛЬКО снаружи – здесь она не нужна
    return await asyncio.to_thread(func, *args, **kwargs)

async def safe_delete_message(msg: types.Message):
    """Безопасное удаление сообщения (без ошибок)"""
    try:
        await msg.delete()
    except Exception:
        pass

async def send_msg(user_id, text, parse_mode="HTML", reply_markup=None):
    try:
        msg = await bot.send_message(user_id, text, parse_mode=parse_mode, reply_markup=reply_markup)
        last_bot_message[user_id] = msg.message_id
        return msg
    except Exception as e:
        # Если пользователь заблокировал бота – игнорируем, не спамим в лог
        if "blocked" in str(e).lower():
            return None
        print(f"⚠️ Ошибка отправки сообщения {user_id}: {e}")
        return None

# ==================== МОДЕЛИ PYDANTIC ДЛЯ API ====================
class PlayerAction(BaseModel):
    platform: str
    platform_id: int
    action: str
    data: Dict[str, Any] = {}

# ==================== БАЗА ДАННЫХ SQLITE (ФУНКЦИИ) ====================
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    cursor = conn.cursor()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    
    # Таблица игроков
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE,
            vk_id INTEGER UNIQUE,
            nickname TEXT DEFAULT 'Торгаш' UNIQUE,
            shop_name TEXT DEFAULT 'Без названия',
            balance INTEGER DEFAULT 5000,
            day INTEGER DEFAULT 1,
            inventory TEXT DEFAULT '[]',
            car_collection TEXT DEFAULT '[]',
            current_car TEXT DEFAULT 'none',
            house TEXT DEFAULT 'room',
            shop_level TEXT DEFAULT 'none',
            taxopark TEXT DEFAULT '{"level":"none","cars":[]}',
            skin TEXT DEFAULT 'default',
            skin_inventory TEXT DEFAULT '["default"]',
            reputation_score INTEGER DEFAULT 0,
            total_sales INTEGER DEFAULT 0,
            total_profit INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            items_sold INTEGER DEFAULT 0,
            market_demand TEXT DEFAULT '{"👖 Джинсы":1.0,"👕 Худи":1.0,"🧥 Куртки":1.0,"👟 Кроссы":1.0,"🎒 Аксессуары":1.0}',
            current_event TEXT,
            stat_earned_today INTEGER DEFAULT 0,
            stat_sold_today INTEGER DEFAULT 0,
            trading_portfolio TEXT DEFAULT '{}',
            trading_invested INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица истории продаж
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            buyer_id INTEGER,
            item_name TEXT,
            price INTEGER,
            date TEXT,
            FOREIGN KEY (seller_id) REFERENCES players(id)
        )
    ''')
    
    # Таблица друзей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS friends (
            player_id INTEGER, friend_id INTEGER,
            FOREIGN KEY (player_id) REFERENCES players(id),
            PRIMARY KEY (player_id, friend_id)
        )
    ''')
    
    # Таблица покерных игр
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS poker_games (
            id TEXT PRIMARY KEY,
            player_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            pot INTEGER NOT NULL DEFAULT 0,
            community_cards TEXT,
            deck TEXT,
            buy_in INTEGER NOT NULL,
            current_turn INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER,
            payout_done INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

    # Таблица рук игроков (составной первичный ключ)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS poker_hands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            seat_number INTEGER NOT NULL,
            player_id INTEGER,
            bot_id TEXT,
            name TEXT,
            avatar TEXT,
            is_bot INTEGER NOT NULL DEFAULT 0,
            cards TEXT,
            stack INTEGER NOT NULL,
            current_bet INTEGER NOT NULL DEFAULT 0,
            total_bet INTEGER NOT NULL DEFAULT 0,
            folded INTEGER NOT NULL DEFAULT 0,
            all_in INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (game_id) REFERENCES poker_games(id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

    # Таблица гонок
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS races (
            id TEXT PRIMARY KEY, creator_id INTEGER, opponent_id INTEGER,
            creator_car TEXT, opponent_car TEXT, bet INTEGER, prize_pool INTEGER,
            phase INTEGER DEFAULT 0, creator_score INTEGER DEFAULT 0, opponent_score INTEGER DEFAULT 0,
            creator_actions TEXT DEFAULT '[]', opponent_actions TEXT DEFAULT '[]',
            status TEXT DEFAULT 'wait', winner_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица рефералов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            player_id INTEGER PRIMARY KEY, invited TEXT DEFAULT '[]', bonus_claimed INTEGER DEFAULT 0
        )
    ''')
    # Надёжная связь приглашённый -> пригласивший для WebApp startapp
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referral_relations (
            invitee_tg_id INTEGER PRIMARY KEY,
            inviter_tg_id INTEGER NOT NULL,
            activated_at INTEGER NOT NULL,
            reward_paid INTEGER DEFAULT 0
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_referral_relations_inviter_reward ON referral_relations(inviter_tg_id, reward_paid, invitee_tg_id)")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referral_pending (
            invitee_tg_id INTEGER PRIMARY KEY,
            inviter_tg_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            source TEXT DEFAULT 'webapp'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referral_milestones (
            player_id INTEGER NOT NULL,
            target INTEGER NOT NULL,
            reward INTEGER NOT NULL,
            claimed_at INTEGER NOT NULL,
            PRIMARY KEY (player_id, target)
        )
    ''')

    # Сессии игры «Зажми на минуту»
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS hold_sessions (
            player_id INTEGER PRIMARY KEY,
            session_id TEXT,
            started_at INTEGER DEFAULT 0,
            last_completed_at INTEGER DEFAULT 0,
            total_claims INTEGER DEFAULT 0
        )
    ''')
    cursor.execute("PRAGMA table_info(hold_sessions)")
    _hold_cols = [r[1] for r in cursor.fetchall()]
    if 'target_reward' not in _hold_cols:
        cursor.execute("ALTER TABLE hold_sessions ADD COLUMN target_reward INTEGER DEFAULT 0")
    if 'target_duration' not in _hold_cols:
        cursor.execute("ALTER TABLE hold_sessions ADD COLUMN target_duration INTEGER DEFAULT 30")

    # Административные статусы игроков
    cursor.execute("PRAGMA table_info(players)")
    _player_cols = [r[1] for r in cursor.fetchall()]
    if 'is_banned' not in _player_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN is_banned INTEGER DEFAULT 0")
    if 'warning_count' not in _player_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN warning_count INTEGER DEFAULT 0")

    # Аудит-лог: действия игроков и администраторов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_tg_id INTEGER,
            target_tg_id INTEGER,
            action TEXT NOT NULL,
            amount INTEGER DEFAULT 0,
            details TEXT DEFAULT '',
            created_at INTEGER NOT NULL
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_target_time ON audit_logs(target_tg_id, created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_actor_time ON audit_logs(actor_tg_id, created_at DESC)")
    cursor.execute("CREATE TABLE IF NOT EXISTS admin_users(tg_id INTEGER PRIMARY KEY, added_by INTEGER, active INTEGER DEFAULT 1, created_at INTEGER NOT NULL)")

    # Уровни улучшений WebApp
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webapp_upgrades (
            player_id INTEGER NOT NULL,
            upgrade_id TEXT NOT NULL,
            level INTEGER DEFAULT 0,
            PRIMARY KEY (player_id, upgrade_id)
        )
    ''')

    
        # Таблица скинов (с автоинкрементным ID для множественных копий)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            skin_id TEXT,
            equipped INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица аукциона
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS auction (
            id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER,
            item_name TEXT, item_data TEXT, start_price INTEGER, current_bid INTEGER,
            bidder_id INTEGER, end_time INTEGER, active INTEGER DEFAULT 1
        )
    ''')
    
    # Таблица обучения
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning (
            player_id INTEGER PRIMARY KEY, completed TEXT DEFAULT '[]'
        )
    ''')
    
    # Новая таблица для множественных магазинов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            shop_id TEXT,
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')
    
    # Таблица для таксопарков (ПЕРЕМЕЩЕНО СЮДА)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_taxoparks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            level_id TEXT,
            purchase_price INTEGER,
            last_payment INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            paid_until INTEGER DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

    # Улучшения таксопарка — создаются при каждом старте, поэтому новый DB-файл
    # не ломает endpoint /tycoon/taxopark/.../upgrade.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS taxi_upgrades (
            player_id INTEGER PRIMARY KEY,
            drivers_level INTEGER NOT NULL DEFAULT 0,
            advertising_level INTEGER NOT NULL DEFAULT 0,
            dispatch_level INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

    # Таблица достижений игрока (прогресс)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS achievements (
            player_id INTEGER,
            achievement_id TEXT,
            progress INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            completed_at TIMESTAMP,
            PRIMARY KEY (player_id, achievement_id)
        )
    ''')
    
    # Таблица ежедневных заданий
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_quests (
            player_id INTEGER,
            quest_id TEXT,
            progress INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            last_updated TIMESTAMP,
            PRIMARY KEY (player_id, quest_id)
        )
    ''')

    # Таблица постоянных квестов WebApp
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS permanent_quests (
            player_id INTEGER,
            quest_id TEXT,
            progress INTEGER DEFAULT 0,
            completed INTEGER DEFAULT 0,
            reward_claimed INTEGER DEFAULT 0,
            completed_at TIMESTAMP,
            PRIMARY KEY (player_id, quest_id)
        )
    ''')

    # Таблица для истории вращений колеса
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wheel_spins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            prize TEXT,
            amount INTEGER,
            spin_time INTEGER,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')
     
    # ===== МИГРАЦИЯ ТАБЛИЦЫ SKINS ДЛЯ МНОЖЕСТВЕННЫХ КОПИЙ =====
    try:
        cursor.execute("SELECT id FROM skins LIMIT 1")
    except sqlite3.OperationalError:
        # Если колонки id нет – создаём новую таблицу и переносим данные
        cursor.execute('''
            CREATE TABLE skins_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER,
                skin_id TEXT,
                equipped INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('INSERT INTO skins_new (player_id, skin_id, equipped) SELECT player_id, skin_id, equipped FROM skins')
        cursor.execute('DROP TABLE skins')
        cursor.execute('ALTER TABLE skins_new RENAME TO skins')
        print("✅ Таблица skins обновлена для хранения нескольких копий")
    except Exception as e:
        print(f"ℹ️ Миграция skins не требуется: {e}")

    # Добавляем недостающие колонки (если их нет)
    cursor.execute("PRAGMA table_info(players)")
    columns = [col[1] for col in cursor.fetchall()]
    if "notifications" not in columns:
        cursor.execute("ALTER TABLE players ADD COLUMN notifications INTEGER DEFAULT 1")
    if "last_daily_collect" not in columns:
        cursor.execute("ALTER TABLE players ADD COLUMN last_daily_collect INTEGER DEFAULT 0")
    if "last_income_collect" not in columns:
        cursor.execute("ALTER TABLE players ADD COLUMN last_income_collect INTEGER DEFAULT 0")
    
    # Для существующих игроков устанавливаем начальное время для накопления дохода
    cursor.execute("UPDATE players SET last_income_collect = strftime('%s', 'now') WHERE last_income_collect = 0")

    if "market_cycle_key" not in columns:
        cursor.execute("ALTER TABLE players ADD COLUMN market_cycle_key TEXT DEFAULT ''")
    dq_cols = [col[1] for col in cursor.execute("PRAGMA table_info(daily_quests)").fetchall()]
    if "cycle_key" not in dq_cols:
        cursor.execute("ALTER TABLE daily_quests ADD COLUMN cycle_key TEXT DEFAULT ''")
    cursor.execute("CREATE TABLE IF NOT EXISTS api_request_guard (request_key TEXT PRIMARY KEY, endpoint TEXT NOT NULL, player_id INTEGER, created_at INTEGER NOT NULL)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS player_security (player_id INTEGER PRIMARY KEY, first_seen_at INTEGER NOT NULL DEFAULT 0, last_seen_at INTEGER NOT NULL DEFAULT 0, ip_hash TEXT DEFAULT '', ua_hash TEXT DEFAULT '', risk_score INTEGER NOT NULL DEFAULT 0, suspicious_referrals INTEGER NOT NULL DEFAULT 0, meaningful_events INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'normal', ban_reason TEXT DEFAULT '', updated_at INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(player_id) REFERENCES players(id))""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS security_events (id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, event_type TEXT NOT NULL, event_key TEXT DEFAULT '', ip_hash TEXT DEFAULT '', ua_hash TEXT DEFAULT '', score INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, FOREIGN KEY(player_id) REFERENCES players(id))""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_events_player_time ON security_events(player_id,created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_events_ip_time ON security_events(ip_hash,created_at)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS ban_appeals (id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, tg_id INTEGER NOT NULL, appeal_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL, reviewed_at INTEGER DEFAULT 0, reviewed_by INTEGER DEFAULT 0, review_note TEXT DEFAULT '', FOREIGN KEY(player_id) REFERENCES players(id))""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ban_appeals_status_created ON ban_appeals(status,created_at)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS economy_ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, delta INTEGER NOT NULL, balance_after INTEGER NOT NULL, created_at INTEGER NOT NULL, FOREIGN KEY(player_id) REFERENCES players(id))""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_economy_ledger_player_time ON economy_ledger(player_id,created_at)")
    cursor.execute("""CREATE TRIGGER IF NOT EXISTS trg_players_balance_nonnegative BEFORE UPDATE OF balance ON players WHEN NEW.balance < 0 BEGIN SELECT RAISE(ABORT,'balance_negative'); END""")
    cursor.execute("""CREATE TRIGGER IF NOT EXISTS trg_players_balance_ledger AFTER UPDATE OF balance ON players WHEN COALESCE(NEW.balance,0) != COALESCE(OLD.balance,0) BEGIN INSERT INTO economy_ledger(player_id,delta,balance_after,created_at) VALUES(NEW.id,NEW.balance-OLD.balance,NEW.balance,strftime('%s','now')); END""")
    cursor.execute("CREATE TABLE IF NOT EXISTS case_rounds (round_id TEXT PRIMARY KEY, player_id INTEGER NOT NULL, stake INTEGER NOT NULL, status TEXT DEFAULT 'open', created_at INTEGER NOT NULL, paid_amount INTEGER DEFAULT 0)")

    # ===== RESSELL ENGAGEMENT V3 =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_progress (
            player_id INTEGER PRIMARY KEY,
            xp INTEGER NOT NULL DEFAULT 0,
            level INTEGER NOT NULL DEFAULT 1,
            login_streak INTEGER NOT NULL DEFAULT 0,
            last_login_cycle TEXT DEFAULT '',
            last_checkin_at INTEGER DEFAULT 0,
            referral_streak INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_metrics (
            player_id INTEGER PRIMARY KEY,
            farms_completed INTEGER NOT NULL DEFAULT 0,
            passive_collections INTEGER NOT NULL DEFAULT 0,
            container_opens INTEGER NOT NULL DEFAULT 0,
            races_won INTEGER NOT NULL DEFAULT 0,
            upgrades_bought INTEGER NOT NULL DEFAULT 0,
            cars_bought INTEGER NOT NULL DEFAULT 0,
            businesses_bought INTEGER NOT NULL DEFAULT 0,
            xp_events INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_player_progress_level ON player_progress(level)")

    # ===== RCOIN / TON =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rcoin_wallets (
            player_id INTEGER PRIMARY KEY, wallet_address TEXT NOT NULL, network TEXT NOT NULL DEFAULT 'testnet',
            verified INTEGER NOT NULL DEFAULT 0, connected_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rcoin_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, action TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0, token_raw INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
            tx_hash TEXT DEFAULT '', created_at INTEGER NOT NULL, FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rcoin_ledger_player ON rcoin_ledger(player_id, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rcoin_ledger_tx ON rcoin_ledger(tx_hash)")

    # ===== RESSELL R-HOLD CUSTOMIZATION =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rhold_button_skins (
            player_id INTEGER NOT NULL,
            skin_id TEXT NOT NULL,
            purchased_at INTEGER NOT NULL,
            PRIMARY KEY (player_id, skin_id),
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rhold_button_skins_player ON rhold_button_skins(player_id)")

    # ===== RESSELL FRIEND SIGNALS =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS friend_signals (
            player_id INTEGER NOT NULL,
            friend_id INTEGER NOT NULL,
            day_key TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (player_id, friend_id, day_key)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_friend_signals_friend_day ON friend_signals(friend_id,day_key)")
    conn.commit()
    conn.close()

def upgrade_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Persistent interface language for Mini App. Existing players stay RU by default.
    cursor.execute("PRAGMA table_info(players)")
    _player_cols = [c[1] for c in cursor.fetchall()]
    if "language" not in _player_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN language TEXT DEFAULT 'ru'")
    
    # Добавляем колонки для обслуживания магазинов
    cursor.execute("PRAGMA table_info(user_shops)")
    cols = [c[1] for c in cursor.fetchall()]
    if "last_payment" not in cols:
        cursor.execute("ALTER TABLE user_shops ADD COLUMN last_payment INTEGER DEFAULT 0")
    if "status" not in cols:
        cursor.execute("ALTER TABLE user_shops ADD COLUMN status TEXT DEFAULT 'active'")
    if "paid_until" not in cols:
        cursor.execute("ALTER TABLE user_shops ADD COLUMN paid_until INTEGER DEFAULT 0")
    if "purchase_price" not in cols:
        cursor.execute("ALTER TABLE user_shops ADD COLUMN purchase_price INTEGER DEFAULT 0")
    
    # Добавляем колонки для таксопарков
    try:
        cursor.execute("ALTER TABLE user_taxoparks ADD COLUMN purchase_price INTEGER DEFAULT 0")
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e) and "duplicate column name" not in str(e):
            raise
    
    # Таблица для депозитов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            amount INTEGER,
            start_time INTEGER,
            duration_days INTEGER,
            interest_rate REAL,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')
    
    # Таблица для кредитов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            amount INTEGER,
            interest_rate REAL,
            start_time INTEGER,
            due_date INTEGER,
            status TEXT DEFAULT 'active',
            paid_amount INTEGER DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

    # Таблица для майнинг-ферм
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_rigs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            rig_type TEXT,
            hash_rate INTEGER,
            daily_income INTEGER,
            price INTEGER,
            purchase_time INTEGER,
            status TEXT DEFAULT 'active',
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')

    # Таблица глобального джекпота
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS casino_jackpot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            amount INTEGER DEFAULT 100000
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO casino_jackpot (id, amount) VALUES (1, 100000)")
    
    # Получаем список существующих колонок в players
    cursor.execute("PRAGMA table_info(players)")
    existing_cols = [col[1] for col in cursor.fetchall()]
    
    # Legacy casino_balance column may remain in old databases; operational code uses only balance.
    if "balance" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN balance INTEGER DEFAULT 0")

    # Перенос старого отдельного казино-баланса в единый balance.
    # После этого legacy-колонка остаётся только для совместимости старой схемы БД,
    # но больше нигде не используется как отдельный кошелёк.
    if "casino_balance" in existing_cols:
        cursor.execute("UPDATE players SET balance = COALESCE(balance,0) + COALESCE(casino_balance,0), casino_balance = 0 WHERE COALESCE(casino_balance,0) != 0")

    # Статистика казино для игроков
    if "casino_games_played" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_games_played INTEGER DEFAULT 0")
    if "casino_total_bet" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_total_bet INTEGER DEFAULT 0")
    if "casino_total_win" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_total_win INTEGER DEFAULT 0")
    if "casino_wins" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_wins INTEGER DEFAULT 0")
    if "casino_losses" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_losses INTEGER DEFAULT 0")

    # Колонки для скинов
    if "skin" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN skin TEXT DEFAULT 'default'")
    if "skin_inventory" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN skin_inventory TEXT DEFAULT '[\"default\"]'")
    
    # Колонки для уведомлений и сбора дохода
    if "notifications" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN notifications INTEGER DEFAULT 1")
    if "last_daily_collect" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN last_daily_collect INTEGER DEFAULT 0")
    if "last_income_collect" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN last_income_collect INTEGER DEFAULT 0")
    
    # Колонки для статистики продаж и прибыли
    if "total_profit" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN total_profit INTEGER DEFAULT 0")
    if "total_earned" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN total_earned INTEGER DEFAULT 0")
    if "stat_earned_today" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN stat_earned_today INTEGER DEFAULT 0")
    if "stat_sold_today" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN stat_sold_today INTEGER DEFAULT 0")
    if "total_sales" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN total_sales INTEGER DEFAULT 0")
    if "items_sold" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN items_sold INTEGER DEFAULT 0")
    if "epoch_claimed" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN epoch_claimed TEXT DEFAULT '[]'")
    
    # Таблица акций игроков (портфель)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            symbol TEXT,
            quantity INTEGER DEFAULT 0,
            avg_buy_price INTEGER DEFAULT 0,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')
    
    # Таблица текущих цен акций
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_prices (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            price INTEGER,
            change_pct REAL,
            last_update INTEGER
        )
    ''')
    
    # История сделок с акциями
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stock_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER,
            symbol TEXT,
            type TEXT,
            quantity INTEGER,
            price INTEGER,
            total INTEGER,
            date TEXT,
            FOREIGN KEY (player_id) REFERENCES players(id)
        )
    ''')
    
    # Добавляем начальные акции (если таблица пуста)
    cursor.execute("SELECT COUNT(*) FROM stock_prices")
    if cursor.fetchone()[0] == 0:
        stocks = [
            ("AAPL", "Apple Inc.", 17500, 0.0),
            ("GOOGL", "Google", 13500, 0.0),
            ("TSLA", "Tesla", 24000, 0.0),
            ("AMZN", "Amazon", 17800, 0.0),
            ("MSFT", "Microsoft", 42000, 0.0),
        ]
        now = int(time_module.time())
        for sym, name, price, change in stocks:
            cursor.execute(
                "INSERT INTO stock_prices (symbol, name, price, change_pct, last_update) VALUES (?, ?, ?, ?, ?)",
                (sym, name, price, change, now)
            )
    
    # Добавляем колонку total_stock_value в players (необязательно, для быстрого доступа)
    if "total_stock_value" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN total_stock_value INTEGER DEFAULT 0")

    # Статистика конкретных экземпляров автомобилей: пробег, износ, заработок.
    # Нужна для гаража и таксопарка. Миграция обязательна для старых БД.
    if "garage_car_stats" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN garage_car_stats TEXT DEFAULT '[]'")

    # AUTHORITATIVE TAXI VEHICLE STATE.  Kept in a dedicated table so no
    # generic player update can ever reset a vehicle's wear back to zero.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS taxi_vehicle_state (
            player_id INTEGER NOT NULL, instance_index INTEGER NOT NULL,
            car_id TEXT NOT NULL DEFAULT '', wear REAL NOT NULL DEFAULT 0,
            mileage REAL NOT NULL DEFAULT 0, total_income INTEGER NOT NULL DEFAULT 0,
            line_started_at INTEGER NOT NULL DEFAULT 0, taxi_last_tick_at INTEGER NOT NULL DEFAULT 0,
            wear_before REAL NOT NULL DEFAULT 0, mileage_before REAL NOT NULL DEFAULT 0,
            income_before INTEGER NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT 0,
            is_broken INTEGER NOT NULL DEFAULT 0, broken_at INTEGER,
            PRIMARY KEY (player_id, instance_index)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_taxi_vehicle_state_player ON taxi_vehicle_state(player_id)")

    # ==================== RESSELL MARKET HUB / NIGHTCLUB ====================
    # One-time capital sinks and the Night Club loop. Kept separate from
    # businesses, Auto and the existing R-HOLD/Avito catalogs to avoid duplicate
    # functions. All ownership is server-side and idempotent.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS resell_market_assets (
            player_id INTEGER NOT NULL,
            asset_id TEXT NOT NULL,
            purchased_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (player_id, asset_id),
            FOREIGN KEY(player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resell_market_assets_player ON resell_market_assets(player_id)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS night_clubs (
            player_id INTEGER PRIMARY KEY,
            level INTEGER NOT NULL DEFAULT 0,
            venue_style TEXT NOT NULL DEFAULT 'afterdark',
            pending_income INTEGER NOT NULL DEFAULT 0,
            total_income INTEGER NOT NULL DEFAULT 0,
            last_tick_at INTEGER NOT NULL DEFAULT 0,
            guest_count INTEGER NOT NULL DEFAULT 0,
            reputation INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(player_id) REFERENCES players(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_night_clubs_level ON night_clubs(level)")
    try:
        legacy_rows=cursor.execute("SELECT id,car_collection,garage_car_stats FROM players WHERE car_collection IS NOT NULL").fetchall()
        migration_now=int(time_module.time())
        for legacy in legacy_rows:
            pid0=int(legacy[0]); owned0=_safe_json_list(legacy[1] or '[]')
            stats0=_safe_car_stats(legacy[2] or '[]',len(owned0),migration_now)
            for idx0,cid0 in enumerate(owned0):
                if cursor.execute("SELECT 1 FROM taxi_vehicle_state WHERE player_id=? AND instance_index=?",(pid0,idx0)).fetchone():
                    continue
                st0=stats0[idx0] if idx0<len(stats0) and isinstance(stats0[idx0],dict) else {}
                line=int(st0.get('line_started_at') or st0.get('taxi_last_tick_at') or st0.get('updated_at') or 0)
                wear=float(st0.get('wear',0) or 0); mileage=float(st0.get('mileage',0) or 0); income=int(st0.get('total_income',0) or 0)
                cursor.execute(
                    "INSERT INTO taxi_vehicle_state(player_id,instance_index,car_id,wear,mileage,total_income,line_started_at,taxi_last_tick_at,wear_before,mileage_before,income_before,updated_at,is_broken,broken_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid0,idx0,str(cid0 or ''),wear,mileage,income,line,int(st0.get('taxi_last_tick_at') or line),float(st0.get('wear_before',wear) or 0),float(st0.get('mileage_before',mileage) or 0),int(st0.get('income_before',income) or 0),int(st0.get('updated_at') or migration_now),1 if bool(st0.get('is_broken')) else 0,st0.get('broken_at'))
                )
    except Exception as exc:
        print(f'[TAXI_DB] legacy migration warning: {exc}')

    # Mining idempotency: prevents duplicate hourly payouts when multiple app workers briefly overlap.
    cursor.execute("PRAGMA table_info(mining_rigs)")
    mining_cols=[c[1] for c in cursor.fetchall()]
    if "last_paid_at" not in mining_cols:
        cursor.execute("ALTER TABLE mining_rigs ADD COLUMN last_paid_at INTEGER DEFAULT 0")

    # ===================== ПОКЕРНЫЕ ТАБЛИЦЫ =====================
    # 1. poker_games – все необходимые колонки
    cursor.execute("PRAGMA table_info(poker_games)")
    poker_games_cols = [c[1] for c in cursor.fetchall()]
    
    required_games = {
        "player_id": "INTEGER",
        "status": "TEXT DEFAULT 'active'",
        "stage": "TEXT DEFAULT 'preflop'",
        "pot": "INTEGER DEFAULT 0",
        "community_cards": "TEXT DEFAULT '[]'",
        "deck": "TEXT DEFAULT '[]'",
        "buy_in": "INTEGER DEFAULT 0",
        "created_at": "INTEGER DEFAULT 0",
        "updated_at": "INTEGER DEFAULT 0",
        "current_turn": "INTEGER DEFAULT 0",
        "payout_done": "INTEGER DEFAULT 0"
    }
    
    for col, type_def in required_games.items():
        if col not in poker_games_cols:
            cursor.execute(f"ALTER TABLE poker_games ADD COLUMN {col} {type_def}")
            print(f"✅ Добавлена колонка {col} в poker_games")

    # 2. poker_hands – все необходимые колонки
    cursor.execute("PRAGMA table_info(poker_hands)")
    poker_hands_cols = [c[1] for c in cursor.fetchall()]
    
    required_hands = {
        "seat_number": "INTEGER NOT NULL",
        "player_id": "INTEGER",
        "bot_id": "TEXT",
        "bot_type": "TEXT",
        "cards": "TEXT",
        "name": "TEXT",
        "avatar": "TEXT",
        "is_bot": "INTEGER DEFAULT 0",
        "stack": "INTEGER DEFAULT 0",
        "current_bet": "INTEGER DEFAULT 0",
        "total_bet": "INTEGER DEFAULT 0",
        "folded": "INTEGER DEFAULT 0",
        "all_in": "INTEGER DEFAULT 0"
    }
    for col, type_def in required_hands.items():
        if col not in poker_hands_cols:
            cursor.execute(f"ALTER TABLE poker_hands ADD COLUMN {col} {type_def}")
            print(f"✅ Добавлена колонка {col} в poker_hands")

    conn.commit()
    conn.close()

def ensure_stock_prices():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM stock_prices")
    if cursor.fetchone()[0] == 0:
        stocks = [
            ("AAPL", "Apple Inc.", 17500),
            ("GOOGL", "Google", 13500),
            ("TSLA", "Tesla", 24000),
            ("AMZN", "Amazon", 17800),
            ("MSFT", "Microsoft", 42000),
        ]
        now = int(time_module.time())
        for sym, name, price in stocks:
            cursor.execute(
                "INSERT INTO stock_prices (symbol, name, price, change_pct, last_update) VALUES (?, ?, ?, 0.0, ?)",
                (sym, name, price, now)
            )
        conn.commit()
        print("✅ Добавлены начальные акции в stock_prices (таблица была пуста)")
    else:
        print("ℹ️ Таблица stock_prices уже содержит данные")
    conn.close()

def get_db():
    # WAL is configured once during init_db. Repeating journal_mode for every
    # request adds avoidable coordination/write overhead under load.
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def get_or_create_player(platform: str, platform_id: int) -> int:
    conn = get_db()
    cursor = conn.cursor()
    field = 'tg_id' if platform == 'tg' else 'vk_id'
    cursor.execute(f"SELECT id FROM players WHERE {field} = ?", (platform_id,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row['id']
    base_nick = f"Игрок_{platform_id}"
    nickname = base_nick
    counter = 1
    while True:
        cursor.execute("SELECT id FROM players WHERE nickname = ?", (nickname,))
        if not cursor.fetchone():
            break
        nickname = f"{base_nick}_{counter}"
        counter += 1
    cursor.execute(f"INSERT INTO players ({field}, nickname, shop_name, balance) VALUES (?, ?, ?, ?)",
                   (platform_id, nickname, "Моя лавка", 25_000))
    conn.commit()
    player_id = cursor.lastrowid
    cursor.execute("INSERT INTO referrals (player_id, invited) VALUES (?, '[]')", (player_id,))
    cursor.execute("INSERT INTO learning (player_id, completed) VALUES (?, '[]')", (player_id,))
    cursor.execute("INSERT INTO skins (player_id, skin_id, equipped) VALUES (?, 'default', 1)", (player_id,))
    conn.commit()
    conn.close()
    return player_id

def get_player_data(player_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE id = ?", (player_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        data = dict(row)
        for field in ['inventory', 'car_collection', 'taxopark', 'market_demand', 'skin_inventory', 'trading_portfolio', 'current_event']:
            if field in data and data[field]:
                try:
                    data[field] = json.loads(data[field])
                except:
                    pass
        return data
    return None

def make_item_uid() -> str:
    return uuid.uuid4().hex[:16]

def normalize_inventory(items: List[dict]) -> tuple[List[dict], bool]:
    changed = False
    result = []
    for raw in items or []:
        item = dict(raw or {})
        if not item.get("uid"):
            item["uid"] = make_item_uid(); changed = True
        item.setdefault("cat", "🎒 Аксессуары")
        try:
            item["buy_price"] = max(0, int(item.get("buy_price", 0)))
            item["market_price"] = max(1, int(item.get("market_price", item["buy_price"] or 1)))
        except Exception:
            item["buy_price"] = 0; item["market_price"] = 1; changed = True
        result.append(item)
    return result, changed

def market_cycle_key(now=None) -> str:
    now = now or datetime.now()
    return (now.date() if now.hour >= 12 else (now - timedelta(days=1)).date()).isoformat()

def _event_for_cycle(player_id: int, cycle_key: str) -> Optional[dict]:
    seed = int(hashlib.sha256(f"event:{player_id}:{cycle_key}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    if rng.random() < 0.22:
        return None
    return dict(rng.choice(MARKET_EVENTS))

def build_market_state(player: Dict[str, Any], cycle_key: str) -> tuple[dict, Optional[dict]]:
    pid = int(player.get("id", 0))
    seed = int(hashlib.sha256(f"market:{pid}:{cycle_key}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    month = datetime.fromisoformat(cycle_key).month
    seasonal = {c: 1.0 for c in CATEGORIES}
    if month in (12,1,2):
        seasonal.update({"🧥 Куртки":1.22, "👕 Худи":1.14, "👟 Кроссы":0.96})
    elif month in (6,7,8):
        seasonal.update({"🧥 Куртки":0.78, "👖 Джинсы":0.94, "👟 Кроссы":1.12, "🎒 Аксессуары":1.10})
    elif month in (9,10,11):
        seasonal.update({"🧥 Куртки":1.16, "👕 Худи":1.10, "👖 Джинсы":1.08})
    velocity = min(0.12, int(player.get("stat_sold_today",0) or 0)*0.01)
    demand={}
    for cat in CATEGORIES:
        demand[cat] = round(max(0.35,min(2.35,(1+rng.uniform(-0.10,0.10)+velocity)*seasonal.get(cat,1.0))),3)
    event=_event_for_cycle(pid,cycle_key)
    if event and event.get("cat") in demand:
        demand[event["cat"]]=round(max(0.35,min(3.0,demand[event["cat"]]*float(event.get("mult",1.0)))),3)
    elif event and event.get("global"):
        demand={k:round(max(0.35,min(3.0,v*1.05)),3) for k,v in demand.items()}
    return demand,event

def ensure_market_state_sync(player_id: int, player: Optional[dict]=None) -> dict:
    player=player or get_player_data(player_id)
    if not player: return {}
    cycle=market_cycle_key()
    if player.get("market_cycle_key")==cycle and isinstance(player.get("market_demand"),dict) and player.get("market_demand"):
        return player
    demand,event=build_market_state(player,cycle)
    update_player_data(player_id,{"market_demand":demand,"current_event":event,"market_cycle_key":cycle})
    return get_player_data(player_id) or player

def ensure_inventory_uids_sync(player_id: int, player: Optional[dict]=None) -> dict:
    player=player or get_player_data(player_id)
    if not player: return {}
    inv,changed=normalize_inventory(player.get("inventory",[])); player["inventory"]=inv
    if changed: update_player_data(player_id,{"inventory":inv})
    return player

def get_inventory_item(inventory: List[dict], identifier):
    token=str(identifier) if identifier is not None else ""
    for idx,item in enumerate(inventory or []):
        if str(item.get("uid"))==token: return item,idx
    try:
        idx=int(token)
        if 0<=idx<len(inventory): return inventory[idx],idx
    except Exception: pass
    return None,None

def _safe_int(value, default=0):
    try: return int(value)
    except Exception: return default


def _telegram_normalize_token(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def _telegram_init_data_candidates(request: Request):
    """Collect Telegram initData from supported transports, preserving signed values."""
    out = []

    def add_candidate(value):
        value = str(value or "").strip()
        if not value:
            return
        out.append(value)
        # Compatibility for a proxy that percent-encoded the complete payload.
        if "%" in value and any(marker in value.upper() for marker in ("%3D", "%26", "%7B")):
            try:
                decoded = unquote(value).strip()
                if decoded and decoded != value:
                    out.append(decoded)
            except Exception:
                pass

    for name in ("X-Telegram-Init-Data", "x-telegram-init-data"):
        add_candidate(request.headers.get(name))

    auth = str(request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("tma "):
        add_candidate(auth[4:].strip())

    b64 = str(request.query_params.get("tg_auth_b64") or "").strip()
    if b64:
        try:
            raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8")
            add_candidate(raw)
        except Exception as exc:
            print(f"[TG_AUTH] bad tg_auth_b64: {type(exc).__name__}: {exc}")

    for key in ("initData", "tgWebAppData"):
        v = str(request.query_params.get(key) or "").strip()
        if v:
            try:
                if "&" not in v and ("%26" in v.lower() or "%3d" in v.lower() or "%3f" in v.lower()):
                    v = unquote(v).strip()
            except Exception:
                pass
            add_candidate(v)

    return list(dict.fromkeys(x for x in out if x))


def _telegram_init_data_from_request(request: Request) -> str:
    return next(iter(_telegram_init_data_candidates(request)), "")


_TELEGRAM_RESOLVED_TOKEN = ""
_TELEGRAM_RESOLVED_BOT_ID = 0
_TELEGRAM_RESOLVED_BOT_USERNAME = ""
_TELEGRAM_RESOLVED_TOKEN_SOURCE = ""

# Telegram's production Ed25519 public key for validating `signature` in
# third-party/current Mini App payloads. HMAC verification remains the primary
# path; this is a standards-based fallback bound to the bot id.
_TELEGRAM_ED25519_PUBLIC_KEY = "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d"


def _telegram_token_candidates():
    """Return every configured token, plus the exact token used by aiogram."""
    out = []

    # The running Bot instance is the strongest source because it is the token
    # actually used for polling/API calls by this process.
    try:
        running_token = _telegram_normalize_token(getattr(bot, "token", ""))
        if running_token:
            out.append(running_token)
    except Exception:
        pass

    for name in ("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "API_TOKEN", "RESELL_BOT_TOKEN"):
        value = os.getenv(name)
        if not value:
            value = globals().get(name)
        value = _telegram_normalize_token(value)
        if value and value not in out:
            out.append(value)
    return out


def _telegram_bot_token():
    if _TELEGRAM_RESOLVED_TOKEN:
        return _TELEGRAM_RESOLVED_TOKEN
    values = _telegram_token_candidates()
    return values[0] if values else ""


def _telegram_bot_id_candidates():
    out = []
    for source in (
        os.getenv("TELEGRAM_BOT_ID"),
        os.getenv("BOT_ID"),
        _TELEGRAM_RESOLVED_BOT_ID,
    ):
        try:
            value = int(str(source or "").strip())
        except Exception:
            value = 0
        if value > 0 and value not in out:
            out.append(value)

    # Prefer the bot identity resolved during startup. In deployments where
    # startup logging was skipped, use the aiogram Bot identity if available.
    try:
        value = int(_TELEGRAM_RESOLVED_BOT_ID or getattr(bot, "id", 0) or 0)
    except Exception:
        value = 0
    if value > 0 and value not in out:
        out.append(value)
    return out


async def _resolve_telegram_bot_token():
    """Resolve the actual running Telegram bot identity without weakening HMAC."""
    global _TELEGRAM_RESOLVED_TOKEN, _TELEGRAM_RESOLVED_BOT_ID
    global _TELEGRAM_RESOLVED_BOT_USERNAME, _TELEGRAM_RESOLVED_TOKEN_SOURCE

    candidates = _telegram_token_candidates()
    if not candidates:
        print("[TG_AUTH] FATAL: no Telegram bot token configured")
        return

    expected = _telegram_normalize_token(
        os.getenv("BOT_USERNAME") or globals().get("BOT_USERNAME") or ""
    ).lstrip("@").lower()

    probes = []
    for idx, token in enumerate(candidates):
        try:
            probe = Bot(token=token)
            me = await probe.get_me()
            await probe.session.close()
            username = str(me.username or "").strip().lstrip("@").lower()
            fp = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            print(f"[TG_AUTH] token_candidate_{idx+1}: bot_id={me.id} username=@{username} token_fp={fp}")
            probes.append((token, int(me.id or 0), username, idx))
        except Exception as exc:
            print(f"[TG_AUTH] token_candidate_{idx+1} probe failed: {type(exc).__name__}: {exc}")

    chosen = next((x for x in probes if expected and x[2] == expected), None)
    if chosen is None and probes:
        # The first probe is the same token the bot process uses in normal
        # deployments, because _telegram_token_candidates() puts bot.token first.
        chosen = probes[0]

    if chosen:
        token, bot_id, username, idx = chosen
        _TELEGRAM_RESOLVED_TOKEN = token
        _TELEGRAM_RESOLVED_BOT_ID = int(bot_id or 0)
        _TELEGRAM_RESOLVED_BOT_USERNAME = username
        _TELEGRAM_RESOLVED_TOKEN_SOURCE = f"candidate_{idx+1}"
        fp = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
        print(
            f"[TG_AUTH] resolved_bot_id={bot_id} username=@{username} "
            f"token_fp={fp} source={_TELEGRAM_RESOLVED_TOKEN_SOURCE}"
        )
    else:
        print("[TG_AUTH] FATAL: no usable Telegram bot token")


def _telegram_parse_init_data(raw: str):
    """Parse initData without rebuilding or normalizing the signed payload."""
    raw = str(raw or "").strip()
    if not raw:
        return {}, ""

    # Support a whole initData value that arrived percent-encoded as one field.
    if "query_id%3D" in raw.lower() or "auth_date%3D" in raw.lower():
        try:
            decoded = unquote(raw)
            if decoded and "=" in decoded:
                raw = decoded
        except Exception:
            pass

    items = parse_qsl(raw, keep_blank_values=True, strict_parsing=False)
    data = {}
    received_hash = ""
    for key, value in items:
        if key == "hash":
            received_hash = value
        else:
            # Telegram has unique keys; last-value semantics are kept for
            # malformed duplicate-key inputs.
            data[key] = value
    return data, str(received_hash or "")


def _telegram_hmac_checks(data: dict):
    """Return Telegram HMAC check variants, including current signature payloads."""
    # Bot API docs define HMAC validation over all received fields sorted by key.
    full = "\n".join(f"{k}={v}" for k, v in sorted(data.items(), key=lambda x: x[0]))
    checks = [("full", full)]

    # Modern Mini Apps may additionally carry the Ed25519 `signature` field.
    # That field belongs to Telegram's third-party signature flow; keep a
    # compatibility HMAC form for payloads where the hash was generated without
    # that auxiliary signature field.
    if "signature" in data:
        compat = {k: v for k, v in data.items() if k != "signature"}
        without_sig = "\n".join(
            f"{k}={v}" for k, v in sorted(compat.items(), key=lambda x: x[0])
        )
        checks.append(("without_signature", without_sig))
    return checks


def _telegram_verify_ed25519(data: dict, signature_value: str, bot_id: int) -> bool:
    """Verify Telegram's current `signature` field using the official public key."""
    if not signature_value or not bot_id:
        return False
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature

        signature = base64.urlsafe_b64decode(
            str(signature_value) + "=" * (-len(str(signature_value)) % 4)
        )
        # Official third-party validation string:
        # <bot_id>:WebAppData + LF + all fields except hash/signature, sorted.
        check_data = {k: v for k, v in data.items() if k not in ("hash", "signature")}
        check = "\n".join(
            f"{k}={v}" for k, v in sorted(check_data.items(), key=lambda x: x[0])
        )
        message = f"{int(bot_id)}:WebAppData\n{check}".encode("utf-8")

        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(_TELEGRAM_ED25519_PUBLIC_KEY)
        ).verify(signature, message)
        return True
    except InvalidSignature:
        return False
    except Exception as exc:
        print(f"[TG_AUTH] ed25519 unavailable/failed: {type(exc).__name__}: {exc}")
        return False


def _telegram_extract_uid(data: dict) -> int:
    user_raw = str(data.get("user") or "")
    try:
        user = json.loads(user_raw)
        return int(user.get("id") or 0)
    except Exception:
        match = re.search(r'"id"\s*:\s*(\d+)', user_raw)
        return int(match.group(1)) if match else 0


def _telegram_verify_one(raw: str, tg_id: int, max_age: int):
    """Strict Telegram Mini App validation with HMAC + current Ed25519 fallback."""
    try:
        raw = str(raw or "").strip()
        if not raw:
            return False, "missing_init_data"

        data, received_hash = _telegram_parse_init_data(raw)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", str(received_hash or "")):
            return False, "bad_hash_format"

        auth_date = int(data.get("auth_date") or 0)
        now = int(time_module.time())
        if auth_date <= 0:
            return False, "bad_auth_date"
        if auth_date > now + 7 * 24 * 3600:
            return False, "auth_date_future"
        if now - auth_date > max(300, int(max_age)):
            return False, "auth_date_expired"

        uid = _telegram_extract_uid(data)
        if uid <= 0:
            return False, "user_id_missing"
        if uid != int(tg_id):
            return False, "user_id_mismatch"

        tokens = _telegram_token_candidates()
        if _TELEGRAM_RESOLVED_TOKEN and _TELEGRAM_RESOLVED_TOKEN not in tokens:
            tokens.insert(0, _TELEGRAM_RESOLVED_TOKEN)

        checks = _telegram_hmac_checks(data)
        received = str(received_hash).lower()

        # 1) Standard bot-token HMAC, using the exact token of the running bot
        # first and every explicitly configured fallback after it.
        for idx, token in enumerate(tokens):
            secret = hmac.new(
                b"WebAppData", token.encode("utf-8"), hashlib.sha256
            ).digest()
            for variant, check in checks:
                calculated = hmac.new(
                    secret, check.encode("utf-8"), hashlib.sha256
                ).hexdigest()
                if hmac.compare_digest(calculated, received):
                    fp = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
                    source = "running_bot" if idx == 0 else f"candidate_{idx+1}"
                    print(
                        f"[TG_AUTH] verified tg_id={tg_id} token_fp={fp} "
                        f"source={source} variant={variant} method=hmac"
                    )
                    return True, "ok"

        # 2) Standards-based current Telegram signature fallback. It is still
        # bound to this bot's identity via bot_id and cannot authenticate a
        # different Telegram app/bot.
        signature = str(data.get("signature") or "")
        for bot_id in _telegram_bot_id_candidates():
            if _telegram_verify_ed25519(data, signature, bot_id):
                print(
                    f"[TG_AUTH] verified tg_id={tg_id} bot_id={bot_id} "
                    "method=ed25519_signature"
                )
                return True, "ok"

        return False, "hmac_mismatch"
    except Exception as exc:
        print(f"[TG_AUTH] candidate failed: {type(exc).__name__}: {exc}")
        return False, f"verifier_error:{type(exc).__name__}"


def _telegram_verify_reason(
    request: Request, tg_id: int, max_age: int = 365 * 24 * 60 * 60
):
    candidates = _telegram_init_data_candidates(request)
    if not candidates:
        return False, "missing_init_data"

    reasons = []
    for raw in candidates:
        ok, reason = _telegram_verify_one(raw, int(tg_id), int(max_age))
        if ok:
            return True, "ok"
        reasons.append(reason)

    priority = (
        "bot_token_missing",
        "user_id_mismatch",
        "auth_date_expired",
        "auth_date_future",
        "bad_auth_date",
        "bad_hash_format",
        "hmac_mismatch",
    )
    for item in priority:
        if item in reasons:
            return False, item
    return False, reasons[0] if reasons else "bad_init_data"


def _verify_telegram_webapp_request(
    request: Request, tg_id: int, max_age: int = 365 * 24 * 60 * 60
) -> bool:
    ok, reason = _telegram_verify_reason(request, tg_id, max_age)
    if not ok:
        print(
            f"[TG_AUTH] 401 path={request.url.path} tg_id={tg_id} "
            f"reason={reason} candidates={len(_telegram_init_data_candidates(request))}"
        )
    return bool(ok)


def _verify_tycoon_webapp_request(request: Request, tg_id: int) -> bool:
    return _verify_telegram_webapp_request(request, tg_id)


def _verify_hold_and_checkin_request(request: Request, tg_id: int) -> bool:
    return _verify_telegram_webapp_request(request, int(tg_id))

def _security_hash(value: str) -> str:
    return hashlib.sha256((str(globals().get("BOT_TOKEN") or "resell")+"|"+str(value or "")).encode("utf-8","ignore")).hexdigest()

def _request_security_fingerprint(request: Request) -> Tuple[str,str]:
    """Return privacy-preserving request fingerprints. Prefer the real client IP headers supplied by a trusted reverse proxy."""
    host = ""
    try:
        for header_name in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
            raw = str(request.headers.get(header_name) or "").strip()
            if raw:
                host = raw.split(",", 1)[0].strip()
                if host:
                    break
        if not host:
            host = (request.client.host if request.client else "") or ""
    except Exception:
        host = ""
    ua = str(request.headers.get("user-agent") or "")[:512]
    return _security_hash(host),_security_hash(ua)

def _security_touch_sync(player_id:int,event_type:str,ip_hash:str,ua_hash:str,event_key:str="") -> None:
    now=int(time_module.time()); conn=get_db()
    try:
        row=conn.execute("SELECT 1 FROM player_security WHERE player_id=?",(int(player_id),)).fetchone()
        if row: conn.execute("UPDATE player_security SET last_seen_at=?,ip_hash=?,ua_hash=?,updated_at=? WHERE player_id=?",(now,ip_hash,ua_hash,now,int(player_id)))
        else: conn.execute("INSERT INTO player_security(player_id,first_seen_at,last_seen_at,ip_hash,ua_hash,updated_at) VALUES(?,?,?,?,?,?)",(int(player_id),now,now,ip_hash,ua_hash,now))
        conn.execute("INSERT INTO security_events(player_id,event_type,event_key,ip_hash,ua_hash,created_at) VALUES(?,?,?,?,?,?)",(int(player_id),str(event_type)[:64],str(event_key)[:160],ip_hash,ua_hash,now))
        conn.commit()
    finally: conn.close()

def _referral_qualification_sync(invitee_tg_id:int,inviter_tg_id:int)->Dict[str,Any]:
    now=int(time_module.time()); conn=get_db()
    try:
        p=conn.execute("SELECT created_at FROM referral_pending WHERE invitee_tg_id=? AND inviter_tg_id=?",(int(invitee_tg_id),int(inviter_tg_id))).fetchone()
        if not p: return {"qualified":False,"reason":"no_pending"}
        if now-int(p["created_at"] or now)<REFERRAL_MIN_ACCOUNT_AGE_SECONDS: return {"qualified":False,"reason":"account_too_new"}
        rows=conn.execute("SELECT DISTINCT event_type FROM security_events se JOIN players pl ON pl.id=se.player_id WHERE pl.tg_id=? AND se.created_at>=?",(int(invitee_tg_id),int(p["created_at"]))).fetchall()
        types={str(r[0]) for r in rows}
        if len(types)<REFERRAL_MIN_UNIQUE_ACTIONS: return {"qualified":False,"reason":"not_enough_distinct_actions","unique_actions":len(types)}
        span=conn.execute("SELECT COALESCE(MIN(se.created_at),0),COALESCE(MAX(se.created_at),0) FROM security_events se JOIN players pl ON pl.id=se.player_id WHERE pl.tg_id=? AND se.created_at>=?",(int(invitee_tg_id),int(p["created_at"]))).fetchone()
        if int(span[1])-int(span[0])<REFERRAL_MIN_ACTIVITY_SPAN_SECONDS: return {"qualified":False,"reason":"activity_too_short"}
        economic={"game_result","case_purchase","container_open","container_sell","passive_collect","race_join","upgrade_buy","buy_car","buy_shop","taxi_collect","sale"}
        if not types & economic: return {"qualified":False,"reason":"no_economic_action"}
        a=conn.execute("SELECT ip_hash,ua_hash FROM player_security ps JOIN players pl ON pl.id=ps.player_id WHERE pl.tg_id=?",(int(inviter_tg_id),)).fetchone()
        b=conn.execute("SELECT ip_hash,ua_hash FROM player_security ps JOIN players pl ON pl.id=ps.player_id WHERE pl.tg_id=?",(int(invitee_tg_id),)).fetchone()
        if not a or not b: return {"qualified":False,"reason":"security_profile_missing"}
        same_ip=bool(a[0] and a[0]==b[0]); same_ua=bool(a[1] and a[1]==b[1]); rapid1=int(conn.execute("SELECT COUNT(*) FROM referral_pending WHERE inviter_tg_id=? AND created_at>=?",(int(inviter_tg_id),now-3600)).fetchone()[0]); rapid24=int(conn.execute("SELECT COUNT(*) FROM referral_pending WHERE inviter_tg_id=? AND created_at>=?",(int(inviter_tg_id),now-86400)).fetchone()[0])
        score=(40 if same_ip else 0)+(20 if same_ua else 0)+(10 if same_ip and same_ua else 0)+(20 if rapid1>=REFERRAL_RAPID_LINK_LIMIT_1H else 0)+(20 if rapid24>=REFERRAL_RAPID_LINK_LIMIT_24H else 0)
        return {"qualified":True,"suspicious_score":score,"same_ip":same_ip,"same_ua":same_ua}
    finally: conn.close()

def _register_referral_suspicion_sync(inviter_tg_id:int,invitee_tg_id:int,score:int,reason:str)->Dict[str,Any]:
    now=int(time_module.time()); conn=get_db()
    try:
        p=conn.execute("SELECT id FROM players WHERE tg_id=?",(int(inviter_tg_id),)).fetchone()
        if not p: return {"banned":False}
        key=f"{int(invitee_tg_id)}"
        exists=conn.execute("SELECT 1 FROM security_events WHERE player_id=? AND event_type='referral_suspicious_pair' AND event_key=? AND created_at>=?",(int(p[0]),key,now-86400)).fetchone()
        if exists: return {"banned":False}
        conn.execute("INSERT INTO security_events(player_id,event_type,event_key,score,created_at) VALUES(?,?,?,?,?)",(int(p[0]),"referral_suspicious_pair",key,int(score),now))
        pairs=int(conn.execute("SELECT COUNT(DISTINCT event_key) FROM security_events WHERE player_id=? AND event_type='referral_suspicious_pair' AND created_at>=?",(int(p[0]),now-86400)).fetchone()[0])
        old=int(conn.execute("SELECT COALESCE(risk_score,0) FROM player_security WHERE player_id=?",(int(p[0]),)).fetchone()[0])
        risk=min(100,old+int(score)); banned=bool(risk>=REFERRAL_AUTO_BAN_RISK or pairs>=REFERRAL_AUTO_BAN_SUSPICIOUS_PAIRS)
        conn.execute("UPDATE player_security SET risk_score=?,suspicious_referrals=?,status=?,ban_reason=?,updated_at=? WHERE player_id=?",(risk,pairs,"banned" if banned else "normal",reason if banned else "",now,int(p[0])))
        if banned: conn.execute("UPDATE players SET is_banned=1 WHERE id=?",(int(p[0]),))
        conn.commit(); return {"banned":banned,"risk":risk,"suspicious_pairs":pairs}
    finally: conn.close()

def _ban_status_sync(tg_id:int)->Dict[str,Any]:
    conn=get_db()
    try:
        p=conn.execute("SELECT id,is_banned FROM players WHERE tg_id=?",(int(tg_id),)).fetchone()
        if not p: return {"banned":False,"appeal":None}
        a=conn.execute("SELECT id,status,created_at,reviewed_at,review_note FROM ban_appeals WHERE player_id=? ORDER BY id DESC LIMIT 1",(int(p[0]),)).fetchone()
        sec=conn.execute("SELECT risk_score,status,ban_reason,suspicious_referrals FROM player_security WHERE player_id=?",(int(p[0]),)).fetchone()
        return {"banned":bool(p[1]),"appeal":dict(a) if a else None,"security":dict(sec) if sec else None}
    finally: conn.close()

def _submit_ban_appeal_sync(tg_id:int,text:str)->Dict[str,Any]:
    now=int(time_module.time()); conn=get_db()
    try:
        p=conn.execute("SELECT id,is_banned FROM players WHERE tg_id=?",(int(tg_id),)).fetchone()
        if not p or not int(p[1]): return {"ok":False,"reason":"not_banned"}
        if conn.execute("SELECT 1 FROM ban_appeals WHERE player_id=? AND status='pending'",(int(p[0]),)).fetchone(): return {"ok":False,"reason":"appeal_pending"}
        cur=conn.execute("INSERT INTO ban_appeals(player_id,tg_id,appeal_text,created_at) VALUES(?,?,?,?)",(int(p[0]),int(tg_id),str(text).strip()[:2000],now)); conn.commit(); return {"ok":True,"appeal_id":int(cur.lastrowid)}
    finally: conn.close()

def _ensure_moderation_schema_sync():
    conn=get_db(); cur=conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS player_security (player_id INTEGER PRIMARY KEY, first_seen_at INTEGER NOT NULL DEFAULT 0, last_seen_at INTEGER NOT NULL DEFAULT 0, ip_hash TEXT DEFAULT '', ua_hash TEXT DEFAULT '', risk_score INTEGER NOT NULL DEFAULT 0, suspicious_referrals INTEGER NOT NULL DEFAULT 0, meaningful_events INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'normal', ban_reason TEXT DEFAULT '', updated_at INTEGER NOT NULL DEFAULT 0, FOREIGN KEY(player_id) REFERENCES players(id))")
    cur.execute("CREATE TABLE IF NOT EXISTS ban_appeals (id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER NOT NULL, tg_id INTEGER NOT NULL, appeal_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL, reviewed_at INTEGER DEFAULT 0, reviewed_by INTEGER DEFAULT 0, review_note TEXT DEFAULT '', FOREIGN KEY(player_id) REFERENCES players(id))")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ban_appeals_status_created ON ban_appeals(status,created_at)")
    conn.commit(); conn.close()

def _admin_appeals_sync(status:str="pending",limit:int=50)->List[Dict[str,Any]]:
    conn=get_db()
    try:
        if status not in {"pending","approved","rejected","all"}: status="pending"
        q="SELECT a.*,p.nickname,p.shop_name,p.balance,p.total_earned,p.is_banned,COALESCE(ps.risk_score,0) risk_score,COALESCE(ps.suspicious_referrals,0) suspicious_referrals FROM ban_appeals a JOIN players p ON p.id=a.player_id LEFT JOIN player_security ps ON ps.player_id=p.id"
        params=[int(limit)] if status=="all" else [status,int(limit)]
        q += " WHERE a.status=?" if status!="all" else ""
        q += " ORDER BY a.id DESC LIMIT ?"
        return [dict(r) for r in conn.execute(q,tuple(params)).fetchall()]
    finally: conn.close()

def _resolve_ban_appeal_sync(appeal_id:int,admin_tg_id:int,decision:str,note:str)->Dict[str,Any]:
    decision=str(decision or "").lower(); now=int(time_module.time()); conn=get_db()
    try:
        conn.execute("BEGIN IMMEDIATE"); a=conn.execute("SELECT * FROM ban_appeals WHERE id=?",(int(appeal_id),)).fetchone()
        if not a: conn.rollback(); return {"ok":False,"reason":"appeal_missing"}
        if a["status"]!="pending": conn.rollback(); return {"ok":False,"reason":"already_reviewed"}
        st="approved" if decision=="approve" else "rejected" if decision=="reject" else ""
        if not st: conn.rollback(); return {"ok":False,"reason":"invalid_decision"}
        conn.execute("UPDATE ban_appeals SET status=?,reviewed_at=?,reviewed_by=?,review_note=? WHERE id=?",(st,now,int(admin_tg_id),str(note or "")[:1000],int(appeal_id)))
        if st=="approved": conn.execute("UPDATE players SET is_banned=0 WHERE id=?",(int(a["player_id"]),)); conn.execute("UPDATE player_security SET risk_score=0,status='normal',ban_reason='',updated_at=? WHERE player_id=?",(now,int(a["player_id"])))
        conn.commit(); return {"ok":True,"status":st,"tg_id":int(a["tg_id"]),"note":str(note or "")[:1000]}
    finally: conn.close()

def _request_fingerprint(endpoint: str, *parts: Any, bucket_seconds: int = 2) -> str:
    """Детерминированный ключ для защиты старых клиентов от мгновенного повторного POST."""
    bucket = int(time_module.time()) // max(1, bucket_seconds)
    raw = endpoint + "|" + "|".join(str(x) for x in parts) + f"|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_add_balance_sync(player_id:int, amount:int) -> int:
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("UPDATE players SET balance=balance+? WHERE id=?",(int(amount),player_id))
        if cur.rowcount!=1:
            conn.rollback(); return 0
        row=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
        conn.commit(); return int(row["balance"] if row else 0)
    except Exception:
        conn.rollback(); raise
    finally: conn.close()


def claim_request_once_sync(request_key: str, endpoint: str, player_id: Optional[int], ttl: int = 86400) -> bool:
    """Атомарно принимает request_key один раз."""
    now = int(time_module.time())
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("DELETE FROM api_request_guard WHERE created_at < ?", (now - max(300, int(ttl)),))
        cur.execute("INSERT OR IGNORE INTO api_request_guard(request_key,endpoint,player_id,created_at) VALUES(?,?,?,?)", (request_key, endpoint, player_id, now))
        inserted = cur.rowcount == 1
        conn.commit()
        return inserted
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()

def add_sale_record(seller_id: int, buyer_id: int, item_name: str, price: int):
    """Сохраняет завершённую сделку в БД"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO sales_history (seller_id, buyer_id, item_name, price, date) VALUES (?, ?, ?, ?, ?)",
        (seller_id, buyer_id, item_name, price, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def _merge_garage_stats_preserving_live_wear(current_raw, incoming_raw, car_count, now):
    current=_safe_car_stats(current_raw,car_count,now)
    incoming=_safe_car_stats(incoming_raw,car_count,now)
    out=[]
    for i in range(int(car_count or 0)):
        cur=dict(current[i] if i<len(current) else {})
        inc=dict(incoming[i] if i<len(incoming) else {})
        # Old clients/bot actions sometimes sent a freshly-created zeroed entry.
        # Never let that erase an already materialized Taxi stint.
        live_markers=('line_started_at','wear_before','mileage_before','income_before','taxi_last_tick_at')
        incoming_is_blank = not any(k in inc for k in live_markers) and float(inc.get('wear',0) or 0)==0.0 and float(inc.get('mileage',0) or 0)==0.0 and int(inc.get('total_income',0) or 0)==0
        cur_updated=int(cur.get('updated_at') or 0) if cur else 0
        inc_updated=int(inc.get('updated_at') or 0) if inc else 0
        cur_wear=float(cur.get('wear',0) or 0) if cur else 0.0
        inc_wear=float(inc.get('wear',0) or 0) if inc else 0.0
        stale_lower_wear=bool(cur and cur_updated>0 and inc_updated>0 and inc_updated<cur_updated and inc_wear<cur_wear)
        if cur and ((incoming_is_blank and any(k in cur for k in live_markers)) or stale_lower_wear):
            out.append(cur)
        else:
            merged=dict(cur); merged.update(inc); out.append(merged)
    return out

def update_player_data(player_id: int, data: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    fields = []
    values = []
    safe_data=dict(data)
    if 'garage_car_stats' in safe_data:
        row=cursor.execute('SELECT car_collection,garage_car_stats FROM players WHERE id=?',(int(player_id),)).fetchone()
        owned=_safe_json_list(row['car_collection'] if row else [],)
        safe_data['garage_car_stats']=_merge_garage_stats_preserving_live_wear(row['garage_car_stats'] if row else [],safe_data.get('garage_car_stats'),len(owned),int(time_module.time()))
    for key, value in safe_data.items():
        fields.append(f"{key} = ?")
        values.append(json.dumps(value, ensure_ascii=False) if isinstance(value,(list,dict)) else value)
    values.append(player_id)
    query = f"UPDATE players SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(query, values)
    conn.commit()
    conn.close()

async def add_income(player_id: int, amount: int, source: str = "other"):
    if amount <= 0:
        return
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return
    amount = boost_referral_income(amount, player_id)
    new_balance = player.get("balance", 0) + amount
    new_total_earned = player.get("total_earned", 0) + amount
    await run_sync_db(update_player_data, player_id, {
        "balance": new_balance,
        "total_earned": new_total_earned
    })
    await run_sync_db(check_and_update_achievement, player_id, "millionaire", new_total_earned)
    await run_sync_db(update_daily_quest, player_id, "earn_50k", amount)
    if source == "passive":
        await run_sync_db(update_daily_quest, player_id, "collect_passive_10k", amount)

def check_and_update_achievement(player_id:int,achievement_id:str,current_value:int):
    if achievement_id not in ACHIEVEMENTS: return None
    target=int(ACHIEVEMENTS[achievement_id]["target"]); reward=int(ACHIEVEMENTS[achievement_id].get("reward_money",0))
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row=cur.execute("SELECT progress,completed FROM achievements WHERE player_id=? AND achievement_id=?",(player_id,achievement_id)).fetchone()
        if row and row["completed"]: conn.rollback(); return None
        progress=min(target,max(int(row["progress"] if row else 0),int(current_value))); done=int(progress>=target)
        cur.execute("INSERT OR REPLACE INTO achievements(player_id,achievement_id,progress,completed,completed_at) VALUES(?,?,?,?,?)",(player_id,achievement_id,progress,done,datetime.now().strftime("%Y-%m-%d %H:%M:%S") if done else None))
        if done: cur.execute("UPDATE players SET balance=balance+? WHERE id=?",(reward,player_id))
        bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone(); conn.commit()
        return {"achievement":achievement_id,"reward":reward,"balance":int(bal["balance"] if bal else 0)} if done and not(row and row["completed"]) else None
    except Exception: conn.rollback(); raise
    finally: conn.close()

def sync_permanent_quests(player_id: int):
    player = get_player_data(player_id)
    if not player:
        return {}
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM user_shops WHERE player_id = ? AND status = 'active'", (player_id,))
    shops_count = int((cursor.fetchone()["cnt"]))
    metrics = {
        "total_sales": int(player.get("total_sales", 0) or 0),
        "total_earned": int(player.get("total_earned", 0) or 0),
        "shops_count": shops_count,
    }
    for qid, q in PERMANENT_QUESTS.items():
        current = min(metrics.get(q["metric"], 0), int(q["target"]))
        cursor.execute("SELECT progress, completed, reward_claimed, completed_at FROM permanent_quests WHERE player_id = ? AND quest_id = ?", (player_id, qid))
        row = cursor.fetchone()
        old_progress = int(row["progress"]) if row else 0
        old_completed = bool(row["completed"]) if row else False
        reward_claimed = int(row["reward_claimed"]) if row else 0
        completed_at = row["completed_at"] if row else None
        progress = max(old_progress, current)
        completed = old_completed or progress >= int(q["target"])
        if completed and not old_completed:
            completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT OR REPLACE INTO permanent_quests (player_id, quest_id, progress, completed, reward_claimed, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (player_id, qid, progress, 1 if completed else 0, reward_claimed, completed_at)
        )
    conn.commit(); conn.close()
    return True


def get_quest_payload(player_id: int):
    sync_permanent_quests(player_id)
    conn = get_db(); cursor = conn.cursor()
    cursor.execute("SELECT quest_id, progress, completed, reward_claimed FROM permanent_quests WHERE player_id = ?", (player_id,))
    permanent_rows = {r["quest_id"]: r for r in cursor.fetchall()}
    active_ids = get_rotating_daily_quest_ids()
    cursor.execute("SELECT quest_id, progress, completed FROM daily_quests WHERE player_id = ?", (player_id,))
    daily_rows = {r["quest_id"]: r for r in cursor.fetchall()}
    conn.close()

    permanent = []
    for qid, q in PERMANENT_QUESTS.items():
        r = permanent_rows.get(qid)
        permanent.append({
            "id": qid, "name": q["name"], "description": q["description"], "target": int(q["target"]),
            "progress": int(r["progress"]) if r else 0, "completed": bool(r["completed"]) if r else False,
            "reward_money": int(q["reward_money"]), "reward_claimed": bool(r["reward_claimed"]) if r else False,
            "kind": "permanent",
        })
    daily = []
    for qid in active_ids:
        q = DAILY_QUESTS[qid]; r = daily_rows.get(qid)
        daily.append({
            "id": qid, "name": q["name"], "description": q["description"], "target": int(q["target"]),
            "progress": int(r["progress"]) if r else 0, "completed": bool(r["completed"]) if r else False,
            "reward_money": int(q["reward_money"]), "kind": "daily", "reward_mode": "auto",
        })
    return {"permanent": permanent, "daily": daily, "daily_count": len(daily),
            "daily_rotation_date": market_cycle_key(), "next_reset": _daily_reset_label()}


def claim_permanent_quest_sync(player_id:int,quest_id:str):
    if quest_id not in PERMANENT_QUESTS: return {"success":False,"error":"Квест не найден"}
    sync_permanent_quests(player_id); reward=int(PERMANENT_QUESTS[quest_id]["reward_money"])
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row=cur.execute("SELECT completed,reward_claimed FROM permanent_quests WHERE player_id=? AND quest_id=?",(player_id,quest_id)).fetchone()
        if not row or not row["completed"]: conn.rollback(); return {"success":False,"error":"Квест ещё не выполнен"}
        if row["reward_claimed"]: conn.rollback(); return {"success":False,"error":"Награда уже получена"}
        cur.execute("UPDATE players SET balance=balance+? WHERE id=?",(reward,player_id))
        cur.execute("UPDATE permanent_quests SET reward_claimed=1 WHERE player_id=? AND quest_id=? AND reward_claimed=0",(player_id,quest_id))
        if cur.rowcount!=1: conn.rollback(); return {"success":False,"error":"Награда уже была получена"}
        bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone(); conn.commit(); return {"success":True,"reward":reward,"balance":int(bal["balance"] if bal else 0)}
    except Exception: conn.rollback(); raise
    finally: conn.close()

def update_daily_quest(player_id:int,quest_id:str,increment:int=1):
    if quest_id not in DAILY_QUESTS or quest_id not in get_rotating_daily_quest_ids(): return None
    now=datetime.now(); cycle=market_cycle_key(now); target=int(DAILY_QUESTS[quest_id]["target"]); reward=int(DAILY_QUESTS[quest_id]["reward_money"]); inc=max(0,int(increment))
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row=cur.execute("SELECT progress,completed,cycle_key FROM daily_quests WHERE player_id=? AND quest_id=?",(player_id,quest_id)).fetchone()
        progress=0 if not row or row["cycle_key"]!=cycle else int(row["progress"] or 0); completed=0 if not row or row["cycle_key"]!=cycle else int(row["completed"] or 0)
        if completed: conn.rollback(); return None
        new_progress=min(target,progress+inc); newly=int(new_progress>=target)
        cur.execute("INSERT OR REPLACE INTO daily_quests(player_id,quest_id,progress,completed,last_updated,cycle_key) VALUES(?,?,?,?,?,?)",(player_id,quest_id,new_progress,newly,now.strftime("%Y-%m-%d %H:%M:%S"),cycle))
        if newly: cur.execute("UPDATE players SET balance=balance+? WHERE id=?",(reward,player_id))
        bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone(); conn.commit()
        return {"quest":quest_id,"reward":reward,"balance":int(bal["balance"] if bal else 0)} if newly else {"quest":quest_id,"progress":new_progress,"target":target,"reward":0}
    except Exception: conn.rollback(); raise
    finally: conn.close()

def resolve_referrer_token(token: str) -> Optional[int]:
    value = str(token or "").strip()
    if value.startswith("ref_"):
        value = value[4:]
    if not value:
        return None
    if value.isdigit():
        conn = get_db()
        row = conn.execute("SELECT tg_id FROM players WHERE tg_id = ?", (int(value),)).fetchone()
        conn.close()
        return int(row["tg_id"]) if row else None
    return find_user_by_ref_code(value)

def get_upgrade_state(player_id: int) -> Dict[str, int]:
    conn = get_db()
    rows = conn.execute("SELECT upgrade_id, level FROM webapp_upgrades WHERE player_id = ?", (player_id,)).fetchall()
    conn.close()
    result = {key: 0 for key in UPGRADE_CARDS}
    for row in rows:
        if row["upgrade_id"] in result:
            result[row["upgrade_id"]] = int(row["level"] or 0)
    return result

def get_upgrade_income(player_id: int) -> int:
    levels = get_upgrade_state(player_id)
    return sum(levels[key] * int(cfg["income_per_level"]) for key, cfg in UPGRADE_CARDS.items())

def get_upgrade_hold_bonus(player_id: int) -> int:
    levels = get_upgrade_state(player_id)
    return sum(levels[key] * int(cfg["hold_bonus_per_level"]) for key, cfg in UPGRADE_CARDS.items())

def set_pending_referral(invitee_tg_id: int, inviter_tg_id: int, source: str = "webapp") -> bool:
    if not inviter_tg_id or int(inviter_tg_id) == int(invitee_tg_id):
        return False
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT inviter_tg_id FROM referral_relations WHERE invitee_tg_id=?", (int(invitee_tg_id),)).fetchone()
        if existing:
            old_inviter = int(existing["inviter_tg_id"])
            inviter_exists = conn.execute("SELECT 1 FROM players WHERE tg_id=?", (old_inviter,)).fetchone()
            if inviter_exists:
                conn.commit()
                return old_inviter == int(inviter_tg_id)
            # Старый пригласивший был удалён — связь больше не должна блокировать нового реферала.
            conn.execute("DELETE FROM referral_relations WHERE invitee_tg_id=?", (int(invitee_tg_id),))
        existing_pending = conn.execute("SELECT inviter_tg_id FROM referral_pending WHERE invitee_tg_id=?", (int(invitee_tg_id),)).fetchone()
        if existing_pending:
            old_pending = int(existing_pending["inviter_tg_id"])
            pending_inviter_exists = conn.execute("SELECT 1 FROM players WHERE tg_id=?", (old_pending,)).fetchone()
            if pending_inviter_exists:
                conn.commit()
                return old_pending == int(inviter_tg_id)
            conn.execute("DELETE FROM referral_pending WHERE invitee_tg_id=?", (int(invitee_tg_id),))
        conn.execute("INSERT INTO referral_pending(invitee_tg_id,inviter_tg_id,created_at,source) VALUES(?,?,?,?)", (int(invitee_tg_id), int(inviter_tg_id), int(time_module.time()), str(source or "webapp")[:32]))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_pending_referral(tg_id: int) -> Optional[int]:
    conn = get_db()
    row = conn.execute("SELECT inviter_tg_id FROM referral_pending WHERE invitee_tg_id=?", (int(tg_id),)).fetchone()
    conn.close()
    return int(row["inviter_tg_id"]) if row else None

def activate_pending_referral_sync(invitee_tg_id:int,reason:str="action", immediate:bool=False)->Dict[str,Any]:
    inviter=get_pending_referral(int(invitee_tg_id))
    if inviter:
        now=int(time_module.time()); conn=get_db()
        try:
            conn.execute("INSERT INTO security_events(player_id,event_type,event_key,created_at) SELECT id,?,?,? FROM players WHERE tg_id=?",(str(reason)[:64],f"referral:{int(inviter)}:{int(now//300)}",now,int(invitee_tg_id)))
            conn.commit()
        finally: conn.close()
    if not inviter: return {"activated":False,"reason":"no_pending"}
    if not immediate:
        q=_referral_qualification_sync(int(invitee_tg_id),int(inviter))
        if not q.get("qualified"): return {"activated":False,"qualified":False,**q}
        if int(q.get("suspicious_score",0))>=REFERRAL_SUSPICIOUS_PAIR_THRESHOLD:
            m=_register_referral_suspicion_sync(int(inviter),int(invitee_tg_id),int(q["suspicious_score"]),"Подозрительная реферальная связка")
            if m.get("banned"):
                conn=get_db(); conn.execute("DELETE FROM referral_pending WHERE invitee_tg_id=?",(int(invitee_tg_id),)); conn.commit(); conn.close()
                return {"activated":False,"banned":True,"reason":"referral_abuse_banned"}
            return {"activated":False,"reason":"manual_review","risk":m.get("risk",0)}
    conn=get_db()
    try:
        conn.execute("BEGIN IMMEDIATE"); p=conn.execute("SELECT inviter_tg_id FROM referral_pending WHERE invitee_tg_id=?",(int(invitee_tg_id),)).fetchone()
        if not p: conn.rollback(); return {"activated":False,"reason":"no_pending"}
        inviter_tg_id=int(p[0]); inv=conn.execute("SELECT id,is_banned FROM players WHERE tg_id=?",(inviter_tg_id,)).fetchone(); ine=conn.execute("SELECT id,is_banned FROM players WHERE tg_id=?",(int(invitee_tg_id),)).fetchone()
        if not inv or not ine or int(inv[1] or 0) or int(ine[1] or 0): conn.rollback(); return {"activated":False,"reason":"banned_or_missing"}
        if conn.execute("SELECT 1 FROM referral_relations WHERE invitee_tg_id=?",(int(invitee_tg_id),)).fetchone(): conn.execute("DELETE FROM referral_pending WHERE invitee_tg_id=?",(int(invitee_tg_id),)); conn.commit(); return {"activated":False,"reason":"already_attached"}
        now=int(time_module.time()); conn.execute("INSERT INTO referral_relations(invitee_tg_id,inviter_tg_id,activated_at,reward_paid) VALUES(?,?,?,1)",(int(invitee_tg_id),inviter_tg_id,now)); conn.execute("DELETE FROM referral_pending WHERE invitee_tg_id=?",(int(invitee_tg_id),))
        conn.execute("UPDATE players SET balance=balance+?,total_earned=total_earned+? WHERE id=?",(REFERRAL_DIRECT_REWARD,REFERRAL_DIRECT_REWARD,int(inv[0])))
        conn.execute("UPDATE players SET balance=balance+?,total_earned=total_earned+? WHERE id=?",(REFERRAL_INVITEE_BONUS,REFERRAL_INVITEE_BONUS,int(ine[0])))
        active=int(conn.execute("SELECT COUNT(*) FROM referral_relations r JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? AND r.reward_paid=1 AND p.is_banned=0",(inviter_tg_id,)).fetchone()[0]); milestone_reward=0; hits=[]
        for m in REFERRAL_MILESTONES:
            if active>=m["target"] and not conn.execute("SELECT 1 FROM referral_milestones WHERE player_id=? AND target=?",(int(inv[0]),int(m["target"]))).fetchone():
                rw=int(m["reward"]); conn.execute("INSERT INTO referral_milestones(player_id,target,reward,claimed_at) VALUES(?,?,?,?)",(int(inv[0]),int(m["target"]),rw,now)); conn.execute("UPDATE players SET balance=balance+?,total_earned=total_earned+? WHERE id=?",(rw,rw,int(inv[0]))); milestone_reward+=rw; hits.append({"target":int(m["target"]),"reward":rw,"title":m["title"]})
        conn.commit(); return {"activated":True,"inviter_tg_id":inviter_tg_id,"invitee_tg_id":int(invitee_tg_id),"inviter_reward":REFERRAL_DIRECT_REWARD+milestone_reward,"invitee_reward":REFERRAL_INVITEE_BONUS,"milestone_reward":milestone_reward,"milestones":hits,"active_count":active,"reason":reason}
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

async def activate_pending_referral(tg_id: int, reason: str = "action", immediate: bool = False) -> Dict[str, Any]:
    result = await run_sync_db(activate_pending_referral_sync, int(tg_id), reason, immediate)
    if result.get("banned"):
        try:
            await bot.send_message(int(ADMIN_SUPER_ID), f"⛔ <b>Автоблокировка за подозрительную реферальную активность</b>\nИгрок: <code>{int(tg_id)}</code>\nПричина: накрутка/подозрительная сеть рефералов.", parse_mode="HTML")
        except Exception:
            pass
    # V33: referral rewards are delivered silently in-app. Do not send a Telegram
    # chat message to the inviter when a referral becomes active.
    return result

def get_referral_data(player_id: int) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT invited, bonus_claimed FROM referrals WHERE player_id = ?", (player_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"invited": json.loads(row['invited']) if row['invited'] else [], "bonus_claimed": bool(row['bonus_claimed'])}
    return {"invited": [], "bonus_claimed": False}

def update_referral_data(player_id: int, data: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    invited = json.dumps(data.get("invited", []))
    bonus_claimed = 1 if data.get("bonus_claimed", False) else 0
    cursor.execute("UPDATE referrals SET invited = ?, bonus_claimed = ? WHERE player_id = ?", (invited, bonus_claimed, player_id))
    conn.commit()
    conn.close()

def get_skins(player_id: int) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, skin_id, equipped FROM skins WHERE player_id = ?", (player_id,))
    rows = cursor.fetchall()
    conn.close()
    skins = []
    for row in rows:
        skin_info = next((s for s in SKINS if s["id"] == row['skin_id']), None)
        if skin_info:
            skins.append({
                "id": row['skin_id'],
                "instance_id": row['id'],
                "name": skin_info["name"],
                "emoji": skin_info["emoji"],
                "equipped": bool(row['equipped'])
            })
    return skins

def equip_skin(player_id: int, skin_id: str, instance_id: int = None):
    """
    Надевает скин. Если instance_id передан – надевает конкретную копию.
    Иначе – находит первую копию с данным skin_id и надевает её.
    """
    conn = get_db()
    cursor = conn.cursor()
    try:
        # Сбрасываем флаг equipped у всех скинов игрока
        cursor.execute("UPDATE skins SET equipped = 0 WHERE player_id = ?", (player_id,))
        
        if instance_id is not None:
            # Надеваем конкретную копию
            cursor.execute("UPDATE skins SET equipped = 1 WHERE id = ? AND player_id = ?", (instance_id, player_id))
        else:
            # Надеваем первую попавшуюся копию данного типа
            cursor.execute("UPDATE skins SET equipped = 1 WHERE player_id = ? AND skin_id = ? LIMIT 1", (player_id, skin_id))
        
        # Обновляем текущий скин в таблице players (для быстрого доступа)
        cursor.execute("UPDATE players SET skin = ? WHERE id = ?", (skin_id, player_id))
        conn.commit()
    finally:
        conn.close()

def get_learning_data(player_id: int) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT completed FROM learning WHERE player_id = ?", (player_id,))
    row = cursor.fetchone()
    conn.close()
    return {"completed": json.loads(row['completed']) if row and row['completed'] else []}

def update_learning_data(player_id: int, data: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    completed = json.dumps(data.get("completed", []))
    cursor.execute("UPDATE learning SET completed = ? WHERE player_id = ?", (completed, player_id))
    conn.commit()
    conn.close()

def get_friends(player_id: int) -> List[int]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT friend_id FROM friends WHERE player_id = ?", (player_id,))
    rows = cursor.fetchall()
    conn.close()
    return [row['friend_id'] for row in rows]

def update_friends(player_id: int, friends: List[int]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM friends WHERE player_id = ?", (player_id,))
    for friend_id in friends:
        cursor.execute("INSERT INTO friends (player_id, friend_id) VALUES (?, ?)", (player_id, friend_id))
    conn.commit()
    conn.close()

def find_user_by_nickname(nickname: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nickname FROM players WHERE nickname = ?", (nickname,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"id": row['id'], "nickname": row['nickname']}
    return None

async def get_player_id_by_tg(tg_id: int) -> Optional[int]:
    async with db_lock:
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM players WHERE tg_id = ?", (tg_id,))
            row = cursor.fetchone()
            return row['id'] if row else None
        except Exception as e:
            print(f"Ошибка в get_player_id_by_tg: {e}")
            return None
        finally:
            if conn:
                conn.close()


def get_player_id_by_tg_sync(tg_id: int) -> Optional[int]:
    """Синхронный вариант для функций, работающих внутри asyncio.to_thread().

    Нельзя вызывать async get_player_id_by_tg() из синхронного DB-кода:
    это вернёт coroutine, который затем попадает в SQLite и вызывает
    ProgrammingError: type 'coroutine' is not supported.
    """
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM players WHERE tg_id = ?", (int(tg_id),))
        row = cursor.fetchone()
        return int(row["id"]) if row else None
    except Exception as e:
        print(f"Ошибка в get_player_id_by_tg_sync: {e}")
        return None
    finally:
        if conn:
            conn.close()


def reset_player_account_sync(tg_id: int) -> Dict[str, Any]:
    """Полностью удаляет аккаунт игрока и ВСЕ его зависимые данные.

    Важно: referral_relations/referral_pending хранят Telegram ID, а не player_id,
    поэтому простой DELETE FROM players оставляет "призрачную" реферальную связь.
    Этот метод удаляет обе стороны реферальных связей и игровые данные, после чего
    следующий вход того же Telegram ID создаёт чистый профиль и снова показывает регистрацию.
    """
    tg_id = int(tg_id)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT id FROM players WHERE tg_id=?", (tg_id,)).fetchone()
        if not row:
            # Даже если players уже удалён, подчистим старые referral-записи.
            conn.execute("DELETE FROM referral_relations WHERE invitee_tg_id=? OR inviter_tg_id=?", (tg_id, tg_id))
            conn.execute("DELETE FROM referral_pending WHERE invitee_tg_id=? OR inviter_tg_id=?", (tg_id, tg_id))
            conn.commit()
            return {"deleted": False, "tg_id": tg_id, "reason": "player_not_found", "removed_rows": 0}

        player_id = int(row["id"])
        removed = 0

        # Таблицы, где связь хранится как player_id.
        player_tables = [
            "friends", "referrals", "referral_milestones", "hold_sessions", "learning",
            "webapp_upgrades", "skins", "user_shops", "user_taxoparks", "achievements",
            "daily_quests", "permanent_quests", "wheel_spins", "api_request_guard",
            "case_rounds", "deposits", "loans", "mining_rigs", "user_stocks",
            "stock_transactions", "container_inventory", "container_daily", "container_purchases",
            "poker_hands", "poker_games"
        ]
        for table in player_tables:
            try:
                if table == "friends":
                    cur = conn.execute("DELETE FROM friends WHERE player_id=? OR friend_id=?", (player_id, player_id))
                else:
                    cur = conn.execute(f"DELETE FROM {table} WHERE player_id=?", (player_id,))
                removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            except sqlite3.OperationalError:
                # Старые базы могут не иметь часть новых таблиц.
                pass

        # История/аукцион и гонки используют разные имена для player_id.
        for table, columns in {
            "sales_history": ["seller_id", "buyer_id"],
            "auction": ["seller_id", "bidder_id"],
            "races": ["creator_id", "opponent_id", "winner_id"],
        }.items():
            for col in columns:
                try:
                    cur = conn.execute(f"DELETE FROM {table} WHERE {col}=?", (player_id,))
                    removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                except sqlite3.OperationalError:
                    pass

        # Рефералка — отдельная сущность, завязанная на Telegram ID.
        for table in ("referral_relations", "referral_pending"):
            cur = conn.execute(
                f"DELETE FROM {table} WHERE invitee_tg_id=? OR inviter_tg_id=?",
                (tg_id, tg_id)
            )
            removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        # Сам игрок удаляется последним.
        cur = conn.execute("DELETE FROM players WHERE id=? AND tg_id=?", (player_id, tg_id))
        removed += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        conn.commit()
        return {"deleted": True, "tg_id": tg_id, "player_id": player_id, "removed_rows": removed}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

async def resolve_player_id(identifier: str) -> Optional[int]:
    if identifier.isdigit():
        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM players WHERE tg_id = ?", (int(identifier),))
            row = cursor.fetchone()
            return row['id'] if row else None
        except Exception:
            return None
        finally:
            if conn:
                conn.close()

    # 2. Пробуем по Telegram username (через get_chat)
    clean_username = identifier.lstrip('@')
    try:
        chat = await bot.get_chat(f"@{clean_username}")
        if chat and chat.id:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM players WHERE tg_id = ?", (chat.id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row['id']
    except Exception:
        pass

    # 3. Ищем по игровому никнейму (nickname)
    user = find_user_by_nickname(identifier)
    if user:
        return user['id']

    return None

# ==================== ГЕНЕРАЦИЯ ТОВАРОВ У ПОСТАВЩИКОВ ====================
def generate_supplier_items(player_id:int,player_data:dict):
    player_data=ensure_market_state_sync(player_id,player_data); demand=player_data.get("market_demand",{}) or {}
    total_sales=int(player_data.get("total_sales",0) or 0); overall=min(1.18,1+total_sales/5000)
    rarities=list(SUPPLIER_ITEM_RARITIES); weights=[SUPPLIER_ITEM_RARITIES[r]["chance"] for r in rarities]
    for i in range(1,len(weights)): weights[i]*=overall**i
    total=sum(weights) or 1; weights=[w/total for w in weights]
    items=[]; used=set()
    for _ in range(random.randint(8,10)):
        rarity=random.choices(rarities,weights=weights,k=1)[0]; rd=SUPPLIER_ITEM_RARITIES[rarity]; base=random.choice(BASE_ITEMS); dm=float(demand.get(base["cat"],1.0))
        market=max(50,int(round(base["base_price"]*random.uniform(rd["price_mult_min"],rd["price_mult_max"])*(0.92+0.10*dm))))
        buy_factor=max(0.45,min(0.82,random.uniform(0.58,0.80)-max(0,dm-1.3)*0.035)); bp=max(50,int(round(market*buy_factor)))
        iid=uuid.uuid4().int%900000000+100000000
        while iid in used: iid=uuid.uuid4().int%900000000+100000000
        used.add(iid)
        items.append({"id":iid,"uid":make_item_uid(),"name":f"{rd['color']} {base['cat']} {base['name']}","cat":base["cat"],"buy_price":bp,"market_price":market,"rarity":rarity,"rarity_color":rd["color"],"demand":dm,"expected_profit":max(0,market-bp),"margin_pct":round((market-bp)/bp*100,1) if bp else 0,"end_time":time_module.time()+random.randint(300,900)})
    supplier_stock["items_by_player"][player_id]=items; supplier_stock["last_update_by_player"][player_id]=time_module.time()

def check_supplier_update(player_id: int, player_data: dict):
    last_update = supplier_stock["last_update_by_player"].get(player_id, 0)
    items = supplier_stock["items_by_player"].get(player_id, [])
    # если прошло больше 5 минут или список пуст – генерируем новый
    if time_module.time() - last_update >= 300 or not items:
        generate_supplier_items(player_id, player_data)
        return True
    # удаляем просроченные товары (по end_time)
    now = time_module.time()
    fresh_items = [i for i in items if i["end_time"] > now]
    supplier_stock["items_by_player"][player_id] = fresh_items
    return False

async def get_supplier_items(player_id: int, player_data: dict):
    async with supplier_lock:
        check_supplier_update(player_id, player_data)
        return supplier_stock["items_by_player"].get(player_id, [])

# ==================== РЕАЛЬНЫЕ ЦЕНЫ С COINGECKO ====================
async def fetch_crypto_prices():
    """Возвращает словарь {asset: price_in_usd} используя CoinGecko API"""
    try:
        async with aiohttp.ClientSession() as session:
            ids = [TRADING_ASSETS[asset]["coin_id"] for asset in TRADING_ASSETS]
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies=usd"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = {}
                    for asset, info in TRADING_ASSETS.items():
                        coin_id = info["coin_id"]
                        if coin_id in data and "usd" in data[coin_id]:
                            result[asset] = data[coin_id]["usd"]
                        else:
                            raise ValueError(f"No price for {asset}")
                    return result
    except Exception as e:
        print(f"⚠️ Ошибка получения цен с CoinGecko: {e}")
    return None

# ==================== ТРЕЙДИНГ ====================
def init_trading():
    global trading_prices
    if not trading_prices:
        for asset, data in TRADING_ASSETS.items():
            trading_prices[asset] = {
                "price": data["base_price"],
                "trend": random.uniform(-0.03, 0.03),
                "history": deque(maxlen=5)
            }
            trading_prices[asset]["history"].append(data["base_price"])

async def get_trader(player_id: int):
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return {"portfolio": {}, "invested": 0}
    portfolio = player.get("trading_portfolio", {})
    invested = player.get("trading_invested", 0)
    return {"portfolio": portfolio, "invested": invested}

async def save_trader(player_id: int, portfolio: dict, invested: int):
    async with db_lock:
        await run_sync_db(update_player_data, player_id, {"trading_portfolio": portfolio, "trading_invested": invested})

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ИГРЫ ====================
async def start_chat_for_item(seller_id:int,buyer_id:int,item:dict,pub:dict)->dict:
    async with chats_lock:
        item_uid=str(item.get("uid") or item.get("name"))
        for chat in active_chats.values():
            if chat.get("user_id")==seller_id and not chat.get("finished") and str(chat.get("item_uid"))==item_uid:
                return {"success":False,"message":"Чат по этому экземпляру товара уже существует"}
        client_type=random.choices(["normal","skeptic","trader"],weights=[55,30,15],k=1)[0]
        price=max(1,int(item.get("market_price",1)))
        if client_type=="trader": offer=max(100,int(price*random.uniform(.72,.90))); offer=(offer//100)*100+99
        elif client_type=="skeptic": offer=max(100,int(price*random.uniform(.88,.98)))
        else: offer=price
        pool=[d for d in CLIENT_DIALOGUES if d["client_type"]==client_type] or CLIENT_DIALOGUES
        seed=int(hashlib.sha256(f"dialog:{seller_id}:{item_uid}:{int(time_module.time()//86400)}".encode()).hexdigest()[:12],16)
        scenario=pool[seed%len(pool)]
        msg=scenario["phases"][0].format(item=item["name"],price=f"{price:,}",offer=f"{offer:,}")
        chat_key=f"{seller_id}_{buyer_id}_{uuid.uuid4().hex[:8]}"
        active_chats[chat_key]={"user_id":seller_id,"buyer_id":buyer_id,"client_type":client_type,"item":item["name"],"item_uid":item_uid,"price":price,"offer":offer,"round":1,"max_rounds":5,"finished":False,"phase":1,"trust":50,"dialogue":scenario,"history":[{"role":"assistant","content":msg}],"chat_key":chat_key,"item_obj":dict(item),"created_at":time_module.time(),"unread":True,"last_activity_at":time_module.time()}
        return {"success":True,"message":msg,"buyer_id":buyer_id,"offer":offer,"chat_key":chat_key}

def get_display_name(player_data: Dict[str, Any]) -> str:
    nick = player_data.get("nickname")
    if nick:
        return nick
    tg_id = player_data.get("tg_id")
    vk_id = player_data.get("vk_id")
    if tg_id:
        return f"ID:{tg_id}"
    return f"ID:{vk_id}"

def get_car_bonus(car_id: str) -> int:
    car = next((c for c in CARS if c["id"] == car_id), None)
    return car["speed_bonus"] if car else 0

def calculate_race_score(car_id: str, action: str, phase: int) -> Tuple[int, str]:
    speed = get_car_bonus(car_id)
    base = 50 + speed
    luck = random.randint(-15, 15)
    if action == "boost":
        base *= 1.3
        if random.random() < 0.2:
            return int(base + luck), "⚠️ Двигатель перегрет!"
        return int(base + luck), "🚀 БУСТ! +30%"
    elif action == "nitro":
        base *= 1.5
        return int(base + luck), "🔥 НИТРО! +50%"
    else:
        base *= 1.1
        return int(base + luck), "🛡 Ровный ход"
    return int(base + luck), "✅"

def rate_description(desc: str) -> int:
    score = 3
    if len(desc) >= 30:
        score += 1
    if len(desc) >= 80:
        score += 1
    keywords = ["состояние", "размер", "цвет", "бренд", "качество", "материал", "новый"]
    score += min(3, sum(1 for w in keywords if w in desc.lower()))
    return min(10, max(1, score))

def get_quality_bonus(quality: int) -> Dict[str, Any]:
    if quality >= 9:
        return {"name": "🔥 Легендарное", "buyers_bonus": 3}
    elif quality >= 7:
        return {"name": "⭐ Отличное", "buyers_bonus": 2}
    elif quality >= 5:
        return {"name": "👍 Хорошее", "buyers_bonus": 1}
    return {"name": "👌 Обычное", "buyers_bonus": 0}


def fmt_demand(player: Dict[str, Any]) -> str:
    market_demand=player.get("market_demand") or {}
    if not market_demand: market_demand,_=build_market_state(player,market_cycle_key())
    current_event=player.get("current_event")
    if isinstance(current_event,str):
        try: current_event=json.loads(current_event)
        except Exception: current_event=None
    lines=[f"🕛 Цикл рынка до {_daily_reset_label()}"]
    lines.append(f"📰 {current_event['text']}" if isinstance(current_event,dict) and current_event.get('text') else "📊 Сильных событий сейчас нет.")
    for cat in CATEGORIES:
        mult=float(market_demand.get(cat,1.0))
        if mult>=1.45: emoji,label="🔥","ОЧЕНЬ ВЫСОКИЙ"
        elif mult>=1.15: emoji,label="📈","ВЫСОКИЙ"
        elif mult>=0.90: emoji,label="➡️","СТАБИЛЬНЫЙ"
        elif mult>=0.65: emoji,label="📉","НИЗКИЙ"
        else: emoji,label="💀","КРИТИЧЕСКИЙ"
        lines.append(f"{emoji} {cat}: x{mult:.2f} · {label}")
    top=sorted(market_demand.items(),key=lambda x:x[1],reverse=True)[:2]; low=sorted(market_demand.items(),key=lambda x:x[1])[:2]
    lines += ["","💡 <b>Стратегия:</b>",f"Покупать: {top[0][0]}, {top[1][0]}",f"Осторожнее: {low[0][0]}, {low[1][0]}"]
    return "\n".join(lines)

def get_avito_rating(sales: int) -> str:
    if sales == 0: return "⭐ Новый продавец"
    elif sales < 3: return "⭐ 1.0"
    elif sales < 5: return "⭐⭐ 2.0"
    elif sales < 10: return "⭐⭐⭐ 3.0"
    elif sales < 25: return "⭐⭐⭐⭐ 4.0"
    elif sales < 50: return "⭐⭐⭐⭐ 4.5"
    elif sales < 100: return "⭐⭐⭐⭐⭐ 4.8"
    elif sales < 250: return "👑 ⭐⭐⭐⭐⭐ 5.0"
    else: return "💎 👑 ⭐⭐⭐⭐⭐ 5.0"


def get_rep_level(sales: int) -> str:
    """Return the Avito seller reputation level used by the web API.

    This helper is intentionally kept next to get_avito_rating because both
    values are returned by /avito/state and /profile.  Older builds had the
    call sites but lost this function during a merge, which caused a runtime
    NameError as soon as Avito state was opened.
    """
    try:
        sales = max(0, int(sales or 0))
    except (TypeError, ValueError):
        sales = 0

    if sales == 0:
        return "🆕 Новичок"
    if sales < 5:
        return "🔰 Начинающий"
    if sales < 15:
        return "⭐ Проверенный"
    if sales < 50:
        return "🏅 Надёжный"
    if sales < 100:
        return "👑 Профессионал"
    if sales < 250:
        return "💎 Легенда"
    return "🌟 Бог Авито"

def generate_crash_point() -> float:
    r = random.random()
    crash = 1.10 + (8.90 * (r ** 2.5))
    return round(crash, 2)

# ==================== КАЗИНО (ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ) ====================
def get_casino_jackpot() -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM casino_jackpot WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return row["amount"] if row else 100000

def update_casino_jackpot(amount: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE casino_jackpot SET amount = ? WHERE id = 1", (amount,))
    conn.commit()
    conn.close()

def add_to_jackpot(amount: int):
    current = get_casino_jackpot()
    update_casino_jackpot(current + amount)

def reset_jackpot():
    update_casino_jackpot(100000)

def generate_slot_reels():
    symbols = ["🍒", "🍋", "🍊", "🍉", "🔔", "💎", "7️⃣", "🎰"]
    reels = [random.choice(symbols) for _ in range(3)]
    win_mult = 0
    if reels[0] == reels[1] == reels[2]:
        if reels[0] == "7️⃣":
            win_mult = 20
        elif reels[0] == "💎":
            win_mult = 15
        elif reels[0] == "🎰":
            win_mult = 10
        else:
            win_mult = 5
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        win_mult = 2
    return reels, win_mult

def deal_blackjack_hand():
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    return deck, player, dealer

def hand_value(hand):
    value = sum(hand)
    if value > 21 and 11 in hand:
        hand_copy = hand[:]
        hand_copy.remove(11)
        hand_copy.append(1)
        return sum(hand_copy)
    return value

def dealer_play(deck, dealer_hand):
    while hand_value(dealer_hand) < 17:
        dealer_hand.append(deck.pop())
    return dealer_hand

def spin_roulette():
    num = random.randint(0, 36)
    if num == 0:
        color = "зеленый"
    elif num % 2 == 0:
        color = "черный"
    else:
        color = "красный"
    return num, color

async def update_casino_stats(player_id: int, result: str, bet: int = 0, win_amount: int = 0):
    """
    Обновляет статистику казино.
    result: 'win' или 'lose'
    bet: сумма ставки
    win_amount: сумма выигрыша (только при победе)
    """
    async with db_lock:
        def _sync_update():
            conn = get_db()
            cursor = conn.cursor()
            # Увеличиваем количество игр
            cursor.execute("UPDATE players SET casino_games_played = casino_games_played + 1 WHERE id = ?", (player_id,))
            # Обновляем ставки и выигрыши
            if result == 'win':
                cursor.execute("UPDATE players SET casino_wins = casino_wins + 1 WHERE id = ?", (player_id,))
                if win_amount > 0:
                    cursor.execute("UPDATE players SET casino_total_win = casino_total_win + ? WHERE id = ?", (win_amount, player_id))
            else:
                cursor.execute("UPDATE players SET casino_losses = casino_losses + 1 WHERE id = ?", (player_id,))
            if bet > 0:
                cursor.execute("UPDATE players SET casino_total_bet = casino_total_bet + ? WHERE id = ?", (bet, player_id))
            conn.commit()
            conn.close()
        await run_sync_db(_sync_update)

# ---------- МАЙНЁР (MINES) ----------
MINES_GRID_SIZE = 5
MINES_DEFAULT_COUNT = 5
MINES_MAX_COUNT = 12
MINES_MIN_BET = 100
MINES_MAX_BET = 50000
MINES_MULTIPLIER_PER_STEP = 0.10   # базовая прибавка за клетку (будет модифицироваться)
MINES_TAX = 0.05                   # 5% комиссия
MINES_MAX_MULT = 3.0               # максимальный множитель

def generate_mines_field(mines_count: int) -> Tuple[List[List[bool]], List[Tuple[int, int]]]:
    total_cells = MINES_GRID_SIZE * MINES_GRID_SIZE
    if mines_count >= total_cells:
        mines_count = total_cells - 1
    mine_positions = random.sample(range(total_cells), mines_count)
    field = [[False for _ in range(MINES_GRID_SIZE)] for _ in range(MINES_GRID_SIZE)]
    mine_coords = []
    for pos in mine_positions:
        row, col = divmod(pos, MINES_GRID_SIZE)
        field[row][col] = True
        mine_coords.append((row, col))
    return field, mine_coords

def get_luck_factor(user_id: int) -> float:
    return player_luck.get(user_id, 1.0)

def update_luck_factor(user_id: int, net_result: int):
    factor = player_luck.get(user_id, 1.0)
    if net_result > 0:
        factor *= 0.95
    elif net_result < 0:
        factor *= 1.05
    factor = max(0.5, min(1.5, factor))
    player_luck[user_id] = factor

def calc_mines_multiplier(opened_safe: int, mines_count: int, user_id: int) -> float:
    # Базовая прибавка за клетку (зависит от количества мин)
    increment = 0.1 * (1 + mines_count / 10)
    base_multiplier = 1 + opened_safe * increment
    # Адаптивный коэффициент везения
    luck = get_luck_factor(user_id)
    # Случайный разброс ±20%
    random_factor = random.uniform(0.8, 1.2)
    final_multiplier = base_multiplier * luck * random_factor
    return min(final_multiplier, MINES_MAX_MULT)

def calc_mines_win(bet: int, opened_safe: int) -> int:
    """Чистый выигрыш (без учёта ставки)"""
    multiplier = calc_mines_multiplier(opened_safe)
    total = int(bet * multiplier)
    return total  # включая ставку? Сделаем так: выигрыш = bet * multiplier, где multiplier >= 1
    # Игрок получает сумму на баланс: ставка уже списана, поэтому добавим только выигрыш сверх ставки?
    # Лучше: выигрыш = bet * multiplier (включая ставку). Тогда чистый профит = bet*(multiplier-1).
    # В нашем api будем возвращать полный выигрыш (с возвратом ставки).
    # При выигрыше: balance += win_amount (win_amount = bet * multiplier)

# ==================== АКЦИИ ====================
def update_stock_price(symbol: str, price: int, change_pct: float):
    """Синхронное обновление цены акции в БД."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE stock_prices SET price = ?, change_pct = ?, last_update = ? WHERE symbol = ?",
        (price, change_pct, int(time_module.time()), symbol)
    )
    conn.commit()
    conn.close()

def get_stock_prices() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, name, price, change_pct, last_update FROM stock_prices ORDER BY symbol")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_stock_price(symbol: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, name, price, change_pct, last_update FROM stock_prices WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    else:
        print(f"⚠️ Акция {symbol} не найдена в БД")
        return None

def get_user_stocks(player_id: int) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, quantity, avg_buy_price FROM user_stocks WHERE player_id = ? AND quantity > 0", (player_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def update_user_stock(player_id: int, symbol: str, quantity_change: int, price: int):
    """quantity_change может быть отрицательным (продажа). price - цена сделки."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT quantity, avg_buy_price FROM user_stocks WHERE player_id = ? AND symbol = ?", (player_id, symbol))
    row = cursor.fetchone()
    if row:
        old_qty = row["quantity"]
        old_avg = row["avg_buy_price"]
        new_qty = old_qty + quantity_change
        if new_qty <= 0:
            cursor.execute("DELETE FROM user_stocks WHERE player_id = ? AND symbol = ?", (player_id, symbol))
        else:
            # Новая средняя цена (для покупки)
            if quantity_change > 0:
                new_avg = (old_qty * old_avg + quantity_change * price) // new_qty
            else:
                new_avg = old_avg  # при продаже средняя не меняется
            cursor.execute(
                "UPDATE user_stocks SET quantity = ?, avg_buy_price = ? WHERE player_id = ? AND symbol = ?",
                (new_qty, new_avg, player_id, symbol)
            )
    else:
        if quantity_change > 0:
            cursor.execute(
                "INSERT INTO user_stocks (player_id, symbol, quantity, avg_buy_price) VALUES (?, ?, ?, ?)",
                (player_id, symbol, quantity_change, price)
            )
    conn.commit()
    conn.close()

def add_stock_transaction(player_id: int, symbol: str, type_op: str, quantity: int, price: int, total: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO stock_transactions (player_id, symbol, type, quantity, price, total, date) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (player_id, symbol, type_op, quantity, price, total, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

def get_stock_transactions(player_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT symbol, type, quantity, price, total, date FROM stock_transactions WHERE player_id = ? ORDER BY id DESC LIMIT ?",
        (player_id, limit)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def calculate_portfolio_value(player_id: int) -> Tuple[int, int]:
    """Возвращает (общая стоимость, общая прибыль/убыток по отношению к затратам)"""
    stocks = get_user_stocks(player_id)
    total_cost = 0
    current_value = 0
    for s in stocks:
        sym = s["symbol"]
        stock_info = get_stock_price(sym)
        if stock_info:
            current_price = stock_info["price"]
            current_value += current_price * s["quantity"]
            total_cost += s["avg_buy_price"] * s["quantity"]
    profit = current_value - total_cost
    return current_value, profit

def give_dividends():
    """Фоновая задача: раз в сутки начислять дивиденды (0.5-3% от стоимости портфеля)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM players")
    players = cursor.fetchall()
    for row in players:
        pid = row["id"]
        value, _ = calculate_portfolio_value(pid)
        if value > 0:
            dividend_rate = random.uniform(0.005, 0.03)  # 0.5% - 3%
            dividend = int(value * dividend_rate)
            if dividend > 0:
                cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (dividend, pid))
                # Запись в историю (можно опционально)
                add_stock_transaction(pid, "DIV", "dividend", 0, 0, dividend)
    conn.commit()
    conn.close()

def get_hourly_income(player_id: int, include_referrals: bool = True):
    player = get_player_data(player_id)
    if not player:
        return 0, {}

    house = next((h for h in HOUSES if h["id"] == player.get("house", "room")), HOUSES[0])
    house_income = int(house.get("income_per_hour", 0) or 0)
    car = next((c for c in CARS if c["id"] == player.get("current_car", "none")), None)
    car_income = car["income_per_hour"] if car else 0
    taxopark = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_income = _taxi_current_hourly_sync(
        player,
        income_multiplier=_taxi_income_multiplier(_taxi_upgrades_for_player_sync(player_id)),
    )

    conn = get_db()
    shop_rows = conn.execute(
        "SELECT shop_id, COALESCE(status, 'active') AS status FROM user_shops WHERE player_id = ?", (player_id,)
    ).fetchall()
    shops_income = sum(
        next((s["income_per_hour"] for s in SHOP_LEVELS if s["id"] == row["shop_id"]), 0)
        for row in shop_rows if str(row["status"] or "active") == "active"
    )
    mining_rows = conn.execute(
        "SELECT daily_income FROM mining_rigs WHERE player_id = ? AND status = 'active'",
        (player_id,),
    ).fetchall()
    mining_income = sum(int(r["daily_income"] or 0) for r in mining_rows) // 24
    conn.close()

    upgrade_income = get_upgrade_income(player_id)
    breakdown = {
        "house": house_income,
        "car": car_income,
        "taxopark": taxopark_income,
        "shops": shops_income,
        "mining": mining_income,
        "upgrades": upgrade_income,
    }

    referral_multiplier = get_referral_boost_multiplier(player_id)
    for key in ("car", "taxopark", "shops", "mining", "upgrades"):
        breakdown[key] = int(breakdown[key] * referral_multiplier)

    if include_referrals:
        conn = get_db()
        relations = conn.execute(
            "SELECT invitee_tg_id FROM referral_relations WHERE inviter_tg_id = ? AND reward_paid = 1",
            (int(player.get("tg_id") or 0),),
        ).fetchall()
        conn.close()
        referral_income = 0
        referral_passive_percent = get_referral_passive_percent(len(relations))
        for rel in relations:
            invitee_player_id = get_player_id_by_tg_sync(int(rel["invitee_tg_id"]))
            if invitee_player_id:
                invitee_hourly, _ = get_hourly_income(
                    invitee_player_id, include_referrals=False
                )
                referral_income += int(
                    invitee_hourly * referral_passive_percent / 100
                )
        breakdown["referrals"] = referral_income

    # Unified economy: every active passive source contributes its full rate.
    # There is intentionally no artificial 1.25M ₽/hour cap: new Business assets
    # must visibly increase the player's expected income and collection amount.
    return sum(breakdown.values()), breakdown


async def calculate_max_loan(player: Dict[str, Any]) -> int:
    total_earned = player.get("total_earned", 0)
    balance = player.get("balance", 0)
    items_sold = player.get("items_sold", 0)
    
    hourly_income, _ = await run_sync_db(get_hourly_income, player["id"])
    
    base = int(total_earned * 0.2 + balance * 0.3)
    sales_bonus = min(items_sold * 1000, 100_000)
    passive_bonus = min(hourly_income * 2000, 300_000)
    max_loan = base + sales_bonus + passive_bonus
    max_loan = max(10_000, min(1_000_000, max_loan))
    return max_loan

def get_maintenance_cost_shop(shop_price: int) -> int:
    return int(shop_price * 0.1)

def get_maintenance_cost_taxopark(price: int) -> int:
    return int(price * 0.08)

def get_maintenance_cost_shop_per_day(shop_price: int) -> float:
    return shop_price * 0.1 / 30

def get_maintenance_cost_taxopark_per_day(price: int) -> float:
    return price * 0.08 / 30

async def calculate_total_debt(player_id: int) -> int:
    def _sync():
        conn = get_db()
        cursor = conn.cursor()
        now = int(time_module.time())
        total_debt = 0

        # Магазины
        cursor.execute("SELECT id, purchase_price, last_payment FROM user_shops WHERE player_id = ? AND status = 'active'", (player_id,))
        shops = cursor.fetchall()
        for row in shops:
            days = (now - row['last_payment']) / 86400
            if days > 0:
                cost_per_day = get_maintenance_cost_shop_per_day(row['purchase_price'])
                total_debt += int(cost_per_day * days)

        # Таксопарк не участвует в общей задолженности.
        # Его состояние обслуживается только по износу автомобилей в webapp.

        conn.close()
        return total_debt
    return await run_sync_db(_sync)

async def pay_all_debt(player_id: int):
    def _sync():
        conn = get_db()
        cursor = conn.cursor()
        now = int(time_module.time())
        total_debt = 0

        # Проверяем баланс
        cursor.execute("SELECT balance FROM players WHERE id = ?", (player_id,))
        bal_row = cursor.fetchone()
        if not bal_row:
            return False, "Игрок не найден"

        # Считаем долг по магазинам
        shops = cursor.execute("SELECT id, purchase_price, last_payment FROM user_shops WHERE player_id = ? AND status = 'active'", (player_id,)).fetchall()
        for row in shops:
            days = (now - row['last_payment']) / 86400
            if days > 0:
                cost_per_day = get_maintenance_cost_shop_per_day(row['purchase_price'])
                total_debt += int(cost_per_day * days)

        # Таксопарк не участвует в общей задолженности. Обслуживание считается по износу машин.

        if total_debt == 0:
            conn.close()
            return True, "Нет задолженности по обслуживанию."

        if bal_row['balance'] < total_debt:
            conn.close()
            return False, f"Недостаточно средств! Нужно {total_debt}₽."

        # Списываем долг
        new_balance = bal_row['balance'] - total_debt
        cursor.execute("UPDATE players SET balance = ? WHERE id = ?", (new_balance, player_id))

        # Обновляем last_payment для всех активных бизнесов на текущее время
        cursor.execute("UPDATE user_shops SET last_payment = ? WHERE player_id = ? AND status = 'active'", (now, player_id))

        conn.commit()
        conn.close()
        return True, f"Оплачено {total_debt}₽ за обслуживание всех бизнесов. Баланс: {new_balance}₽."

    return await run_sync_db(_sync)

async def pay_shop_maintenance(player_id: int, shop_id: str, shop_price: int):
    def _sync():
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT id, last_payment, paid_until FROM user_shops "
                "WHERE player_id = ? AND shop_id = ? AND status = 'active'",
                (player_id, shop_id)
            )
            row = cursor.fetchone()
            if not row:
                return False, "Магазин не найден или уже изъят."
            
            now = int(time_module.time())
            cost = get_maintenance_cost_shop(shop_price)

            # Проверяем баланс
            cursor.execute("SELECT balance FROM players WHERE id = ?", (player_id,))
            bal_row = cursor.fetchone()
            if not bal_row or bal_row['balance'] < cost:
                return False, f"Недостаточно средств! Нужно {cost}₽."

            new_balance = bal_row['balance'] - cost
            new_paid_until = max(now, row['paid_until']) + 30 * 86400

            # Обновляем всё в одной транзакции
            cursor.execute(
                "UPDATE user_shops SET last_payment = ?, paid_until = ? WHERE id = ?",
                (now, new_paid_until, row['id'])
            )
            cursor.execute("UPDATE players SET balance = ? WHERE id = ?", (new_balance, player_id))
            conn.commit()
            return True, f"Обслуживание оплачено на 30 дней. Списано {cost}₽."
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    return await run_sync_db(_sync)

async def fetch_stock_price(symbol: str) -> tuple[Optional[int], Optional[float]]:
    """Возвращает (цена_в_рублях, процент_изменения) или (None, None) при ошибке."""
    async with aiohttp.ClientSession() as session:
        try:
            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    quote = data.get("Global Quote", {})
                    price_str = quote.get("05. price")
                    change_pct_str = quote.get("10. change percent", "0%")
                    if price_str:
                        price_usd = float(price_str)
                        # Получаем курс рубля (можно кэшировать)
                        usd_rate = await get_usd_rub_rate()
                        price_rub = int(price_usd * usd_rate)
                        change_pct = float(change_pct_str.replace("%", ""))
                        return price_rub, change_pct
        except Exception as e:
            print(f"Ошибка получения цены {symbol}: {e}")
    return None, None

async def get_usd_rub_rate() -> float:
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://www.cbr-xml-daily.ru/daily_json.js"
            async with session.get(url, timeout=5) as resp:
                data = await resp.json()
                return data["Valute"]["USD"]["Value"]
    except Exception:
        return 90.0  # запасной курс

async def update_all_stock_prices():
    # Получаем список акций без блокировки БД
    stocks = await run_sync_db(get_stock_prices)
    
    for stock in stocks:
        symbol = stock["symbol"]
        # Внешний API-запрос – вне блокировки
        price_rub, change_pct = await fetch_stock_price(symbol)
        
        if price_rub is not None:
            # Короткая блокировка только на запись
            async with db_lock:
                await run_sync_db(update_stock_price, symbol, price_rub, change_pct)
        else:
            # Симуляция изменения цены
            old_price = stock["price"]
            change_pct = random.uniform(-3.0, 3.0)
            new_price = int(old_price * (1 + change_pct / 100))
            new_price = max(100, new_price)
            async with db_lock:
                await run_sync_db(update_stock_price, symbol, new_price, change_pct)

async def pay_taxopark_maintenance(player_id: int, level_id: str, price: int):
    return False, "Старая система оплаты таксопарка отключена. Обслуживание выполняется по износу машин."

async def process_deposits():
    def _sync_deposits():
        conn = get_db()
        cursor = conn.cursor()
        now = int(time_module.time())
        cursor.execute(
            "SELECT id, player_id, amount, start_time, duration_days, interest_rate FROM deposits WHERE status = 'active' AND start_time + duration_days*86400 <= ?",
            (now,)
        )
        matured = cursor.fetchall()
        for dep in matured:
            profit = int(dep['amount'] * dep['interest_rate'] / 100)
            total = dep['amount'] + profit
            cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (total, dep['player_id']))
            cursor.execute("UPDATE deposits SET status = 'closed' WHERE id = ?", (dep['id'],))
        conn.commit()
        conn.close()
        return matured
    while True:
        await asyncio.sleep(86400)
        async with db_lock:
            matured = await asyncio.to_thread(_sync_deposits)
        for dep in matured:
            player = await run_sync_db(get_player_data, dep['player_id'])
            if player and player.get('tg_id'):
                try:
                    await bot.send_message(player['tg_id'], f"🏦 Ваш депозит на {dep['amount']}₽ завершён! Получено {dep['amount'] + int(dep['amount'] * dep['interest_rate'] / 100)}₽ (включая {int(dep['amount'] * dep['interest_rate'] / 100)}₽ процентов).")
                except:
                    pass

async def process_mining():
    def _sync_mining():
        conn = get_db()
        cursor = conn.cursor()
        now=int(time_module.time())
        cursor.execute("SELECT id, player_id, daily_income, COALESCE(last_paid_at,0) last_paid_at FROM mining_rigs WHERE status='active'")
        rigs = cursor.fetchall()
        for rig in rigs:
            hourly=max(0,int(rig['daily_income'] or 0)//24)
            if hourly<=0: continue
            cur=cursor.execute("UPDATE mining_rigs SET last_paid_at=? WHERE id=? AND (COALESCE(last_paid_at,0)=0 OR last_paid_at<=?)",(now,int(rig['id']),now-3600))
            if cur.rowcount==1:
                cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (hourly, rig['player_id']))
        conn.commit()
        conn.close()
    while True:
        await asyncio.sleep(3600)
        async with db_lock:
            await asyncio.to_thread(_sync_mining)


async def check_business_expiry():
    """Background expiry checker for shops only.

    Taxi parks no longer use the old 30-day payment/expiry model; their
    maintenance is handled by vehicle wear/repair logic elsewhere.
    """
    def _sync_business():
        conn = get_db()
        cursor = conn.cursor()
        now = int(time_module.time())

        cursor.execute(
            "SELECT id, player_id, shop_id, purchase_price, last_payment FROM user_shops WHERE status = 'active'"
        )
        shops = cursor.fetchall()
        expired_shops = []
        for row in shops:
            last_payment = row['last_payment'] or now
            days = (now - last_payment) / 86400
            if days > 0:
                cost_per_day = get_maintenance_cost_shop_per_day(row['purchase_price'])
                debt = int(cost_per_day * days)
                if debt > 3 * row['purchase_price']:
                    expired_shops.append(row)

        for row in expired_shops:
            cursor.execute("UPDATE user_shops SET status = 'seized' WHERE id = ?", (row['id'],))
            refund = int(row['purchase_price'] * 0.7)
            cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (refund, row['player_id']))

        conn.commit()
        conn.close()
        return expired_shops

    while True:
        await asyncio.sleep(86400)
        async with db_lock:
            expired_shops = await asyncio.to_thread(_sync_business)
        for row in expired_shops:
            player = await run_sync_db(get_player_data, row['player_id'])
            if player and player.get('tg_id'):
                try:
                    await bot.send_message(
                        player['tg_id'],
                        f"⚠️ Ваш магазин «{row['shop_id']}» изъят за неуплату (долг превысил 3 стоимости). Возвращено {int(row['purchase_price'] * 0.7)}₽."
                    )
                except Exception:
                    pass

async def load_auction_items_from_db():
    async with auction_lock:
        auction_items.clear()
        conn=get_db()
        rows=conn.execute("SELECT id,seller_id,item_name,item_data,start_price,current_bid,bidder_id,end_time,active FROM auction WHERE active=1").fetchall()
        conn.close()
        for r in rows:
            try: item=json.loads(r["item_data"] or "{}")
            except Exception: item={"name":r["item_name"],"type":"inventory"}
            try: lot_id=int(r["id"])
            except (TypeError,ValueError): continue
            try: seller_id=int(r["seller_id"])
            except (TypeError,ValueError): continue
            try: start_price=int(r["start_price"] or 0)
            except (TypeError,ValueError): start_price=0
            try: current_bid=int(r["current_bid"] or 0)
            except (TypeError,ValueError): current_bid=0
            try: bidder_id=int(r["bidder_id"]) if r["bidder_id"] is not None else None
            except (TypeError,ValueError): bidder_id=None
            try: end_time=float(r["end_time"] or 0)
            except (TypeError,ValueError): end_time=0.0
            auction_items.append({"id":lot_id,"lot_id":lot_id,"seller_id":seller_id,"item":item,"start_price":start_price,"current_bid":current_bid,"bidder_id":bidder_id,"end_time":end_time,"active":True,"item_type":str(item.get("type","inventory") or "inventory"),"inventory_uid":item.get("uid")})

async def _return_auction_item(player_id:int,item:dict):
    player=await run_sync_db(get_player_data,player_id)
    if not player: return
    kind=item.get("type","inventory")
    if kind=="inventory":
        inv,_=normalize_inventory(player.get("inventory",[])); inv.append(item); await run_sync_db(update_player_data,player_id,{"inventory":inv})
    elif kind=="skin" and item.get("skin_id"):
        conn=get_db(); conn.execute("INSERT INTO skins(player_id,skin_id,equipped) VALUES(?,?,0)",(player_id,item["skin_id"])); conn.commit(); conn.close()
    elif kind=="car" and item.get("car_id"):
        cars=list(player.get("car_collection",[]));
        if item["car_id"] not in cars: cars.append(item["car_id"])
        await run_sync_db(update_player_data,player_id,{"car_collection":cars})

def _simple_balance_add_sync(player_id:int, amount:int):
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("UPDATE players SET balance=COALESCE(balance,0)+? WHERE id=?",(int(amount),int(player_id)))
        conn.commit()
        return cur.rowcount==1
    finally: conn.close()

async def auction_loop():
    await load_auction_items_from_db()
    while True:
        await asyncio.sleep(10)
        now=time_module.time()
        async with auction_lock:
            expired=[lot for lot in auction_items if lot.get("active",True) and float(lot.get("end_time",0))<=now]
            for lot in expired: lot["active"]=False
            if expired: auction_items[:]=[lot for lot in auction_items if lot not in expired]
        for lot in expired:
            try:
                lot_id=int(lot.get("lot_id",lot.get("id")))
                seller_id=int(lot.get("seller_id"))
            except (TypeError,ValueError):
                continue
            try:
                def _take_expired_auction_sync(lid:int):
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        row=cur.execute("SELECT active,item_data,current_bid,bidder_id,seller_id FROM auction WHERE id=?",(int(lid),)).fetchone()
                        if not row or int(row["active"] or 0)!=1:
                            conn.rollback(); return None
                        try: item=json.loads(row["item_data"] or "{}")
                        except Exception: item=dict(lot.get("item") or {})
                        current_bid=int(row["current_bid"] or 0)
                        bidder_raw=row["bidder_id"]
                        bidder=int(bidder_raw) if bidder_raw is not None else None
                        seller=int(row["seller_id"] or seller_id)
                        cur.execute("UPDATE auction SET active=0 WHERE id=? AND active=1",(int(lid),))
                        if cur.rowcount!=1:
                            conn.rollback(); return None
                        conn.commit()
                        return item,current_bid,bidder,seller
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                result=await run_sync_db(_take_expired_auction_sync,lot_id)
                if not result:
                    continue
                item,current_bid,bidder,seller_id=result
                if bidder:
                    winner=await run_sync_db(get_player_data,int(bidder))
                    if winner:
                        await _return_auction_item(int(bidder),item)
                        await run_sync_db(_simple_balance_add_sync,int(seller_id),int(current_bid))
                    else:
                        await run_sync_db(_simple_balance_add_sync,int(seller_id),int(current_bid))
                        await _return_auction_item(int(seller_id),item)
                        bidder=None
                else:
                    await _return_auction_item(int(seller_id),item)
                seller=await run_sync_db(get_player_data,int(seller_id))
                if seller and seller.get("tg_id"):
                    msg=(f"💰 Лот «{item.get('name','товар')}» продан за {int(current_bid):,}₽." if bidder else f"⏱ Лот «{item.get('name','товар')}» завершён без ставок — товар возвращён.")
                    await bot.send_message(int(seller["tg_id"]),msg)
                if bidder:
                    winner=await run_sync_db(get_player_data,int(bidder))
                    if winner and winner.get("tg_id"):
                        await bot.send_message(int(winner["tg_id"]),f"🎉 Вы выиграли лот «{item.get('name','товар')}» и получили его в инвентарь.")
            except Exception as e:
                print(f"⚠️ auction_loop {lot_id}: {type(e).__name__}: {e}")

async def _handle_action_locked(action: PlayerAction):
    player_id = await run_sync_db(get_or_create_player, action.platform, action.platform_id)
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return {"success": False, "message": "Player not found"}
    player = await run_sync_db(ensure_inventory_uids_sync, player_id, player)
    
    # ===== НАЧИСЛЕНИЕ ПАССИВНОГО ДОХОДА – временно отключено для ускорения =====
    # Доход будет начисляться только при вызове /collect или через отдельную кнопку.
    pass

    # ---------- БАЛАНС И СТАТЫ ----------
    if action.action == "get_balance":
        return {"success": True, "balance": player.get("balance", 0)}
    
    elif action.action == "get_stats":
        return {
            "success": True,
            "stats": {
                "balance": player.get("balance", 0),
                "day": player.get("day", 1),
                "inventory_count": len(player.get("inventory", [])),
                "items_sold": player.get("total_sales", 0),
                "total_earned": player.get("total_earned", 0),
                "nickname": player.get("nickname"),
                "shop_name": player.get("shop_name"),
                "total_profit": player.get("total_profit", 0),
                "reputation_score": player.get("reputation_score", 0),
                "house": player.get("house", "room"),
                "shop_level": player.get("shop_level", "none"),
                "current_car": player.get("current_car", "none"),
                "car_collection_count": len(player.get("car_collection", []))
            }
        }
    
    elif action.action == "sell_shop":
        shop_id = action.data.get("shop_id")
        shop = next((s for s in SHOP_LEVELS if s["id"] == shop_id), None)
        if not shop:
            return {"success": False, "message": "Магазин не найден"}
        
        def _check_and_delete():
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM user_shops WHERE player_id = ? AND shop_id = ? LIMIT 1", (player_id, shop_id))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False, "У вас нет такого магазина"
            cursor.execute("DELETE FROM user_shops WHERE id = ?", (row["id"],))
            conn.commit()
            conn.close()
            return True, None
        
        success, err = await run_sync_db(_check_and_delete)
        if not success:
            return {"success": False, "message": err}
        
        refund = int(shop["price"] * 0.7)
        balance = player.get("balance", 0)
        new_balance = balance + refund
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        return {"success": True, "message": f"✅ Магазин «{shop['name']}» продан за {refund}₽ (70% стоимости).", "balance": new_balance}

    elif action.action == "get_shop_name":
        return {"success": True, "shop_name": player.get("shop_name", "Без названия")}
    
    elif action.action == "set_shop_name":
        name = action.data.get("name", "")
        if len(name) < 2:
            return {"success": False, "message": "Минимум 2 символа"}
        if len(name) > 30:
            return {"success": False, "message": "Максимум 30 символов"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"shop_name": name})
        return {"success": True, "message": f"✅ Магазин: {name}", "shop_name": name}

    elif action.action == "get_balance":
        return {"success": True, "balance": player.get("balance", 0)}
  
    elif action.action == "set_nickname":
        nickname = action.data.get("nickname", "")
        if len(nickname) < 2:
            return {"success": False, "message": "Минимум 2 символа"}
        if len(nickname) > 20:
            return {"success": False, "message": "Максимум 20 символов"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"nickname": nickname})
        return {"success": True, "message": f"✅ Никнейм: {nickname}", "nickname": nickname}
    
    elif action.action == "next_day":
        income=await collect_income(player); new_day=int(player.get("day",1) or 1)+1
        player=await run_sync_db(ensure_market_state_sync,player_id,player); await run_sync_db(update_player_data,player_id,{"day":new_day}); fresh=await run_sync_db(get_player_data,player_id)
        return {"success":True,"message":f"День {new_day}, доход: {income}₽","day":new_day,"balance":fresh.get("balance",0),"income":income,"market_cycle_key":player.get("market_cycle_key")}

    elif action.action == "get_demand":
        player=await run_sync_db(ensure_market_state_sync,player_id,player)
        return {"success":True,"demand":player.get("market_demand",{}),"event":player.get("current_event"),"cycle_key":player.get("market_cycle_key"),"formatted":fmt_demand(player)}

    # ---------- ПОСТАВЩИКИ ----------
    elif action.action == "get_suppliers":
        player=await run_sync_db(ensure_market_state_sync,player_id,player); items=await get_supplier_items(player_id,player)
        items=sorted(items,key=lambda x:(float(x.get("demand",1)),float(x.get("margin_pct",0))),reverse=True)
        return {"success":True,"suppliers":items,"market_demand":player.get("market_demand",{})}

    elif action.action == "buy_from_supplier":
        item_id=action.data.get("item_id")
        async with supplier_lock:
            player_data=await run_sync_db(get_player_data,player_id); player_data=await run_sync_db(ensure_inventory_uids_sync,player_id,player_data); check_supplier_update(player_id,player_data)
            items=supplier_stock["items_by_player"].get(player_id,[]); item=next((i for i in items if str(i.get("id"))==str(item_id)),None)
            if not item: return {"success":False,"message":"Товар уже купили или время истекло!"}
            if item.get("end_time",0)<=time_module.time(): return {"success":False,"message":"Предложение поставщика уже истекло."}
            price=int(item.get("buy_price",0)); balance=int(player_data.get("balance",0) or 0)
            if balance<price: return {"success":False,"message":f"❌ Недостаточно денег! Нужно {price:,}₽"}
            inv=list(player_data.get("inventory",[])); new_item={"uid":item.get("uid") or make_item_uid(),"name":item["name"],"cat":item["cat"],"buy_price":price,"market_price":int(item.get("market_price",price)),"rarity":item.get("rarity","обычный"),"rarity_color":item.get("rarity_color","⬜")}
            inv.append(new_item); new_balance=balance-price
            await run_sync_db(update_player_data,player_id,{"balance":new_balance,"inventory":inv})
            supplier_stock["items_by_player"][player_id]=[i for i in items if str(i.get("id"))!=str(item_id)]
        return {"success":True,"message":f"✅ Куплен {item['name']} за {price:,}₽\n📈 Спрос: x{float(item.get('demand',1)):.2f} · прогноз прибыли: +{int(item.get('expected_profit',0)):,}₽","balance":new_balance,"item":new_item}

    # ---------- ИНВЕНТАРЬ ----------
    elif action.action == "get_inventory":
        player=await run_sync_db(ensure_inventory_uids_sync,player_id,player)
        return {"success":True,"inventory":player.get("inventory",[]),"demand":player.get("market_demand",{})}

    elif action.action == "publish_item":
        identifier=action.data.get("item_uid",action.data.get("item_idx")); description=str(action.data.get("description","")).strip()[:1000]
        if len(description)<10: return {"success":False,"message":"Описание должно содержать хотя бы 10 символов и реальные характеристики товара."}
        player=await run_sync_db(ensure_inventory_uids_sync,player_id,player); inv=list(player.get("inventory",[])); item,idx=get_inventory_item(inv,identifier)
        if not item: return {"success":False,"message":"Товар не найден в инвентаре."}
        async with published_lock:
            if published_items.get(player_id) and not published_items[player_id].get("finished"):
                return {"success":False,"message":"У тебя уже есть активное объявление."}
            quality=rate_description(description); published_items[player_id]={"item":dict(item),"item_uid":item.get("uid"),"description":description,"quality":quality,"created_at":time_module.time(),"finished":False}
            buyer_id=random.randint(10000,99999); result=await start_chat_for_item(player_id,buyer_id,item,published_items[player_id])
        if not result.get("success"): return result
        qb=get_quality_bonus(quality)
        return {"success":True,"message":f"📢 ОПУБЛИКОВАНО!\n📦 {item['name']}\n💰 {int(item['market_price']):,}₽\n📝 Качество: {qb['name']} ({quality}/10)\n\n{result.get('message','')}","buyer_id":buyer_id,"chat_key":result.get("chat_key")}

    elif action.action == "get_published_item":
        pub=published_items.get(player_id)
        if not pub: return {"success":False,"message":"Нет активных объявлений"}
        return {"success":True,"item":pub["item"],"quality":pub.get("quality",0),"description":pub.get("description","")}

    elif action.action == "unpublish_item":
        async with published_lock:
            published_items.pop(player_id,None)
        async with chats_lock:
            for key in [k for k,v in active_chats.items() if v.get("user_id")==player_id and not v.get("finished")]: active_chats.pop(key,None)
        return {"success":True,"message":"Объявление снято с публикации"}

    # ---------- ПОКУПАТЕЛИ (ЧАТЫ) ----------
    elif action.action == "get_chats":
        async with chats_lock:
            chats = []
            for key, chat in active_chats.items():
                if chat.get("user_id") == player_id and not chat.get("finished"):
                    chats.append({
                        "buyer_id": chat.get("buyer_id"),
                        "item": chat.get("item"),
                        "offer": chat.get("offer"),
                        "round": chat.get("round", 0),
                        "max_rounds": chat.get("max_rounds", 0),
                        "client_type": chat.get("client_type"),
                        "chat_key": key
                    })
        return {"success": True, "chats": chats}
    
    # ---------- АВТОМОБИЛИ ----------
    elif action.action == "get_cars":
        return {"success": True, "cars": CARS}
    
    elif action.action == "buy_car":
        async with db_lock:
            car_id = action.data.get("car_id")
            car = next((c for c in CARS if c["id"] == car_id), None)
            if not car:
                return {"success": False, "message": "Машина не найдена"}
            balance = player.get("balance", 0)
            if balance < car["price"]:
                return {"success": False, "message": f"Недостаточно денег! Нужно {car['price']}₽"}
            car_collection = list(player.get("car_collection", []) or [])
            car_collection.append(car_id)
            garage_stats = list(player.get("garage_car_stats", []) or [])
            garage_stats.append({"mileage":0.0,"wear":0.0,"total_income":0,"updated_at":int(time_module.time())})
            new_balance = balance - car["price"]
            await run_sync_db(update_player_data, player_id, {"balance": new_balance, "car_collection": car_collection, "garage_car_stats": garage_stats})
            
            # === ДОСТИЖЕНИЕ Автолюбитель ===
            new_car_count = len(car_collection)
            # ⬇️ ЗАМЕНА: check_and_update_achievement → await run_sync_db
            await run_sync_db(check_and_update_achievement, player_id, "car_lover", new_car_count)
            # ⬇️ ЗАМЕНА: update_daily_quest → await run_sync_db
            await run_sync_db(update_daily_quest, player_id, "buy_car", 1)
            
            if len(car_collection) == 1 or player.get("current_car") == "none":
                # ⬇️ ЗАМЕНА: update_player_data → await run_sync_db
                await run_sync_db(update_player_data, player_id, {"current_car": car_id})
            
            return {"success": True, "message": f"✅ {car['name']} куплена!", "balance": new_balance}
    
    elif action.action == "get_car_collection":
        car_collection = player.get("car_collection", [])
        cars_data = []
        for car_id in car_collection:
            car = next((c for c in CARS if c["id"] == car_id), None)
            if car:
                cars_data.append({"id": car_id, "name": car["name"], "is_current": car_id == player.get("current_car", "none")})
        return {"success": True, "cars": cars_data}
    
    elif action.action == "set_current_car":
        car_id = action.data.get("car_id")
        car_collection = player.get("car_collection", [])
        if car_id not in car_collection:
            return {"success": False, "message": "У вас нет этой машины!"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"current_car": car_id})
        car = next((c for c in CARS if c["id"] == car_id), None)
        return {"success": True, "message": f"✅ {car['name'] if car else car_id} теперь ваша текущая машина!"}
    
    elif action.action == "get_current_car":
        current_car = player.get("current_car", "none")
        car = next((c for c in CARS if c["id"] == current_car), None)
        return {"success": True, "car": car, "car_id": current_car}
    
    # ---------- НЕДВИЖИМОСТЬ ----------
    elif action.action == "get_houses":
        return {"success": True, "houses": HOUSES}
    
    elif action.action == "buy_house":
        house_id = action.data.get("house_id")
        house = next((h for h in HOUSES if h["id"] == house_id), None)
        if not house:
            return {"success": False, "message": "Дом не найден"}
        current_house_id = player.get("house", "room")
        if current_house_id == house_id:
            return {"success": False, "message": "У вас уже есть этот дом"}
        current_house = next((h for h in HOUSES if h["id"] == current_house_id), HOUSES[0])
        
        price_new = house["price"]
        price_old = current_house["price"]
        balance = player.get("balance", 0)
        
        if price_new > price_old:
            diff = price_new - price_old
            if balance < diff:
                return {"success": False, "message": f"Недостаточно денег! Нужно доплатить {diff}₽"}
            new_balance = balance - diff
            message = f"✅ {house['name']} куплен! (старый {current_house['name']} обменян с доплатой {diff}₽)"
        elif price_new < price_old:
            return {"success": False, "message": f"Нельзя купить дом дешевле текущего ({current_house['name']}). Сначала продайте старый."}
        else:
            return {"success": False, "message": "Вы уже владеете домом аналогичной стоимости."}
        
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": new_balance, "house": house_id})
        return {"success": True, "message": message, "balance": new_balance}
    
    elif action.action == "sell_house":
        current_house_id = player.get("house", "room")
        if current_house_id == "room":
            return {"success": False, "message": "У вас и так базовое жильё. Нечего продавать."}
        current_house = next((h for h in HOUSES if h["id"] == current_house_id), None)
        if not current_house:
            return {"success": False, "message": "Ошибка: текущий дом не найден."}
        refund = current_house["price"]
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {
                "balance": player.get("balance", 0) + refund,
                "house": "room"
            })
        return {"success": True, "message": f"🏠 Дом {current_house['name']} продан за {refund}₽. Вы переехали в комнату в общаге.", "balance": player.get("balance", 0) + refund}
    
    elif action.action == "get_current_house":
        house_id = player.get("house", "room")
        house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
        return {"success": True, "house": house}
    
    # ---------- МАГАЗИНЫ ----------
    elif action.action == "get_shops":
        return {"success": True, "shops": SHOP_LEVELS}
    
    elif action.action == "get_current_shop":
        shop_level_id = player.get("shop_level", "none")
        shop = next((s for s in SHOP_LEVELS if s["id"] == shop_level_id), SHOP_LEVELS[0])
        return {"success": True, "shop": shop}
    
    elif action.action == "buy_shop":
        shop_id = action.data.get("shop_id")
        shop = next((s for s in SHOP_LEVELS if s["id"] == shop_id), None)
        if not shop:
            return {"success": False, "message": "Магазин не найден"}
        current_shop = player.get("shop_level", "none")
        if current_shop == shop_id:
            return {"success": False, "message": "У вас уже есть этот магазин"}
        levels = [s["id"] for s in SHOP_LEVELS]
        if levels.index(shop_id) <= levels.index(current_shop):
            return {"success": False, "message": "Вы можете покупать только более дорогие магазины!"}
        balance = player.get("balance", 0)
        if balance < shop["price"]:
            return {"success": False, "message": f"Недостаточно денег! Нужно {shop['price']}₽"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance - shop["price"], "shop_level": shop_id})
        return {"success": True, "message": f"✅ {shop['name']} куплен!", "balance": balance - shop["price"]}

    elif action.action == "buy_shop_multiple":
        shop_id = action.data.get("shop_id")
        shop = next((s for s in SHOP_LEVELS if s["id"] == shop_id), None)
        if not shop:
            return {"success": False, "message": "Магазин не найден"}
        balance = player.get("balance", 0)
        if balance < shop["price"]:
            return {"success": False, "message": f"Недостаточно денег! Нужно {shop['price']}₽"}

        def _buy_shop_sync():
            conn = get_db()
            cursor = conn.cursor()
            # Проверка количества
            cursor.execute("SELECT COUNT(*) FROM user_shops WHERE player_id = ? AND shop_id = ?", (player_id, shop_id))
            count = cursor.fetchone()[0]
            if count >= 2:
                conn.close()
                return False, f"❌ Нельзя купить больше 2 магазинов типа «{shop['name']}»!"
            # Вставка и списание — одной транзакцией. Баланс проверяется повторно внутри БД,
            # поэтому два быстрых нажатия не могут создать отрицательный баланс.
            now = int(time_module.time())
            cursor.execute(
                "INSERT INTO user_shops (player_id, shop_id, purchase_price, last_payment, paid_until, status) VALUES (?, ?, ?, ?, ?, 'active')",
                (player_id, shop_id, shop["price"], now, 0)
            )
            cursor.execute(
                "UPDATE players SET balance = balance - ? WHERE id = ? AND balance >= ?",
                (shop["price"], player_id, shop["price"])
            )
            if cursor.rowcount != 1:
                conn.rollback()
                conn.close()
                return False, "Недостаточно денег! Баланс изменился, обновите экран."
            conn.commit()
            # Получение свежего баланса и активов из той же БД.
            new_balance_row = cursor.execute("SELECT balance FROM players WHERE id = ?", (player_id,)).fetchone()
            cursor.execute("SELECT COUNT(*) as cnt FROM user_shops WHERE player_id = ? AND COALESCE(status, 'active')='active'", (player_id,))
            total_shops = cursor.fetchone()["cnt"]
            cursor.execute("SELECT DISTINCT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
            owned = {row["shop_id"] for row in cursor.fetchall()}
            conn.close()
            return True, {"total_shops": total_shops, "owned": owned, "new_balance": int(new_balance_row["balance"] if new_balance_row else 0)}

        async with db_lock:
            success, result = await run_sync_db(_buy_shop_sync)
            if not success:
                return {"success": False, "message": result}
            total_shops = result["total_shops"]
            owned = result["owned"]
            new_balance = result["new_balance"]
            await run_sync_db(check_and_update_achievement, player_id, "tycoon", total_shops)
            all_shop_types = [s["id"] for s in SHOP_LEVELS if s["id"] != "none"]
            if all(t in owned for t in all_shop_types):
                await run_sync_db(check_and_update_achievement, player_id, "shop_lover", len(all_shop_types))
            await run_sync_db(update_daily_quest, player_id, "buy_shop", 1)

        return {"success": True, "message": f"✅ {shop['name']} куплен! Доход +{shop['income_per_hour']}₽/час", "balance": new_balance}
    
    # ---------- ТАКСОПАРК ----------
    elif action.action == "get_taxopark_levels":
        return {"success": True, "levels": TAXOPARK_LEVELS}
    
    elif action.action == "get_taxopark":
        taxopark = player.get("taxopark", {"level": "none", "cars": []})
        level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark.get("level")), TAXOPARK_LEVELS[0])
        return {"success": True, "taxopark": taxopark, "level_info": level}
    
    elif action.action == "buy_taxopark":
        level_id = action.data.get("level_id")
        level = next((l for l in TAXOPARK_LEVELS if l["id"] == level_id), None)
        if not level:
            return {"success": False, "message": "Уровень не найден"}
        taxopark = player.get("taxopark", {"level": "none", "cars": []})
        current_level = taxopark.get("level", "none")
        if current_level == level_id:
            return {"success": False, "message": "У вас уже есть этот таксопарк"}
        levels = [l["id"] for l in TAXOPARK_LEVELS]
        if levels.index(level_id) <= levels.index(current_level):
            return {"success": False, "message": "Вы можете покупать только более дорогие таксопарки!"}
        balance = player.get("balance", 0)
        if balance < level["price"]:
            return {"success": False, "message": f"Недостаточно денег! Нужно {level['price']}₽"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance - level["price"], "taxopark": {"level": level_id, "cars": taxopark.get("cars", []), "car_instance_indices": taxopark.get("car_instance_indices", []), "last_service_at": int(time_module.time()), "last_collect_at": int(taxopark.get("last_collect_at") or time_module.time()), "car_stats": taxopark.get("car_stats", [])}})
            # Добавляем запись в user_taxoparks
            conn = get_db()
            cursor = conn.cursor()
            now = int(time_module.time())
            cursor.execute(
                "INSERT INTO user_taxoparks (player_id, level_id, purchase_price, last_payment, paid_until) VALUES (?, ?, ?, ?, ?)",
                (player_id, level_id, level["price"], 0, 0)
            )
            conn.commit()
            conn.close()
        return {"success": True, "message": f"✅ {level['name']} куплен!", "balance": balance - level["price"]}
    
    elif action.action == "add_car_to_taxopark":
        car_id = action.data.get("car_id")
        raw_index = action.data.get("instance_index")
        taxopark = player.get("taxopark", {"level":"none","cars":[]})
        level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark.get("level")), TAXOPARK_LEVELS[0])
        if level["slots"] == 0: return {"success":False,"message":"Купите таксопарк сначала!"}
        cars=list(taxopark.get("cars",[]) or [])
        if len(cars)>=level["slots"]: return {"success":False,"message":f"Нет мест! Максимум {level['slots']} авто."}
        collection=list(player.get("car_collection",[]) or [])
        try: instance_index=int(raw_index) if raw_index is not None else -1
        except Exception: instance_index=-1
        if instance_index<0:
            used_indices=set(int(x) for x in (taxopark.get("car_instance_indices") or []) if str(x).isdigit())
            matches=[i for i,x in enumerate(collection) if x==car_id]
            instance_index=next((i for i in matches if i not in used_indices),-1)
        if instance_index<0 or instance_index>=len(collection) or collection[instance_index]!=car_id: return {"success":False,"message":"Экземпляр автомобиля не найден в гараже."}
        instance_indices=list(taxopark.get("car_instance_indices") or [])
        if instance_index in instance_indices: return {"success":False,"message":"Эта машина уже на линии."}
        cars.append(car_id); instance_indices.append(instance_index)
        await run_sync_db(update_player_data, player_id, {"taxopark":{"level":taxopark.get("level"),"cars":cars,"car_instance_indices":instance_indices,"last_service_at":taxopark.get("last_service_at") or int(time_module.time()),"last_collect_at":taxopark.get("last_collect_at") or int(time_module.time()),"car_stats":taxopark.get("car_stats",[])}})
        return {"success":True,"message":"✅ Машина добавлена в таксопарк!"}

    elif action.action == "remove_car_from_taxopark":
        car_id = action.data.get("car_id")
        raw_index = action.data.get("instance_index")
        taxopark = player.get("taxopark", {"level":"none","cars":[]})
        cars=list(taxopark.get("cars",[]) or []); indices=list(taxopark.get("car_instance_indices",[]) or [])
        try: instance_index=int(raw_index) if raw_index is not None else -1
        except Exception: instance_index=-1
        pos=indices.index(instance_index) if instance_index in indices else (cars.index(car_id) if car_id in cars else -1)
        if pos<0: return {"success":False,"message":"Этой машины нет в таксопарке"}
        cars.pop(pos)
        if pos<len(indices): indices.pop(pos)
        await run_sync_db(update_player_data, player_id, {"taxopark":{"level":taxopark.get("level"),"cars":cars,"car_instance_indices":indices,"last_service_at":taxopark.get("last_service_at") or int(time_module.time()),"car_stats":taxopark.get("car_stats",[])}})
        return {"success":True,"message":"✅ Машина убрана из таксопарка"}

    # ---------- СКИНЫ ----------
    elif action.action == "get_skins":
        return {"success": True, "skins": SKINS}
    
    elif action.action == "get_player_skins":
        player_skins = await run_sync_db(get_skins, player_id)
        current_skin = player.get("skin", "default")
        return {"success": True, "skins": player_skins, "current": current_skin}
    
    elif action.action == "buy_skin":
        skin_id = action.data.get("skin_id")
        skin = next((s for s in SKINS if s["id"] == skin_id), None)
        if not skin:
            return {"success": False, "message": "Скин не найден"}
        if player.get("skin") == skin_id:
            return {"success": False, "message": "Уже надет!"}
        
        # Проверка лимита (синхронная – но можно оставить, т.к. get_skins будет вызван через run_sync_db)
        player_skins = await run_sync_db(get_skins, player_id)
        if skin.get("limited"):
            count = sum(1 for s in player_skins if s["id"] == skin_id)
            if count >= skin["max_count"]:
                return {"success": False, "message": f"Лимит исчерпан! ({skin['max_count']} шт.)"}
        
        if skin.get("sales_required", 0) > 0:
            total_sales = player.get("total_sales", 0)
            if total_sales < skin["sales_required"]:
                return {"success": False, "message": f"Нужно {skin['sales_required']} продаж! (у тебя {total_sales})"}
        
        balance = player.get("balance", 0)
        if skin["price"] > 0 and balance < skin["price"]:
            return {"success": False, "message": f"Недостаточно! Нужно {skin['price']}₽"}

        # Выполняем транзакцию в отдельной синхронной функции
        def purchase_skin():
            conn = get_db()
            cursor = conn.cursor()
            try:
                # Проверяем, сколько уже есть таких скинов
                cursor.execute("SELECT COUNT(*) as cnt FROM skins WHERE player_id = ? AND skin_id = ?", (player_id, skin_id))
                count = cursor.fetchone()["cnt"]
                
                # Ограничение: не больше 10 штук
                if count >= 10:
                    conn.close()
                    return {"success": False, "message": "❌ У вас уже 10 таких скинов!"}
                
                if skin["price"] > 0:
                    cursor.execute("UPDATE players SET balance = ? WHERE id = ?", (balance - skin["price"], player_id))
                
                # Всегда добавляем новый скин, даже если такой уже есть
                cursor.execute("INSERT INTO skins (player_id, skin_id, equipped) VALUES (?, ?, 0)", (player_id, skin_id))
                
                # Если это первый скин такого типа - делаем его активным
                if count == 0:
                    cursor.execute("UPDATE skins SET equipped = 0 WHERE player_id = ?", (player_id,))
                    cursor.execute("UPDATE skins SET equipped = 1 WHERE player_id = ? AND skin_id = ?", (player_id, skin_id))
                    cursor.execute("UPDATE players SET skin = ? WHERE id = ?", (skin_id, player_id))
                
                conn.commit()
                new_balance = balance - skin["price"] if skin["price"] > 0 else balance
                return {"success": True, "new_balance": new_balance}
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

        try:
            result = await run_sync_db(purchase_skin)
            if result.get("success"):
                # Обновляем player в памяти (необязательно)
                player = await run_sync_db(get_player_data, player_id)
                return {"success": True, "message": f"✅ {skin['name']} куплен и надет!", "balance": result["new_balance"]}
            else:
                return {"success": False, "message": "Ошибка при покупке"}
        except Exception as e:
            return {"success": False, "message": f"Ошибка БД: {str(e)}"}

    elif action.action == "equip_skin":
        skin_id = action.data.get("skin_id")
        instance_id = action.data.get("instance_id")  # может быть None
        skin = next((s for s in SKINS if s["id"] == skin_id), None)
        if not skin:
            return {"success": False, "message": "Скин не найден"}
        # Проверяем, есть ли скин у игрока (хотя бы одна копия)
        player_skins = await run_sync_db(get_skins, player_id)
        if not any(s["id"] == skin_id for s in player_skins):
            return {"success": False, "message": "У вас нет этого скина"}
        # Если instance_id не указан, берем первую копию
        if instance_id is None:
            for s in player_skins:
                if s["id"] == skin_id:
                    instance_id = s["instance_id"]
                    break
        # Экипируем конкретную копию
        await run_sync_db(equip_skin, player_id, skin_id, instance_id)
        return {"success": True, "message": f"✅ Скин {skin['name']} надет!"}

    # ---------- РЕПУТАЦИЯ ----------
    elif action.action == "get_reputation":
        total_sales = player.get("total_sales", 0)
        total_profit = player.get("total_profit", 0)
        return {
            "success": True,
            "total_sales": total_sales,
            "total_profit": total_profit,
            "rating": get_avito_rating(total_sales),
            "level": get_rep_level(total_sales)
        }
    
    # ---------- ПОДРАБОТКИ ----------
    elif action.action == "get_jobs":
        return {"success": True, "jobs": JOBS}
    
    elif action.action == "start_job":
        job_idx = action.data.get("job_idx")
        if job_idx is None or job_idx >= len(JOBS):
            return {"success": False, "message": "Работа не найдена"}
        async with side_jobs_lock:
            if player_id in side_jobs and not side_jobs[player_id].get("done", True):
                return {"success": False, "message": "Вы уже работаете!"}
            side_jobs[player_id] = {"job_type": job_idx, "start_time": time_module.time(), "done": False}
        job = JOBS[job_idx]
        return {"success": True, "message": f"💼 {job['emoji']} {job['name']} начата! Через {job['duration']} сек. получите {job['reward']}₽", "duration": job["duration"]}
    
    elif action.action == "check_job":
        if player_id not in side_jobs:
            return {"success": False, "message": "Нет активной работы"}
        job = side_jobs[player_id]
        if job.get("done"):
            reward = JOBS[job["job_type"]]["reward"]
            del side_jobs[player_id]
            return {"success": True, "finished": True, "reward": reward}
        else:
            elapsed = time_module.time() - job["start_time"]
            remaining = max(0, JOBS[job["job_type"]]["duration"] - elapsed)
            return {"success": True, "finished": False, "remaining": int(remaining)}
    # ---------- ТРЕЙДИНГ ----------
    elif action.action == "get_trading_prices":
        async with trading_lock:
            return {"success": True, "prices": trading_prices.copy()}
    
    elif action.action == "buy_trading_item":
        category = action.data.get("category")
        amount = action.data.get("amount", 0)
        async with trading_lock:
            if category not in trading_prices:
                return {"success": False, "message": "Категория не найдена"}
            price = trading_prices[category]["price"]
        total = price * amount
        balance = player.get("balance", 0)
        if balance < total:
            return {"success": False, "message": f"Недостаточно денег! Нужно {total}₽"}
        trader = await get_trader(player_id)
        portfolio = trader["portfolio"]
        portfolio[category] = portfolio.get(category, 0) + amount
        await save_trader(player_id, portfolio, trader["invested"] + total)
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance - total})
        return {"success": True, "message": f"✅ Куплено {amount} ед. {category} за {total}₽", "balance": balance - total}
    
    elif action.action == "sell_trading_item":
        category = action.data.get("category")
        amount = action.data.get("amount", 0)
        async with trading_lock:
            if category not in trading_prices:
                return {"success": False, "message": "Категория не найдена"}
            price = trading_prices[category]["price"]
        trader = await get_trader(player_id)   # ← добавлен await
        portfolio = trader["portfolio"]
        if portfolio.get(category, 0) < amount:
            return {"success": False, "message": "Недостаточно товара"}
        total = price * amount
        portfolio[category] -= amount
        if portfolio[category] == 0:
            del portfolio[category]
        await save_trader(player_id, portfolio, trader["invested"])   # ← добавлен await
        balance = player.get("balance", 0)
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance + total})   # ← обёрнуто в run_sync_db
        return {"success": True, "message": f"✅ Продано {amount} ед. {category} за {total}₽", "balance": balance + total}
    
    elif action.action == "get_trading_portfolio":
        trader = await get_trader(player_id)
        return {"success": True, "portfolio": trader["portfolio"], "invested": trader["invested"]}
    
    # ---------- РАЗБОР ПОСТАВКИ ----------
    elif action.action == "start_supply":
        async with supply_drop_lock:
            if player_id in supply_drop and supply_drop[player_id].get("active"):
                return {"success": False, "message": "У вас уже есть активная поставка!"}
        balance = player.get("balance", 0)
        if balance < 10000:
            return {"success": False, "message": "Нужно 10 000₽ для покупки поставки!"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance - 10000})
        items_in_box = []
        for _ in range(random.randint(1, 3)):
            rarities = list(SUPPLIER_ITEM_RARITIES.keys())
            weights = [SUPPLIER_ITEM_RARITIES[r]["chance"] for r in rarities]
            rarity = random.choices(rarities, weights=weights, k=1)[0]
            rd = SUPPLIER_ITEM_RARITIES[rarity]
            base = random.choice(BASE_ITEMS)
            mp = random.randint(3000, 20000)
            items_in_box.append({
                "name": f"{rd['color']} {base['cat']} {base['name']}",
                "cat": base["cat"],
                "buy_price": int(mp * 0.5),
                "market_price": mp,
                "rarity": rarity
            })
        async with supply_drop_lock:
            supply_drop[player_id] = {"items": items_in_box, "found": [], "clicks": 0, "active": True}
        return {"success": True, "message": f"📦 Поставка куплена за 10 000₽! Внутри {len(items_in_box)} товаров. Жмите кнопку разбора.", "items_count": len(items_in_box)}
    
    elif action.action == "supply_click":
        async with supply_drop_lock:
            drop = supply_drop.get(player_id)
            if not drop or not drop.get("active"):
                return {"success": False, "message": "Нет активной поставки"}
            drop["clicks"] += 1
            found_item = None
            if random.random() < 0.4 and drop["items"]:
                found_item = drop["items"].pop(random.randint(0, len(drop["items"])-1))
                drop["found"].append(found_item)
            remaining = 10 - drop["clicks"]
            if remaining <= 0:
                async with db_lock:
                    inventory = player.get("inventory", [])
                    for item in drop["found"]:
                        inventory.append(item)
                    await run_sync_db(update_player_data, player_id, {"inventory": inventory})
                await run_sync_db(update_daily_quest, player_id, "supply_unpack", 1)
                supply_drop[player_id]["active"] = False
                return {
                    "success": True,
                    "finished": True,
                    "found": drop["found"],
                    "message": f"📦 Поставка разобрана! Найдено {len(drop['found'])} вещей."
                }
            else:
                if found_item:
                    msg_part = f"Найдено: {found_item['name']}!"
                else:
                    msg_part = "Ничего..."
                return {
                    "success": True,
                    "finished": False,
                    "remaining": remaining,
                    "found_item": found_item,
                    "found_count": len(drop["found"]),
                    "message": f"🔍 Клик {drop['clicks']}/10. {msg_part}"
                }
    
    # ---------- ОБУЧЕНИЕ ----------
    elif action.action == "get_learning":
        learning = await run_sync_db(get_learning_data, player_id)
        return {"success": True, "completed": learning.get("completed", [])}
    
    elif action.action == "complete_lesson":
        lesson_id = action.data.get("lesson_id")
        reward = action.data.get("reward", 0)
        learning = await run_sync_db(get_learning_data, player_id)
        completed = learning.get("completed", [])
        if lesson_id in completed:
            return {"success": False, "message": "Урок уже пройден"}
        async with db_lock:
            completed.append(lesson_id)
            await run_sync_db(update_learning_data, player_id, {"completed": completed})
            balance = player.get("balance", 0)
            await run_sync_db(update_player_data, player_id, {"balance": balance + reward})
        return {"success": True, "message": f"✅ Урок пройден! Получено {reward}₽", "balance": balance + reward}
    
    # ---------- РЕФЕРАЛЫ ----------
    elif action.action == "get_referral_data":
        ref_data = await run_sync_db(get_referral_data, player_id)
        return {"success": True, "invited": ref_data["invited"], "count": len(ref_data["invited"])}
    
    elif action.action == "claim_referral_bonus":
        ref_data = await run_sync_db(get_referral_data, player_id)
        invited = ref_data.get("invited", [])
        already_claimed = ref_data.get("bonus_claimed", False)
        if already_claimed:
            return {"success": False, "message": "Бонус уже получен"}
        async with db_lock:
            bonus = len(invited) * 10000
            balance = player.get("balance", 0)
            await run_sync_db(update_player_data, player_id, {"balance": balance + bonus})
            await run_sync_db(update_referral_data, player_id, {"invited": invited, "bonus_claimed": True})
        return {"success": True, "message": f"✅ Получено {bonus}₽ за {len(invited)} приглашённых", "balance": balance + bonus}
    
    # ---------- ДРУЗЬЯ ----------
    elif action.action == "get_friends":
        friends = await run_sync_db(get_friends, player_id)
        return {"success": True, "friends": friends}
    
    elif action.action == "add_friend":
        friend_name = action.data.get("friend_name")
        friend_info = find_user_by_nickname(friend_name)
        if not friend_info:
            return {"success": False, "message": "Игрок не найден"}
        friend_id = friend_info["id"]
        if friend_id == player_id:
            return {"success": False, "message": "Нельзя добавить себя!"}
        async with db_lock:
            friends = await run_sync_db(get_friends, player_id)
            if friend_id in friends:
                return {"success": False, "message": "Уже в друзьях!"}
            friends.append(friend_id)
            await run_sync_db(update_friends, player_id, friends)
        return {"success": True, "message": "✅ Добавлен в друзья!"}
    
    elif action.action == "remove_friend":
        friend_id = action.data.get("friend_id")
        async with db_lock:
            friends = await run_sync_db(get_friends, player_id)
            if friend_id not in friends:
                return {"success": False, "message": "Не в друзьях!"}
            friends.remove(friend_id)
            await run_sync_db(update_friends, player_id, friends)
        return {"success": True, "message": "Удалён из друзей."}
    
    elif action.action == "get_achievements":
        def _sync_achievements():
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT achievement_id, progress, completed FROM achievements WHERE player_id = ?", (player_id,))
            rows = cursor.fetchall()
            cursor.execute("SELECT quest_id, progress, completed FROM daily_quests WHERE player_id = ?", (player_id,))
            quest_rows = cursor.fetchall()
            conn.close()
            achievements_info = {}
            for row in rows:
                achievements_info[row["achievement_id"]] = {
                    "progress": row["progress"],
                    "completed": bool(row["completed"])
                }
            quests_info = {}
            for row in quest_rows:
                quests_info[row["quest_id"]] = {
                    "progress": row["progress"],
                    "completed": bool(row["completed"])
                }
            return achievements_info, quests_info
        
        achievements_info, quests_info = await run_sync_db(_sync_achievements)
        return {"success": True, "achievements": achievements_info, "quests": quests_info}

    # ---------- ГОНКИ ----------
    elif action.action == "get_races":
        async with races_lock:
            now = time_module.time()
            for race_id, race in list(active_races.items()):
                if race.get("status") == "wait" and now - race.get("created_at", 0) > 3600:
                    creator = race.get("creator")
                    if creator:
                        creator_data = await run_sync_db(get_player_data, creator)  # <-- ИСПРАВЛЕНО
                        if creator_data:
                            async with db_lock:
                                await run_sync_db(update_player_data, creator, {"balance": creator_data.get("balance", 0) + race.get("bet", 0)})
                    del active_races[race_id]
            races = []
            for race_id, race in active_races.items():
                if race.get("status") not in ("finished", "draw"):
                    races.append({
                        "id": race_id,
                        "creator": race.get("creator"),
                        "opponent": race.get("opponent"),
                        "creator_car": race.get("creator_car"),
                        "bet": race.get("bet"),
                        "status": race.get("status")
                    })
        return {"success": True, "races": races}
    
    elif action.action == "create_race":
        car_id = action.data.get("car_id")
        bet = action.data.get("bet", 5000)
        if bet < 5000:
            return {"success": False, "message": "Минимальная ставка: 5 000₽"}
        car_collection = player.get("car_collection", [])
        if car_id not in car_collection:
            return {"success": False, "message": "Этой машины нет в гараже!"}
        balance = player.get("balance", 0)
        if balance < bet:
            return {"success": False, "message": "Недостаточно денег!"}
        race_id = f"race_{player_id}_{int(time_module.time() * 1000)}"
        async with races_lock:
            active_races[race_id] = {
                "creator": player_id,
                "opponent": None,
                "creator_car": car_id,
                "opponent_car": None,
                "bet": bet,
                "phase": 1,
                "creator_score": 0,
                "opponent_score": 0,
                "creator_choice": None,
                "opponent_choice": None,
                "prize_pool": bet,
                "status": "wait",
                "created_at": time_module.time(),
                "last_action_time": time_module.time()
            }
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance - bet})
        return {"success": True, "race_id": race_id, "message": "🏎 Гонка создана!", "balance": balance - bet}
    
    elif action.action == "join_race":
        race_id = action.data.get("race_id")
        car_id = action.data.get("car_id")
        async with races_lock:
            race = active_races.get(race_id)
            if not race:
                return {"success": False, "message": "Гонка не найдена!"}
            if race["status"] != "wait":
                return {"success": False, "message": "Гонка уже началась!"}
            if race["creator"] == player_id:
                return {"success": False, "message": "Нельзя гонять с собой!"}
        car_collection = player.get("car_collection", [])
        if car_id not in car_collection:
            return {"success": False, "message": "Этой машины нет в гараже!"}
        balance = player.get("balance", 0)
        if balance < race["bet"]:
            return {"success": False, "message": "Недостаточно денег!"}
        async with db_lock:
            def _debit_race():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    row=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                    fresh_balance=int(row["balance"] or 0) if row else 0
                    if not row or fresh_balance<race["bet"]:
                        conn.rollback(); return (False,fresh_balance)
                    cur.execute("UPDATE players SET balance=balance-? WHERE id=? AND balance>=?",(race["bet"],player_id,race["bet"]))
                    if cur.rowcount!=1:
                        conn.rollback(); return (False,fresh_balance)
                    conn.commit(); return (True,fresh_balance-race["bet"])
                except Exception:
                    conn.rollback(); raise
                finally: conn.close()
            debited,new_balance=await run_sync_db(_debit_race)
        if not debited:
            return {"success":False,"message":"Недостаточно денег!"}
        async with races_lock:
            race = active_races.get(race_id)
            if not race or race["status"] != "wait":
                await run_sync_db(_atomic_add_balance_sync, player_id, int(race["bet"]) if race else 0)
                return {"success":False,"message":"Гонка уже началась или завершена! Ставка возвращена."}
            race["opponent"] = player_id
            race["opponent_car"] = car_id
            race["status"] = "phase_1"
            race["phase"] = 1
            race["prize_pool"] = race["bet"] * 2
            race["creator_choice"] = None
            race["opponent_choice"] = None
            race["creator_score"] = 0
            race["opponent_score"] = 0
        
        # Отправляем обоим игрокам сообщение о начале гонки
        creator_data = await run_sync_db(get_player_data, race["creator"])  # <-- ИСПРАВЛЕНО
        opponent_data = await run_sync_db(get_player_data, player_id)       # <-- ИСПРАВЛЕНО
        creator_tg = creator_data.get("tg_id")
        opponent_tg = opponent_data.get("tg_id")
        text = f"🏎 <b>ГОНКА НАЧАЛАСЬ!</b>\nСтавка: {race['bet']}₽\n\nФаза 1/3. Выберите действие:"
        kb = get_race_action_keyboard(race_id)
        if creator_tg:
            try:
                await bot.send_message(creator_tg, text, parse_mode="HTML", reply_markup=kb)
            except:
                pass
        if opponent_tg:
            try:
                await bot.send_message(opponent_tg, text, parse_mode="HTML", reply_markup=kb)
            except:
                pass
        return {"success": True, "message": "🏎 Вы в гонке! Ожидайте ход соперника.", "race": race, "balance": balance - race["bet"]}
    
    elif action.action == "get_race":
        race_id = action.data.get("race_id")
        race = active_races.get(race_id)
        if not race:
            return {"success": False, "message": "Гонка не найдена"}
        return {"success": True, "race": race}
    
    elif action.action == "race_action":
        race_id = action.data.get("race_id")
        race_action_type = action.data.get("race_action")

        async with races_lock:
            race = active_races.get(race_id)
            if not race:
                return {"success": False, "message": "Гонка не найдена!"}

            is_creator = (player_id == race["creator"])
            if is_creator:
                if race["creator_choice"] is not None:
                    return {"success": False, "message": "Вы уже сделали выбор в этой фазе!"}
                race["creator_choice"] = race_action_type
            else:
                if race["opponent_choice"] is not None:
                    return {"success": False, "message": "Вы уже сделали выбор в этой фазе!"}
                race["opponent_choice"] = race_action_type

            # Обновляем время последнего действия (для таймаута)
            race["last_action_time"] = time_module.time()

            # Если выборы сделаны не оба – ждём
            if race["creator_choice"] is None or race["opponent_choice"] is None:
                return {"success": True, "finished": False, "waiting": True, "message": "Ожидаем ход соперника..."}

            # Оба выбрали – обрабатываем фазу
            creator_car = race["creator_car"]
            opponent_car = race["opponent_car"]
            creator_action = race["creator_choice"]
            opponent_action = race["opponent_choice"]

            # Списание за нитро
            if creator_action == "nitro":
                fee = int(race["bet"] * 0.05)
                creator_data = await run_sync_db(get_player_data, race["creator"])
                if creator_data and creator_data.get("balance", 0) >= fee:
                    async with db_lock:
                        await run_sync_db(update_player_data, race["creator"], {"balance": creator_data.get("balance", 0) - fee})
                    race["prize_pool"] += fee
            if opponent_action == "nitro":
                fee = int(race["bet"] * 0.05)
                opponent_data = await run_sync_db(get_player_data, race["opponent"])
                if opponent_data and opponent_data.get("balance", 0) >= fee:
                    async with db_lock:
                        await run_sync_db(update_player_data, race["opponent"], {"balance": opponent_data.get("balance", 0) - fee})
                    race["prize_pool"] += fee

            # Рассчитываем очки
            creator_score, _ = calculate_race_score(creator_car, creator_action, race["phase"])
            opponent_score, _ = calculate_race_score(opponent_car, opponent_action, race["phase"])
            race["creator_score"] += creator_score
            race["opponent_score"] += opponent_score

            # Сбрасываем выборы
            race["creator_choice"] = None
            race["opponent_choice"] = None

            # Проверяем окончание гонки (после 3 фаз)
            if race["phase"] >= 3:
                winner_id = None
                if race["creator_score"] > race["opponent_score"]:
                    winner_id = race["creator"]
                elif race["opponent_score"] > race["creator_score"]:
                    winner_id = race["opponent"]

                if winner_id:
                    async with db_lock:
                        winner_player = await run_sync_db(get_player_data, winner_id)
                        if winner_player:
                            await run_sync_db(update_player_data, winner_id, {"balance": winner_player.get("balance", 0) + race["prize_pool"]})
                    race["winner"] = winner_id
                    await run_sync_db(update_daily_quest, winner_id, "win_race", 1)
                    race["status"] = "finished"
                    creator_score_val = race["creator_score"]
                    opponent_score_val = race["opponent_score"]
                    prize = race["prize_pool"]
                    # Сохраняем данные для уведомлений
                    winner_data = await run_sync_db(get_player_data, winner_id)
                    loser_id = race["opponent"] if winner_id == race["creator"] else race["creator"]
                    loser_data = await run_sync_db(get_player_data, loser_id)
                    # Удаляем гонку из памяти ПОСЛЕ того, как собрали данные
                    del active_races[race_id]
                    # Уведомления вне блокировки races_lock
                    if winner_data and winner_data.get("tg_id"):
                        await bot.send_message(winner_data["tg_id"], f"🏆 Вы выиграли гонку! +{prize}₽")
                    if loser_data and loser_data.get("tg_id"):
                        await bot.send_message(loser_data["tg_id"], f"😔 Вы проиграли гонку. Соперник выиграл {prize}₽")
                    return {
                        "success": True,
                        "finished": True,
                        "winner": winner_id,
                        "prize_pool": prize,
                        "creator_score": creator_score_val,
                        "opponent_score": opponent_score_val
                    }
                else:
                    # Ничья
                    async with db_lock:
                        creator_data = await run_sync_db(get_player_data, race["creator"])
                        opponent_data = await run_sync_db(get_player_data, race["opponent"])
                        if creator_data:
                            await run_sync_db(update_player_data, race["creator"], {"balance": creator_data.get("balance", 0) + race["bet"]})
                        if opponent_data:
                            await run_sync_db(update_player_data, race["opponent"], {"balance": opponent_data.get("balance", 0) + race["bet"]})
                    race["status"] = "draw"
                    creator_tg = (await run_sync_db(get_player_data, race["creator"])).get("tg_id")
                    opponent_tg = (await run_sync_db(get_player_data, race["opponent"])).get("tg_id")
                    del active_races[race_id]
                    if creator_tg:
                        await bot.send_message(creator_tg, "🤝 Ничья! Ваши ставки возвращены.")
                    if opponent_tg:
                        await bot.send_message(opponent_tg, "🤝 Ничья! Ваши ставки возвращены.")
                    return {"success": True, "finished": True}
            else:
                # Переход к следующей фазе
                race["phase"] += 1
                creator_data = await run_sync_db(get_player_data, race["creator"])
                opponent_data = await run_sync_db(get_player_data, race["opponent"])
                creator_tg = creator_data.get("tg_id") if creator_data else None
                opponent_tg = opponent_data.get("tg_id") if opponent_data else None
                phase = race["phase"]
                creator_score = race["creator_score"]
                opponent_score = race["opponent_score"]
                kb = get_race_action_keyboard(race_id)
                text_phase = f"🏎 <b>ФАЗА {phase}/3</b>\nСчёт: {creator_score} : {opponent_score}\nВыберите действие:"
                if creator_tg:
                    await bot.send_message(creator_tg, text_phase, parse_mode="HTML", reply_markup=kb)
                if opponent_tg:
                    await bot.send_message(opponent_tg, text_phase, parse_mode="HTML", reply_markup=kb)
                return {"success": True, "finished": False, "phase": phase, "message": f"Фаза {phase} начата!"}
    
    # ---------- ПЕРЕВОД ДЕНЕГ ----------
    elif action.action == "transfer":
        to_player_id=int(action.data.get("to_player_id") or 0)
        amount=_safe_int(action.data.get("amount",0))
        if amount < 100:
            return {"success":False,"message":"Минимальная сумма перевода: 100₽"}
        if to_player_id == player_id:
            return {"success":False,"message":"Нельзя переводить деньги самому себе"}
        async with db_lock:
            def _transfer():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    sender=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                    receiver=cur.execute("SELECT balance FROM players WHERE id=?",(to_player_id,)).fetchone()
                    if not receiver: conn.rollback(); return ("missing",None)
                    if not sender or int(sender["balance"] or 0)<amount:
                        conn.rollback(); return ("funds",int(sender["balance"] or 0) if sender else 0)
                    new_sender=int(sender["balance"])-amount; new_receiver=int(receiver["balance"])+amount
                    cur.execute("UPDATE players SET balance=? WHERE id=?",(new_sender,player_id))
                    cur.execute("UPDATE players SET balance=? WHERE id=?",(new_receiver,to_player_id))
                    conn.commit(); return ("ok",new_sender)
                except Exception:
                    conn.rollback(); raise
                finally: conn.close()
            res=await run_sync_db(_transfer)
        if res[0]=="missing": return {"success":False,"message":"Получатель не найден"}
        if res[0]=="funds": return {"success":False,"message":f"Недостаточно денег! У вас: {res[1]}₽"}
        return {"success":True,"message":f"✅ Переведено {amount}₽","balance":res[1]}

    # ---------- АУКЦИОН ----------
    elif action.action == "get_auction_items":
        async with auction_lock:
            items=[dict(x) for x in auction_items if x.get("active",True)]
        return {"success":True,"auction_items":items}

    elif action.action == "add_auction_item":
        item_type=action.data.get("item_type",""); start_price=max(0,_safe_int(action.data.get("start_price",0)))
        if item_type in ("","item","inventory") and (action.data.get("item_uid") is not None or action.data.get("item_idx") is not None):
            fresh=await run_sync_db(ensure_inventory_uids_sync,player_id,player); inv=list(fresh.get("inventory",[])); item,idx=get_inventory_item(inv,action.data.get("item_uid",action.data.get("item_idx")))
            if not item: return {"success":False,"message":"Товар не найден в инвентаре."}
            uid=str(item.get("uid")); price=start_price or max(100,int(item.get("market_price",100)*.75))
            inv.pop(idx)
            async with db_lock:
                await run_sync_db(update_player_data,player_id,{"inventory":inv}); conn=get_db(); cur=conn.cursor(); end_time=int(time_module.time()+3600)
                cur.execute("INSERT INTO auction(seller_id,item_name,item_data,start_price,current_bid,bidder_id,end_time,active) VALUES(?,?,?,?,?,?,?,1)",(player_id,item["name"],json.dumps({**item,"type":"inventory"},ensure_ascii=False),price,price,None,end_time)); lot_id=cur.lastrowid; conn.commit(); conn.close()
            lot={"id":lot_id,"lot_id":lot_id,"seller_id":player_id,"item":{**item,"type":"inventory"},"inventory_uid":uid,"start_price":price,"current_bid":price,"bidder_id":None,"end_time":end_time,"active":True,"item_type":"inventory"}
            async with auction_lock: auction_items.append(lot)
            return {"success":True,"message":f"✅ {item['name']} выставлен на аукцион от {price:,}₽.","lot_id":lot_id}

        if item_type=="skin":
            skin_id=action.data.get("skin_id"); skin=next((x for x in SKINS if x["id"]==skin_id),None)
            if not skin: return {"success":False,"message":"Скин не найден"}
            skins=get_skins(player_id); candidate=next((x for x in skins if x["id"]==skin_id),None)
            if not candidate: return {"success":False,"message":"У вас нет этого скина"}
            price=start_price or max(1000,skin["price"]//2 or 1000); end_time=int(time_module.time()+3600)
            async with db_lock:
                conn=get_db(); cur=conn.cursor(); cur.execute("DELETE FROM skins WHERE id=? AND player_id=?",(candidate["instance_id"],player_id))
                if cur.rowcount!=1: conn.close(); return {"success":False,"message":"Скин уже выставлен или отсутствует."}
                cur.execute("INSERT INTO auction(seller_id,item_name,item_data,start_price,current_bid,bidder_id,end_time,active) VALUES(?,?,?,?,?,?,?,1)",(player_id,f"🎨 Скин: {skin['name']}",json.dumps({"name":f"🎨 Скин: {skin['name']}","skin_id":skin_id,"type":"skin"},ensure_ascii=False),price,price,None,end_time)); lot_id=cur.lastrowid; conn.commit(); conn.close()
            lot={"id":lot_id,"lot_id":lot_id,"seller_id":player_id,"item":{"name":f"🎨 Скин: {skin['name']}","skin_id":skin_id,"type":"skin"},"start_price":price,"current_bid":price,"bidder_id":None,"end_time":end_time,"active":True,"item_type":"skin"}
            async with auction_lock: auction_items.append(lot)
            return {"success":True,"message":f"✅ Скин {skin['name']} выставлен на аукцион!","lot_id":lot_id}

        if item_type=="car":
            car_id=action.data.get("car_id"); car=next((x for x in CARS if x["id"]==car_id),None)
            if not car: return {"success":False,"message":"Машина не найдена"}
            price=start_price or max(1000,car["price"]//2); end_time=int(time_module.time()+3600)
            async with db_lock:
                fresh=await run_sync_db(get_player_data,player_id); cars=list(fresh.get("car_collection",[])) if fresh else []
                if car_id not in cars: return {"success":False,"message":"У вас нет этой машины"}
                cars.remove(car_id); await run_sync_db(update_player_data,player_id,{"car_collection":cars,"current_car":"none" if fresh.get("current_car")==car_id else fresh.get("current_car","none")})
                conn=get_db(); cur=conn.cursor(); cur.execute("INSERT INTO auction(seller_id,item_name,item_data,start_price,current_bid,bidder_id,end_time,active) VALUES(?,?,?,?,?,?,?,1)",(player_id,f"🚗 {car['name']}",json.dumps({"name":f"🚗 {car['name']}","car_id":car_id,"type":"car"},ensure_ascii=False),price,price,None,end_time)); lot_id=cur.lastrowid; conn.commit(); conn.close()
            lot={"id":lot_id,"lot_id":lot_id,"seller_id":player_id,"item":{"name":f"🚗 {car['name']}","car_id":car_id,"type":"car"},"start_price":price,"current_bid":price,"bidder_id":None,"end_time":end_time,"active":True,"item_type":"car"}
            async with auction_lock: auction_items.append(lot)
            return {"success":True,"message":f"✅ {car['name']} выставлена на аукцион!","lot_id":lot_id}
        return {"success":False,"message":"Неизвестный тип лота."}

    elif action.action == "bid_auction":
        lot_id=action.data.get("lot_id",action.data.get("item_index")); bid=_safe_int(action.data.get("bid",0))
        if bid<=0: return {"success":False,"message":"Ставка должна быть положительной."}
        async with auction_lock:
            item=next((x for x in auction_items if x.get("active",True) and str(x.get("lot_id",x.get("id")))==str(lot_id)),None)
            if not item:
                return {"success":False,"message":"Лот не найден или уже завершён."}
            if item["seller_id"]==player_id: return {"success":False,"message":"Нельзя ставить на свой лот!"}
            current=int(item.get("current_bid",0)); min_bid=current if not item.get("bidder_id") else int(current*1.10)
            if bid<min_bid: return {"success":False,"message":f"Минимальная ставка: {min_bid:,}₽"}
            if item.get("bidder_id")==player_id: return {"success":False,"message":"Вы уже лидер этого лота."}
            prev_bidder=item.get("bidder_id"); prev_amount=current if prev_bidder else 0
            async with db_lock:
                fresh=await run_sync_db(get_player_data,player_id)
                if not fresh or int(fresh.get("balance",0))<bid: return {"success":False,"message":f"Недостаточно средств. Нужно {bid:,}₽."}
                if prev_bidder:
                    prev=await run_sync_db(get_player_data,int(prev_bidder));
                    if prev: await run_sync_db(update_player_data,int(prev_bidder),{"balance":int(prev.get("balance",0))+prev_amount})
                new_balance=int(fresh.get("balance",0))-bid; await run_sync_db(update_player_data,player_id,{"balance":new_balance})
                conn=get_db(); conn.execute("UPDATE auction SET current_bid=?,bidder_id=? WHERE id=? AND active=1",(bid,player_id,int(item["lot_id"]))); conn.commit(); conn.close()
            item["current_bid"]=bid; item["bidder_id"]=player_id
            return {"success":True,"message":f"✅ Ставка {bid:,}₽ принята!","balance":new_balance,"lot_id":item["lot_id"]}

    elif action.action == "get_player_by_nickname":
        nickname = action.data.get("nickname")
        player_info = await run_sync_db(find_user_by_nickname, nickname)
        if not player_info:
            return {"success": False, "message": "Игрок не найден"}
        return {"success": True, "player": {"id": player_info["id"], "nickname": player_info["nickname"]}}
    
    elif action.action == "get_leaderboard":
        # Синхронная функция для получения топа
        def _get_top_sellers():
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, nickname, total_sales, total_profit FROM players ORDER BY total_sales DESC LIMIT 10")
            rows = cursor.fetchall()
            conn.close()
            return [{"id": row["id"], "nickname": row["nickname"], "sales": row["total_sales"], "profit": row["total_profit"]} for row in rows]

        top = await run_sync_db(_get_top_sellers)
        return {"success": True, "leaderboard": top}

    elif action.action == "get_leaderboard_wealth":
        # Синхронная функция для расчёта богатства
        def _get_wealth_leaderboard():
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("SELECT id, tg_id, nickname, balance FROM players")
            players = cursor.fetchall()
            conn.close()

            wealth_list = []
            for p in players:
                player_id = p["id"]
                tg_id = p["tg_id"]
                nickname = p["nickname"] or f"ID:{tg_id}"
                balance = p["balance"]
                total_wealth = balance
                shops_count = 0  # <-- ИНИЦИАЛИЗИРУЕМ ПЕРЕМЕННУЮ

                # Стоимость всех магазинов
                conn2 = get_db()
                cursor2 = conn2.cursor()
                cursor2.execute("SELECT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
                shops = cursor2.fetchall()
                shops_value = 0
                for row in shops:
                    shop = next((s for s in SHOP_LEVELS if s["id"] == row["shop_id"]), None)
                    if shop:
                        shops_value += shop["price"]
                        shops_count += 1  # <-- УВЕЛИЧИВАЕМ СЧЁТЧИК
                conn2.close()
                total_wealth += shops_value

                # Стоимость машин и дома
                player_data = get_player_data(player_id)
                if player_data:
                    car_collection = player_data.get("car_collection", [])
                    cars_value = 0
                    for car_id in car_collection:
                        car = next((c for c in CARS if c["id"] == car_id), None)
                        if car:
                            cars_value += car["price"]
                    house_id = player_data.get("house", "room")
                    house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
                    house_value = house["price"]
                    total_wealth += cars_value + house_value
                    cars_count = len(car_collection)
                else:
                    cars_count = 0

                wealth_list.append({
                    "nickname": nickname,
                    "wealth": total_wealth,
                    "balance": balance,
                    "shops_count": shops_count,  # <-- ТЕПЕРЬ ПЕРЕМЕННАЯ ОПРЕДЕЛЕНА
                    "cars_count": cars_count
                })

            wealth_list.sort(key=lambda x: x["wealth"], reverse=True)
            return wealth_list[:10]

        top10 = await run_sync_db(_get_wealth_leaderboard)
        return {"success": True, "leaderboard": top10}

    elif action.action == "get_player_profile":
        target_player_id = action.data.get("player_id")
        if not target_player_id:
            return {"success": False, "message": "Не указан игрок"}

        # Синхронная функция для сбора профиля
        def _get_profile(pid):
            conn = get_db()
            cursor = conn.cursor()
            target = get_player_data(pid)
            if not target:
                conn.close()
                return None

            nickname = target.get("nickname", "Без имени")
            balance = target.get("balance", 0)
            total_sales = target.get("total_sales", 0)
            total_earned = target.get("total_earned", 0)
            house_id = target.get("house", "room")
            house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
            current_car_id = target.get("current_car", "none")
            current_car = next((c for c in CARS if c["id"] == current_car_id), None)
            car_collection = target.get("car_collection", [])
            cars_count = len(car_collection)

            cursor.execute("SELECT COUNT(*) as cnt FROM user_shops WHERE player_id = ?", (pid,))
            shops_count = cursor.fetchone()["cnt"]
            conn.close()

            profile_text = (
                f"👤 <b>ПРОФИЛЬ ИГРОКА</b>\n\n"
                f"📛 Ник: {nickname}\n"
                f"💰 Баланс: {balance:,}₽\n"
                f"📊 Продано товаров: {total_sales}\n"
                f"💸 Прибыль: {total_earned:,}₽\n"
                f"🏠 Недвижимость: {house['name']}\n"
                f"🚗 Текущая машина: {current_car['name'] if current_car else 'Нет'}\n"
                f"🎮 Машин в гараже: {cars_count}\n"
                f"🏪 Магазинов: {shops_count}\n"
            )
            return profile_text

        profile = await run_sync_db(_get_profile, target_player_id)
        if not profile:
            return {"success": False, "message": "Игрок не найден"}
        return {"success": True, "profile": profile}

    # ---------- ДОБАВЛЕНИЕ БАЛАНСА (ДЛЯ БОНУСОВ) ----------
    elif action.action == "add_balance":
        amount = action.data.get("amount", 0)
        balance = player.get("balance", 0)
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance + amount})
        return {"success": True, "balance": balance + amount}
    
    # ---------- ДОБАВЛЕНИЕ РЕФЕРАЛА С БОНУСАМИ ----------
    elif action.action == "add_referral":
        inviter_id = action.data.get("inviter_id")
        new_player_id = action.data.get("new_player_id")
        if not inviter_id or not new_player_id:
            return {"success": False, "message": "Ошибка параметров"}
        async with db_lock:
            ref_data = await run_sync_db(get_referral_data, inviter_id)
            invited = ref_data.get("invited", [])
            if new_player_id in invited:
                return {"success": False, "message": "Уже приглашён"}
            invited.append(new_player_id)
            await run_sync_db(update_referral_data, inviter_id, {"invited": invited, "bonus_claimed": False})
        return {"success": True, "message": "Реферал добавлен. Награду можно получить в меню рефералов."}

    # ---------- АКЦИИ ----------
    elif action.action == "stocks_menu":
        prices = await run_sync_db(get_stock_prices)
        portfolio = await run_sync_db(get_user_stocks, player_id)
        portfolio_value, profit = await run_sync_db(calculate_portfolio_value, player_id)
        text = "📈 <b>ФОНДОВЫЙ РЫНОК</b>\n\n"
        for stock in prices:
            sym = stock["symbol"]
            name = stock["name"]
            price = stock["price"]
            change = stock["change_pct"]
            arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            text += f"{arrow} <b>{sym}</b> {name}\n💰 {price:,}₽ ({change:+.2f}%)\n\n"
        text += f"📊 <b>Ваш портфель</b>\n"
        if portfolio:
            for s in portfolio:
                curr_price = (await run_sync_db(get_stock_price, s["symbol"]))["price"]
                profit_loss = (curr_price - s["avg_buy_price"]) * s["quantity"]
                pl_sign = "+" if profit_loss >= 0 else ""
                text += f"• {s['symbol']}: {s['quantity']} шт. (ср. {s['avg_buy_price']:,}₽) → {curr_price:,}₽ | {pl_sign}{profit_loss:,}₽\n"
        else:
            text += "У вас нет акций.\n"
        text += f"\n💰 Общая стоимость портфеля: {portfolio_value:,}₽\n"
        text += f"📈 Прибыль/убыток: {profit:+,}₽"
        return {"success": True, "text": text, "prices": prices, "portfolio": portfolio}

    elif action.action == "buy_stock":
        symbol = action.data.get("symbol")
        quantity = action.data.get("quantity", 0)

        # ЖЁСТКАЯ ЗАЩИТА от неверного символа
        if symbol in ("buy", "sell", "stock", None, ""):
            return {"success": False, "message": "❌ Ошибка: вы выбрали недействительную акцию. Пожалуйста, вернитесь в меню акций и выберите акцию заново."}

        stock = await run_sync_db(get_stock_price, symbol)
        if not stock:
            # Принудительно заполняем таблицу акций
            await run_sync_db(ensure_stock_prices)
            stock = await run_sync_db(get_stock_price, symbol)
            if not stock:
                return {"success": False, "message": f"❌ Акция {symbol} не найдена в системе. Обратитесь к администратору."}

        price = stock["price"]
        total = price * quantity

        if player["balance"] < total:
            return {"success": False, "message": f"Недостаточно средств! Нужно {total}₽"}

        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": player["balance"] - total})

        await run_sync_db(update_user_stock, player_id, symbol, quantity, price)
        await run_sync_db(add_stock_transaction, player_id, symbol, "buy", quantity, price, total)

        return {"success": True, "message": f"✅ Куплено {quantity} акций {symbol} за {total}₽", "balance": player["balance"] - total}

    elif action.action == "sell_stock":
        symbol = action.data.get("symbol")
        quantity = action.data.get("quantity", 0)

        if symbol in ("buy", "sell", "stock", None, ""):
            return {"success": False, "message": "❌ Ошибка: неверный символ акции."}

        stock = await run_sync_db(get_stock_price, symbol)
        if not stock:
            return {"success": False, "message": f"❌ Акция {symbol} не найдена"}

        user_stocks = await run_sync_db(get_user_stocks, player_id)
        user_stock = next((s for s in user_stocks if s["symbol"] == symbol), None)

        if not user_stock or user_stock["quantity"] < quantity:
            return {"success": False, "message": "❌ У вас недостаточно акций"}

        price = stock["price"]
        total = price * quantity

        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": player["balance"] + total})

        await run_sync_db(update_user_stock, player_id, symbol, -quantity, price)
        await run_sync_db(add_stock_transaction, player_id, symbol, "sell", quantity, price, total)

        return {"success": True, "message": f"✅ Продано {quantity} акций {symbol} за {total}₽", "balance": player["balance"] + total}

    elif action.action == "stock_transactions":
        transactions = await run_sync_db(get_stock_transactions, player_id, 15)
        if not transactions:
            return {"success": True, "text": "📋 История сделок пуста."}
        text = "📋 <b>ИСТОРИЯ СДЕЛОК С АКЦИЯМИ</b>\n\n"
        for t in transactions:
            if t["type"] == "buy":
                icon = "🟢 ПОКУПКА"
            elif t["type"] == "sell":
                icon = "🔴 ПРОДАЖА"
            else:
                icon = "💎 ДИВИДЕНДЫ"
            text += f"{icon} {t['symbol']}\n{t['quantity']} шт. по {t['price']:,}₽ → {t['total']:,}₽\n{t['date']}\n\n"
        return {"success": True, "text": text}

# ==================== УЛУЧШЕННЫЕ КЛАВИАТУРЫ ====================
def make_main_kb(category=1):
    if category == 1:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏭 ЗАКУП", callback_data="buy_menu", style=ButtonStyle.DANGER), 
             InlineKeyboardButton(text="📦 ИНВЕНТАРЬ", callback_data="inventory_menu", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="💬 ЧАТЫ", callback_data="chats_menu"), 
             InlineKeyboardButton(text="🔨 АУКЦИОН", callback_data="auction_menu")],
            [InlineKeyboardButton(text="📈 СПРОС", callback_data="get_demand")],
            [InlineKeyboardButton(text="👤 СКИНЫ", callback_data="skins_menu"), 
             InlineKeyboardButton(text="⭐ РЕПУТАЦИЯ", callback_data="reputation")],
            [InlineKeyboardButton(text="🎯 КВЕСТЫ", callback_data="quests_menu"), 
             InlineKeyboardButton(text="🏢 БИЗНЕСЫ", callback_data="balance_details")],
            [InlineKeyboardButton(text="📜 ИСТОРИЯ ПРОДАЖ", callback_data="sales_history")],
            [InlineKeyboardButton(text="🎮 МИНИ-ИГРЫ", callback_data="minigames_menu", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="🏠 ТОРГОВЛЯ", callback_data="main_cat_1", style=ButtonStyle.DANGER),
             InlineKeyboardButton(text="💰 ФИНАНСЫ/ИМУЩЕСТВО", callback_data="main_cat_2", style=ButtonStyle.PRIMARY),
             InlineKeyboardButton(text="👥 СОЦИУМ", callback_data="main_cat_3", style=ButtonStyle.DANGER)]
        ])
    elif category == 2:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💼 РАБОТА", callback_data="jobs_entry")], 
            [InlineKeyboardButton(text="💸 ПЕРЕВОД", callback_data="transfer_menu")],
            [InlineKeyboardButton(text="🏠 НЕДВИЖИМОСТЬ", callback_data="houses_entry"), 
             InlineKeyboardButton(text="🚗 АВТОМОБИЛИ", callback_data="cars_menu")],
            [InlineKeyboardButton(text="🚕 ТАКСОПАРК", callback_data="taxopark_menu")],
            [InlineKeyboardButton(text="🏠 ГАРАЖ", callback_data="garage_menu")],
            [InlineKeyboardButton(text="🏦 БАНК", callback_data="bank_menu", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="🖥 МАЙНИНГ", callback_data="mining_menu", style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="📊 ТРЕЙДИНГ", web_app=WebAppInfo(url=URL_TRADING), style=ButtonStyle.PRIMARY)],
            [InlineKeyboardButton(text="🏠 ТОРГОВЛЯ", callback_data="main_cat_1", style=ButtonStyle.DANGER),
             InlineKeyboardButton(text="💰 ФИНАНСЫ/ИМУЩЕСТВО", callback_data="main_cat_2", style=ButtonStyle.PRIMARY),
             InlineKeyboardButton(text="👥 СОЦИУМ", callback_data="main_cat_3", style=ButtonStyle.DANGER)]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👥 ДРУЗЬЯ", callback_data="friends_menu"), 
             InlineKeyboardButton(text="🔗 РЕФЕРАЛЫ", callback_data="referral_menu")],
            [InlineKeyboardButton(text="🏆 ЛИДЕРЫ", callback_data="leaderboard_menu"), 
             InlineKeyboardButton(text="📚 ОБУЧЕНИЕ", callback_data="learning_menu")],
            [InlineKeyboardButton(text="⚙️ НАСТРОЙКИ", callback_data="settings_menu")],
            [InlineKeyboardButton(text="🏠 ТОРГОВЛЯ", callback_data="main_cat_1", style=ButtonStyle.DANGER),
             InlineKeyboardButton(text="💰 ФИНАНСЫ/ИМУЩЕСТВО", callback_data="main_cat_2", style=ButtonStyle.PRIMARY),
             InlineKeyboardButton(text="👥 СОЦИУМ", callback_data="main_cat_3", style=ButtonStyle.DANGER)]
        ])
    return kb

def make_settings_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Сменить никнейм", callback_data="change_nickname")],
        [InlineKeyboardButton(text="🏪 Сменить название магазина", callback_data="change_shopname")],
        [InlineKeyboardButton(text="🔔 Уведомления", callback_data="notifications_settings")],
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])

# Также обновите вызовы make_main_kb() в других местах, например, в start_new_game_btn, continue_game_btn,
# чтобы они использовали make_main_kb(1) вместо make_main_kb().
# В send_menu_with_skin замените вызов make_main_kb() на make_main_kb(1) при необходимости.

def menu_kb():
    """Клавиатура с одной кнопкой '🏠 В МЕНЮ'"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В МЕНЮ", callback_data="back_to_menu")]
    ])

def get_race_action_keyboard(race_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 ГАЗ В ПОЛ (+30%, риск 20%)", callback_data=f"race_action|{race_id}|boost")],
        [InlineKeyboardButton(text="🛡 РОВНЫЙ ХОД (+10%)", callback_data=f"race_action|{race_id}|normal")],
        [InlineKeyboardButton(text="🔥 НИТРО (+50%, -5% ставки)", callback_data=f"race_action|{race_id}|nitro")],
    ])

# ---------- КЛАВИАТУРЫ ДЛЯ ЧАТОВ С КЛИЕНТАМИ ----------
def get_chat_keyboard(chat:dict)->InlineKeyboardMarkup:
    phase=int(chat.get("phase",1)); chat_key=chat["chat_key"]; price=int(chat.get("price",0))
    if phase==5:
        opts=[(.85,10,"🟢",ButtonStyle.SUCCESS),(1.0,25,"🟡",ButtonStyle.PRIMARY),(1.15,40,"🔴",ButtonStyle.DANGER)]
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{e} {max(1,int(price*m)):,}₽ · риск {r}%",callback_data=f"chat_choice;{chat_key};{max(1,int(price*m))};{r}",style=st)] for m,r,e,st in opts])
    opts={1:["✅ Обсудить цену","📌 Показать выгоду","🤝 Узнать, что важно покупателю"],2:["📸 Подтвердить состояние","🧾 Дать факты и детали","💬 Уточнить ожидания"],3:["🚚 Быстрая отправка","📦 Обсудить доставку","🤝 Предложить самовывоз"],4:["🛍 Объяснить причину продажи","💡 Подчеркнуть выгоду","🤝 Перейти к торгу"]}.get(phase,["🤝 Перейти к торгу"])
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t,callback_data=f"chat_answer;{chat_key};{phase};{i}")] for i,t in enumerate(opts)])

async def send_menu_with_skin(user_id: int, text: str, reply_markup: InlineKeyboardMarkup = None):
    skin_id = await get_player_skin(user_id)
    skin = next((s for s in SKINS if s["id"] == skin_id), SKINS[0])
    kb = reply_markup if reply_markup else make_main_kb(1)   # ← заменили make_main_kb() на make_main_kb(1)
    if skin.get("image_url"):
        try:
            msg = await bot.send_photo(user_id, skin["image_url"], caption=text, parse_mode="HTML", reply_markup=kb)
            last_bot_message[user_id] = msg.message_id
            return
        except Exception as e:
            print(f"Ошибка отправки фото: {e}")
    await send_msg(user_id, text, reply_markup=kb)

async def del_prev(user_id):
    if user_id in last_bot_message:
        try:
            await bot.delete_message(user_id, last_bot_message[user_id])
        except:
            pass

async def del_user_msgs(user_id):
    for msg_id in pending_messages.get(user_id, []):
        try:
            await bot.delete_message(user_id, msg_id)
        except:
            pass
    pending_messages[user_id] = []

# ==================== TELEGRAM БОТ (КЛИЕНТСКАЯ ЧАСТЬ) ====================
bot = Bot(token=API_TOKEN)

async def _log_telegram_auth_config():
    """Log the running bot identity without ever printing the bot token."""
    try:
        await _resolve_telegram_bot_token()
        if not _TELEGRAM_RESOLVED_TOKEN:
            return
        expected=str(os.getenv("BOT_USERNAME") or globals().get("BOT_USERNAME") or "").strip().lstrip("@").lower()
        if expected and _TELEGRAM_RESOLVED_BOT_USERNAME and expected != _TELEGRAM_RESOLVED_BOT_USERNAME:
            print(f"[TG_AUTH] WARNING: configured BOT_USERNAME=@{expected} but resolved token belongs to @{_TELEGRAM_RESOLVED_BOT_USERNAME}")
    except Exception as exc:
        print(f"[TG_AUTH] startup bot identity check failed: {type(exc).__name__}: {exc}")

dp = Dispatcher(storage=MemoryStorage())

# ---------- ГАРАЖ ----------
@dp.callback_query(lambda c: c.data == "garage_menu")
async def garage_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_car_collection")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    cars = r.get("cars", [])
    if not cars:
        await safe_delete_message(callback.message)
        await callback.message.answer(
            "🏠 <b>ГАРАЖ ПУСТ</b>\n\nКупите машины в автосалоне! 👇",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛒 АВТОСАЛОН", callback_data="cars_menu")],
                [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
            ])
        )
        await safe_callback_answer(callback)
        return
    
    if not hasattr(garage_menu_callback, "page"):
        garage_menu_callback.page = {}
    page = garage_menu_callback.page.get(user_id, 0)
    total = len(cars)
    if page < 0: page = 0
    if page >= total: page = total - 1
    
    car_ref = cars[page]
    full_car = next((c for c in CARS if c["id"] == car_ref["id"]), None)
    if not full_car:
        await safe_callback_answer(callback, "Ошибка: машина не найдена", show_alert=True)
        return
    full_car["is_current"] = car_ref.get("is_current", False)
    
    text = (f"🏠 <b>ТВОЙ ГАРАЖ</b>\n📄 {page+1}/{total}\n\n"
            f"{full_car['name']}\n⭐ {full_car.get('rarity', 'обычный').upper()}\n"
            f"⚡ Ускорение: {full_car.get('speed_bonus', 0)}%\n"
            f"💰 Доход: {full_car.get('income_per_hour', 0)}₽/час\n")
    if full_car.get("is_current"):
        text += "\n✅ <b>ТЕКУЩАЯ МАШИНА</b>"
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"garage_page_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"garage_page_{page+1}"))
    
    kb = []
    if nav:
        kb.append(nav)
    if not full_car.get("is_current"):
        kb.append([InlineKeyboardButton(text="🚗 СДЕЛАТЬ ТЕКУЩЕЙ", callback_data=f"set_car_{full_car['id']}")])
    kb.append([InlineKeyboardButton(text="🚕 ТАКСОПАРК", callback_data="taxopark_menu")])
    kb.append([InlineKeyboardButton(text="🛒 АВТОСАЛОН", callback_data="cars_menu")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    
    if full_car.get("image_url"):
        try:
            await safe_delete_message(callback.message)
            msg = await bot.send_photo(
                user_id, full_car["image_url"],
                caption=text, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
            )
            last_bot_message[user_id] = msg.message_id
        except Exception as e:
            print(f"Ошибка отправки фото: {e}")
            await send_msg(user_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await send_msg(user_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
    garage_menu_callback.page[user_id] = page
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "quests_menu")
async def quests_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_achievements")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    ach = r.get("achievements", {})
    quests = r.get("quests", {})
    
    text = "🎯 <b>КВЕСТЫ</b>\n\n"
    payload = await run_sync_db(get_quest_payload, await get_player_id_by_tg(user_id))
    for q in payload.get("permanent", []):
        status = "✅" if q["completed"] else f"⚡ {q['progress']}/{q['target']}"
        if q["reward_claimed"]:
            status += " ЗАБРАНО"
        text += f"{status} {q['name']} · +{q['reward_money']:,}₽\n   {q['description']}\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "📅 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b> · обновляются каждый день\n\n"
    for q in payload.get("daily", []):
        status = "✅ НАГРАДА ЗАЧИСЛЕНА" if q["completed"] else f"⚡ {q['progress']}/{q['target']}"
        text += f"{status} {q['name']} · +{q['reward_money']:,}₽\n   {q['description']}\n\n"
    kb_rows = []
    for q in payload.get("permanent", []):
        if q["completed"] and not q["reward_claimed"]:
            kb_rows.append([InlineKeyboardButton(text=f"💰 Забрать +{q['reward_money']:,}₽ · {q['name']}", callback_data=f"claim_permquest:{q['id']}")])
    kb_rows.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("claim_permquest:"))
async def claim_permanent_quest_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    quest_id = callback.data.split(":", 1)[1]
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Игрок не найден", show_alert=True)
        return
    async with db_lock:
        result = await run_sync_db(claim_permanent_quest_sync, player_id, quest_id)
    if not result.get("success"):
        await safe_callback_answer(callback, result.get("error", "Не удалось получить награду"), show_alert=True)
        return
    await safe_callback_answer(callback, f"+{result['reward']:,}₽ зачислено")
    try:
        await quests_menu_callback(callback)
    except Exception as e:
        print(f"Ошибка обновления меню квестов: {e}")

@dp.callback_query(lambda c: c.data == "sell_shop_list")
async def sell_shop_list_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
    shops = cursor.fetchall()
    conn.close()
    if not shops:
        await safe_callback_answer(callback, "У вас нет магазинов для продажи.", show_alert=True)
        return
    text = "🏪 <b>ВЫБЕРИТЕ МАГАЗИН ДЛЯ ПРОДАЖИ</b>\n\n"
    kb = []
    for row in shops:
        shop_id = row["shop_id"]
        shop = next((s for s in SHOP_LEVELS if s["id"] == shop_id), None)
        if shop:
            refund = int(shop["price"] * 0.7)
            text += f"• {shop['name']} — продажа за {refund}₽\n"
            kb.append([InlineKeyboardButton(text=f"🪙 Продать {shop['name']} за {refund}₽", callback_data=f"sell_shop_{shop_id}")])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="balance_details")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("sell_shop_"))
async def sell_shop_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    shop_id = callback.data.split("_")[2]
    r = await api_call(user_id, "sell_shop", {"shop_id": shop_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(r.get("message"), parse_mode="HTML", reply_markup=menu_kb())
        # Перенаправляем на обновлённый баланс
        await unified_profit_callback(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data == "take_loan")
async def take_loan_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_loan_amount)
    await callback.message.answer("💰 Введите сумму кредита (от 10 000 до 1 000 000₽):")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_loan_amount))
async def process_loan_amount(message: Message, state: FSMContext):
    try:
        requested_amount = int(message.text.strip())
        if requested_amount < 10000 or requested_amount > 1000000:
            raise ValueError
    except:
        await message.answer("❌ Сумма должна быть от 10 000 до 1 000 000₽.")
        return

    user_id = message.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await message.answer("❌ Вы не зарегистрированы.")
        await state.clear()
        return

    player = await run_sync_db(get_player_data, player_id)
    if not player:
        await message.answer("❌ Ошибка данных.")
        await state.clear()
        return

    # Проверяем, нет ли активного непогашенного кредита
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, due_date FROM loans WHERE player_id = ? AND status = 'active'", (player_id,))
    active_loan = cursor.fetchone()
    conn.close()
    if active_loan:
        due_date = active_loan['due_date']
        remaining_days = (due_date - int(time_module.time())) // 86400
        await message.answer(f"❌ У вас уже есть активный кредит (осталось {remaining_days} дн.). Сначала погасите его.")
        await state.clear()
        return

    # ---- КРЕДИТНЫЙ СКОРИНГ ----
    max_loan = await calculate_max_loan(player)
    if requested_amount > max_loan:
        await message.answer(
            f"❌ Банк не одобряет запрошенную сумму {requested_amount}₽.\n"
            f"📊 Ваш кредитный лимит: {max_loan:,}₽.\n"
            f"💡 Попробуйте взять меньшую сумму или увеличьте свой доход (продавайте больше товаров, покупайте пассивные активы)."
        )
        await state.clear()
        return

    # Одобрено – выдаём кредит
    interest_rate = 5.0   # 5% за 2 дня
    start_time = int(time_module.time())
    due_date = start_time + 2 * 86400   # 2 дня
    total_to_return = int(requested_amount * (1 + interest_rate / 100))

    async with db_lock:
        # Увеличиваем баланс игрока
        await run_sync_db(update_player_data, player_id, {"balance": player["balance"] + requested_amount})
        # Сохраняем запись о кредите
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO loans (player_id, amount, interest_rate, start_time, due_date, status) VALUES (?, ?, ?, ?, ?, 'active')",
            (player_id, requested_amount, interest_rate, start_time, due_date)
        )
        conn.commit()
        conn.close()

    await message.answer(
        f"✅ Кредит на сумму {requested_amount}₽ одобрен и выдан!\n"
        f"📅 Срок возврата: 2 дня (до {datetime.fromtimestamp(due_date).strftime('%d.%m.%Y %H:%M')})\n"
        f"📈 Проценты: {interest_rate}% (всего к возврату: {total_to_return:,}₽)\n"
        f"⚠️ Не забудьте погасить вовремя, иначе будут начислены штрафы!"
    )
    await state.clear()

@dp.callback_query(lambda c: c.data == "casino_new")
async def casino_new_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await callback.answer("❌ Вы не зарегистрированы", show_alert=True)
        return
    player = await run_sync_db(get_player_data, player_id)
    balance = player.get("balance", 0) if player else 0
    
    # Лог для проверки (можно посмотреть в консоли)
    print(f"🔍 Casino balance for user {user_id}: {balance}")
    
    # Добавляем случайный параметр, чтобы избежать кеширования
    webapp_url = (
        f"https://ruslangodunov66-alt.github.io/resellcrash/casino.html"
        f"?userId={user_id}"
        f"&balance={balance}"
        f"&_={int(time.time())}"   # <-- случайное число, меняется каждый раз
    )
    
    web_app_button = KeyboardButton(text="🎰 ОТКРЫТЬ КАЗИНО", web_app=WebAppInfo(url=webapp_url))
    reply_keyboard = ReplyKeyboardMarkup(keyboard=[[web_app_button]], resize_keyboard=True)
    await callback.message.answer(
        "🎮 <b>ДОБРО ПОЖАЛОВАТЬ В КАЗИНО!</b>\n\n"
        "Нажми на кнопку внизу, чтобы открыть казино.\n"
        "После игры отправь /hide, чтобы убрать эту клавиатуру.",
        parse_mode="HTML",
        reply_markup=reply_keyboard
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "my_loans")
async def my_loans(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, amount, interest_rate, start_time, due_date, status, paid_amount FROM loans WHERE player_id = ? ORDER BY id DESC", (player_id,))
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        text = "💰 <b>МОИ КРЕДИТЫ</b>\n\nУ вас нет ни одного кредита."
    else:
        text = "💰 <b>МОИ КРЕДИТЫ</b>\n\n"
        for row in rows:
            status_emoji = "✅" if row['status'] == 'closed' else "⚠️" if row['status'] == 'overdue' else "🟢"
            text += f"{status_emoji} Кредит #{row['id']}\n"
            text += f"Сумма: {row['amount']}₽\n"
            text += f"Проценты: {row['interest_rate']}%\n"
            text += f"К возврату: {int(row['amount'] * (1 + row['interest_rate']/100))}₽\n"
            text += f"Дата выдачи: {datetime.fromtimestamp(row['start_time']).strftime('%d.%m.%Y')}\n"
            text += f"Срок до: {datetime.fromtimestamp(row['due_date']).strftime('%d.%m.%Y')}\n"
            text += f"Статус: {'Закрыт' if row['status'] == 'closed' else 'Просрочен' if row['status'] == 'overdue' else 'Активен'}\n\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 ПОГАСИТЬ КРЕДИТ", callback_data="repay_loan")],
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="loan_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "repay_loan")
async def repay_loan_menu(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, amount, interest_rate FROM loans WHERE player_id = ? AND status = 'active'", (player_id,))
    loan = cursor.fetchone()
    conn.close()

    if not loan:
        await safe_callback_answer(callback, "У вас нет активных кредитов.", show_alert=True)
        return

    total_due = int(loan['amount'] * (1 + loan['interest_rate'] / 100))
    await state.update_data(repay_loan_id=loan['id'], repay_amount=total_due)
    await state.set_state(Form.waiting_for_loan_repayment)   # ← изменено
    await callback.message.answer(f"💰 Для погашения кредита необходимо внести {total_due}₽. Введите сумму (можно больше, излишек пополнит баланс):")
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "crash_open")
async def crash_open(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await callback.answer("❌ Вы не зарегистрированы", show_alert=True)
        return
    player = await run_sync_db(get_player_data, player_id)
    balance = player.get("balance", 0) if player else 0
    webapp_url = f"https://ruslangodunov66-alt.github.io/resellcrash/crash.html?userId={user_id}&balance={balance}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💥 ИГРАТЬ CRASH", web_app=WebAppInfo(url=webapp_url))]
    ])
    await callback.message.answer("Нажми кнопку, чтобы открыть игру:", reply_markup=kb)
    await callback.answer()

@dp.message(StateFilter(Form.waiting_for_loan_repayment))
async def process_loan_repayment(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.")
        return
    
    data = await state.get_data()
    loan_id = data.get('repay_loan_id')
    required = data.get('repay_amount')
    if not loan_id or not required:
        await message.answer("❌ Ошибка: информация о кредите не найдена.")
        await state.clear()
        return
    
    user_id = message.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await message.answer("❌ Ошибка игрока.")
        await state.clear()
        return
    
    player = await run_sync_db(get_player_data, player_id)
    if player['balance'] < amount:
        await message.answer(f"❌ Недостаточно средств. Ваш баланс: {player['balance']}₽")
        return
    
    async with db_lock:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT amount, interest_rate, status FROM loans WHERE id = ? AND player_id = ?", (loan_id, player_id))
        loan = cursor.fetchone()
        if not loan or loan['status'] != 'active':
            await message.answer("❌ Кредит не найден или уже погашен.")
            conn.close()
            await state.clear()
            return
        
        total_due = int(loan['amount'] * (1 + loan['interest_rate'] / 100))
        if amount >= total_due:
            # Погашение полностью
            overpay = amount - total_due
            new_balance = player['balance'] - amount + overpay  # по сути вычитаем только total_due, но проще: balance - amount
            # но мы уже списали amount, а нужно списать total_due и вернуть overpay? Лучше списать amount, затем добавить overpay
            # Сделаем проще: списываем amount, затем если есть переплата – добавляем обратно
            cursor.execute("UPDATE loans SET status = 'closed', paid_amount = ? WHERE id = ?", (total_due, loan_id))
            cursor.execute("UPDATE players SET balance = balance - ? WHERE id = ?", (amount, player_id))
            if overpay > 0:
                cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (overpay, player_id))
            conn.commit()
            await message.answer(f"✅ Кредит полностью погашен! Спасибо за доверие.\nПереплата {overpay}₽ возвращена на баланс.")
        else:
            # Частичное погашение
            await message.answer("❌ Требуется полное погашение кредита. Внесите необходимую сумму.")
            conn.close()
            await state.clear()
            return
        conn.close()
    
    await state.clear()

@dp.callback_query(lambda c: c.data.startswith("garage_page_"))
async def garage_page_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split("_")[2])
    if not hasattr(garage_menu_callback, "page"):
        garage_menu_callback.page = {}
    garage_menu_callback.page[user_id] = page
    await garage_menu_callback(callback)

# ==================== ОБРАБОТЧИКИ ПЕРЕКЛЮЧЕНИЯ СТРАНИЦ ====================
@dp.callback_query(lambda c: c.data.startswith("main_page_"))
async def switch_main_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    result = await api_call(user_id, "get_stats")
    if result.get("success"):
        s = result.get("stats", {})
        skin_res = await api_call(user_id, "get_player_skins")
        current_skin = skin_res.get("current", "default") if skin_res.get("success") else "default"
        skin_emoji = "👤"
        skin_name = "Новичок"
        for skin in SKINS:
            if skin["id"] == current_skin:
                skin_emoji = skin.get("emoji", "👤")
                skin_name = skin.get("name", "Новичок")
                break
        text = (f"🎮 <b>RESELL TYCOON</b>\n\n"
                f"{skin_emoji} <b>{skin_name}</b>\n"
                f"👤 {s.get('nickname', 'Торгаш')}\n"
                f"💰 {s.get('balance', 0):,}₽\n"
                f"📅 День {s.get('day', 1)} | 📦 {s.get('inventory_count', 0)} товаров\n"
                f"📋 Продано: {s.get('items_sold', 0)} | 💸 {s.get('total_earned', 0):,}₽\n\n"
                f"<i>Страница {page} из 3</i>")   # ← изменено с 4 на 3
        await safe_delete_message(callback.message)
        await send_menu_with_skin(user_id, text, reply_markup=make_main_kb(page))
    else:
        await safe_callback_answer(callback, "Ошибка загрузки", show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("race_action|"))
async def race_action_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("|")
    if len(parts) != 3:
        await safe_callback_answer(callback, "Неверный формат", show_alert=True)
        return
    race_id = parts[1]
    action = parts[2]
    r = await api_call(user_id, "race_action", {"race_id": race_id, "race_action": action})
    
    if not r.get("success"):
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)
        return
    
    if r.get("finished"):
        # гонка завершена
        winner = r.get("winner")
        text = (f"🏁 <b>ГОНКА ЗАВЕРШЕНА!</b>\n"
                f"Ваши очки: {r.get('creator_score' if user_id == winner else 'opponent_score', 0)}\n"
                f"Соперник: {r.get('opponent_score' if user_id == winner else 'creator_score', 0)}\n"
                f"🏆 Победитель: {'Вы' if winner == user_id else 'Соперник'}\n"
                f"💰 Призовой фонд: {r.get('prize_pool', 0)}₽")
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML")
        await safe_callback_answer(callback)
    elif r.get("waiting"):
        # ждём ход соперника
        await safe_callback_answer(callback, r.get("message", "Ожидаем ход соперника..."), show_alert=False)
        await safe_delete_message(callback.message)
    else:
        # переходим к следующей фазе
        phase = r.get("phase")
        message_text = f"🏎 <b>ФАЗА {phase}/3</b>\n{r.get('message')}\n\nВыбери следующее действие:"
        kb = get_race_action_keyboard(race_id)
        await safe_delete_message(callback.message)
        await callback.message.answer(message_text, parse_mode="HTML", reply_markup=kb)
        await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("main_cat_"))
async def switch_category(callback: CallbackQuery):
    cat = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    result = await api_call(user_id, "get_stats")
    if result.get("success"):
        s = result.get("stats", {})
        skin_res = await api_call(user_id, "get_player_skins")
        current_skin = skin_res.get("current", "default") if skin_res.get("success") else "default"
        skin_emoji = "👤"
        skin_name = "Новичок"
        for skin in SKINS:
            if skin["id"] == current_skin:
                skin_emoji = skin.get("emoji", "👤")
                skin_name = skin.get("name", "Новичок")
                break
        if cat == 1:
            title = "🏭 ТОРГОВЛЯ"
        elif cat == 2:
            title = "💰 ФИНАНСЫ И ИМУЩЕСТВО"
        else:
            title = "👥 СОЦИУМ"
        text = (f"🎮 <b>RESELL TYCOON</b>\n\n"
                f"{skin_emoji} <b>{skin_name}</b>\n"
                f"👤 {s.get('nickname', 'Торгаш')}\n"
                f"💰 {s.get('balance', 0):,}₽\n"
                f"📅 День {s.get('day', 1)} | 📦 {s.get('inventory_count', 0)} товаров\n"
                f"📋 Продано: {s.get('items_sold', 0)} | 💸 {s.get('total_earned', 0):,}₽\n\n"
                f"<b>{title}</b>")
        await safe_delete_message(callback.message)
        await send_menu_with_skin(user_id, text, reply_markup=make_main_kb(cat))
    else:
        await safe_callback_answer(callback, "Ошибка загрузки", show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    result = await api_call(user_id, "get_stats")
    if result.get("success"):
        s = result.get("stats", {})
        skin_res = await api_call(user_id, "get_player_skins")
        current_skin = skin_res.get("current", "default") if skin_res.get("success") else "default"
        skin_emoji = "👤"
        skin_name = "Новичок"
        for skin in SKINS:
            if skin["id"] == current_skin:
                skin_emoji = skin.get("emoji", "👤")
                skin_name = skin.get("name", "Новичок")
                break
        text = (f"🎮 <b>RESELL TYCOON</b>\n\n"
                f"{skin_emoji} <b>{skin_name}</b>\n"
                f"👤 {s.get('nickname', 'Торгаш')}\n"
                f"💰 {s.get('balance', 0):,}₽\n"
                f"📅 День {s.get('day', 1)} | 📦 {s.get('inventory_count', 0)} товаров\n"
                f"📋 Продано: {s.get('items_sold', 0)} | 💸 {s.get('total_earned', 0):,}₽\n\n"
                f"<b>🏭 ТОРГОВЛЯ</b>")
        await safe_delete_message(callback.message)
        await send_menu_with_skin(user_id, text, reply_markup=make_main_kb(1))
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "bank_menu")
async def bank_menu(callback: CallbackQuery):
    text = (
        "🏦 <b>БАНК «Resell Tycoon»</b>\n\n"
        "Вы можете открыть депозит под проценты:\n"
        "• 1 день — 2% доход\n"
        "• 3 дня — 5% доход\n"
        "• 7 дней — 10% доход\n\n"
        "Сумма депозита от 10 000 до 10 000 000₽.\n"
        "Проценты начисляются в конце срока.\n\n"
        "Выберите срок вклада:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 ДЕПОЗИТЫ", callback_data="deposit_menu")],
        [InlineKeyboardButton(text="💰 КРЕДИТЫ", callback_data="loan_menu")],
        [InlineKeyboardButton(text="📈 АКЦИИ", callback_data="stocks_entry")],   # <-- добавить
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="back_to_menu")]
     ])
    photo_id = "AgACAgIAAxkBAAIb4GoYdcW3grQ8bIlyZ5foSK885TJ_AAIZHGsbVcfBSPPaBe8AATcM_gEAAwIAA3kAAzsE"
    try:
        await safe_delete_message(callback.message)
        msg = await bot.send_photo(callback.from_user.id, photo_id, caption=text, parse_mode="HTML", reply_markup=kb)
        last_bot_message[callback.from_user.id] = msg.message_id
    except Exception as e:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("deposit_"))
async def deposit_choice(callback: CallbackQuery, state: FSMContext):
    days = int(callback.data.split("_")[1])
    rates = {1: 2, 3: 5, 7: 10}
    rate = rates.get(days)
    if not rate:
        await safe_callback_answer(callback, "Неверный срок", show_alert=True)
        return
    await state.update_data(deposit_duration=days, deposit_rate=rate)
    await state.set_state(Form.waiting_for_deposit_amount)
    await callback.message.answer(f"💰 Введите сумму депозита (от 10 000 до 10 000 000₽) на {days} дней под {rate}%:")
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "mining_menu")
async def mining_menu(callback: CallbackQuery):
    text = (
        "🖥 <b>МАЙНИНГ-ФЕРМЫ</b>\n\n"
        "Инвестируйте в майнинг криптовалют и получайте пассивный доход:\n"
        "• Малая ферма — 50 000₽ → +3 000₽/день\n"
        "• Средняя ферма — 200 000₽ → +15 000₽/день\n"
        "• Крупная ферма — 1 000 000₽ → +100 000₽/день\n\n"
        "Доход начисляется каждый час.\n"
        "Выберите ферму для покупки:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Малая (50 000₽)", callback_data="buy_mining_small")],
        [InlineKeyboardButton(text="🛒 Средняя (200 000₽)", callback_data="buy_mining_medium")],
        [InlineKeyboardButton(text="🛒 Крупная (1 000 000₽)", callback_data="buy_mining_large")],
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="back_to_menu")]
    ])
    photo_id = "AgACAgIAAxkBAAIb02oYdOPrg50NLjYRHS8cINlbD3b2AAIXHGsbVcfBSMqZednvkdzBAQADAgADdwADOwQ"
    try:
        await safe_delete_message(callback.message)
        msg = await bot.send_photo(callback.from_user.id, photo_id, caption=text, parse_mode="HTML", reply_markup=kb)
        last_bot_message[callback.from_user.id] = msg.message_id
    except Exception as e:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_mining_"))
async def buy_mining(callback: CallbackQuery):
    rig_type = callback.data.split("_")[2]  # small, medium, large
    rig = MINING_RIGS[rig_type]
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    player = await run_sync_db(get_player_data, player_id)
    if player['balance'] < rig['price']:
        await safe_callback_answer(callback, f"Недостаточно денег! Нужно {rig['price']}₽", show_alert=True)
        return
    async with db_lock:
        new_balance = player['balance'] - rig['price']
        await run_sync_db(update_player_data, player_id, {"balance": new_balance})
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO mining_rigs (player_id, rig_type, hash_rate, daily_income, price, purchase_time) VALUES (?, ?, ?, ?, ?, ?)",
        (player_id, rig_type, 0, rig['daily_income'], rig['price'], int(time_module.time()))
    )
    conn.commit()
    conn.close()
    await safe_delete_message(callback.message)
    await callback.message.answer(f"✅ Вы купили {rig['name']} за {rig['price']}₽. Доход {rig['daily_income']}₽/день будет начисляться каждый час.")
    await unified_profit_callback(callback)

@dp.message(Form.waiting_for_deposit_amount)
async def deposit_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount < 10000 or amount > 10000000:
            raise ValueError
    except:
        await message.answer("❌ Сумма должна быть от 10 000 до 10 000 000₽.")
        return
    user_id = message.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    player = await run_sync_db(get_player_data, player_id)  # <-- ИСПРАВЛЕНО
    if player['balance'] < amount:
        await message.answer("❌ Недостаточно средств.")
        return
    data = await state.get_data()
    duration = data['deposit_duration']
    rate = data['deposit_rate']
    
    async with db_lock:
        await run_sync_db(update_player_data, player_id, {"balance": player['balance'] - amount})  # <-- ИСПРАВЛЕНО
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO deposits (player_id, amount, start_time, duration_days, interest_rate) VALUES (?, ?, ?, ?, ?)",
        (player_id, amount, int(time_module.time()), duration, rate)
    )
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Депозит на {amount}₽ открыт на {duration} дней под {rate}%.\nПо окончании срока вы получите {int(amount * rate / 100) + amount}₽.")
    await state.clear()
    await message.answer("✅ Депозит успешно открыт!", reply_markup=menu_kb())

# ---------- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ВЫЗОВА API ИЗ БОТА ----------
player_action_locks = defaultdict(asyncio.Lock)

async def handle_action(action: PlayerAction):
    key=f"{action.platform}:{action.platform_id}"
    async with player_action_locks[key]:
        return await _handle_action_locked(action)

async def api_call(user_id: int, action: str, data: dict = None) -> dict:
    req_action = PlayerAction(platform="tg", platform_id=user_id, action=action, data=data or {})
    try:
        result = await handle_action(req_action)
        if result is None:
            return {"success": False, "message": "Неизвестное действие"}
        if not isinstance(result, dict):
            print(f"API Call Error: unexpected result type {type(result).__name__} for action={action}")
            return {"success": False, "message": "Некорректный ответ игрового обработчика"}
        return result
    except Exception as e:
        print(f"API Call Error: {e}")
        return {"success": False, "message": f"Ошибка сервера: {str(e)}"}

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ТЕЛЕГРАМ (ОБЁРТКИ НАД API) ----------
async def get_player_skin(tg_id: int) -> str:
    r = await api_call(tg_id, "get_player_skins")
    return r.get("current", "default") if r.get("success") else "default"

async def get_nickname(tg_id: int) -> str:
    r = await api_call(tg_id, "get_stats")
    return r.get("stats", {}).get("nickname", "Торгаш") if r.get("success") else "Торгаш"

async def get_shop_name(tg_id: int) -> str:
    r = await api_call(tg_id, "get_shop_name")
    return r.get("shop_name", "Без названия") if r.get("success") else "Без названия"

async def set_nickname(tg_id: int, nickname: str) -> tuple:
    r = await api_call(tg_id, "set_nickname", {"nickname": nickname})
    return r.get("success", False), r.get("message", "")

async def set_shop_name(tg_id: int, shopname: str) -> tuple:
    r = await api_call(tg_id, "set_shop_name", {"name": shopname})
    return r.get("success", False), r.get("message", "")

# ---------- ОБРАБОТЧИКИ КОМАНД ----------
@dp.message(Command('start'))
async def start_cmd(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    args = message.text.split()

    # 1. Проверяем, существует ли игрок
    player_id = await get_player_id_by_tg(user_id)

    if player_id:
        # Игрок мог быть создан автоматически первым открытием Mini App,
        # но ещё не завершить регистрацию. В таком случае referral/start снова
        # должен вести именно в RESSELL, а не возвращать старое текстовое меню.
        player = await run_sync_db(get_player_data, player_id)
        registration_incomplete = bool(
            player and (
                str(player.get("nickname") or "").startswith("Игрок_") or
                str(player.get("shop_name") or "") == "Моя лавка"
            )
        )
        if registration_incomplete:
            ref_arg = args[1] if len(args) > 1 and args[1].startswith("ref_") else ""
            resell_url = f"{URL_RESELL}?ref={ref_arg}" if ref_arg else URL_RESELL
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🚀 ОТКРЫТЬ RESSELL", web_app=WebAppInfo(url=resell_url))]
            ])
            await message.answer(
                "🚀 <b>Продолжи регистрацию в RESSELL</b>\n\n"
                "Твой профиль уже подготовлен. Открой приложение и заполни два шага регистрации.",
                parse_mode="HTML", reply_markup=kb
            )
            return
        # Существующий зарегистрированный игрок – показываем меню
        skin_id = player.get("skin", "default")
        skin_obj = next((s for s in SKINS if s["id"] == skin_id), SKINS[0])
        nick = await get_nickname(user_id) or f"ID:{user_id}"
        shop = await get_shop_name(user_id)
        rating = get_avito_rating(player.get("total_sales", 0))
        text = (f"👋 <b>С ВОЗВРАЩЕНИЕМ!</b>\n"
                f"📅 День {player.get('day', 1)} | 💰 {player.get('balance', 0):,}₽\n"
                f"👤 {nick} | 📱 {shop}\n"
                f"⭐ {rating}\n"
                f"👤 Скин: {skin_obj['emoji']} {skin_obj['name']}\n\n"
                f"<i>Нажми «ПРОДОЛЖИТЬ»</i>")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 ПРОДОЛЖИТЬ", callback_data="continue_game")],
            [InlineKeyboardButton(text="👤 СКИНЫ", callback_data="skins_menu")],
            [InlineKeyboardButton(text="🔄 ЗАНОВО", callback_data="restart_game_confirm")],
        ])
        await send_menu_with_skin(user_id, text, reply_markup=kb)
        return

    # 2. Реферальный старт: новый пользователь сразу получает кнопку RESSELL Mini App.
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]
        inviter_id = await run_sync_db(find_user_by_ref_code, ref_code)
        if inviter_id and inviter_id != user_id:
            await run_sync_db(set_pending_referral, int(user_id), int(inviter_id), "telegram_start")
        resell_url = f"{URL_RESELL}?ref={args[1]}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 ОТКРЫТЬ RESSELL", web_app=WebAppInfo(url=resell_url))]
        ])
        await message.answer(
            "🚀 <b>Добро пожаловать в RESSELL</b>\n\n"
            "Регистрация и весь аккаунт теперь проходят прямо внутри приложения.\n\n"
            "Нажми кнопку ниже — откроется RESSELL, где ты сразу сможешь создать аккаунт.",
            parse_mode="HTML", reply_markup=kb
        )
        return

    # 3. Приветствие для нового игрока
    welcome_text = (
        "🎮 <b>RESELL TYCOON</b>\n\n"
        "<b>ЗАРАБАТЫВАЙ • ПРОДАВАЙ • ВЛАСТВУЙ</b>\n\n"
        "🏭 Покупай товары у поставщиков\n"
        "💰 Продавай и зарабатывай на перепродаже\n"
        "🏪 Открывай бизнесы и получай пассивный доход\n"
        "🚗 Покупай легендарные автомобили\n"
        "🏠 Покупай недвижимость\n"
        "👤 Кастомизируй своего персонажа\n\n"
        "<b>И всё это — абсолютно бесплатно!</b>\n\n"
        "👇 Выбери действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 НАЧАТЬ РЕГИСТРАЦИЮ", callback_data="start_register")],
    ])

    photo_file_id = "AgACAgIAAxkBAAILVmn7nUTFFZ0bIbIrcdpk3VloWiUWAALwE2sbsr_gS2A_JEo7mNSVAQADAgADeQADOwQ"
    try:
        msg = await bot.send_photo(user_id, photo_file_id, caption=welcome_text, parse_mode="HTML", reply_markup=kb)
        last_bot_message[user_id] = msg.message_id
    except Exception as e:
        print(f"⚠️ Ошибка отправки фото в /start: {e}")
        msg = await send_msg(user_id, welcome_text, reply_markup=kb)
        if msg:
            last_bot_message[user_id] = msg.message_id

@dp.callback_query(lambda c: c.data == "start_new_game")
async def start_new_game_btn(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    # Игрок уже создан при регистрации, просто переходим в игру
    await state.set_state(GameState.playing)
    skin = await get_player_skin(user_id)
    skin_obj = next((s for s in SKINS if s["id"] == skin), SKINS[0])
    nick = await get_nickname(user_id)
    shop = await get_shop_name(user_id)
    # Получаем баланс и день через API
    stats = await api_call(user_id, "get_stats")
    if stats.get("success"):
        s = stats["stats"]
        balance = s.get("balance", 0)
        day = s.get("day", 1)
    else:
        balance, day = 0, 1
    # Получаем спрос
    demand = await api_call(user_id, "get_demand")
    demand_text = demand.get("formatted", "Нет данных") if demand.get("success") else "Нет данных"
    text = (f"🚀 <b>ИГРА НАЧАЛАСЬ!</b>\n💰 {balance:,}₽\n👤 {nick} | 📱 {shop}\n"
            f"👤 Скин: {skin_obj['emoji']} {skin_obj['name']}\n📅 День {day}\n\n"
            f"📊 <b>СПРОС:</b>\n{demand_text}")
    await send_menu_with_skin(user_id, text)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "deposit_menu")
async def deposit_menu_callback(callback: CallbackQuery):
    text = (
        "📅 <b>ДЕПОЗИТЫ</b>\n\n"
        "Выберите срок вклада:\n\n"
        "• 1 день — 2% доход\n"
        "• 3 дня — 5% доход\n"
        "• 7 дней — 10% доход\n\n"
        "Сумма депозита от 10 000 до 10 000 000₽."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 1 ДЕНЬ (2%)", callback_data="deposit_1")],
        [InlineKeyboardButton(text="📅 3 ДНЯ (5%)", callback_data="deposit_3")],
        [InlineKeyboardButton(text="📅 7 ДНЕЙ (10%)", callback_data="deposit_7")],
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="bank_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "continue_game")
async def continue_game_btn(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.set_state(GameState.playing)
    skin = await get_player_skin(user_id)
    skin_obj = next((s for s in SKINS if s["id"] == skin), SKINS[0])
    nick = await get_nickname(user_id)
    shop = await get_shop_name(user_id)
    stats = await api_call(user_id, "get_stats")
    if stats.get("success"):
        s = stats["stats"]
        balance = s.get("balance", 0)
        day = s.get("day", 1)
        sold = s.get("items_sold", 0)
    else:
        balance, day, sold = 0, 1, 0
    rating = get_avito_rating(sold)  # эта функция уже есть в коде
    demand = await api_call(user_id, "get_demand")
    demand_text = demand.get("formatted", "Нет данных") if demand.get("success") else "Нет данных"
    text = (f"📅 <b>День {day}</b> | 💰 {balance:,}₽\n👤 {nick} | 📱 {shop}\n⭐ {rating}\n"
            f"👤 Скин: {skin_obj['emoji']} {skin_obj['name']}\n\n📊 <b>СПРОС:</b>\n{demand_text}")
    await send_menu_with_skin(user_id, text)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "restart_game_confirm")
async def restart_confirm(callback: CallbackQuery):
    await send_msg(callback.from_user.id, "⚠️ <b>СБРОСИТЬ ПРОГРЕСС?</b>\nБаланс и инвентарь потеряются.", 
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                       [InlineKeyboardButton(text="⚠️ ДА", callback_data="restart_game_yes")],
                       [InlineKeyboardButton(text="❌ НЕТ", callback_data="continue_game")]
                   ]))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "restart_game_yes")
async def restart_yes(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM players WHERE tg_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        player_id = row['id']
        await run_sync_db(reset_player_account_sync, int(user_id))
    conn.close()
    await start_register(callback, state)

@dp.callback_query(lambda c: c.data == "start_register")
async def start_register(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await state.set_state(GameState.writing_nickname)
    await send_msg(
        user_id,
        "👤 <b>ШАГ 1/2: ТВОЙ НИКНЕЙМ</b>\n\n"
        "Придумай себе имя (от 2 до 20 символов).\n"
        "Оно будет отображаться в игре.\n\n"
        "✍️ Напиши никнейм в чат:"
    )
    await safe_callback_answer(callback)

@dp.message(StateFilter(GameState.writing_nickname))
async def handle_nickname(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    nickname = message.text.strip()
    if len(nickname) < 2:
        return await message.answer("❌ Минимум 2 символа! Попробуй ещё раз:")
    if len(nickname) > 20:
        return await message.answer("❌ Максимум 20 символов! Попробуй ещё раз:")
    success, msg = await set_nickname(user_id, nickname)
    if not success:
        return await message.answer(f"❌ {msg} Попробуй ещё раз:")
    await state.set_state(GameState.writing_shopname)
    await send_msg(
        user_id,
        f"✅ Никнейм: <b>{nickname}</b>\n\n"
        f"📱 <b>ШАГ 2/2: НАЗВАНИЕ МАГАЗИНА</b>\n\n"
        f"Придумай название для своего Авито-аккаунта\n"
        f"(от 2 до 30 символов).\n\n"
        f"✍️ Напиши название в чат:",
        parse_mode="HTML"
    )

@dp.message(StateFilter(GameState.writing_shopname))
async def handle_shopname(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    shopname = message.text.strip()
    if len(shopname) < 2:
        return await message.answer("❌ Минимум 2 символа! Попробуй ещё раз:")
    if len(shopname) > 30:
        return await message.answer("❌ Максимум 30 символов! Попробуй ещё раз:")
    success, msg = await set_shop_name(user_id, shopname)
    if not success:
        return await message.answer(f"❌ {msg} Попробуй ещё раз:")
    await state.set_state(GameState.playing)

    # --- АКТИВАЦИЯ СОХРАНЁННОГО РЕФЕРАЛА ПОСЛЕ РЕГИСТРАЦИИ ---
    try:
        await activate_pending_referral(int(user_id), "telegram_registration")
    except Exception as e:
        print(f"⚠️ Ошибка referral activation: {e}")

    player_id = await get_player_id_by_tg(user_id)
    if player_id:
        for qid in DAILY_QUESTS.keys():
            await run_sync_db(update_daily_quest, player_id, qid, 0)

    nick = await get_nickname(user_id)
    shop = await get_shop_name(user_id)
    skin = await get_player_skin(user_id)
    skin_obj = next((s for s in SKINS if s["id"] == skin), SKINS[0])
    txt = (
        f"🎉 <b>РЕГИСТРАЦИЯ ЗАВЕРШЕНА!</b>\n\n"
        f"👤 Ник: {nick}\n"
        f"📱 Магазин: {shop}\n"
        f"👤 Скин: {skin_obj['emoji']} {skin_obj['name']}\n\n"
        f"Теперь ты готов начать!\n"
        f"Жми 🚀 НАЧАТЬ ИГРУ!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 НАЧАТЬ ИГРУ", callback_data="start_new_game")],
        [InlineKeyboardButton(text="👤 СКИНЫ", callback_data="skins_menu")],
    ])
    await send_msg(user_id, txt, reply_markup=kb)
    await run_sync_db(update_daily_quest, player_id, "sell_3", 0)
    await run_sync_db(update_daily_quest, player_id, "earn_50k", 0)
    await run_sync_db(update_daily_quest, player_id, "buy_shop", 0)

@dp.message(Command('menu'))
async def menu_cmd(message: Message):
    user_id = message.from_user.id
    result = await api_call(user_id, "get_stats")
    if result.get("success"):
        s = result.get("stats", {})
        skin_res = await api_call(user_id, "get_player_skins")
        current_skin = skin_res.get("current", "default") if skin_res.get("success") else "default"
        skin_emoji = "👤"
        skin_name = "Новичок"
        for skin in SKINS:
            if skin["id"] == current_skin:
                skin_emoji = skin.get("emoji", "👤")
                skin_name = skin.get("name", "Новичок")
                break
        text = (f"🎮 <b>RESELL TYCOON</b>\n\n"
                f"{skin_emoji} <b>{skin_name}</b>\n"
                f"👤 {s.get('nickname', 'Торгаш')}\n"
                f"💰 {s.get('balance', 0):,}₽\n"
                f"📅 День {s.get('day', 1)} | 📦 {s.get('inventory_count', 0)} товаров\n"
                f"📋 Продано: {s.get('items_sold', 0)} | 💸 {s.get('total_earned', 0):,}₽\n\n"
                f"<b>🏭 ТОРГОВЛЯ</b>")
        await send_menu_with_skin(user_id, text, reply_markup=make_main_kb(1))
    else:
        await message.answer("❌ Ошибка загрузки профиля", reply_markup=make_main_kb(1))

@dp.message(Command('nick'))
async def nick_cmd(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("👤 Введи новый никнейм: /nick ТвойНик")
        return
    nickname = args[1]
    r = await api_call(message.from_user.id, "set_nickname", {"nickname": nickname})
    if r.get("success"):
        await message.answer(r.get("message"), parse_mode="HTML")
    else:
        await message.answer(f"❌ {r.get('message')}")

@dp.message(Command('shopname'))
async def shopname_cmd(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("🏪 Введи новое название магазина: /shopname Название")
        return
    name = args[1]
    r = await api_call(message.from_user.id, "set_shop_name", {"name": name})
    if r.get("success"):
        await message.answer(r.get("message"), parse_mode="HTML")
    else:
        await message.answer(f"❌ {r.get('message')}")

@dp.message(Command('pay'))
async def pay_command(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "❌ Используйте: /pay [никнейм / @username / tg_id] [сумма]\n"
            "Примеры:\n"
            "/pay Барыга 5000\n"
            "/pay @vintagestore61 1000\n"
            "/pay 123456789 200"
        )
        return

    target = args[1]
    try:
        amount = int(args[2])
    except ValueError:
        await message.answer("❌ Сумма должна быть числом.")
        return

    if amount < 100:
        await message.answer("❌ Минимальная сумма перевода: 100₽")
        return

    from_user_id = message.from_user.id

    # --- Определяем tg_id получателя ---
    target_tg_id = None

    # 1. Если target — число, считаем это tg_id
    if target.isdigit():
        target_tg_id = int(target)
    else:
        # 2. Пробуем получить по Telegram username (убираем @ в начале)
        clean_username = target.lstrip('@')
        try:
            chat = await bot.get_chat(f"@{clean_username}")
            if chat and chat.id:
                target_tg_id = chat.id
        except Exception:
            target_tg_id = None

        # 3. Если по username не нашли — ищем по игровому nickname
        if not target_tg_id:
            user_info = await api_call(from_user_id, "get_player_by_nickname", {"nickname": target})
            if user_info.get("success"):
                player_data = user_info.get("player", {})
                target_player_id = player_data.get("id")
                if target_player_id:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("SELECT tg_id FROM players WHERE id = ?", (target_player_id,))
                    row = cursor.fetchone()
                    conn.close()
                    if row and row['tg_id']:
                        target_tg_id = row['tg_id']
                    else:
                        target_tg_id = None

    if not target_tg_id:
        await message.answer(f"❌ Игрок '{target}' не найден.")
        return

    # Получаем player_id отправителя и получателя
    from_player_id = await get_player_id_by_tg(from_user_id)
    to_player_id = await get_player_id_by_tg(target_tg_id)

    if not from_player_id:
        await message.answer("❌ Вы не зарегистрированы. Напишите /start")
        return

    if not to_player_id:
        await message.answer(f"❌ Игрок с tg_id {target_tg_id} не зарегистрирован в игре.")
        return

    # Выполняем перевод через API
    r = await api_call(from_user_id, "transfer", {"to_player_id": to_player_id, "amount": amount})
    if r.get("success"):
        await message.answer(
            f"✅ {r.get('message')}\n💰 Ваш баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML"
        )
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка перевода')}")

# ---------- ОБРАБОТЧИКИ CALLBACK (МЕНЮ) ----------
@dp.callback_query(lambda c: c.data == "menu_page_2")
async def menu_page_2_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    result = await api_call(user_id, "get_stats")
    if result.get("success"):
        s = result.get("stats", {})
        text = (f"🏠 <b>ИМУЩЕСТВО</b>\n\n"
                f"💰 Баланс: {s.get('balance', 0):,}₽\n"
                f"🏠 Жильё: {s.get('house', 'room')}\n"
                f"🏪 Магазин: {s.get('shop_level', 'none')}\n"
                f"🚗 Машина: {s.get('current_car', 'none')}\n"
                f"🎮 В гараже: {s.get('car_collection_count', 0)} шт.\n\n"
                f"<i>Управляй своим имуществом</i>")
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=make_main_kb(2))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "menu_page_3")
async def menu_page_3_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    result = await api_call(user_id, "get_stats")
    if result.get("success"):
        s = result.get("stats", {})
        text = (f"👥 <b>СОЦИУМ</b>\n\n"
                f"👤 Игрок: {s.get('nickname', 'Торгаш')}\n"
                f"⭐ Репутация: {s.get('reputation_score', 0)}\n"
                f"📦 Продано: {s.get('items_sold', 0)}\n\n"
                f"<i>Общайся, соревнуйся, развивайся</i>")
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=make_main_kb(3))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@dp.message(Command('friend'))
async def friend_cmd(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используй: /friend add ник  или  /friend remove ник")
        return
    action = args[1]
    if action == "add" and len(args) >= 3:
        friend_name = args[2]
        r = await api_call(message.from_user.id, "add_friend", {"friend_name": friend_name})
        await message.answer(r.get("message", "Ошибка"))
    elif action == "remove" and len(args) >= 3:
        friend_name = args[2]
        user_info = await api_call(message.from_user.id, "get_player_by_nickname", {"nickname": friend_name})
        if user_info.get("success"):
            friend_id = user_info.get("player", {}).get("id")
            if friend_id:
                r = await api_call(message.from_user.id, "remove_friend", {"friend_id": friend_id})
                await message.answer(r.get("message", "Ошибка"))
            else:
                await message.answer("Игрок не найден")
        else:
            await message.answer("Игрок не найден")
    else:
        await message.answer("Неверная команда. Пример: /friend add Барыга")

# ==================== ОБРАБОТЧИКИ ОСНОВНЫХ ДЕЙСТВИЙ ====================
# (все они остаются такими же, как в вашем рабочем коде, только меняется клавиатура при возврате)

@dp.callback_query(lambda c: c.data == "balance")
async def balance_callback(callback: CallbackQuery):
    r = await api_call(callback.from_user.id, "get_balance")
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(f"💰 Ваш баланс: {r.get('balance', 0):,}₽", parse_mode="HTML")
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "loan_menu")
async def loan_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    player = await run_sync_db(get_player_data, player_id)
    max_loan = await calculate_max_loan(player)

    text = (
        "💰 <b>КРЕДИТНЫЙ ОТДЕЛ</b>\n\n"
        f"💎 Ваш кредитный лимит: <b>{max_loan:,}₽</b>\n\n"
        "Условия кредитования:\n"
        "• Сумма от 10 000 до лимита\n"
        "• Процентная ставка: 5% за 2 дня\n"
        "• Срок: 2 дня\n"
        "• При просрочке: +10% к сумме долга\n\n"
        "ВНИМАНИЕ: Неуплата может привести к штрафам и аресту имущества!\n\n"
        "Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 ВЗЯТЬ КРЕДИТ", callback_data="take_loan")],
        [InlineKeyboardButton(text="📋 МОИ КРЕДИТЫ", callback_data="my_loans")],
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="bank_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "balance_details")
async def unified_profit_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    player = await run_sync_db(get_player_data, player_id)
    if not player:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return

    # ---- 1. Данные из старого balance_details ----
    house_id = player.get("house", "room")
    house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
    house_income_day = house["income_bonus"]

    hourly, _ = await run_sync_db(get_hourly_income, player_id)
    total_income_day = hourly * 24

    car_id = player.get("current_car", "none")
    car = next((c for c in CARS if c["id"] == car_id), None)
    car_income_day = (car["income_per_hour"] * 24) if car else 0

    taxopark = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_income_day = _taxi_current_hourly_sync(player, income_multiplier=_taxi_income_multiplier(_taxi_upgrades_for_player_sync(player_id))) * 24

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
    shops = cursor.fetchall()
    conn.close()
    shops_income_day = 0
    shops_list = []
    for row in shops:
        shop = next((s for s in SHOP_LEVELS if s["id"] == row["shop_id"]), None)
        if shop:
            shops_income_day += shop["income_per_hour"] * 24
            shops_list.append(f"{shop['name']} (+{shop['income_per_hour']}₽/ч)")

    pending, hourly_pending, pending_breakdown = await get_pending_income(player_id)

    # ---- 3. Формируем текст ----
    text = (
        f"💰 <b>БАЛАНС И ПРИБЫЛЬ</b>\n\n"
        f"💰 Доступно: {player.get('balance', 0):,}₽\n"
        f"📈 Общая прибыль: {player.get('total_earned', 0):,}₽\n"
        f"📊 Продано товаров: {player.get('total_sales', 0)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ <b>ПАССИВНЫЙ ДОХОД</b>\n"
        f"💵 <b>В час:</b> {hourly:,}₽/ч\n"
        f"💵 <b>Накоплено:</b> {pending:,}₽\n\n"
        f"🏠 <b>За день (от имущества):</b>\n"
        f"🏠 Недвижимость: +{house_income_day:,}₽\n"
        f"🏪 Все магазины: +{shops_income_day:,}₽\n"
        f"🚗 Транспорт: +{car_income_day:,}₽\n"
        f"🚕 Таксопарк: +{taxopark_income_day:,}₽\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Итого за день: +{total_income_day:,}₽</b>\n\n"
        f"📅 Статистика сегодня:\n"
        f"💸 Заработано: {player.get('stat_earned_today', 0):,}₽\n"
        f"📦 Продано: {player.get('stat_sold_today', 0)} шт.\n"
    )

    if shops_list:
        text += f"\n📦 <b>Ваши магазины ({len(shops_list)} шт.):</b>\n" + "\n".join(shops_list) + "\n"
        text += f"<i>Продать магазин — вернётся 70% его стоимости.</i>\n"
    else:
        text += "\n📦 <b>У вас нет магазинов.</b> Купите первый!\n"

    # Рассчитываем долг
    debt = await calculate_total_debt(player_id)

    # Добавляем информацию о долге в текст
    debt_text = f"\n⚠️ <b>Задолженность по обслуживанию:</b> {debt:,}₽" if debt > 0 else "\n✅ <b>Задолженности нет.</b>"
    text += debt_text

    # ---- 4. Клавиатура ----
    kb_buttons = [
        [InlineKeyboardButton(text="💰 ЗАБРАТЬ ПРИБЫЛЬ", callback_data="collect_income", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🏪 КУПИТЬ МАГАЗИН", callback_data="buy_shop_entry", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="🏪 ПРОДАТЬ МАГАЗИН", callback_data="sell_shop_list", style=ButtonStyle.DANGER)],
    ]

    if debt > 0:
        kb_buttons.append([InlineKeyboardButton(text=f"💸 ОПЛАТИТЬ БИЗНЕС ({debt:,}₽)", callback_data="pay_all_debt", style=ButtonStyle.PRIMARY)])

    kb_buttons.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: CallbackQuery):
    r = await api_call(callback.from_user.id, "get_stats")
    if r.get("success"):
        s = r.get("stats", {})
        text = (f"📊 <b>СТАТИСТИКА</b>\n\n👤 {s.get('nickname', 'Торгаш')}\n📱 {s.get('shop_name', 'Без названия')}\n"
                f"💰 {s.get('balance', 0):,}₽\n📅 День {s.get('day', 1)}\n📦 {s.get('inventory_count', 0)} товаров\n"
                f"📋 Продано: {s.get('items_sold', 0)}\n💸 Прибыль: {s.get('total_earned', 0):,}₽\n"
                f"🏠 {s.get('house', 'room')}\n🏪 {s.get('shop_level', 'none')}\n🚗 {s.get('current_car', 'none')}\n"
                f"🎮 Машин: {s.get('car_collection_count', 0)}")
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "reputation")
async def reputation_callback(callback: CallbackQuery):
    r = await api_call(callback.from_user.id, "get_reputation")
    if r.get("success"):
        text = (f"⭐ <b>РЕПУТАЦИЯ АВИТО</b>\n\nУровень: <b>{r.get('level', 'Новичок')}</b>\n"
                f"Рейтинг: {r.get('rating', '⭐ Новый продавец')}\n📦 Продаж: {r.get('total_sales', 0)}\n"
                f"💰 Прибыль: {r.get('total_profit', 0):,}₽\n\n<i>5 продаж → Темщик, 15 продаж → Мажор</i>")
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 СКИНЫ", callback_data="skins_menu")], [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)

@dp.callback_query(lambda c: c.data == "get_demand")
async def get_demand_callback(callback: CallbackQuery):
    r = await api_call(callback.from_user.id, "get_demand")
    if r.get("success"):
        text = f"📈 <b>СПРОС НА РЫНКЕ</b>\n\n{r.get('formatted', 'Нет данных')}"
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
# ---------- ЗАКУПКА ----------
@dp.callback_query(lambda c: c.data == "buy_menu")
async def buy_menu_callback(callback: CallbackQuery):
    user_id=callback.from_user.id; res=await api_call(user_id,"get_suppliers")
    if not res.get("success"): await safe_callback_answer(callback,res.get("message","Ошибка"),show_alert=True); return
    items=res.get("suppliers",[]); demand=res.get("market_demand",{})
    if not items:
        await safe_delete_message(callback.message); await callback.message.answer("🏭 <b>ЗАКУП</b>\n\nПоставки обновятся автоматически.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 ОБНОВИТЬ",callback_data="buy_menu")],[InlineKeyboardButton(text="🔙 В МЕНЮ",callback_data="back_to_menu")]])); await safe_callback_answer(callback); return
    p=await api_call(user_id,"get_balance"); balance=int(p.get("balance",0))
    top=sorted(demand.items(),key=lambda x:x[1],reverse=True)[:2]
    text=f"🏭 <b>ЗАКУП</b> · баланс {balance:,}₽\n<code>Обновление поставок каждые 5 минут</code>\n\n📈 Горячие категории: {top[0][0]} x{top[0][1]:.2f}, {top[1][0]} x{top[1][1]:.2f}\n\n<b>Выбирай конкретный товар:</b>"
    kb=[]
    for it in items[:10]:
        tl=max(0,int(it.get("end_time",0)-time_module.time())); margin=float(it.get("margin_pct",0)); dm=float(it.get("demand",1));
        text+=f"{it.get('rarity_color','⬜')} {it.get('name')}\n💸 {int(it.get('buy_price',0)):,}₽ → ~{int(it.get('market_price',0)):,}₽ · +{margin:.0f}% · спрос x{dm:.2f} · {tl//60}м\n\n"
        label=f"🛒 КУПИТЬ · {str(it.get('name','ТОВАР'))[:24]}"
        kb.append([InlineKeyboardButton(text=label,callback_data=f"buy_{it.get('id')}")])
    kb += [[InlineKeyboardButton(text="🔄 ОБНОВИТЬ СПИСОК",callback_data="buy_menu")],[InlineKeyboardButton(text="📈 СПРОС",callback_data="get_demand")],[InlineKeyboardButton(text="🔙 В МЕНЮ",callback_data="back_to_menu")]]
    await safe_delete_message(callback.message); await callback.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_") and c.data.split("_")[1].isdigit())
async def buy_item_callback(callback:CallbackQuery):
    user_id=callback.from_user.id; item_id=int(callback.data.split("_")[1]); r=await api_call(user_id,"buy_from_supplier",{"item_id":item_id})
    if r.get("success"):
        await callback.message.answer(f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance',0):,}₽",parse_mode="HTML",reply_markup=menu_kb()); await safe_callback_answer(callback,"✅ Куплено!")
    else: await safe_callback_answer(callback,r.get("message","Ошибка"),show_alert=True)

# ---------- ИНВЕНТАРЬ ----------
@dp.callback_query(lambda c: c.data == "inventory_menu")
async def inventory_menu_callback(callback: CallbackQuery):
    user_id=callback.from_user.id; r=await api_call(user_id,"get_inventory")
    if not r.get("success"): await safe_callback_answer(callback,"Ошибка",show_alert=True); return
    inv=r.get("inventory",[])
    if not inv:
        await safe_delete_message(callback.message); await callback.message.answer("📦 <b>ИНВЕНТАРЬ ПУСТ</b>\n\nКупи товары у поставщиков!",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏭 ЗАКУП",callback_data="buy_menu")],[InlineKeyboardButton(text="🔙 В МЕНЮ",callback_data="back_to_menu")]])); await safe_callback_answer(callback); return
    text=f"📦 <b>ИНВЕНТАРЬ</b> · {len(inv)} шт.\n\n"; kb=[]
    for i,it in enumerate(inv):
        uid=it.get("uid",i); buy=int(it.get("buy_price",0)); market=int(it.get("market_price",0)); margin=market-buy
        text+=f"<b>{i+1}. {it.get('name')}</b>\n💸 Куплен: {buy:,}₽\n📈 Рынок: {market:,}₽\n💵 Потенциал: +{margin:,}₽\n\n"
        kb.append([InlineKeyboardButton(text=f"📢 ПРОДАТЬ · {str(it.get('name',''))[:24]}",callback_data=f"publish_{uid}")])
        kb.append([InlineKeyboardButton(text=f"🔨 АУКЦИОН · {str(it.get('name',''))[:22]}",callback_data=f"auction_sell_item_{uid}")])
    kb += [[InlineKeyboardButton(text="🏭 ЗАКУП",callback_data="buy_menu")],[InlineKeyboardButton(text="🔙 В МЕНЮ",callback_data="back_to_menu")]]
    await safe_delete_message(callback.message); await callback.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "chats_menu")
async def chats_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Вы не зарегистрированы", show_alert=True)
        return
    
    async with chats_lock:
        my_chats = []
        for key, chat in active_chats.items():
            if chat.get("user_id") == player_id and not chat.get("finished"):
                my_chats.append(chat)
    
    if not my_chats:
        text = "💬 <b>ЧАТЫ С ПОКУПАТЕЛЯМИ</b>\n\nУ вас нет активных диалогов.\nОпубликуйте товар, чтобы начать общение."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
        ])
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await safe_callback_answer(callback)
        return
    
    text = "💬 <b>ЧАТЫ С ПОКУПАТЕЛЯМИ</b>\n\n"
    kb = []
    for i, chat in enumerate(my_chats, 1):
        text += f"{i}. {chat['item']} – покупатель #{chat['buyer_id']}\n"
        kb.append([InlineKeyboardButton(text=f"✉️ Чат {i}", callback_data=f"open_chat_{chat['chat_key']}")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("publish_"))
async def publish_item_callback(callback: CallbackQuery, state: FSMContext):
    item_uid=callback.data.split("_",1)[1]
    await state.update_data(publish_item_uid=item_uid)
    await state.set_state(Form.waiting_for_description)
    await safe_delete_message(callback.message)
    r=await api_call(callback.from_user.id,"get_inventory")
    inv=r.get("inventory",[]) if r.get("success") else []
    item=next((x for x in inv if str(x.get("uid"))==str(item_uid)),None)
    if not item:
        await callback.message.answer("❌ Товар уже исчез из инвентаря."); await safe_callback_answer(callback); return
    market=int(item.get("market_price",0)); buy=int(item.get("buy_price",0));
    await callback.message.answer(f"📢 <b>ПРОДАЖА ТОВАРА</b>\n\n📦 <b>{item.get('name')}</b>\n💸 Закуп: {buy:,}₽\n📈 Рынок: {market:,}₽\n💵 Потенциальная разница: +{max(0,market-buy):,}₽\n\n✍️ Теперь напиши описание: состояние, комплектацию, размеры/модель и главную выгоду.\n\nЧем понятнее объявление, тем выше качество продажи.", parse_mode="HTML")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_description))
async def handle_description(message: Message, state: FSMContext):
    user_id = message.from_user.id
    desc = message.text.strip()
    data = await state.get_data()
    item_uid=data.get("publish_item_uid")
    r=await api_call(user_id,"publish_item",{"item_uid":item_uid,"description":desc})
    if r.get("success"):
        chat_key = r.get("chat_key")
        if chat_key:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 ПЕРЕЙТИ В ЧАТ", callback_data=f"open_chat_{chat_key}")]
            ])
            await message.answer(r.get("message"), parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(r.get("message"), parse_mode="HTML")
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка')}")
    await state.clear()

# ---------- ЧАТЫ С ПОКУПАТЕЛЯМИ ----------
@dp.callback_query(lambda c: c.data.startswith("open_chat_"))
async def open_chat_callback(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        await safe_callback_answer(callback, "Вы не зарегистрированы. Напишите /start", show_alert=True)
        return

    chat_key = callback.data[len("open_chat_"):]

    async with chats_lock:
        if chat_key not in active_chats:
            await safe_callback_answer(callback, "Чат не найден. Возможно, диалог уже завершён.", show_alert=True)
            return
        chat = active_chats[chat_key]
        if chat.get("user_id") != player_id:
            await safe_callback_answer(callback, "Это не ваш чат", show_alert=True)
            return
        if chat.get("finished"):
            await safe_callback_answer(callback, "Диалог уже завершён", show_alert=True)
            return
        last_msg = chat["history"][-1]["content"] if chat["history"] else "Чат открыт"
        kb = get_chat_keyboard(chat)
    await safe_delete_message(callback.message)
    await callback.message.answer(
        f"👤 <b>Покупатель #{chat['buyer_id']}</b>\n\n{last_msg}\n\n<i>Выберите вариант ответа:</i>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await safe_callback_answer(callback)

# ---------- АВТОМОБИЛИ ----------
@dp.callback_query(lambda c: c.data == "cars_menu")
async def cars_category_menu(callback: CallbackQuery):
    text = "🚗 <b>АВТОСАЛОН</b>\n\nВыберите класс автомобиля:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 ЭКОНОМ (до 50 000₽)", callback_data="cars_cat_economy")],
        [InlineKeyboardButton(text="🚙 СРЕДНИЙ (50 000–500 000₽)", callback_data="cars_cat_medium")],
        [InlineKeyboardButton(text="🏎 ЛЮКС (от 500 000₽)", callback_data="cars_cat_luxury")],
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    try:
        msg = await bot.send_photo(
            callback.from_user.id,
            photo="AgACAgIAAxkBAAIZfmoWvalmKTiseC7qzwGHslhPW2tQAALOGmsb9FaxSBoXVgyKCcnKAQADAgADeQADOwQ",
            caption=text,
            parse_mode="HTML",
            reply_markup=kb
        )
        last_bot_message[callback.from_user.id] = msg.message_id
    except Exception as e:
        # Если фото не отправилось (проблемы с file_id), покажем обычный текст
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

async def show_cars_by_category(callback: CallbackQuery, category: str = None):
    category_map = {
        "economy": "🚗 ЭКОНОМ",
        "medium": "🚙 СРЕДНИЙ",
        "luxury": "🏎 ЛЮКС"
    }
    if category is None:
        cat_key = callback.data.split("_")[2]
    else:
        cat_key = category

    user_id = callback.from_user.id
    
    # Фильтруем автомобили по категории
    filtered_cars = [c for c in CARS if c.get("category") == cat_key]
    if not filtered_cars:
        await safe_callback_answer(callback, "В этой категории пока нет автомобилей", show_alert=True)
        return

    # Пагинация
    if not hasattr(show_cars_by_category, "page"):
        show_cars_by_category.page = {}
    key = f"{user_id}_{cat_key}"
    page = show_cars_by_category.page.get(key, 0)
    total = len(filtered_cars)
    if page < 0: page = 0
    if page >= total: page = total - 1
    
    car = filtered_cars[page]
    # Получаем баланс и коллекцию
    p = await api_call(user_id, "get_stats")
    balance = p.get("stats", {}).get("balance", 0) if p.get("success") else 0
    collection = await api_call(user_id, "get_car_collection")
    owned = car["id"] in collection.get("cars", []) if collection.get("success") else False
    current_car = await api_call(user_id, "get_current_car")
    is_current = current_car.get("car_id") == car["id"] if current_car.get("success") else False
    
    # Формируем текст
    txt = f"🛒 <b>АВТОСАЛОН — {category_map[cat_key]}</b>\n📄 {page+1}/{total}\n\n{car['name']}\n⭐ {car['rarity'].upper()}\n⚡ Ускорение: {car['speed_bonus']}%\n💰 Доход: {car['income_per_hour']}₽/час\n"
    
    # Клавиатура
    kb = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"cars_cat_{cat_key}_page_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"cars_cat_{cat_key}_page_{page+1}"))
    if nav:
        kb.append(nav)
    
    # Кнопка покупки
    if balance >= car["price"]:
        btn_text = "🛒 КУПИТЬ ЕЩЁ" if owned else "🛒 КУПИТЬ"
        kb.append([InlineKeyboardButton(text=f"{btn_text} — {car['price']:,}₽".replace(",", " "), callback_data=f"buy_car_{car['id']}")])
    else:
        shortage = car['price'] - balance
        txt += f"\n❌ Нужно {car['price']:,}₽ (не хватает {shortage:,}₽)".replace(",", " ")
    
    if owned and not is_current:
        kb.append([InlineKeyboardButton(text="🚗 СДЕЛАТЬ ТЕКУЩЕЙ", callback_data=f"set_car_{car['id']}")])
    if is_current:
        txt += "\n✅ <b>ТВОЯ ТЕКУЩАЯ МАШИНА</b>"
    elif owned:
        txt += "\n✅ <b>КУПЛЕНО</b> (в гараже)"
    
    txt += f"\n\n💼 Баланс: {balance:,}₽".replace(",", " ")
    kb.append([InlineKeyboardButton(text="🔙 К КАТЕГОРИЯМ", callback_data="cars_menu")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    
    # Отправляем сообщение (с фото или без)
    if car.get("image_url"):
        try:
            await safe_delete_message(callback.message)
            msg = await bot.send_photo(user_id, car["image_url"], caption=txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            last_bot_message[user_id] = msg.message_id
        except Exception as e:
            print(f"Ошибка отправки фото: {e}")
            await send_msg(user_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await send_msg(user_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
    # Сохраняем страницу
    show_cars_by_category.page[key] = page
    # НЕ вызываем callback.answer() здесь – это сделает вызывающий обработчик

@dp.callback_query(lambda c: c.data.startswith("cars_cat_") and not "_page_" in c.data)
async def cars_category_callback(callback: CallbackQuery):
    await show_cars_by_category(callback)
    await safe_callback_answer(callback)  # только здесь один раз

@dp.callback_query(lambda c: c.data.startswith("cars_cat_") and "_page_" in c.data)
async def cars_category_page(callback: CallbackQuery):
    parts = callback.data.split("_")
    cat_key = parts[2]  # economy, medium, luxury
    page = int(parts[4])

    user_id = callback.from_user.id
    key = f"{user_id}_{cat_key}"

    if not hasattr(show_cars_by_category, "page"):
        show_cars_by_category.page = {}

    show_cars_by_category.page[key] = page
    await show_cars_by_category(callback, category=cat_key)
    await safe_callback_answer(callback)

# ---------- ТАКСОПАРК ----------
@dp.callback_query(lambda c: c.data == "taxopark_menu")
async def taxopark_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_taxopark")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    tax = r.get("taxopark", {})
    level_info = r.get("level_info", {})

    text = f"🚕 <b>ТАКСОПАРК</b>\n\nТекущий: {level_info.get('name', 'Нет')}\n"
    if level_info.get("slots", 0) > 0:
        text += f"📊 Слотов: {len(tax.get('cars', []))}/{level_info.get('slots', 0)}\n💰 Доход: {level_info.get('income_per_car', 0)}₽/час с машины\n"
        if tax.get("cars"):
            text += "\n<b>Машины в таксопарке:</b>\n" + "\n".join(f"• {c}" for c in tax.get("cars", []))
    
    kb = []
    levels_res = await api_call(user_id, "get_taxopark_levels")
    if levels_res.get("success"):
        for lvl in levels_res.get("levels", []):
            if lvl.get("price", 0) > 0 and lvl.get("id") != tax.get("level"):
                kb.append([InlineKeyboardButton(text=f"⬆️ {lvl.get('name')} - {lvl.get('price'):,}₽", callback_data=f"buy_taxopark_{lvl.get('id')}")])
    kb.append([InlineKeyboardButton(text="➕ ДОБАВИТЬ МАШИНУ", callback_data="taxopark_add_menu")])
    kb.append([InlineKeyboardButton(text="🔙 В ГАРАЖ", callback_data="garage_menu")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])

    await safe_delete_message(callback.message)
    try:
        msg = await bot.send_photo(
            user_id,
            photo="AgACAgIAAxkBAAIZ6moWwqa2RbcFEqk7_SqvfdlPJNbSAAMZaxv0VrlIUAzCreut-SABAAMCAAN5AAM7BA",
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
        last_bot_message[user_id] = msg.message_id
    except Exception as e:
        # Если фото не отправилось – покажем обычный текст
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "collect_income")
async def collect_income_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    collected, hourly, breakdown = await collect_pending_income(player_id)
    if collected > 0:
        # Сначала обновляем экран баланса (уже с обнулённым накопленным доходом)
        await unified_profit_callback(callback)
        
        # Затем отправляем детализацию полученного дохода
        lines = []
        if breakdown.get("house", 0) > 0:
            lines.append(f"🏠 Недвижимость: +{breakdown['house']:,}₽")
        if breakdown.get("shops", 0) > 0:
            lines.append(f"🏪 Магазины: +{breakdown['shops']:,}₽")
        if breakdown.get("car", 0) > 0:
            lines.append(f"🚗 Транспорт: +{breakdown['car']:,}₽")
        if breakdown.get("taxopark", 0) > 0:
            lines.append(f"🚕 Таксопарк: +{breakdown['taxopark']:,}₽")
        
        details = "\n".join(lines) if lines else "Нет накоплений"
        
        await callback.message.answer(
            f"✅ <b>ВЫ ПОЛУЧИЛИ ПАССИВНЫЙ ДОХОД!</b>\n\n"
            f"<b>Общая сумма:</b> +{collected:,}₽\n\n"
            f"<b>Источники:</b>\n{details}",
            parse_mode="HTML"
        )
    else:
        await safe_callback_answer(callback, "Накоплений пока нет.", show_alert=True)

@dp.callback_query(lambda c: c.data == "pay_all_debt")
async def pay_all_debt_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    try:
        success, msg = await pay_all_debt(player_id)
        await safe_delete_message(callback.message)
        await callback.message.answer(msg, parse_mode="HTML", reply_markup=menu_kb())
        if success:
            await unified_profit_callback(callback)
    except Exception as e:
        print(f"Ошибка в pay_all_debt_callback: {e}")
        import traceback
        traceback.print_exc()
        await safe_delete_message(callback.message)
        await callback.message.answer(f"❌ Произошла ошибка: {str(e)}", parse_mode="HTML", reply_markup=menu_kb())
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
    else:
        await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "shop_entry")
async def shop_entry_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    text = (
        "🏪 <b>ТОРГОВЫЙ ЦЕНТР «Resell Tycoon»</b>\n\n"
        "Добро пожаловать в наш торговый комплекс!\n"
        "• Просмотрите текущий магазин\n"
        "• Приобретите новые торговые точки\n"
        "• Каждый магазин приносит пассивный доход\n"
        "• Доход от всех магазинов суммируется\n\n"
        "Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 ВОЙТИ В МАГАЗИН", callback_data="shop_menu")],
        [InlineKeyboardButton(text="🔙 ВЫЙТИ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    try:
        msg = await bot.send_photo(
            user_id,
            photo="AgACAgIAAxkBAAIaGGoWx6TJp3U89XKlNVY9BMEjpxXZAAIhGWsb9Fa5SBXzeekbHBuVAQADAgADeQADOwQ",  # ← твой file_id
            caption=text,
            parse_mode="HTML",
            reply_markup=kb
        )
        last_bot_message[user_id] = msg.message_id
    except Exception as e:
        # Если фото не отправилось – покажем обычный текст
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "buy_shop_entry")
async def buy_shop_entry_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    text = (
        "🏪 <b>ТОРГОВЫЙ ЦЕНТР «Resell Tycoon»</b>\n\n"
        "Здесь вы можете приобрести магазины для вашего бизнеса:\n"
        "• каждый магазин приносит пассивный доход\n"
        "• можно купить до 2 магазинов каждого типа\n"
        "• доход от всех магазинов суммируется\n\n"
        "Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 ВОЙТИ В КАТАЛОГ МАГАЗИНОВ", callback_data="buy_shop_menu")],
        [InlineKeyboardButton(text="🔙 ВЫЙТИ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    try:
        msg = await bot.send_photo(
            user_id,
            photo="AgACAgIAAxkBAAIaGGoWx6TJp3U89XKlNVY9BMEjpxXZAAIhGWsb9Fa5SBXzeekbHBuVAQADAgADeQADOwQ",
            caption=text,
            parse_mode="HTML",
            reply_markup=kb
        )
        last_bot_message[user_id] = msg.message_id
    except Exception as e:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "buy_shop_menu")
async def buy_shop_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    shops = [s for s in SHOP_LEVELS if s["id"] != "none"]
    text = "🏪 <b>ВЫБЕРИ МАГАЗИН ДЛЯ ПОКУПКИ</b>\n\n"
    kb = []
    for shop in shops:
        text += f"{shop['name']}\n💰 {shop['price']:,}₽ | 📈 +{shop['income_per_hour']}₽/час\n\n"
        kb.append([InlineKeyboardButton(text=f"🛒 {shop['name']} - {shop['price']:,}₽", callback_data=f"buy_shop_multiple_{shop['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="balance_details")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_shop_multiple_"))
async def buy_shop_multiple_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    shop_id = callback.data.split("_")[3]  # формат: buy_shop_multiple_<shop_id>
    r = await api_call(user_id, "buy_shop_multiple", {"shop_id": shop_id})
    if r.get("success"):
        await safe_callback_answer(callback, "✅ Магазин куплен!")
        await unified_profit_callback(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("buy_taxopark_"))
async def buy_taxopark_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    level_id = callback.data.split("_")[2]
    r = await api_call(user_id, "buy_taxopark", {"level_id": level_id})
    if r.get("success"):
        await safe_callback_answer(callback, "✅ Куплено!")
        await taxopark_menu_callback(callback)  # обновляет меню таксопарка
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data == "taxopark_add_menu")
async def taxopark_add_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    cars_res = await api_call(user_id, "get_car_collection")
    if not cars_res.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    cars = cars_res.get("cars", [])
    if not cars:
        await safe_callback_answer(callback, "Нет машин в гараже", show_alert=True)
        return
    text = "➕ <b>ВЫБЕРИ МАШИНУ ДЛЯ ТАКСОПАРКА:</b>\n\n"
    kb = []
    for car in cars:
        text += f"• {car.get('name')}\n"
        kb.append([InlineKeyboardButton(text=f"➕ {car.get('name')}", callback_data=f"add_taxopark_{car.get('id')}")])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="taxopark_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("add_taxopark_"))
async def add_taxopark_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    car_id = callback.data.split("_")[2]
    r = await api_call(user_id, "add_car_to_taxopark", {"car_id": car_id})
    if r.get("success"):
        await safe_callback_answer(callback, "✅ Добавлено!")
        await taxopark_menu_callback(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

# ---------- НЕДВИЖИМОСТЬ ----------
@dp.callback_query(lambda c: c.data == "houses_entry")
async def houses_entry_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    text = (
        "🏢 <b>РИЕЛТОРСКАЯ КОМПАНИЯ «Resell Tycoon»</b>\n\n"
        "Добро пожаловать! Здесь вы можете приобрести недвижимость:\n"
        "• от скромной комнаты до роскошного небоскрёба\n"
        "• каждый объект приносит пассивный доход\n"
        "• улучшайте жильё, чтобы зарабатывать больше\n\n"
        "Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 ВОЙТИ В КАТАЛОГ", callback_data="houses_menu")],
        [InlineKeyboardButton(text="🔙 ВЫЙТИ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    try:
        msg = await bot.send_photo(
            user_id,
            photo="AgACAgIAAxkBAAIZ-moWxChVGd40T0zl7nHSZD9Wm6UKAAIGGWsb9Fa5SFjCSqkLcdcTAQADAgADeQADOwQ",  # ← вставлен твой file_id
            caption=text,
            parse_mode="HTML",
            reply_markup=kb
        )
        last_bot_message[user_id] = msg.message_id
    except Exception as e:
        # Если фото не отправилось – покажем обычный текст
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "houses_menu")
async def houses_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    houses = HOUSES
    if not hasattr(houses_menu_callback, "page"):
        houses_menu_callback.page = {}
    page = houses_menu_callback.page.get(user_id, 0)
    total = len(houses)
    if page < 0: page = 0
    if page >= total: page = total - 1
    if total == 0:
        await safe_delete_message(callback.message)
        await callback.message.answer("🏠 Недвижимость временно недоступна.", parse_mode="HTML")
        await safe_callback_answer(callback)
        return
    house = houses[page]
    p = await api_call(user_id, "get_stats")
    balance = p.get("stats", {}).get("balance", 0) if p.get("success") else 0
    current_house = await api_call(user_id, "get_current_house")
    current_id = current_house.get("house", {}).get("id") if current_house.get("success") else "room"
    owned = house["id"] == current_id
    txt = f"🏠 <b>НЕДВИЖИМОСТЬ</b>\n📄 {page+1}/{total}\n\n{house['name']}\n💰 Доход: +{house['income_bonus']}₽/день\n"
    if house.get("description"):
        txt += f"{house['description']}\n"
    if owned:
        txt += "\n✅ <b>ТВОЁ ЖИЛЬЁ</b>"
        act = None
    elif balance >= house["price"]:
        txt += f"\n💰 Цена: {house['price']:,}₽"
        act = InlineKeyboardButton(text="🛒 КУПИТЬ", callback_data=f"buy_house_{house['id']}", style=ButtonStyle.SUCCESS)
    else:
        txt += f"\n❌ Нужно {house['price']:,}₽ (не хватает {house['price'] - balance:,}₽)"
        act = None
    txt += f"\n\n💼 Баланс: {balance:,}₽"

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"house_page_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"house_page_{page+1}"))

    kb = []
    if nav:
        kb.append(nav)
    if act:
        kb.append([act])
    if current_id != "room":
        kb.append([InlineKeyboardButton(text="🏠 ПРОДАТЬ ДОМ", callback_data="sell_house", style=ButtonStyle.DANGER)])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])

    if house.get("image_url"):
        try:
            await safe_delete_message(callback.message)
            msg = await bot.send_photo(user_id, house["image_url"], caption=txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            last_bot_message[user_id] = msg.message_id
        except Exception as e:
            print(f"Ошибка отправки фото для {house['name']}: {e}")
            await send_msg(user_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await send_msg(user_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

    houses_menu_callback.page[user_id] = page
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("house_page_"))
async def house_page_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split("_")[2])
    houses_menu_callback.page[user_id] = page
    await houses_menu_callback(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_house_"))
async def buy_house_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    house_id = callback.data.split("_")[2]
    r = await api_call(user_id, "buy_house", {"house_id": house_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback, "✅ Куплено!")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data == "sell_house")
async def sell_house_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "sell_house")
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback, "🏠 Дом продан!")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("buy_car_"))
async def buy_car_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    car_id = callback.data.split("_")[2]
    r = await api_call(user_id, "buy_car", {"car_id": car_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback, "✅ Куплено!")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

# ---------- МАГАЗИН ----------
@dp.callback_query(lambda c: c.data == "shop_menu")
async def shop_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_shops")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    shops = r.get("shops", [])
    cur = await api_call(user_id, "get_current_shop")
    current_shop = cur.get("shop") if cur.get("success") else None
    text = "🏪 <b>МАГАЗИН ОДЕЖДЫ</b>\n\n"
    if current_shop and current_shop.get("id") != "none":
        text += f"Текущий: {current_shop.get('name')}\n💰 Доход: {current_shop.get('income_per_hour')}₽/час\n\n"
    kb = []
    for shop in shops:
        if shop.get("id") == "none":
            continue
        status = "✅ " if current_shop and current_shop.get("id") == shop.get("id") else ""
        text += f"{status}{shop.get('name')}\n💰 {shop.get('price'):,}₽ | 📈 +{shop.get('income_per_hour')}₽/час\n\n"
        if not (current_shop and current_shop.get("id") == shop.get("id")):
            kb.append([InlineKeyboardButton(text=f"🛒 КУПИТЬ {shop.get('name')} - {shop.get('price'):,}₽", callback_data=f"buy_shop_{shop.get('id')}")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_shop_"))
async def buy_shop_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    shop_id = callback.data.split("_")[2]
    r = await api_call(user_id, "buy_shop", {"shop_id": shop_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback, "✅ Куплено!")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

# ---------- СКИНЫ ----------
@dp.callback_query(lambda c: c.data == "skins_menu")
async def skins_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    skins = SKINS
    rarity_order = {"обычный": 0, "редкий": 1, "эпический": 2, "легендарный": 3, "мифический": 4}
    skins.sort(key=lambda x: rarity_order.get(x.get("rarity", "обычный"), 0))
    if not hasattr(skins_menu_callback, "page"):
        skins_menu_callback.page = {}
    page = skins_menu_callback.page.get(user_id, 0)
    total = len(skins)
    if page < 0: page = 0
    if page >= total: page = total - 1
    if total == 0:
        await safe_delete_message(callback.message)
        await callback.message.answer("👤 Скины временно недоступны.", parse_mode="HTML")
        await safe_callback_answer(callback)
        return
    skin = skins[page]
    player_skins = await api_call(user_id, "get_player_skins")
    owned_skins = [s["id"] for s in player_skins.get("skins", [])] if player_skins.get("success") else []
    current = player_skins.get("current", "default") if player_skins.get("success") else "default"
    p = await api_call(user_id, "get_stats")
    balance = p.get("stats", {}).get("balance", 0) if p.get("success") else 0
    rep = await api_call(user_id, "get_reputation")
    total_sales = rep.get("total_sales", 0) if rep.get("success") else 0
    txt = f"👤 <b>МАГАЗИН СКИНОВ</b>\n📄 {page+1}/{total}\n\n{skin['emoji']} <b>{skin['name']}</b>\n⭐ {skin['rarity'].upper()}\n📝 {skin['description']}\n"
    if skin["id"] == current:
        txt += "\n✅ <b>НАДЕТ</b>"
        act = None
    elif skin["id"] in owned_skins:
        txt += "\n✅ <b>В ИНВЕНТАРЕ</b>"
        act = InlineKeyboardButton(text="👕 НАДЕТЬ", callback_data=f"equip_skin_{skin['id']}")
    elif skin.get("sales_required", 0) > 0:
        if total_sales >= skin["sales_required"]:
            txt += "\n🎁 <b>ДОСТУПЕН!</b>"
            act = InlineKeyboardButton(text="🎁 ПОЛУЧИТЬ", callback_data=f"buy_skin_{skin['id']}")
        else:
            txt += f"\n🔒 Нужно {skin['sales_required']} продаж (у тебя {total_sales})"
            act = None
    else:
        if skin.get("limited"):
            txt += f"\n🔒 <b>ТОЛЬКО ПО ВЫДАЧЕ</b>"
            act = None
        else:
            if balance >= skin["price"]:
                txt += f"\n💰 Цена: {skin['price']:,}₽"
                act = InlineKeyboardButton(text="🛒 КУПИТЬ", callback_data=f"buy_skin_{skin['id']}")
            else:
                txt += f"\n❌ {skin['price']:,}₽ (не хватает {skin['price'] - balance:,}₽)"
                act = None
    txt += f"\n\n💼 Баланс: {balance:,}₽ | ⭐ Продано: {total_sales}"
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"skin_page_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"skin_page_{page+1}"))
    kb = []
    if nav:
        kb.append(nav)
    if act:
        kb.append([act])
    kb.append([InlineKeyboardButton(text="🎒 ИНВЕНТАРЬ СКИНОВ", callback_data="skin_inventory")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    if skin.get("image_url"):
        try:
            await safe_delete_message(callback.message)
            msg = await bot.send_photo(user_id, skin["image_url"], caption=txt, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            last_bot_message[user_id] = msg.message_id
        except:
            await send_msg(user_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    else:
        await send_msg(user_id, txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    skins_menu_callback.page[user_id] = page
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("skin_page_"))
async def skin_page_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = int(callback.data.split("_")[2])
    skins_menu_callback.page[user_id] = page
    await skins_menu_callback(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_skin_"))
async def buy_skin_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    skin_id = callback.data.split("_")[2]
    r = await api_call(user_id, "buy_skin", {"skin_id": skin_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback, "✅ Куплено!")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("equip_skin_"))
async def equip_skin_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    skin_id = parts[2]
    instance_id = int(parts[3]) if len(parts) > 3 else None
    r = await api_call(user_id, "equip_skin", {"skin_id": skin_id, "instance_id": instance_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await back_to_menu_callback(callback)
        await callback.message.answer(f"✅ {r.get('message')}", parse_mode="HTML")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "skin_inventory")
async def skin_inventory_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_player_skins")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    skins = r.get("skins", [])
    current = r.get("current", "default")
    if not skins:
        await safe_delete_message(callback.message)
        await callback.message.answer("🎒 <b>ИНВЕНТАРЬ СКИНОВ ПУСТ</b>\n\nКупи скины в магазине! 👇", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛒 В МАГАЗИН", callback_data="skins_menu")], [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
        return
    text = "🎒 <b>ТВОИ СКИНЫ:</b>\n\n"
    kb = []
    for skin in skins:
        active = "✅ НАДЕТ" if skin["id"] == current else ""
        text += f"{skin.get('emoji', '👤')} {skin.get('name')} ({skin.get('rarity', 'обычный')}) {active}\n"
        if skin["id"] != current:
            kb.append([InlineKeyboardButton(text=f"👕 НАДЕТЬ: {skin.get('emoji')} {skin.get('name')}", callback_data=f"equip_skin_{skin.get('id')}")])
    kb.append([InlineKeyboardButton(text="🔙 В МАГАЗИН СКИНОВ", callback_data="skins_menu")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

# ---------- ПОДРАБОТКИ ----------

@dp.callback_query(lambda c: c.data == "jobs_entry")
async def jobs_entry_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    text = (
        "🏢 <b>ЦЕНТР ЗАНЯТОСТИ «Resell Tycoon»</b>\n\n"
        "Здесь вы можете заработать дополнительные средства:\n"
        "• выберите подходящую подработку\n"
        "• выполните задание и получите оплату\n"
        "• развивайтесь и открывайте новые возможности\n\n"
        "Выберите действие:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💼 ВОЙТИ В КАТАЛОГ РАБОТ", callback_data="jobs_menu", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="🔙 ВЫЙТИ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    try:
        msg = await bot.send_photo(
            user_id,
            photo="AgACAgIAAxkBAAIaC2oWxg3xUhrzqBl24J_aU66YVV6VAAIQGWsb9Fa5SMwND64ipS9UAQADAgADeQADOwQ",
            caption=text,
            parse_mode="HTML",
            reply_markup=kb
        )
        last_bot_message[user_id] = msg.message_id
    except Exception as e:
        # Если фото не отправилось – покажем обычный текст
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "jobs_menu")
async def jobs_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_jobs")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    jobs = r.get("jobs", [])
    text = "💼 <b>ПОДРАБОТКИ</b>\n\nВыбери работу:\n"
    kb = []
    for i, job in enumerate(jobs):
        text += f"{job.get('emoji')} {job.get('name')} — {job.get('reward')}₽ ({job.get('duration')}с)\n"
        kb.append([InlineKeyboardButton(text=f"{job.get('emoji')} {job.get('name')} — {job.get('reward')}₽", callback_data=f"start_job_{i}", style=ButtonStyle.PRIMARY)])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("start_job_"))
async def start_job_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    job_idx = int(callback.data.split("_")[2])
    r = await api_call(user_id, "start_job", {"job_idx": job_idx})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"💼 <b>РАБОТА НАЧАТА!</b>\n{r.get('message')}",
            parse_mode="HTML",
            reply_markup=menu_kb()   # ← добавили кнопку
        )
        asyncio.create_task(check_job_completion(callback.message, user_id))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

async def check_job_completion(msg: types.Message, user_id: int):
    await asyncio.sleep(1)
    for _ in range(60):
        await asyncio.sleep(2)
        r = await api_call(user_id, "check_job")
        if r.get("success") and r.get("finished"):
            # ЗАМЕНИТЬ ЭТУ СТРОКУ:
            # await msg.answer(...)
            await bot.send_message(
                user_id,
                f"✅ <b>РАБОТА ЗАВЕРШЕНА!</b>\n💰 +{r.get('reward')}₽",
                parse_mode="HTML",
                reply_markup=menu_kb()
            )
            await send_notification(user_id, f"Работа завершена! Получено {r.get('reward')}₽")
            return
        elif r.get("success") and not r.get("finished"):
            continue
        else:
            break

async def send_notification(user_id: int, text: str):
    player_id = await get_player_id_by_tg(user_id)
    if player_id:
        player = await run_sync_db(get_player_data, player_id)
        if player and player.get("notifications", 1):
            await bot.send_message(user_id, f"🔔 {text}")

# ---------- ТРЕЙДИНГ ----------
@dp.callback_query(lambda c: c.data == "trading_menu")
async def trading_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with trading_lock:
        if not trading_prices:
            await safe_callback_answer(callback, "Цены загружаются, попробуйте чуть позже", show_alert=True)
            return
        text = "📊 <b>POCKET OPTION</b>\n\n"
        # История ставок игрока
        user_bets = bet_history.get(user_id, [])[-5:]
        if user_bets:
            text += "<b>📋 Последние ставки:</b>\n"
            for bet in reversed(user_bets):
                sign = "✅" if bet["result"] == "win" else "❌"
                text += f"{sign} {bet['asset']} {bet['direction']} {bet['bet']}₽ → {bet['profit']}₽\n"
            text += "\n"
        else:
            text += "<i>Нет сделок</i>\n\n"

        # Текущие цены и график
        for asset, data in trading_prices.items():
            info = TRADING_ASSETS[asset]
            price = data["price"]
            trend = data["trend"]
            history = list(data["history"])
            # Тренд стрелка
            arrow = "📈" if trend > 0 else "📉" if trend < 0 else "➡️"
            # Процент изменения за последние 5 обновлений
            if len(history) >= 2:
                change_pct = (history[-1] - history[0]) / history[0] * 100
                change_str = f"{'+' if change_pct>=0 else ''}{change_pct:.1f}%"
            else:
                change_str = "—"
            # Текстовый график (5 свечей)
            candles = []
            for i in range(1, len(history)):
                if history[i] > history[i-1]:
                    candles.append("🟢")
                elif history[i] < history[i-1]:
                    candles.append("🔴")
                else:
                    candles.append("⚪")
            graph = "".join(candles[-5:]) if candles else "⚪⚪⚪⚪⚪"
            text += (f"{info['color']} <b>{asset}</b> {arrow} {change_str}\n"
                     f"💰 ${price:,.2f}\n"
                     f"{graph} {trend*100:+.1f}%\n"
                     f"⚡ Ставка: {info['min_bet']}–{info['max_bet']}₽\n\n")

    kb = []
    for asset in trading_prices.keys():
        kb.append([
            InlineKeyboardButton(text=f"🟢 {asset} ВВЕРХ", callback_data=f"trade_up_{asset}", style=ButtonStyle.SUCCESS),
            InlineKeyboardButton(text=f"🔴 {asset} ВНИЗ", callback_data=f"trade_down_{asset}", style=ButtonStyle.DANGER)
        ])
    kb.append([InlineKeyboardButton(text="💰 ПОРТФЕЛЬ", callback_data="trading_portfolio")])
    kb.append([InlineKeyboardButton(text="❓ ИНСТРУКЦИЯ", callback_data="trading_help")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])

    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "trading_portfolio")
async def trading_portfolio_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    
    # Получаем историю ставок игрока
    history = bet_history.get(user_id, [])
    total_bets = len(history)
    wins = sum(1 for bet in history if bet["result"] == "win")
    losses = total_bets - wins
    total_profit = sum(bet["profit"] for bet in history)
    
    if total_bets == 0:
        text = "📊 <b>ВАШ ПОРТФЕЛЬ</b>\n\nУ вас пока нет сделок.\n\n💡 Сделайте первую ставку в POCKET OPTION!"
    else:
        winrate = (wins / total_bets * 100) if total_bets > 0 else 0
        text = (f"📊 <b>ВАШ ПОРТФЕЛЬ</b>\n\n"
                f"📈 Всего сделок: {total_bets}\n"
                f"✅ Выигрышей: {wins}\n"
                f"❌ Проигрышей: {losses}\n"
                f"🏆 Процент побед: {winrate:.1f}%\n"
                f"💰 Общая прибыль: {total_profit:,}₽\n\n"
                f"📋 <b>Последние 5 ставок:</b>\n")
        for bet in history[-5:][::-1]:
            sign = "✅" if bet["result"] == "win" else "❌"
            text += f"{sign} {bet['asset']} {bet['direction']} {bet['bet']}₽ → {bet['profit']:+}₽\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 НОВАЯ СТАВКА", callback_data="trading_menu")],
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "trading_help")
async def trading_help_callback(callback: CallbackQuery):
    text = (
        "📚 <b>ИНСТРУКЦИЯ ПО ТРЕЙДИНГУ (POCKET OPTION)</b>\n\n"
        "🎯 <b>Как играть:</b>\n"
        "1. Выберите актив (BTC, ETH, SOL, DOGE)\n"
        "2. Нажмите ВВЕРХ (если думаете, что цена вырастет) или ВНИЗ (если упадёт)\n"
        "3. Введите сумму ставки (от 5 до 10 000 ₽ в зависимости от актива)\n"
        "4. Через 30 секунд бот покажет результат и выплатит выигрыш\n\n"
        "💰 <b>Выигрыш:</b>\n"
        "• При верном прогнозе вы получаете от 150% до 250% от ставки\n"
        "• Множитель выбирается случайно (1.5x – 2.5x)\n\n"
        "📈 <b>Реальные цены:</b>\n"
        "• Цены обновляются каждые 30 секунд с CoinGecko\n"
        "• Вы видите мини-график из 5 свечей и процент изменения\n\n"
        "📊 <b>Статистика:</b>\n"
        "• В разделе «ПОРТФЕЛЬ» хранятся все ваши сделки\n"
        "• Вы увидите процент побед и общую прибыль\n\n"
        "💡 <b>Совет:</b> Следите за трендом (стрелка 📈/📉) – он помогает предугадать движение!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 К ТРЕЙДИНГУ", callback_data="trading_menu")],
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

# ---------- ТРЕЙДИНГ (используем waiting_for_trade_amount) ----------
@dp.callback_query(lambda c: c.data.startswith("trade_up_") or c.data.startswith("trade_down_"))
async def trade_bet_callback(callback: CallbackQuery, state: FSMContext):
    direction = "up" if "up" in callback.data else "down"
    asset = callback.data.split("_")[2]
    await state.update_data(trade_asset=asset, trade_direction=direction)
    await state.set_state(Form.waiting_for_trade_amount)   # <-- ИЗМЕНЕНО
    await callback.message.answer(f"💵 Введите сумму ставки для {asset} ({direction}):\nМин: {TRADING_ASSETS[asset]['min_bet']}₽, Макс: {TRADING_ASSETS[asset]['max_bet']}₽")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_trade_amount))   # <-- ИЗМЕНЕНО
async def handle_trade_bet(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        amount = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    asset = data.get("trade_asset")
    direction = data.get("trade_direction")
    if not asset or not direction:
        await message.answer("❌ Ошибка, начните заново.")
        await state.clear()
        return

    asset_info = TRADING_ASSETS.get(asset)
    if not asset_info:
        await message.answer("❌ Актив не найден.")
        await state.clear()
        return

    if amount < asset_info["min_bet"] or amount > asset_info["max_bet"]:
        await message.answer(f"❌ Ставка должна быть от {asset_info['min_bet']} до {asset_info['max_bet']}₽")
        return

    player_id = await get_player_id_by_tg(user_id)
    player = await run_sync_db(get_player_data, player_id)
    if not player or player.get("balance", 0) < amount:
        await message.answer("❌ Недостаточно средств!")
        await state.clear()
        return

    async with trading_lock:
        if asset not in trading_prices:
            await message.answer("❌ Цены ещё не загружены, попробуйте позже.")
            await state.clear()
            return
        start_price = trading_prices[asset]["price"]

    async with db_lock:
        await run_sync_db(update_player_data, player_id, {"balance": player["balance"] - amount})

    bet_id = f"{user_id}_{int(time_module.time()*1000)}"
    active_bets[bet_id] = {
        "user_id": user_id,
        "asset": asset,
        "direction": direction,
        "amount": amount,
        "start_price": start_price,
        "start_time": time_module.time()
    }

    await message.answer(f"⏳ Ставка {amount}₽ на {asset} {direction} принята!\n💰 Фиксированная цена: ${start_price:.2f}\nРезультат через 30 секунд.")
    await state.clear()
    asyncio.create_task(check_bet_result(bet_id))

async def check_bet_result(bet_id: str):
    await asyncio.sleep(30)
    bet = active_bets.pop(bet_id, None)
    if not bet:
        return

    user_id = bet["user_id"]
    asset = bet["asset"]
    direction = bet["direction"]
    amount = bet["amount"]
    start_price = bet["start_price"]

    async with trading_lock:
        if asset not in trading_prices:
            return
        current_price = trading_prices[asset]["price"]

    if direction == "up":
        win = current_price > start_price
    else:
        win = current_price < start_price

    multiplier = random.uniform(1.5, 2.5) if win else 0
    profit = int(amount * multiplier) if win else -amount

    player_id = await get_player_id_by_tg(user_id)
    if win and player_id:
        profit = boost_referral_income(profit, player_id)
    if player_id:
        async with db_lock:
            player = await run_sync_db(get_player_data, player_id)
            if player:
                new_balance = player["balance"] + (amount + profit if win else -amount)
                await run_sync_db(update_player_data, player_id, {"balance": new_balance})

    bet_history[user_id].append({
        "asset": asset,
        "direction": "вверх" if direction == "up" else "вниз",
        "bet": amount,
        "result": "win" if win else "loss",
        "profit": profit,
        "time": time_module.time()
    })

    if win:
        await bot.send_message(user_id, f"✅ ВЫИГРЫШ! Ставка {amount}₽ на {asset}.\n💰 Выигрыш: {amount + profit}₽ (+{profit}₽)")
        if player_id:
            await run_sync_db(update_daily_quest, player_id, "trade_win", 1)
    else:
        await bot.send_message(user_id, f"❌ ПРОИГРЫШ! Ставка {amount}₽ на {asset}.\n💸 Потеряно: {amount}₽")

# ---------- РАЗБОР ПОСТАВКИ (МИНИ-ИГРЫ) ----------
@dp.callback_query(lambda c: c.data == "minigames_menu")
async def minigames_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    casino_url = f"{URL_CASINO}?userId={user_id}"
    racing_url = f"{BASE_WEBAPP_URL}racing.html?userId={user_id}"   # ← новая ссылка
    text = "🎮 <b>МИНИ-ИГРЫ</b>\n\nВыберите игру:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 РАЗОБРАТЬ ПОСТАВКУ", callback_data="start_supply")],
        [InlineKeyboardButton(text="🏎 ГОНКИ", web_app=WebAppInfo(url=racing_url))],  # ← заменено
        [InlineKeyboardButton(text="🎰 КАЗИНО", web_app=WebAppInfo(url=casino_url))],
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "start_supply")
async def start_supply_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "start_supply")
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(f"📦 <b>ПОСТАВКА КУПЛЕНА!</b>\n{r.get('message')}\n\n<i>Нажми на кнопку, чтобы разбирать коробку</i>", parse_mode="HTML",
                                         reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 РАЗОБРАТЬ (10 кликов)", callback_data="supply_click")], [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data == "supply_click")
async def supply_click_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "supply_click")
    if not r.get("success"):
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)
        return
    if r.get("finished"):
        found = r.get("found", [])
        text = f"📦 <b>ПОСТАВКА РАЗОБРАНА!</b>\n\n🎁 Найдено {len(found)} вещей:\n" + "\n".join(f"• {it.get('name')} (~{it.get('market_price')}₽)" for it in found)
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
    else:
        remaining = r.get("remaining", 0)
        found_item = r.get("found_item")
        found_count = r.get("found_count", 0)
        msg = f"🔍 Кликов осталось: {remaining}\n🎁 Найдено вещей: {found_count}\n"
        if found_item:
            msg += f"✅ Найден {found_item.get('name')}!"
        else:
            msg += "❌ Ничего..."
        await safe_delete_message(callback.message)
        await callback.message.answer(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"📦 РАЗОБРАТЬ (ещё {remaining})", callback_data="supply_click")], [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)

# ---------- ГОНКИ ----------
@dp.callback_query(lambda c: c.data == "race_menu")
async def race_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_races")
    races = r.get("races", []) if r.get("success") else []
    text = "🏎 <b>ГОНКИ</b>\n\nТвои гонки:\n"
    my = [rc for rc in races if rc.get("creator") == user_id or rc.get("opponent") == user_id]
    if my:
        for rc in my:
            text += f"🏎 Ставка: {rc.get('bet')}₽ | Статус: {rc.get('status')}\n"
    else:
        text += "Нет активных гонок\n"
    kb = [[InlineKeyboardButton(text="🏎 СОЗДАТЬ ГОНКУ", callback_data="race_create")]]
    for rc in races:
        if rc.get("status") == "wait" and rc.get("creator") != user_id:
            kb.append([InlineKeyboardButton(text=f"🏎 Ставка {rc.get('bet')}₽", callback_data=f"race_join_{rc.get('id')}")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "race_create")
async def race_create_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    cars = await api_call(user_id, "get_car_collection")
    cars_list = cars.get("cars", []) if cars.get("success") else []
    if not cars_list:
        await safe_callback_answer(callback, "Нет машин в гараже!", show_alert=True)
        return
    text = "🏎 <b>ВЫБЕРИ МАШИНУ И СТАВКУ</b>\n\n"
    kb = []
    for car in cars_list:
        kb.append([InlineKeyboardButton(text=f"{car.get('name')} — ставка 5 000₽", callback_data=f"race_start_{car.get('id')}_5000")])
        kb.append([InlineKeyboardButton(text=f"{car.get('name')} — ставка 25 000₽", callback_data=f"race_start_{car.get('id')}_25000")])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="race_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("race_start_"))
async def race_start_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    parts = callback.data.split("_")
    car_id = parts[2]
    bet = int(parts[3])
    r = await api_call(user_id, "create_race", {"car_id": car_id, "bet": bet})
    if r.get("success"):
        race_id = r.get("race_id")
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"🏎 <b>ГОНКА СОЗДАНА!</b>\nID: {race_id}\nСтавка: {bet}₽\n\nОтправь другу: /race join {race_id}",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

@dp.callback_query(lambda c: c.data.startswith("race_join_"))
async def race_join_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    race_id = callback.data.replace("race_join_", "")
    cars = await api_call(user_id, "get_car_collection")
    cars_list = cars.get("cars", []) if cars.get("success") else []
    if not cars_list:
        await safe_callback_answer(callback, "Нет машин в гараже!", show_alert=True)
        return
    text = "🏎 <b>ВЫБЕРИ МАШИНУ ДЛЯ УЧАСТИЯ</b>\n\n"
    kb = []
    for car in cars_list:
        kb.append([InlineKeyboardButton(text=f"{car.get('name')}", callback_data=f"race_confirm_{race_id}|{car.get('id')}")])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="race_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("race_confirm_"))
async def race_confirm_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data.replace("race_confirm_", "")
    race_id, car_id = data.split("|")
    r = await api_call(user_id, "join_race", {"race_id": race_id, "car_id": car_id})
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(f"✅ {r.get('message')}", parse_mode="HTML")
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("chat_answer;") or c.data.startswith("chat_custom;") or c.data.startswith("chat_sell;") or c.data.startswith("chat_choice;"))
async def chat_answer_callback(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        await safe_callback_answer(callback, "Вы не зарегистрированы. Напишите /start", show_alert=True)
        return

    parts = callback.data.split(";")
    action = parts[0]
    chat_key = parts[1]
    choice_idx = _safe_int(parts[3],1) if len(parts)>3 else 1
    
    if chat_key not in active_chats:
        await safe_callback_answer(callback, "Чат не найден", show_alert=True)
        return
    chat = active_chats[chat_key]

    if chat.get("finished"):
        await safe_callback_answer(callback, "Диалог уже завершён", show_alert=True)
        return
    if chat["user_id"] != player_id:
        await safe_callback_answer(callback, "Это не ваш чат", show_alert=True)
        return

    player = await run_sync_db(get_player_data, player_id)
    if not player:
        await safe_callback_answer(callback, "Ошибка игрока", show_alert=True)
        return

    await safe_delete_message(callback.message)

    # ====== НОВЫЙ ВАРИАНТ: выбор цены с риском ======
    if action == "chat_choice":
        chosen_price = int(parts[2])
        risk = int(parts[3])
        # Определяем, согласен ли клиент
        if random.randint(1, 100) > risk:
            # Клиент согласен
            client = CLIENT_TYPES[chat["client_type"]]
            answer=chat.get("dialogue",{}).get("final_agree") or random.choice(client["phrases"].get("agree",["Хорошо, беру!"]))
            if isinstance(answer,list): answer=random.choice(answer)
            answer=answer.replace("{price}",f"{chosen_price:,}")
            await callback.message.answer(f"👤 Покупатель: {answer}")
            chat["offer"] = chosen_price
            await complete_sale_universal(chat, player_id, callback=callback)
        else:
            # Клиент отказался
            client = CLIENT_TYPES[chat["client_type"]]
            answer=chat.get("dialogue",{}).get("final_decline") or random.choice(client["phrases"].get("decline",["Дорого, не буду брать."]))
            if isinstance(answer,list): answer=random.choice(answer)
            await callback.message.answer(f"👤 Покупатель: {answer}")
            chat["finished"] = True
            # Очистка чата из памяти
            async with chats_lock:
                if chat_key in active_chats:
                    del active_chats[chat_key]
            await callback.message.answer("❌ Сделка не состоялась. Покупатель ушёл.")
        await safe_callback_answer(callback)
        return

    # ====== ОБЫЧНЫЙ ОТВЕТ (для фаз 1-4) ======
    if action == "custom":
        await state.update_data(chat_key=chat_key)
        await state.set_state(Form.waiting_for_chat_price)
        await callback.message.answer("✍️ Введите вашу цену (только число):")
        await safe_callback_answer(callback)
        return

    # Для ответов на фазах 1-4
    old_phase=int(chat.get("phase",1)); chat["round"]=int(chat.get("round",1))+1; chat["trust"]=min(100,int(chat.get("trust",50))+({0:10,1:8,2:5}.get(choice_idx,5)))

    # Проверяем, достаточно ли раундов для перехода к финальному торгу (фаза 5)
    if chat["round"] >= 3:
        # Переходим к финальной фазе (предложение цены)
        chat["phase"] = 5
        client = CLIENT_TYPES[chat["client_type"]]
        # Случайная фраза от клиента о готовности торговаться
        wait_phrase=chat.get("dialogue",{}).get("final_prompt") or random.choice(client["phrases"].get("wait",["Давайте обсудим цену."]))
        await callback.message.answer(f"👤 Покупатель: {wait_phrase}")
        kb = get_chat_keyboard(chat)
        await callback.message.answer("💰 Выберите вариант цены (риск отказа указан в %):", reply_markup=kb)
        await safe_callback_answer(callback)
        return
    else:
        # Переход к следующей фазе (1->2->3->4)
        new_phase = old_phase + 1 if old_phase < 4 else 4
        chat["phase"] = new_phase
        client = CLIENT_TYPES[chat["client_type"]]
        dialogue=chat.get("dialogue") or {}
        if new_phase<=4 and len(dialogue.get("phases",[]))>=new_phase:
            client_msg=dialogue["phases"][new_phase-1].format(item=chat["item"],price=f"{chat['price']:,}",offer=f"{chat['offer']:,}")
        else:
            phase_key=["greet","state_reaction","delivery_reaction","reason_reaction"][new_phase-1] if new_phase<=4 else "wait"
            client_msg=random.choice(client["phrases"].get(phase_key,["Продолжим."])).replace("{price}",str(chat["price"])).replace("{offer}",str(chat["offer"])).replace("{item}",chat["item"])
        await callback.message.answer(f"👤 Покупатель: {client_msg}")
        kb = get_chat_keyboard(chat)
        await callback.message.answer("Выберите ответ:", reply_markup=kb)
        await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "settings_menu")
async def settings_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    nick = await get_nickname(user_id)
    shop = await get_shop_name(user_id)
    text = f"⚙️ <b>НАСТРОЙКИ</b>\n\n👤 Ник: {nick}\n🏪 Магазин: {shop}\n\nВыберите действие:"
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=make_settings_kb())
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "change_nickname")
async def change_nickname_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_nickname)
    await callback.message.answer("✍️ Введите новый никнейм (2-20 символов):")
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "change_shopname")
async def change_shopname_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_shopname)
    await callback.message.answer("✍️ Введите новое название магазина (2-30 символов):")
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "notifications_settings")
async def notifications_settings_callback(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.waiting_for_notifications)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ВКЛЮЧИТЬ", callback_data="notif_on")],
        [InlineKeyboardButton(text="❌ ВЫКЛЮЧИТЬ", callback_data="notif_off")],
        [InlineKeyboardButton(text="🔙 НАЗАД", callback_data="settings_menu")]
    ])
    await callback.message.answer("🔔 Настройка уведомлений\n\nВключить уведомления о сделках и событиях?", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data in ("notif_on", "notif_off"))
async def set_notifications(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    enabled = callback.data == "notif_on"
    player_id = await get_player_id_by_tg(user_id)
    if player_id:
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"notifications": 1 if enabled else 0})
    await callback.message.answer(f"🔔 Уведомления {'включены' if enabled else 'выключены'}.")
    await state.clear()
    # Возвращаем в меню настроек
    await settings_menu_callback(callback)   # без передачи state
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_nickname))
async def process_nickname_change(message: Message, state: FSMContext):
    user_id = message.from_user.id
    nickname = message.text.strip()
    if len(nickname) < 2 or len(nickname) > 20:
        await message.answer("❌ Никнейм должен быть от 2 до 20 символов.")
        return
    r = await api_call(user_id, "set_nickname", {"nickname": nickname})
    if r.get("success"):
        await message.answer(f"✅ {r.get('message')}", parse_mode="HTML")
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка')}")
    await state.clear()

@dp.message(StateFilter(Form.waiting_for_shopname))
async def process_shopname_change(message: Message, state: FSMContext):
    user_id = message.from_user.id
    shopname = message.text.strip()
    if len(shopname) < 2 or len(shopname) > 30:
        await message.answer("❌ Название магазина должно быть от 2 до 30 символов.")
        return
    r = await api_call(user_id, "set_shop_name", {"name": shopname})
    if r.get("success"):
        await message.answer(f"✅ {r.get('message')}", parse_mode="HTML")
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка')}")
    await state.clear()

def _complete_avito_sale_sync(player_id: int, chat: dict, boosted_profit: int):
    """Атомарно завершает продажу и удаляет ровно один экземпляр из inventory.

    Важно: раньше удаление товара и начисление денег выполнялись через несколько
    отдельных операций. При старых/дублированных inventory это позволяло получить
    деньги, но оставить товар в складе. Здесь оба изменения находятся в одной
    SQLite-транзакции.
    """
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
        if not row:
            conn.rollback(); return {"success": False, "message": "❌ Игрок не найден."}
        player = dict(row)
        raw_inv = player.get("inventory", "[]")
        try:
            inventory = json.loads(raw_inv) if isinstance(raw_inv, str) else (raw_inv or [])
        except Exception:
            inventory = []
        if not isinstance(inventory, list): inventory = []

        item_obj = chat.get("item_obj") or {}
        target_uid = str(chat.get("item_uid") or item_obj.get("uid") or "")
        sold_idx = None
        sold_item = None
        if target_uid:
            for i, inv in enumerate(inventory):
                if isinstance(inv, dict) and str(inv.get("uid") or "") == target_uid:
                    sold_idx, sold_item = i, dict(inv); break
        if sold_item is None and item_obj:
            # Совместимость со старыми чатами, созданными до UID.
            target_name = str(item_obj.get("name") or chat.get("item") or "")
            target_buy = int(item_obj.get("buy_price", -1) or -1)
            for i, inv in enumerate(inventory):
                if not isinstance(inv, dict) or str(inv.get("name") or "") != target_name: continue
                if target_buy >= 0 and int(inv.get("buy_price", -2) or -2) != target_buy: continue
                sold_idx, sold_item = i, dict(inv); break
        if sold_item is None:
            conn.rollback(); return {"success": False, "message": "❌ Товар не найден в инвентаре."}

        inventory.pop(sold_idx)
        final_price = max(1, int(chat.get("offer", 0) or 0))
        buy_price = max(0, int(sold_item.get("buy_price", 0) or 0))
        raw_profit = final_price - buy_price
        total_sales = int(player.get("total_sales", 0) or 0) + 1
        total_profit = int(player.get("total_profit", 0) or 0) + int(boosted_profit)
        new_balance = int(player.get("balance", 0) or 0) + final_price + max(0, int(boosted_profit) - raw_profit)
        new_total_earned = int(player.get("total_earned", 0) or 0) + int(boosted_profit)
        stat_earned_today = int(player.get("stat_earned_today", 0) or 0) + int(boosted_profit)
        stat_sold_today = int(player.get("stat_sold_today", 0) or 0) + 1

        cur.execute("""UPDATE players SET balance=?, inventory=?, total_sales=?, total_profit=?,
                       total_earned=?, items_sold=?, stat_earned_today=?, stat_sold_today=? WHERE id=?""",
                    (new_balance, json.dumps(inventory, ensure_ascii=False), total_sales, total_profit,
                     new_total_earned, total_sales, stat_earned_today, stat_sold_today, player_id))
        if cur.rowcount != 1:
            conn.rollback(); return {"success": False, "message": "❌ Не удалось сохранить склад."}
        conn.commit()
        return {"success": True, "final_price": final_price, "raw_profit": raw_profit,
                "profit": int(boosted_profit), "balance": new_balance, "total_sales": total_sales,
                "sold_item": sold_item}
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()

async def complete_sale_universal(
    chat: dict,
    player_id: int,
    callback: Optional[CallbackQuery] = None,
    message: Optional[Message] = None
):
    final_price = 0
    profit = 0
    need_error = False
    error_msg = ""

    player = await run_sync_db(get_player_data, player_id)
    if not player:
        need_error = True
        error_msg = "❌ Игрок не найден."
    else:
        final_price = max(1, int(chat.get("offer", 0) or 0))
        item_obj = chat.get("item_obj") or {}
        buy_price = max(0, int(item_obj.get("buy_price", 0) or 0))
        raw_profit = final_price - buy_price
        # Реферальный X-boost распространяется и на прибыль от продаж Avito.
        profit = boost_referral_income(raw_profit, player_id) if raw_profit > 0 else raw_profit
        sale = await run_sync_db(_complete_avito_sale_sync, player_id, chat, profit)
        if not sale.get("success"):
            need_error = True
            error_msg = sale.get("message", "❌ Не удалось завершить сделку.")
        else:
            final_price = int(sale["final_price"])
            profit = int(sale["profit"])
            total_sales = int(sale["total_sales"])
            new_total_earned = int((await run_sync_db(get_player_data, player_id) or {}).get("total_earned", 0) or 0)
            await run_sync_db(add_sale_record, player_id, chat.get("buyer_id", 0), sale["sold_item"].get("name", chat.get("item", "Товар")), final_price)
            await run_sync_db(check_and_update_achievement, player_id, "millionaire", new_total_earned)
            await run_sync_db(check_and_update_achievement, player_id, "seller", total_sales)
            await run_sync_db(update_daily_quest, player_id, "sell_3", 1)
            await run_sync_db(update_daily_quest, player_id, "earn_50k", profit)
            chat["finished"] = True
            need_error = False

    # ----- ОЧИСТКА ПАМЯТИ (удаляем чат и опубликованный товар) -----
    if not need_error:
        chat_key = chat['chat_key']
        async with chats_lock:
            if chat_key in active_chats:
                del active_chats[chat_key]
        async with published_lock:
            if player_id in published_items:
                del published_items[player_id]

    # ----- ОТВЕТ ПОЛЬЗОВАТЕЛЮ -----
    msg_text = error_msg if need_error else f"🎉 ПРОДАНО! Получено {final_price}₽, прибыль {profit}₽"
    menu_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В МЕНЮ", callback_data="back_to_menu")]
    ])

    if callback:
        await callback.message.answer(msg_text, parse_mode="HTML", reply_markup=menu_kb)
        if not need_error:
            await safe_callback_answer(callback)
    elif message:
        await message.answer(msg_text, parse_mode="HTML", reply_markup=menu_kb)
    else:
        pass
    return {"success": not need_error, "message": msg_text, "final_price": int(final_price), "profit": int(profit)}

    # ----- ОЧИСТКА ПАМЯТИ (удаляем чат и опубликованный товар) -----
    if not need_error:
        chat_key = chat['chat_key']
        async with chats_lock:
            if chat_key in active_chats:
                del active_chats[chat_key]
        async with published_lock:
            if player_id in published_items:
                del published_items[player_id]

    # ----- ОТВЕТ ПОЛЬЗОВАТЕЛЮ -----
    msg_text = error_msg if need_error else f"🎉 ПРОДАНО! Получено {final_price}₽, прибыль {profit}₽"
    menu_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 В МЕНЮ", callback_data="back_to_menu")]
    ])

    if callback:
        await callback.message.answer(msg_text, parse_mode="HTML", reply_markup=menu_kb)
        if not need_error:
            await safe_callback_answer(callback)
    elif message:
        await message.answer(msg_text, parse_mode="HTML", reply_markup=menu_kb)
    else:
        # Веб-продажи больше не дублируем отдельным сообщением в Telegram-боте.
        # Frontend показывает собственный toast/звук непосредственно в Mini App.
        pass
    return {"success": not need_error, "message": msg_text, "final_price": int(final_price), "profit": int(profit)}

# ---------- АУКЦИОН ----------
@dp.callback_query(lambda c: c.data == "auction_menu")
async def auction_menu_callback(callback: CallbackQuery):
    tg_id=callback.from_user.id; my_pid=await get_player_id_by_tg(tg_id); r=await api_call(tg_id,"get_auction_items"); items=r.get("auction_items",[]) if r.get("success") else []
    if not items:
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📤 ВЫСТАВИТЬ",callback_data="auction_sell")],[InlineKeyboardButton(text="🔙 В МЕНЮ",callback_data="back_to_menu")]])
        await safe_delete_message(callback.message); await callback.message.answer("🔨 <b>АУКЦИОН</b>\n\nНет активных лотов.",parse_mode="HTML",reply_markup=kb); await safe_callback_answer(callback); return
    text="🔨 <b>АУКЦИОН</b>\n<i>Все лоты привязаны к уникальному ID — ставка не может уйти в соседний лот.</i>\n\n"; kb=[]
    for it in items:
        tl=max(0,int(it.get("end_time",0)-time_module.time())); h,rem=divmod(tl,3600); m=rem//60; current=int(it.get("current_bid",0)); lid=it.get("lot_id",it.get("id")); mine=(my_pid is not None and it.get("seller_id")==my_pid);
        min_bid=current if not it.get("bidder_id") else int(current*1.1)
        text+=f"📦 <b>Лот #{lid}</b> · {it.get('item',{}).get('name','?')}\n💰 {current:,}₽ · ⏳ {h}ч {m}м\n"
        if mine: text+="👤 <i>Ваш лот</i>\n\n"
        else:
            text+="\n"; kb.append([InlineKeyboardButton(text=f"💰 СТАВИТЬ · от {min_bid:,}₽",callback_data=f"auction_bid_{lid}",style=ButtonStyle.SUCCESS)])
    kb += [[InlineKeyboardButton(text="📤 ВЫСТАВИТЬ",callback_data="auction_sell",style=ButtonStyle.PRIMARY)],[InlineKeyboardButton(text="🔙 В МЕНЮ",callback_data="back_to_menu")]]
    await safe_delete_message(callback.message); await callback.message.answer(text,parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "auction_sell")
async def auction_sell_menu(callback: CallbackQuery):
    user_id=callback.from_user.id; inv_res=await api_call(user_id,"get_inventory"); inv=inv_res.get("inventory",[]) if inv_res.get("success") else []
    if not inv: await safe_callback_answer(callback,"Нет товаров для выставления",show_alert=True); return
    kb=[]
    for it in inv:
        token=it.get("uid"); kb.append([InlineKeyboardButton(text=f"📦 {str(it.get('name'))[:28]} · {int(it.get('market_price',0)):,}₽",callback_data=f"auction_sell_item_{token}",style=ButtonStyle.PRIMARY)])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД",callback_data="auction_menu")]); await safe_delete_message(callback.message); await callback.message.answer("📤 <b>ВЫСТАВЛЕНИЕ ТОВАРА</b>\n\nВыбери конкретный экземпляр:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("auction_sell_item_"))
async def auction_sell_item(callback: CallbackQuery,state:FSMContext):
    token=callback.data.split("_",3)[3]; await state.update_data(auction_item_uid=token); await state.set_state(Form.waiting_for_auction_price); await callback.message.answer("✍️ Введи начальную цену для лота (0 = 75% от текущей рыночной цены):"); await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_auction_price))
async def handle_auction_price(message:Message,state:FSMContext):
    try: price=int(message.text.strip())
    except Exception: await message.answer("❌ Введи целое число."); return
    if price<0: await message.answer("❌ Цена не может быть отрицательной."); return
    data=await state.get_data(); token=data.get("auction_item_uid")
    r=await api_call(message.from_user.id,"add_auction_item",{"item_type":"inventory","item_uid":token,"start_price":price})
    await message.answer(("✅ Лот выставлен на аукцион!" if r.get("success") else f"❌ {r.get('message','Ошибка')}"),reply_markup=menu_kb() if r.get("success") else None); await state.clear()

@dp.callback_query(lambda c: c.data.startswith("auction_bid_"))
async def auction_bid_callback(callback:CallbackQuery,state:FSMContext):
    token=callback.data.split("_",2)[2]; await state.update_data(auction_lot_id=token); await state.set_state(Form.waiting_for_auction_bid); await callback.message.answer("✍️ Введи сумму ставки. Если другой игрок уже поставил, нужно минимум +10%."); await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_auction_bid))
async def handle_auction_bid(message:Message,state:FSMContext):
    try: bid=int(message.text.strip())
    except Exception: await message.answer("❌ Введи число."); return
    if bid<=0: await message.answer("❌ Ставка должна быть больше 0."); return
    data=await state.get_data(); lot_id=data.get("auction_lot_id")
    r=await api_call(message.from_user.id,"bid_auction",{"lot_id":lot_id,"bid":bid})
    if r.get("success"): await message.answer(f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance',0):,}₽",parse_mode="HTML")
    else: await message.answer(f"❌ {r.get('message','Ошибка')}")
    await state.clear()

@dp.callback_query(lambda c: c.data == "friends_menu")
async def friends_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_friends")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    friends_ids = r.get("friends", [])
    if not friends_ids:
        text = "👥 <b>ДРУЗЬЯ</b>\n\nУ тебя пока нет друзей!\n\nДобавить друга:\n<code>/friend add ник</code>"
        kb = [[InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await safe_callback_answer(callback)
        return
    text = f"👥 <b>ТВОИ ДРУЗЬЯ ({len(friends_ids)}):</b>\n\n"
    kb = []
    for fid in friends_ids:
        friend_player = await run_sync_db(get_player_data, fid)
        if friend_player:
            friend_nick = friend_player.get("nickname", f"ID:{fid}")
            text += f"• {friend_nick}\n"
            kb.append([InlineKeyboardButton(text=f"👤 {friend_nick}", callback_data=f"view_friend_{fid}")])
        else:
            text += f"• ID:{fid}\n"
            kb.append([InlineKeyboardButton(text=f"👤 ID:{fid}", callback_data=f"view_friend_{fid}")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("view_friend_"))
async def view_friend_callback(callback: CallbackQuery):
    friend_id = int(callback.data.split("_")[2])
    r = await api_call(callback.from_user.id, "get_player_profile", {"player_id": friend_id})
    if r.get("success"):
        text = r.get("profile")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💸 ПЕРЕВЕСТИ", callback_data=f"transfer_to_friend_{friend_id}")],
            [InlineKeyboardButton(text="🔙 К ДРУЗЬЯМ", callback_data="friends_menu")],
            [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
        ])
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("transfer_to_friend_"))
async def transfer_to_friend_callback(callback: CallbackQuery, state: FSMContext):
    friend_id = int(callback.data.split("_")[3])
    await state.update_data(transfer_friend_id=friend_id)
    await state.set_state(Form.waiting_for_transfer_to_friend)
    await callback.message.answer("💸 Введите сумму перевода (мин. 100₽):")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_transfer_to_friend))
async def handle_transfer_to_friend(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        amount = int(message.text.strip())
        if amount < 100:
            raise ValueError
    except:
        await message.answer("❌ Введите целое число не менее 100.")
        return
    
    data = await state.get_data()
    friend_player_id = data.get("transfer_friend_id")
    if not friend_player_id:
        await message.answer("❌ Ошибка: получатель не найден.")
        await state.clear()
        return
    
    # Получаем tg_id получателя
    def get_tg_id(player_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT tg_id FROM players WHERE id = ?", (player_id,))
        row = cursor.fetchone()
        conn.close()
        return row['tg_id'] if row else None
    
    target_tg_id = await run_sync_db(get_tg_id, friend_player_id)
    if not target_tg_id:
        await message.answer("❌ Получатель не зарегистрирован в игре.")
        await state.clear()
        return
    
    # Выполняем перевод через API
    r = await api_call(user_id, "transfer", {"to_player_id": friend_player_id, "amount": amount})
    if r.get("success"):
        await message.answer(
            f"✅ {r.get('message')}\n💰 Ваш баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка перевода')}")
    await state.clear()

# ---------- РЕФЕРАЛЫ ----------
@dp.callback_query(lambda c: c.data == "referral_menu")
async def referral_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_referral_data")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    invited = r.get("invited", [])
    count = r.get("count", 0)
    total_bonus = count * 10000
    text = (f"🔗 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
            f"Твоя ссылка:\n<code>https://t.me/{BOT_USERNAME}?start=ref_{user_id}</code>\n\n"
            f"👥 Приглашено: {count} чел.\n"
            f"💰 Заработано: {total_bonus:,}₽\n"
            f"⭐ Бонус: +5 репутации за друга\n\n"
            f"<b>🎁 Награды:</b>\n"
            f"• Ты получаешь <b>80 000₽</b> за каждого друга\n"
            f"• Друг получает <b>50 000₽</b> стартового бонуса")
    kb = [
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ]
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "claim_referral_bonus")
async def claim_referral_bonus_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "claim_referral_bonus")
    if r.get("success"):
        await safe_delete_message(callback.message)
        await callback.message.answer(
            f"✅ {r.get('message')}\n💰 Баланс: {r.get('balance', 0):,}₽",
            parse_mode="HTML",
            reply_markup=menu_kb()
        )
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

# ---------- ОБУЧЕНИЕ ----------
@dp.callback_query(lambda c: c.data == "learning_menu")
async def learning_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_learning")
    completed = r.get("completed", []) if r.get("success") else []
    
    lessons = [
        {"id": 1, "title": "📖 Как покупать товары", "reward": 500, "text": "Зайди в ЗАКУП и купи любой товар у поставщика."},
        {"id": 2, "title": "📖 Как продавать товары", "reward": 500, "text": "Опубликуй товар из инвентаря и ответь покупателю."},
        {"id": 3, "title": "📖 Пассивный доход", "reward": 1000, "text": "Купи магазин, машину или таксопарк."},
        {"id": 4, "title": "📖 Гонки", "reward": 500, "text": "Создай или присоединись к гонке в мини-играх."},
        {"id": 5, "title": "📖 Трейдинг", "reward": 500, "text": "Сделай ставку в POCKET OPTION."},
        {"id": 6, "title": "🧠 Психология продаж", "reward": 1000, "text": "Покупатель принимает решение эмоционально. Создавай дефицит, используй срочность ('только сегодня'), показывай выгоду. Не бойся торговаться, но знай свою минимальную цену."},
        {"id": 7, "title": "💼 Техника «Дверь в лицо»", "reward": 1000, "text": "Проси больше, чем хочешь получить – затем уступай. Покупатель чувствует, что выиграл, и охотнее соглашается на реальную цену."},
        {"id": 8, "title": "📈 Анализ спроса", "reward": 1000, "text": "Следи за трендами (погода, сезон, новости). В игре это отражается в разделе «Спрос». Покупай товары с растущим спросом – продашь дороже."},
    ]
    
    text = "📚 <b>ОБУЧЕНИЕ</b>\n\n"
    kb = []
    for lesson in lessons:
        if lesson["id"] in completed:
            btn_text = f"✅ {lesson['title']} (пройден)"
        else:
            btn_text = f"📖 {lesson['title']} (+{lesson['reward']}₽)"
        kb.append([InlineKeyboardButton(text=btn_text, callback_data=f"start_lesson_{lesson['id']}")])
    
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("start_lesson_"))
async def start_lesson_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lesson_id = int(callback.data.split("_")[2])
    
    lessons_content = {
        1: "1. Нажми кнопку 🏭 ЗАКУП\n2. Выбери товар\n3. Нажми КУПИТЬ\n\nТовар появится в инвентаре!",
        2: "1. Открой 📦 ИНВЕНТАРЬ\n2. Нажми ОПУБЛИКОВАТЬ\n3. Напиши описание\n4. Общайся с покупателем в 💬 ЧАТЫ\n5. Продай и получи деньги!",
        3: "🏠 Недвижимость – доход каждый день\n🏪 Магазин – доход каждый час\n🚗 Машина – доход каждый час\n🚕 Таксопарк – доход каждый час\n\nЧем дороже имущество, тем больше доход!",
        4: "1. Зайди в 🎮 МИНИ-ИГРЫ → 🏎 ГОНКИ\n2. Создай гонку или присоединись\n3. Выбирай действия: газ, нитро\n4. Победитель забирает банк!",
        5: "1. Зайди в 🎮 МИНИ-ИГРЫ → 📊 ТРЕЙДИНГ\n2. Выбери актив (BTC, ETH, SOL, DOGE)\n3. Поставь на ВВЕРХ или ВНИЗ\n4. Если угадаешь направление – выиграешь до 250%!",
    }
    
    r = await api_call(user_id, "get_learning")
    completed = r.get("completed", []) if r.get("success") else []
    if lesson_id in completed:
        await safe_callback_answer(callback, "Урок уже пройден!", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПОЛУЧИТЬ НАГРАДУ", callback_data=f"claim_lesson_{lesson_id}")],
        [InlineKeyboardButton(text="🔙 К УРОКАМ", callback_data="learning_menu")]
    ])
    await callback.message.answer(f"📖 <b>Урок {lesson_id}</b>\n\n{lessons_content.get(lesson_id, 'Изучи материал.')}", parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("claim_lesson_"))
async def claim_lesson_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    lesson_id = int(callback.data.split("_")[2])
    rewards = {1: 500, 2: 500, 3: 1000, 4: 500, 5: 500, 6: 1000, 7: 1000, 8: 1000}
    reward = rewards.get(lesson_id, 500)
    r = await api_call(user_id, "complete_lesson", {"lesson_id": lesson_id, "reward": reward})
    if r.get("success"):
        await callback.message.edit_text(
            f"✅ Урок {lesson_id} пройден! Получено {reward}₽.",
            parse_mode="HTML",
            reply_markup=None
        )
        await callback.message.answer("🎉 Поздравляем! Продолжайте обучение или перейдите в меню.", reply_markup=menu_kb())
        await safe_callback_answer(callback)
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)

# ---------- ЛИДЕРБОРД ----------
@dp.callback_query(lambda c: c.data == "leaderboard_menu")
async def leaderboard_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_leaderboard_wealth")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    top = r.get("leaderboard", [])
    if not top:
        text = "🏆 <b>РЕЙТИНГ БОГАТСТВА (ФОРБС)</b>\n\nПока нет данных."
    else:
        text = "🏆 <b>РЕЙТИНГ БОГАТСТВА (ФОРБС)</b>\n\n"
        for i, p in enumerate(top, 1):
            medal = ""
            if i == 1:
                medal = "👑 "
            elif i == 2:
                medal = "🥈 "
            elif i == 3:
                medal = "🥉 "
            text += f"{medal}{i}. {p['nickname']}\n"
            text += f"   💰 Состояние: {p['wealth']:,}₽\n"
            text += f"   🏪 Магазинов: {p['shops_count']} | 🚗 Машин: {p['cars_count']}\n\n"
    kb = [[InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

# ---------- ПЕРЕВОДЫ ----------
@dp.callback_query(lambda c: c.data == "transfer_menu")
async def transfer_menu_callback(callback: CallbackQuery):
    await callback.message.answer("💸 <b>ПЕРЕВОД ДЕНЕГ</b>\n\nВведите команду:\n<code>/pay ник сумма</code>\n\nПример: /pay Барыга 5000", parse_mode="HTML")
    await safe_callback_answer(callback)

@dp.message(Command('admin'))
async def admin_cmd(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return await message.answer("❌ Нет доступа!")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer(
            "🔑 <b>АДМИН-ПАНЕЛЬ</b>\n\n"
            "<b>Команды:</b>\n"
            "/admin players — список игроков\n"
            "/admin give [ник / @username / tg_id] [сумма] — выдать деньги\n"
            "/admin skin [ник / @username / tg_id] [skin_id] — выдать скин\n"
            "/admin reset [ник / @username / tg_id] — сбросить игрока",
            parse_mode="HTML"
        )

    cmd = args[1]
    conn = get_db()
    cursor = conn.cursor()

    if cmd == "players":
        cursor.execute("SELECT tg_id, nickname, balance, day, total_sales FROM players ORDER BY total_sales DESC")
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            await message.answer("Нет зарегистрированных игроков.")
            return
        txt = "👥 <b>ИГРОКИ:</b>\n\n"
        for row in rows:
            tg = row['tg_id']
            name = row['nickname'] or f"ID:{tg}"
            txt += f"🆔 {name}\n💰 {row['balance']:,}₽ | День {row['day']} | Продано: {row['total_sales']}\n\n"
        await message.answer(txt, parse_mode="HTML")
        return

    elif cmd == "give" and len(args) >= 4:
        identifier = args[2]
        try:
            amount = int(args[3])
        except ValueError:
            await message.answer("❌ Сумма должна быть числом.")
            conn.close()
            return

        player_id = await resolve_player_id(identifier)
        if not player_id:
            await message.answer(f"❌ Игрок '{identifier}' не найден.")
            conn.close()
            return

        cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (amount, player_id))
        conn.commit()
        await message.answer(f"✅ Игроку '{identifier}' начислено {amount}₽.")
        conn.close()

    elif cmd == "reset" and len(args) >= 3:
        identifier = args[2]
        player_id = await resolve_player_id(identifier)
        if not player_id:
            await message.answer(f"❌ Игрок '{identifier}' не найден.")
            conn.close()
            return

        def _tg_for_player():
            c=get_db(); r=c.execute("SELECT tg_id FROM players WHERE id=?", (player_id,)).fetchone(); c.close(); return int(r["tg_id"]) if r and r["tg_id"] is not None else None
        target_tg = await run_sync_db(_tg_for_player)
        if not target_tg:
            conn.close()
            await message.answer("❌ Не удалось определить Telegram ID игрока.")
            return
        await run_sync_db(reset_player_account_sync, target_tg)
        await message.answer(f"✅ Игрок '{identifier}' полностью сброшен. Реферальные связи и все игровые данные удалены.")
        conn.close()

    elif cmd == "skin" and len(args) >= 4:
        identifier = args[2]
        skin_id = args[3]
        player_id = await resolve_player_id(identifier)
        if not player_id:
            await message.answer(f"❌ Игрок '{identifier}' не найден.")
            conn.close()
            return

        skin = next((s for s in SKINS if s["id"] == skin_id), None)
        if not skin:
            await message.answer("❌ Скин не найден.")
            conn.close()
            return

        async with db_lock:
            cursor.execute("INSERT OR IGNORE INTO skins (player_id, skin_id, equipped) VALUES (?, ?, 0)", (player_id, skin_id))
            conn.commit()
        await message.answer(f"✅ Скин {skin_id} выдан игроку '{identifier}'.")
        conn.close()

    else:
        await message.answer("❌ Неверная команда. Используйте /admin players /admin give /admin reset /admin skin")

@dp.message(Command('ip'))
async def show_ip(message: types.Message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        await message.answer("❌ Нет доступа!")
        return
    try:
        import urllib.request
        ip = urllib.request.urlopen('https://api.ipify.org').read().decode()
        await message.answer(f"🌐 Публичный IP сервера: `{ip}`", parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"❌ Ошибка получения IP: {e}")

@dp.message(StateFilter(Form.waiting_for_chat_price))
async def handle_chat_price(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        price = int(message.text.strip())
        if price <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.")
        return
    data = await state.get_data()
    chat_key = data.get("chat_key")
    if not chat_key or chat_key not in active_chats:
        await message.answer("Чат не найден.")
        await state.clear()
        return
    chat = active_chats[chat_key]
    if chat["user_id"] != await get_player_id_by_tg(user_id):
        await message.answer("Это не ваш чат.")
        await state.clear()
        return
    if price < max(1,int(chat["price"]*0.65)):
        await message.answer(f"❌ Слишком низкое предложение. Минимум для обсуждения: {int(chat['price']*.65):,}₽"); return
    chat["offer"]=price; chat["phase"]=5; client=CLIENT_TYPES[chat["client_type"]]
    threshold=chat["price"]*(0.82 if int(chat.get("trust",50))>=70 else 0.90)
    if price <= threshold:
        answer=chat.get("dialogue",{}).get("final_agree") or random.choice(client["phrases"].get("agree",["Хорошо, беру!"]))
        if isinstance(answer,list): answer=random.choice(answer)
        answer=answer.replace("{price}",f"{price:,}")
        await message.answer(f"👤 Покупатель: {answer}")
        player_id = await get_player_id_by_tg(user_id)
        if player_id:
            await complete_sale_universal(chat, player_id, message=message)
        else:
            await message.answer("❌ Ошибка: игрок не найден")
    else:
        answer=chat.get("dialogue",{}).get("final_decline") or random.choice(client["phrases"].get("decline",["Дорого, не буду брать."]))
        if isinstance(answer,list): answer=random.choice(answer)
        chat["finished"]=True
        # Очистка чата из памяти
        chat_key = chat['chat_key']
        async with chats_lock:
            if chat_key in active_chats:
                del active_chats[chat_key]
        await message.answer(f"👤 Покупатель: {answer}")
        await message.answer("Диалог завершён.")
    await state.clear()


@dp.callback_query(lambda c: c.data == "sales_history")
async def sales_history_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Вы не зарегистрированы", show_alert=True)
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT item_name, price, date FROM sales_history WHERE seller_id = ? ORDER BY id DESC LIMIT 20",
        (player_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    if not rows:
        text = "📜 <b>ИСТОРИЯ ПРОДАЖ</b>\n\nУ вас пока нет завершённых продаж."
    else:
        text = "📜 <b>ИСТОРИЯ ПРОДАЖ</b>\n\n"
        for row in rows:
            text += f"📦 {row['item_name']}\n💰 {row['price']}₽\n🕒 {row['date']}\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.message(F.photo, StateFilter(None))
async def get_photo_id(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        file_id = message.photo[-1].file_id
        await message.answer(f"✅ <code>{file_id}</code>", parse_mode="HTML")

# ==================== ТАЙМАУТ ГОНОК ====================
async def race_timeout_check():
    while True:
        await asyncio.sleep(30)
        now=time_module.time(); expired=[]
        async with races_lock:
            for race_id,race in list(active_races.items()):
                if race.get("status") not in ("wait","finished","draw") and now-race.get("last_action_time",now)>90:
                    expired.append((race_id,dict(race)))
                    active_races.pop(race_id,None)
        for race_id,race in expired:
            creator_id=race.get("creator"); opponent_id=race.get("opponent"); bet=int(race.get("bet",0))
            async with db_lock:
                if creator_id: await run_sync_db(_atomic_add_balance_sync,creator_id,bet)
                if opponent_id: await run_sync_db(_atomic_add_balance_sync,opponent_id,bet)
            creator_data=await run_sync_db(get_player_data,creator_id) if creator_id else None
            opponent_data=await run_sync_db(get_player_data,opponent_id) if opponent_id else None
            if creator_data and creator_data.get("tg_id"):
                try: await bot.send_message(creator_data["tg_id"],"⏰ Гонка отменена из-за неактивности соперника. Ставка возвращена.")
                except Exception: pass
            if opponent_data and opponent_data.get("tg_id"):
                try: await bot.send_message(opponent_data["tg_id"],"⏰ Гонка отменена из-за неактивности соперника. Ставка возвращена.")
                except Exception: pass

# ---------- АКЦИИ ----------
@dp.callback_query(lambda c: c.data == "stocks_entry")
async def stocks_entry_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "stocks_menu")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка загрузки", show_alert=True)
        return
    text = r.get("text")
    prices = r.get("prices", [])
    # Формируем клавиатуру
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for stock in prices:
        symbol = stock["symbol"]
        name = stock["name"]
        price = stock["price"]
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"📈 {symbol} ({name}) - {price:,}₽", callback_data=f"stock_{symbol}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="📋 ИСТОРИЯ СДЕЛОК", callback_data="stock_history")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 В БАНК", callback_data="bank_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "stock_history")
async def stock_history_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "stock_transactions")
    if r.get("success"):
        text = r.get("text", "📋 История сделок пуста.")
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=menu_kb())
    else:
        await safe_callback_answer(callback, "Ошибка загрузки истории", show_alert=True)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("stock_") and not c.data.startswith(("stock_buy_", "stock_sell_")))
async def stock_detail_callback(callback: CallbackQuery):
    symbol = callback.data.split("_")[1]
    user_id = callback.from_user.id
    # Получаем информацию об акции
    stock = await run_sync_db(get_stock_price, symbol)
    if not stock:
        await safe_callback_answer(callback, "Акция не найдена", show_alert=True)
        return
    # Получаем портфель игрока по этой акции
    user_stocks = await run_sync_db(get_user_stocks, user_id)
    user_stock = next((s for s in user_stocks if s["symbol"] == symbol), None)
    quantity = user_stock["quantity"] if user_stock else 0
    avg_price = user_stock["avg_buy_price"] if user_stock else 0
    current_price = stock["price"]
    profit_per_share = current_price - avg_price
    total_profit = profit_per_share * quantity
    
    text = (f"📈 <b>{stock['name']} ({symbol})</b>\n\n"
            f"💰 Текущая цена: {current_price:,}₽\n"
            f"📊 Изменение: {stock['change_pct']:+.2f}%\n"
            f"📦 У вас в портфеле: {quantity} шт.\n"
            f"📈 Средняя цена покупки: {avg_price:,}₽\n"
            f"💸 Прибыль/убыток по этой акции: {total_profit:+,}₽\n\n"
            f"Выберите действие:")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 КУПИТЬ", callback_data=f"stock_buy_{symbol}"),
         InlineKeyboardButton(text="🔴 ПРОДАТЬ", callback_data=f"stock_sell_{symbol}")],
        [InlineKeyboardButton(text="🔙 К РЫНКУ", callback_data="stocks_entry")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)


@dp.callback_query(lambda c: c.data.startswith("stock_buy_"))
async def stock_buy_callback(callback: CallbackQuery, state: FSMContext):
    symbol = callback.data.split("_")[2]
    await state.update_data(stock_symbol=symbol, stock_action="buy")
    await state.set_state(Form.waiting_for_stock_quantity)
    await callback.message.answer(f"💰 Введите количество акций {symbol} для покупки (цена за штуку уточняется на рынке):")
    await safe_callback_answer(callback)


@dp.callback_query(lambda c: c.data.startswith("stock_sell_"))
async def stock_sell_callback(callback: CallbackQuery, state: FSMContext):
    symbol = callback.data.split("_")[2]
    await state.update_data(stock_symbol=symbol, stock_action="sell")
    await state.set_state(Form.waiting_for_stock_quantity)
    await callback.message.answer(f"💰 Введите количество акций {symbol} для продажи (у вас их можно посмотреть в портфеле):")
    await safe_callback_answer(callback)

@dp.message(F.web_app_data)
async def handle_web_app_data(message: Message):
    user_id = message.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    try:
        data = json.loads(message.web_app_data.data)
        action = data.get("action")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        return

    # ---- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ОБНОВЛЕНИЯ БАЛАНСА И СТАТИСТИКИ ----
    async def process_game_result(bet: int, win_amount: int, game_name: str):
        """Обрабатывает результат игры: проверяет баланс, списывает ставку, начисляет выигрыш, обновляет статистику."""
        if bet <= 0:
            await message.answer("❌ Ставка должна быть больше 0")
            return False
        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer("❌ Игрок не найден")
            return False
        current_balance = player.get("balance", 0)
        if current_balance < bet:
            await message.answer(f"❌ Недостаточно средств! Доступно: {current_balance}₽")
            return False
        # Реферальный X увеличивает только прибыль, а не возвращаемую ставку.
        if win_amount > bet:
            profit = win_amount - bet
            win_amount = bet + boost_referral_income(profit, player_id)
        # Вычисляем изменение баланса: выигрыш - ставка
        delta = win_amount - bet
        new_balance = current_balance + delta
        if new_balance < 0:
            new_balance = 0
        # Обновляем баланс в БД
        await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        # Обновляем статистику
        if win_amount > 0:
            await update_casino_stats(player_id, "win", bet, win_amount)
        else:
            await update_casino_stats(player_id, "lose", bet, 0)
        return True

    # ===== CRASH =====
    if action == "crash_result":
        try:
            win = data.get("win", False)
            bet = data.get("bet", 0)
            multiplier = data.get("multiplier", 1.0)
            if bet < 10 or bet > 5000:
                await message.answer("❌ Некорректная ставка")
                return
            win_amount = int(bet * multiplier) if win else 0
            success = await process_game_result(bet, win_amount, "crash")
            if success:
                await message.answer("✅ Результат CRASH зафиксирован (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "crash_session":
        try:
            total_profit = data.get("total_profit", 0)
            await message.answer("✅ Сессия CRASH завершена (статистика обновлена).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    # ===== БЛЭКДЖЕК =====
    elif action == "blackjack_win":
        try:
            win_amount = data.get("win", 0)
            bet = data.get("bet", 0)
            if win_amount <= 0 or bet <= 0:
                return
            success = await process_game_result(bet, win_amount, "blackjack")
            if success:
                await message.answer("✅ Победа в блэкджеке зафиксирована (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "blackjack_lose":
        try:
            bet = data.get("bet", 0)
            if bet <= 0:
                return
            success = await process_game_result(bet, 0, "blackjack")
            if success:
                await message.answer("✅ Поражение в блэкджеке зафиксировано (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "blackjack_push":
        try:
            bet = data.get("bet", 0)
            if bet <= 0:
                return
            # Ничья – возвращаем ставку
            player = await run_sync_db(get_player_data, player_id)
            if player:
                current = player.get("balance", 0)
                await run_sync_db(update_player_data, player_id, {"balance": current + bet})
            await message.answer("✅ Ничья в блэкджеке зафиксирована (ставка возвращена).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "blackjack_session":
        try:
            total_profit = data.get("total_profit", 0)
            await message.answer("✅ Сессия блэкджека завершена.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    # ===== СЛОТЫ =====
    elif action == "slots_result":
        try:
            result = data.get("result")
            bet = data.get("bet", 0)
            win = data.get("win", 0)
            if bet <= 0:
                return
            win_amount = win if result == "win" else 0
            success = await process_game_result(bet, win_amount, "slots")
            if success:
                await message.answer("✅ Результат слотов зафиксирован (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "slots_session":
        try:
            total_profit = data.get("total_profit", 0)
            await message.answer("✅ Сессия слотов завершена.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    # ===== РУЛЕТКА =====
    elif action == "win" and data.get("game") == "roulette":
        try:
            win_amount = data.get("win", 0)
            bet = data.get("bet", 0)
            if win_amount <= 0 or bet <= 0:
                return
            success = await process_game_result(bet, win_amount, "roulette")
            if success:
                await message.answer("✅ Победа в рулетке зафиксирована (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "lose" and data.get("game") == "roulette":
        try:
            bet = data.get("bet", 0)
            if bet <= 0:
                return
            success = await process_game_result(bet, 0, "roulette")
            if success:
                await message.answer("✅ Поражение в рулетке зафиксировано (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action in ("roulette_session", "roulette_session_close"):
        try:
            total_profit = data.get("total_profit", 0)
            await message.answer("✅ Сессия рулетки завершена.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    # ===== MINES =====
    elif action == "mines_result":
        try:
            result = data.get("result")
            bet = data.get("bet", 0)
            win = data.get("win", 0)
            if bet <= 0:
                return
            win_amount = win if result == "win" else 0
            success = await process_game_result(bet, win_amount, "mines")
            if success:
                await message.answer("✅ Результат MINES зафиксирован (баланс обновлён).")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    elif action == "mines_session":
        try:
            total_profit = data.get("total_profit", 0)
            await message.answer("✅ Сессия MINES завершена.")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")
        return

    # ===== ПОЛУЧЕНИЕ БАЛАНСА КАЗИНО =====
    elif action == "get_balance":
        print(f"🔍 get_balance: user_id={user_id}")
        
        player_id = await get_player_id_by_tg(user_id)
        print(f"🔍 player_id найден: {player_id}")
        
        if not player_id:
            player_id = await run_sync_db(get_or_create_player, "tg", user_id)
            print(f"🔍 создан новый player_id: {player_id}")
        
        if not player_id:
            await message.answer(json.dumps({"error": "Player not found"}))
            return
        
        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer(json.dumps({"error": "Player not found"}))
            return
        
        balance = player.get("balance", 0)
        print(f"💰 balance: {balance}")
        await message.answer(json.dumps({"balance": balance}))
        return

    # ===== ЕДИНЫЙ БАЛАНС (legacy compatibility) =====
    elif action in ("deposit", "deposit_to_casino", "withdraw", "withdraw_from_casino"):
        player = await run_sync_db(get_player_data, player_id) if player_id else None
        unified = int((player or {}).get("balance", 0) or 0)
        await message.answer(json.dumps({"action": "balance_updated", "balance": unified, "message": "Используется единый баланс."}))
        return

    # ===== ЗАПРОС НА ПОПОЛНЕНИЕ (ПРОВЕРКА ОСНОВНОГО БАЛАНСА) =====
    elif action == "deposit_request":
        amount = data.get("amount", 0)
        if amount <= 0:
            await message.answer(json.dumps({"error": "Сумма должна быть больше 0"}))
            return

        player_id = await get_player_id_by_tg(user_id)
        if not player_id:
            player_id = await run_sync_db(get_or_create_player, "tg", user_id)
        if not player_id:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        main_balance = player.get("balance", 0)
        if main_balance < amount:
            await message.answer(json.dumps({
                "error": f"Недостаточно средств на основном балансе! Доступно: {main_balance}₽"
            }))
            return

        # Сохраняем заявку
        pending_deposits[user_id] = amount

        # Отвечаем, что проверка пройдена
        await message.answer(json.dumps({
            "status": "ok",
            "amount": amount,
            "message": f"Проверка пройдена. Подтвердите пополнение на {amount}₽."
        }))
        return

    # ===== ПОДТВЕРЖДЕНИЕ ПОПОЛНЕНИЯ =====
    elif action == "deposit_confirm":
        if pending_deposits.get(user_id) is None:
            await message.answer(json.dumps({"error": "Нет активной заявки на пополнение"}))
            return

        amount = pending_deposits.pop(user_id)

        player_id = await get_player_id_by_tg(user_id)
        if not player_id:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        main_balance = player.get("balance", 0)
        if main_balance < amount:
            # на случай, если баланс изменился за время ожидания
            await message.answer(json.dumps({"error": "Недостаточно средств на основном балансе"}))
            return

        # СПИСЫВАЕМ с основного баланса
        new_main = main_balance - amount
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": new_main})

        # ОТВЕЧАЕМ КЛИЕНТУ – он сам добавит сумму к localBalance
        await message.answer(json.dumps({
            "action": "deposit_success",
            "amount": amount,
            "new_main_balance": new_main,
            "message": f"Пополнение на {amount}₽ выполнено!"
        }))
        return

    # ===== ОТМЕНА ПОПОЛНЕНИЯ =====
    elif action == "deposit_cancel":
        if user_id in pending_deposits:
            del pending_deposits[user_id]
        await message.answer(json.dumps({"status": "cancelled", "message": "Пополнение отменено"}))
        return

    # ===== ВЫВОД СРЕДСТВ (старый метод, оставлен для совместимости) =====
    elif action == "withdraw_from_casino":
        amount = data.get("amount", 0)
        if amount <= 0:
            await message.answer(json.dumps({"error": "Сумма должна быть больше 0"}))
            return

        player_id = await get_player_id_by_tg(user_id)
        if not player_id:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        # Зачисляем на основной баланс (без проверки локального баланса – доверяем клиенту)
        new_balance = player.get("balance", 0) + amount
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": new_balance})

        await message.answer(json.dumps({
            "action": "withdraw_success",
            "amount": amount,
            "new_main_balance": new_balance,
            "message": f"Вывод {amount}₽ выполнен!"
        }))
        return

    # ===== РЕФЕРАЛЫ =====
    elif action == "generate_referral_link":
        try:
            player_id = await get_player_id_by_tg(user_id)
            if not player_id:
                await message.answer("❌ Вы не зарегистрированы.")
                return
            ref_code = gen_ref(user_id)
            link = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"
            await message.answer(
                f"🔗 Ваша реферальная ссылка:\n<code>{link}</code>",
                parse_mode="HTML"
            )
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
        return

    elif action == "view_referral_users":
        try:
            player_id = await get_player_id_by_tg(user_id)
            if not player_id:
                await message.answer("❌ Вы не зарегистрированы.")
                return
            ref_data = await run_sync_db(get_referral_data, player_id)
            invited = ref_data.get("invited", [])
            if not invited:
                await message.answer("👥 У вас пока нет приглашённых.")
                return
            users = []
            for inv_id in invited:
                player = await run_sync_db(get_player_data, inv_id)
                if player:
                    nick = player.get("nickname", f"ID:{player.get('tg_id', inv_id)}")
                    users.append(nick)
                else:
                    users.append(f"ID:{inv_id}")
            text = "👥 <b>Ваши приглашённые:</b>\n" + "\n".join(f"• {u}" for u in users)
            await message.answer(text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
        return

    elif action == "view_referral_income":
        try:
            player_id = await get_player_id_by_tg(user_id)
            if not player_id:
                await message.answer("❌ Вы не зарегистрированы.")
                return
            ref_data = await run_sync_db(get_referral_data, player_id)
            invited = ref_data.get("invited", [])
            count = len(invited)
            income = count * REFERRAL_DIRECT_REWARD
            bonus = (count // 5) * 150000
            multiplier = 1.0
            for target, mult in REFERRAL_BOOST_TIERS:
                if count >= target: multiplier = mult
                else: break
            passive_percent = get_referral_passive_percent(count)
            title = get_referral_title(count)
            total = income + bonus
            text = (
                f"💰 <b>Ваш реферальный доход</b>\n\n"
                f"👥 Активных друзей: {count} чел.\n"
                f"🧾 По {REFERRAL_DIRECT_REWARD:,}₽ за каждого: {income:,} ₽\n"
                f"🎁 Бонус каждые 5 друзей: {bonus:,} ₽\n"
                f"⚡ Буст аккаунта: ×{multiplier:g}\n"
                f"🏆 Звание: <b>{title}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>Всего прямых наград:</b> {total:,} ₽"
            )
            await message.answer(text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
        return

    elif action == "get_balance":
        await message.answer("💰 Баланс казино отображается в самой игре.")
        return

    elif action == "profile":
        return

    # ===== ТРЕЙДИНГ =====
    elif action == "get_trading_prices":
        async with trading_lock:
            prices = trading_prices.copy()
        await message.answer(json.dumps({"success": True, "prices": prices}))

    elif action == "get_trading_portfolio":
        player_id = await get_player_id_by_tg(user_id)
        if not player_id:
            await message.answer(json.dumps({"success": False, "error": "Player not found"}))
            return
        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer(json.dumps({"success": False, "error": "Player not found"}))
            return
        history = bet_history.get(user_id, [])
        total_bets = len(history)
        wins = sum(1 for bet in history if bet["result"] == "win")
        losses = total_bets - wins
        total_profit = sum(bet["profit"] for bet in history)
        portfolio = {
            "balance": player.get("balance", 0),
            "total_bets": total_bets,
            "wins": wins,
            "losses": losses,
            "total_profit": total_profit,
            "history": history[-10:]
        }
        await message.answer(json.dumps({"success": True, "portfolio": portfolio}))

    elif action == "trade_bet":
        asset = data.get("asset")
        direction = data.get("direction")
        amount = data.get("amount", 0)
        if not asset or direction not in ("up", "down") or amount <= 0:
            await message.answer(json.dumps({"success": False, "error": "Invalid parameters"}))
            return

        asset_info = TRADING_ASSETS.get(asset)
        if not asset_info:
            await message.answer(json.dumps({"success": False, "error": "Asset not found"}))
            return

        if amount < asset_info["min_bet"] or amount > asset_info["max_bet"]:
            await message.answer(json.dumps({"success": False, "error": f"Bet must be between {asset_info['min_bet']} and {asset_info['max_bet']}"}))
            return

        player_id = await get_player_id_by_tg(user_id)
        if not player_id:
            await message.answer(json.dumps({"success": False, "error": "Player not found"}))
            return

        player = await run_sync_db(get_player_data, player_id)
        if not player or player.get("balance", 0) < amount:
            await message.answer(json.dumps({"success": False, "error": "Insufficient funds"}))
            return

        async with trading_lock:
            if asset not in trading_prices:
                await message.answer(json.dumps({"success": False, "error": "Prices not loaded"}))
                return
            start_price = trading_prices[asset]["price"]

        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": player["balance"] - amount})

        bet_id = f"{user_id}_{int(time_module.time()*1000)}"
        active_bets[bet_id] = {
            "user_id": user_id,
            "asset": asset,
            "direction": direction,
            "amount": amount,
            "start_price": start_price,
            "start_time": time_module.time()
        }

        asyncio.create_task(check_bet_result(bet_id))

        await message.answer(json.dumps({
            "success": True,
            "message": f"Bet placed: {amount}₽ on {asset} {direction} at ${start_price:.2f}",
            "bet_id": bet_id
        }))

    # ===== КОЛЕСО ПРИЗОВ =====
    elif action == "spin_wheel":
        amount = data.get("amount", 1000)
        if amount < 1000 or amount > 5000:
            await message.answer(json.dumps({"error": "Ставка должна быть от 1000 до 5000₽"}))
            return

        player_id = await get_player_id_by_tg(user_id)
        if not player_id:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        player = await run_sync_db(get_player_data, player_id)
        if not player:
            await message.answer(json.dumps({"error": "Игрок не найден"}))
            return

        balance = player.get("balance", 0)
        if balance < amount:
            await message.answer(json.dumps({"error": f"Недостаточно средств в казино! Доступно: {balance}₽"}))
            return

        # === Определяем приз (вероятности) ===
        prizes = [
            {"name": "50 000 ₽", "chance": 0.02, "reward": 50000, "type": "money"},
            {"name": "10 000 ₽", "chance": 0.08, "reward": 10000, "type": "money"},
            {"name": "1 000 ₽", "chance": 0.20, "reward": 1000, "type": "money"},
            {"name": "Бесплатное вращение", "chance": 0.15, "reward": amount, "type": "free_spin"},
            {"name": "Бонус ×2", "chance": 0.10, "reward": amount * 2, "type": "bonus"},
            {"name": "5 000 ₽", "chance": 0.15, "reward": 5000, "type": "money"},
            {"name": "BRABUS MANSORY", "chance": 0.001, "reward": 5000000, "type": "car"},
            {"name": "Ничего", "chance": 0.25, "reward": 0, "type": "nothing"},
            {"name": "Ещё раз", "chance": 0.049, "reward": amount, "type": "retry"},
        ]

        roll = random.random()
        cumulative = 0
        chosen_prize = None
        for prize in prizes:
            cumulative += prize["chance"]
            if roll <= cumulative:
                chosen_prize = prize
                break
        if not chosen_prize:
            chosen_prize = {"name": "Ничего", "reward": 0, "type": "nothing"}

        # === Обработка выигрыша ===
        async with db_lock:
            new_balance = balance - amount
            if chosen_prize["type"] == "money":
                new_balance += chosen_prize["reward"]
            elif chosen_prize["type"] == "free_spin":
                new_balance += amount
            elif chosen_prize["type"] == "bonus":
                new_balance += chosen_prize["reward"]
            elif chosen_prize["type"] == "car":
                car_collection = player.get("car_collection", [])
                if "brabus" not in car_collection:
                    car_collection.append("brabus")
                    await run_sync_db(update_player_data, player_id, {"car_collection": car_collection})
                new_balance += chosen_prize["reward"]
            elif chosen_prize["type"] == "retry":
                new_balance += amount
            await run_sync_db(update_player_data, player_id, {"balance": new_balance})

        # === Сохраняем историю ===
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO wheel_spins (player_id, prize, amount, spin_time) VALUES (?, ?, ?, ?)",
            (player_id, chosen_prize["name"], amount, int(time_module.time()))
        )
        conn.commit()
        conn.close()

        # === Отправляем результат ===
        await message.answer(json.dumps({
            "success": True,
            "prize": chosen_prize["name"],
            "prize_type": chosen_prize["type"],
            "reward": chosen_prize["reward"],
            "new_balance": new_balance,
            "message": f"🎡 Выпало: {chosen_prize['name']}!"
        }))
        return

    else:
        await message.answer("⚠️ Неизвестное действие.")

@dp.message(StateFilter(Form.waiting_for_stock_quantity))
async def handle_stock_quantity(message: Message, state: FSMContext):
    try:
        quantity = int(message.text.strip())
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное целое число.")
        return
    data = await state.get_data()
    symbol = data.get("stock_symbol")
    action = data.get("stock_action")
    if not symbol or not action:
        await message.answer("❌ Ошибка, начните заново.")
        await state.clear()
        return
    user_id = message.from_user.id
    if action == "buy":
        r = await api_call(user_id, "buy_stock", {"symbol": symbol, "quantity": quantity})
    else:
        r = await api_call(user_id, "sell_stock", {"symbol": symbol, "quantity": quantity})
    if r.get("success"):
        await message.answer(f"{r.get('message')}\n💰 Ваш баланс: {r.get('balance', 0):,}₽", parse_mode="HTML", reply_markup=menu_kb())
    else:
        await message.answer(f"❌ {r.get('message')}")
    await state.clear()

@dp.message(Command('check_casino'))
async def check_balance(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    user_id = message.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await message.answer("❌ Игрок не найден")
        return
    player = await run_sync_db(get_player_data, player_id)
    if player:
        casino_bal = player.get("balance", 0)
        await message.answer(f"💰 Ваш balance в БД: {casino_bal}₽")
    else:
        await message.answer("❌ Ошибка получения данных")

@dp.message(Command('hide'))
async def hide_keyboard(message: Message):
    await message.answer("✅ Клавиатура скрыта. Используй /menu, чтобы вернуться.", reply_markup=ReplyKeyboardRemove())

# ========== ДОБАВИТЬ ЭТУ ФУНКЦИЮ СЮДА ==========
async def clean_inactive_chats():
    """Удаляет чаты, которые не завершены и старше 30 минут."""
    while True:
        await asyncio.sleep(600)
        now = time_module.time()
        async with chats_lock:
            for key, chat in list(active_chats.items()):
                if not chat.get("finished"):
                    created = chat.get("created_at", 0)
                    if created == 0:
                        created = chat.get("last_action", now)
                    if now - created > 1800:
                        del active_chats[key]

# ========== ФОНОВЫЕ ЗАДАЧИ (ДОБАВЛЕННЫЕ) ==========
async def update_trading_loop():
    """Обновление цен криптовалют для POCKET OPTION каждые 30 секунд"""
    while True:
        try:
            prices = await fetch_crypto_prices()
            if prices:
                async with trading_lock:
                    for asset, price in prices.items():
                        if asset in trading_prices:
                            old_price = trading_prices[asset]["price"]
                            # изменение в процентах
                            change = (price - old_price) / old_price if old_price else 0
                            trading_prices[asset]["price"] = price
                            trading_prices[asset]["trend"] = change
                            trading_prices[asset]["history"].append(price)
                            # ограничим историю
                            if len(trading_prices[asset]["history"]) > 10:
                                trading_prices[asset]["history"].popleft()
        except Exception as e:
            print(f"Ошибка в update_trading_loop: {e}")
        await asyncio.sleep(30)

async def check_overdue_loans():
    """Проверка просроченных кредитов (раз в сутки)"""
    while True:
        try:
            now = int(time_module.time())
            async with db_lock:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, player_id, amount, interest_rate FROM loans WHERE status = 'active' AND due_date < ?",
                    (now,)
                )
                overdue = cursor.fetchall()
                for loan in overdue:
                    # Штраф 10% от суммы долга
                    total_due = int(loan['amount'] * (1 + loan['interest_rate'] / 100))
                    penalty = int(total_due * 0.1)
                    cursor.execute(
                        "UPDATE loans SET status = 'overdue', amount = amount + ? WHERE id = ?",
                        (penalty, loan['id'])
                    )
                    # Уведомляем игрока (если есть tg_id)
                    cursor.execute("SELECT tg_id FROM players WHERE id = ?", (loan['player_id'],))
                    row = cursor.fetchone()
                    if row and row['tg_id']:
                        try:
                            await bot.send_message(
                                row['tg_id'],
                                f"⚠️ Ваш кредит просрочен! Начислен штраф {penalty}₽. Погасите долг как можно скорее."
                            )
                        except:
                            pass
                conn.commit()
                conn.close()
        except Exception as e:
            print(f"Ошибка в check_overdue_loans: {e}")
        await asyncio.sleep(86400)  # раз в сутки

# ========== ДОБАВИТЬ ЭТУ ФУНКЦИЮ (если её нет) ==========
async def update_stock_prices_loop():
    while True:
        await update_all_stock_prices()
        await asyncio.sleep(60)

async def daily_day_increment():
    """Фоновая задача: раз в сутки увеличиваем день у всех игроков на 1."""
    while True:
        await asyncio.sleep(86400)  # ждём 24 часа
        async with db_lock:
            def _increment_day():
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("UPDATE players SET day = day + 1")
                conn.commit()
                conn.close()
            await run_sync_db(_increment_day)
        print("✅ Дни всех игроков увеличены на 1")

# ========== ДОБАВЛЕННЫЕ ФУНКЦИИ ДЛЯ ЗАПУСКА ==========
async def dividends_loop():
    """Фоновая задача для дивидендов (заглушка)"""
    while True:
        await asyncio.sleep(86400)  # раз в сутки
        # Здесь можно реализовать начисление дивидендов по акциям
        # Пока просто ничего не делаем
        pass

def ensure_stock_prices_table():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_prices (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            price INTEGER,
            change_pct REAL,
            last_update INTEGER
        )
    """)
    # Заполним начальными данными, если таблица пуста
    cursor.execute("SELECT COUNT(*) FROM stock_prices")
    if cursor.fetchone()[0] == 0:
        stocks = [
            ("AAPL", "Apple Inc.", 17500),
            ("GOOGL", "Google", 13500),
            ("TSLA", "Tesla", 24000),
            ("AMZN", "Amazon", 17800),
            ("MSFT", "Microsoft", 42000),
        ]
        now = int(time_module.time())
        for sym, name, price in stocks:
            cursor.execute(
                "INSERT INTO stock_prices (symbol, name, price, change_pct, last_update) VALUES (?, ?, ?, 0.0, ?)",
                (sym, name, price, now)
            )
    conn.commit()
    conn.close()
    print("✅ Таблица stock_prices проверена/создана")

# ==================== LIFESPAN ДЛЯ FASTAPI ====================


# Restored core helpers from the last known-good bot.py to keep legacy API contracts intact.
MAX_OFFLINE_PASSIVE_SECONDS = 24 * 60 * 60

async def collect_pending_income(player_id: int):
    """Collect all passive income.

    Business and Taxopark have independent collection cursors. The Business
    button collects both ledgers in one atomic transaction.
    """
    lock = player_action_locks.setdefault(
        f"taxi:{int(player_id)}", asyncio.Lock()
    )
    async with lock:
        return await _collect_pending_income_locked(int(player_id))



async def _collect_pending_income_locked(player_id: int):
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return 0, 0, {}

    def _collect_sync():
        # Snapshot hourly sources before opening the write transaction. Calling
        # get_hourly_income() from inside BEGIN IMMEDIATE can deadlock SQLite
        # because that helper opens its own connection.
        _current_hourly_snapshot, _breakdown_snapshot = get_hourly_income(player_id)
        current_breakdown_snapshot = {k:max(0,int(v or 0)) for k,v in (_breakdown_snapshot or {}).items()}
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            row = cur.execute(
                "SELECT balance,total_earned,last_income_collect,taxopark,car_collection,garage_car_stats "
                "FROM players WHERE id=?",
                (player_id,),
            ).fetchone()
            if not row:
                conn.rollback()
                return None

            now = int(time_module.time())
            business_cursor = int(row["last_income_collect"] or 0)

            tax = _safe_taxopark(row["taxopark"])
            owned = _safe_json_list(row["car_collection"])
            stats = _taxi_load_persistent_stats(conn,player_id,owned,row["garage_car_stats"],now)
            indices = _taxi_indices(tax, owned)

            taxi_cursor = int(tax.get("last_collect_at") or 0)
            if taxi_cursor <= 0:
                taxi_cursor = business_cursor if business_cursor > 0 else now
                tax["last_collect_at"] = taxi_cursor

            stats, _, _ = _taxi_materialize_shared_state(
                stats, owned, indices, now, legacy_start=taxi_cursor
            )

            current_breakdown = current_breakdown_snapshot
            pending_breakdown = {}
            ordinary_elapsed = (
                min(MAX_OFFLINE_PASSIVE_SECONDS, max(0, now - business_cursor)) if business_cursor > 0 else 0
            )
            for source, hourly_value in current_breakdown.items():
                if source == "taxopark":
                    continue
                pending_breakdown[source] = int(
                    hourly_value * ordinary_elapsed / 3600.0
                )

            taxi_pending = max(0, int(tax.get("pending_carry", 0) or 0))
            taxi_pending += _taxi_pending_from_state(
                stats,
                owned,
                indices,
                taxi_cursor,
                now,
                multiplier=_taxi_multiplier_for_player(player_id),
            )
            pending_breakdown["taxopark"] = int(taxi_pending)

            total = max(0, int(sum(pending_breakdown.values())))
            new_balance = int(row["balance"] or 0) + total
            new_total = int(row["total_earned"] or 0) + total

            tax["last_collect_at"] = now
            tax["pending_carry"] = 0

            cur.execute(
                "UPDATE players SET balance=?,total_earned=?,last_income_collect=?,taxopark=? "
                "WHERE id=? AND last_income_collect=?",
                (
                    new_balance,
                    new_total,
                    now,
                    json.dumps(tax, ensure_ascii=False),
                    player_id,
                    business_cursor,
                ),
            )
            if cur.rowcount != 1:
                conn.rollback()
                return (
                    0,
                    int(row["balance"] or 0),
                    0,
                    {},
                    int(sum(current_breakdown.values())),
                    False,
                )

            conn.commit()
            return (
                int(total),
                int(new_balance),
                now,
                pending_breakdown,
                int(sum(current_breakdown.values())),
                True,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    result = await run_sync_db(_collect_sync)
    if not result or not result[-1]:
        return 0, 0, {}

    collected, _, _, pending_breakdown, hourly, _ = result

    if collected > 0:
        await run_sync_db(
            check_and_update_achievement,
            player_id,
            "millionaire",
            int(player.get("total_earned", 0) or 0) + collected,
        )
        await run_sync_db(update_daily_quest, player_id, "earn_50k", collected)
        await run_sync_db(
            update_daily_quest, player_id, "collect_passive_10k", collected
        )

    return int(collected), int(hourly), pending_breakdown



async def collect_income(player: dict | int) -> int:
    """Legacy compatibility wrapper used by the old ``next_day`` action.

    The current economy keeps Business Center income and Taxopark income on
    separate collection cursors, so this wrapper intentionally collects only
    the normal passive/business ledger.
    """
    try:
        player_id = int(player.get("id")) if isinstance(player, dict) else int(player)
    except (TypeError, ValueError, AttributeError):
        return 0
    collected, _hourly, _breakdown = await collect_pending_income(player_id)
    return int(collected)


async def collect_taxopark_income(player_id: int):
    """Fast atomic Taxi collection. Response is not blocked by side effects."""
    lock=player_action_locks.setdefault(f"taxi:{int(player_id)}",asyncio.Lock())
    async with lock:
        def tx():
            conn=get_db()
            try:
                cur=conn.cursor(); cur.execute('BEGIN IMMEDIATE')
                row=cur.execute('SELECT balance,total_earned,last_income_collect,taxopark,car_collection,garage_car_stats FROM players WHERE id=?',(int(player_id),)).fetchone()
                if not row: conn.rollback(); return None
                now=int(time_module.time()); business_cursor=int(row['last_income_collect'] or 0)
                tax=_safe_taxopark(row['taxopark']); owned=_safe_json_list(row['car_collection'])
                stats=_taxi_load_persistent_stats(conn,int(player_id),owned,row['garage_car_stats'],now)
                indices=_taxi_indices(tax,owned)
                cursor=int(tax.get('last_collect_at') or 0)
                if cursor<=0:
                    cursor=business_cursor if business_cursor>0 else now
                    tax['last_collect_at']=cursor
                stats,_,_=_taxi_materialize_shared_state(stats,owned,indices,now,legacy_start=cursor)
                mult=_taxi_multiplier_for_player_conn(conn,int(player_id))
                pending=max(0,int(tax.get('pending_carry',0) or 0))+_taxi_pending_from_state(stats,owned,indices,cursor,now,multiplier=mult)
                hourly=_taxi_current_hourly_from_state(stats,owned,indices,mult)
                new_balance=int(row['balance'] or 0)+pending; new_total=int(row['total_earned'] or 0)+pending
                tax['last_collect_at']=now; tax['pending_carry']=0
                _taxi_save_persistent_stats(conn,int(player_id),owned,stats)
                cur.execute('UPDATE players SET balance=?,total_earned=?,taxopark=?,garage_car_stats=? WHERE id=?',(new_balance,new_total,json.dumps(tax,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),int(player_id)))
                if cur.rowcount!=1: conn.rollback(); return None
                conn.commit(); return int(pending),int(new_balance),int(hourly),now
            except Exception:
                try: conn.rollback()
                except Exception: pass
                raise
            finally: conn.close()
        result=await run_sync_db(tx)
    if not result: return 0,0,0,0
    collected,balance,hourly,server_time=result
    if collected>0:
        async def side_effects(amount,pid):
            try:
                fresh=await run_sync_db(get_player_data,int(pid)) or {}
                await run_sync_db(check_and_update_achievement,int(pid),'millionaire',int(fresh.get('total_earned',0) or 0))
                await run_sync_db(update_daily_quest,int(pid),'earn_50k',int(amount))
                await run_sync_db(update_daily_quest,int(pid),'collect_passive_10k',int(amount))
            except Exception as exc:
                print(f'[TAXI] post-collect side effects skipped: {type(exc).__name__}: {exc}')
        asyncio.create_task(side_effects(int(collected),int(player_id)))
    return int(collected),int(balance),int(hourly),int(server_time)

def find_user_by_ref_code(ref_code: str) -> Optional[int]:
    """Находит tg_id игрока по реферальному коду (хешу)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT tg_id FROM players WHERE tg_id IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    for row in rows:
        tg_id = row['tg_id']
        if gen_ref(tg_id) == ref_code:
            print(f"🔍 Найден пригласивший по коду {ref_code}: tg_id={tg_id}")
            return tg_id
    print(f"⚠️ Реферальный код {ref_code} не найден в БД")
    return None

def gen_ref(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

def _taxi_pending_income_sync_legacy(player: dict, since: int = 0, until: int = 0) -> int:
    tax = _safe_taxopark(player.get("taxopark"))
    start = int(
        since
        or tax.get("last_collect_at")
        or player.get("last_income_collect")
        or 0
    )
    end = int(until or time_module.time())
    owned = _safe_json_list(player.get("car_collection"))
    stats = _safe_car_stats(player.get("garage_car_stats"), len(owned), end)
    indices = _taxi_indices(tax, owned)
    return _taxi_pending_from_state(
        stats, owned, indices, start, end,
        _taxi_multiplier_for_player(int(player.get("id") or 0)),
    )


async def get_pending_income(player_id: int):
    """Read pending passive income using separate Business and Taxi clocks."""
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return 0, 0, {}

    now = int(time_module.time())
    business_cursor = int(player.get("last_income_collect", 0) or 0)
    hourly_all, breakdown_all = await run_sync_db(get_hourly_income, player_id)
    breakdown_all = {
        k: max(0, int(v or 0))
        for k, v in (breakdown_all or {}).items()
    }

    ordinary_elapsed = (
        min(MAX_OFFLINE_PASSIVE_SECONDS, max(0, now - business_cursor)) if business_cursor > 0 else 0
    )
    pending_breakdown = {}
    for source, hourly_value in breakdown_all.items():
        if source == "taxopark":
            continue
        pending_breakdown[source] = int(
            hourly_value * ordinary_elapsed / 3600.0
        )

    tax = _safe_taxopark(player.get("taxopark"))
    owned = _safe_json_list(player.get("car_collection"))
    stats = _safe_car_stats(
        player.get("garage_car_stats"), len(owned), now
    )
    indices = _taxi_indices(tax, owned)

    taxi_cursor = int(tax.get("last_collect_at") or 0)
    if taxi_cursor <= 0:
        taxi_cursor = business_cursor if business_cursor > 0 else now

    stats, _, _ = _taxi_materialize_shared_state(
        stats, owned, indices, now, legacy_start=taxi_cursor
    )

    taxi_pending = max(0, int(tax.get("pending_carry", 0) or 0))
    taxi_pending += _taxi_pending_from_state(
        stats, owned, indices, taxi_cursor, now,
        multiplier=_taxi_multiplier_for_player(player_id),
    )
    pending_breakdown["taxopark"] = int(taxi_pending)

    return (
        max(0, int(sum(pending_breakdown.values()))),
        int(hourly_all),
        pending_breakdown,
    )



def get_top_players(limit=10):
    """Возвращает топ игроков через SQLite"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT tg_id, total_earned, items_sold FROM players ORDER BY items_sold DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append((row['tg_id'], row['total_earned'], row['items_sold']))
    return result

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup-local workers. They intentionally do not depend on global
    # process_deposits/process_mining symbols, so a partial/older deployment
    # cannot break application startup with NameError.
    async def _startup_process_deposits():
        def _sync_deposits():
            conn = get_db()
            cursor = conn.cursor()
            now = int(time_module.time())
            cursor.execute(
                "SELECT id, player_id, amount, start_time, duration_days, interest_rate "
                "FROM deposits WHERE status = 'active' AND start_time + duration_days*86400 <= ?",
                (now,)
            )
            matured = cursor.fetchall()
            for dep in matured:
                profit = int(dep['amount'] * dep['interest_rate'] / 100)
                total = dep['amount'] + profit
                cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (total, dep['player_id']))
                cursor.execute("UPDATE deposits SET status = 'closed' WHERE id = ?", (dep['id'],))
            conn.commit()
            conn.close()
            return matured

        while True:
            await asyncio.sleep(86400)
            try:
                async with db_lock:
                    matured = await asyncio.to_thread(_sync_deposits)
                for dep in matured:
                    player = await run_sync_db(get_player_data, dep['player_id'])
                    if player and player.get('tg_id'):
                        try:
                            profit = int(dep['amount'] * dep['interest_rate'] / 100)
                            total = dep['amount'] + profit
                            await bot.send_message(
                                player['tg_id'],
                                f"🏦 Ваш депозит на {dep['amount']}₽ завершён! Получено {total}₽ (включая {profit}₽ процентов)."
                            )
                        except Exception:
                            pass
            except Exception as exc:
                print(f"Ошибка в _startup_process_deposits: {exc}")

    async def _startup_process_mining():
        def _sync_mining():
            conn = get_db()
            cursor = conn.cursor()
            now=int(time_module.time())
            cursor.execute("SELECT id, player_id, daily_income, COALESCE(last_paid_at,0) last_paid_at FROM mining_rigs WHERE status='active'")
            rigs = cursor.fetchall()
            for rig in rigs:
                hourly=max(0,int(rig['daily_income'] or 0)//24)
                if hourly<=0: continue
                won=cursor.execute("UPDATE mining_rigs SET last_paid_at=? WHERE id=? AND (COALESCE(last_paid_at,0)=0 OR last_paid_at<=?)",(now,int(rig['id']),now-3600))
                if won.rowcount==1:
                    cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (hourly, rig['player_id']))
            conn.commit()
            conn.close()

        while True:
            await asyncio.sleep(3600)
            try:
                async with db_lock:
                    await asyncio.to_thread(_sync_mining)
            except Exception as exc:
                print(f"Ошибка в _startup_process_mining: {exc}")

    # ---- 1. Инициализация (то, что было в main()) ----
    # Keep the shop-expiry worker local to lifespan so startup never depends
    # on a stale/missing global symbol from an older bot.py deployment.
    async def _business_expiry_loop():
        def _sync_business_expiry():
            conn = get_db()
            cursor = conn.cursor()
            now = int(time_module.time())
            cursor.execute(
                "SELECT id, player_id, shop_id, purchase_price, last_payment FROM user_shops WHERE status = 'active'"
            )
            shops = cursor.fetchall()
            expired = []
            for row in shops:
                last_payment = row['last_payment'] or now
                days = max(0.0, (now - last_payment) / 86400)
                if days <= 0:
                    continue
                cost_per_day = get_maintenance_cost_shop_per_day(row['purchase_price'])
                debt = int(cost_per_day * days)
                if debt > 3 * row['purchase_price']:
                    expired.append(row)
            for row in expired:
                cursor.execute("UPDATE user_shops SET status = 'seized' WHERE id = ?", (row['id'],))
                refund = int(row['purchase_price'] * 0.7)
                cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (refund, row['player_id']))
            conn.commit()
            conn.close()
            return expired

        while True:
            await asyncio.sleep(86400)
            try:
                async with db_lock:
                    expired_shops = await asyncio.to_thread(_sync_business_expiry)
                for row in expired_shops:
                    player = await run_sync_db(get_player_data, row['player_id'])
                    if player and player.get('tg_id'):
                        try:
                            await bot.send_message(
                                player['tg_id'],
                                f"⚠️ Ваш магазин «{row['shop_id']}» изъят за неуплату. Возвращено {int(row['purchase_price'] * 0.7)}₽."
                            )
                        except Exception:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"⚠️ Business expiry worker error: {e}")

    init_db()
    upgrade_db()
    ensure_stock_prices_table()
    await load_auction_items_from_db()
    # generate_supplier_items()   # УДАЛЕНО – теперь генерируется для каждого игрока отдельно
    init_trading()
    
    # ---- 2. Фоновые задачи (все твои asyncio.create_task) ----
    tasks = [
        asyncio.create_task(update_trading_loop()),
        asyncio.create_task(auction_loop()),
        asyncio.create_task(_business_expiry_loop()),
        asyncio.create_task(_startup_process_deposits()),
        asyncio.create_task(_startup_process_mining()),
        asyncio.create_task(check_overdue_loans()),
        asyncio.create_task(race_timeout_check()),
        asyncio.create_task(update_stock_prices_loop()),
        asyncio.create_task(dividends_loop()),
        asyncio.create_task(clean_inactive_chats()),
        asyncio.create_task(daily_day_increment()),
        asyncio.create_task(reset_daily_quests_at_noon()),
    ]
    # (start_web_server_async мы не запускаем – он больше не нужен)
    
    # ---- 3. Telegram identity/auth sanity check ----
    # This makes a wrong deployment token immediately visible in server logs.
    await _log_telegram_auth_config()

    # ---- 4. Запуск aiogram polling (единственный!) ----
    await bot.delete_webhook(drop_pending_updates=True)
    polling_task = asyncio.create_task(dp.start_polling(bot, allowed_updates=["message", "callback_query", "web_app_data"]))
    tasks.append(polling_task)
    
    print("✅ Бот и фоновые задачи запущены")
    
    yield  # здесь приложение работает
    
    # ---- 5. Остановка (при завершении) ----
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await bot.session.close()
    print("✅ Приложение остановлено")

app = FastAPI(title="Resell Tycoon API", lifespan=lifespan)

# ==================== ADMIN / AUDIT HELPERS ====================
ADMIN_SUPER_ID = ADMIN_ID
ADMIN_EXTRA_IDS = set()

def _admin_is_allowed_sync(tg_id: int) -> bool:
    if int(tg_id) == int(ADMIN_SUPER_ID):
        return True
    try:
        conn=get_db(); row=conn.execute("SELECT 1 FROM admin_users WHERE tg_id=? AND active=1",(int(tg_id),)).fetchone(); conn.close()
        return bool(row)
    except Exception:
        return False

def _audit_log_sync(actor_tg_id, target_tg_id, action, amount=0, details=""):
    conn=get_db()
    conn.execute("INSERT INTO audit_logs(actor_tg_id,target_tg_id,action,amount,details,created_at) VALUES(?,?,?,?,?,?)",(int(actor_tg_id) if actor_tg_id else None,int(target_tg_id) if target_tg_id else None,str(action)[:120],int(amount or 0),str(details or '')[:1000],int(time_module.time())))
    conn.commit(); conn.close()

# Создаём таблицу администраторов отдельно, чтобы старые БД мигрировали автоматически.
try:
    _c=get_db(); _c.execute("CREATE TABLE IF NOT EXISTS admin_users(tg_id INTEGER PRIMARY KEY, added_by INTEGER, active INTEGER DEFAULT 1, created_at INTEGER NOT NULL)"); _c.commit(); _c.close()
except Exception:
    pass

async def admin_allowed(tg_id:int)->bool:
    return await run_sync_db(_admin_is_allowed_sync,int(tg_id))

async def audit(actor_tg_id,target_tg_id,action,amount=0,details=""):
    try: await run_sync_db(_audit_log_sync,actor_tg_id,target_tg_id,action,amount,details)
    except Exception as e: print(f"⚠️ audit log: {e}")

def _is_banned_sync(tg_id:int)->bool:
    conn=get_db(); row=conn.execute("SELECT is_banned FROM players WHERE tg_id=?",(int(tg_id),)).fetchone(); conn.close()
    return bool(row and int(row["is_banned"] or 0))



# ==================== CONTAINER / RESALE GAME ====================
# Серверная экономика контейнеров. Добавлена поверх существующего backend,
# без удаления или замены старых механик.

CONTAINER_TYPES = {
    # Current prices are kept as the source of truth for the live RESSELL economy.
    "small_bag": {"name":"SMALL BAG","price":5_000,"multiplier":1.02},
    "delivery_box": {"name":"DELIVERY BOX","price":15_000,"multiplier":1.02},
    "mystery_suitcase": {"name":"MYSTERY SUITCASE","price":35_000,"multiplier":1.02},
    "tech_crate": {"name":"TECH CRATE","price":60_000,"multiplier":1.02},
    "pallet": {"name":"PALLET","price":120_000,"multiplier":1.02},
    "car_load": {"name":"CAR LOAD","price":250_000,"multiplier":1.02},
    "import_container": {"name":"IMPORT CONTAINER","price":500_000,"multiplier":1.02},
    "black_market": {"name":"BLACK MARKET","price":1_000_000,"multiplier":1.02},
}

# Per-container loot pools. Values are calibrated around the CURRENT container prices,
# while rare pools still contain materially larger jackpots. The adaptive controller
# chooses among sampled candidates instead of forcing a flat 3x payout.
CONTAINER_LOOT_BY_TYPE = {
    "small_bag": [
        ("COMMON","Чехол для iPhone","📱",1800,10479), ("COMMON","Наушники","🎧",3000,67064),
        ("UNCOMMON","Умные часы","⌚",6400,25148), ("RARE","AirPods Pro","🎧",12000,22000),
        ("EPIC","PlayStation Portal","🎮",24000,50000),
    ],
    "delivery_box": [
        ("COMMON","Кроссовки","👟",8400,16800), ("COMMON","Худи","🧥",13000,26000),
        ("UNCOMMON","Nike Tech","🥋",21000,42000), ("RARE","iPhone 14","📱",36000,72000),
        ("EPIC","PS5 Slim","🎮",76000,152000), ("LEGENDARY","Золотые часы","⌚",170000,340000),
    ],
    "mystery_suitcase": [
        ("COMMON","Брендовая футболка","👕",18667,37334), ("COMMON","Кроссовки New Drop","👟",25667,51334),
        ("UNCOMMON","Кожаная куртка","🧥",51333,102666), ("RARE","iPhone 15 Pro","📱",98000,196000),
        ("EPIC","MacBook Air","💻",191333,382666), ("LEGENDARY","Rolex Vintage","⌚",513333,900000),
    ],
    "tech_crate": [
        ("COMMON","Игровая мышь","🖱️",30000,60000), ("COMMON","Механическая клавиатура","⌨️",38000,76000),
        ("UNCOMMON","Nintendo Switch","🎮",72000,144000), ("RARE","RTX 4070","🖥️",130000,260000),
        ("EPIC","MacBook Pro","💻",250000,500000), ("LEGENDARY","iPhone 17 Pro Max","📱",480000,960000),
    ],
    "pallet": [
        ("COMMON","Премиум обувь","👟",60000,120000), ("COMMON","Куртка","🧥",84000,168000),
        ("UNCOMMON","PlayStation 5 Pro","🎮",144000,288000), ("RARE","MacBook Pro","💻",270000,540000),
        ("EPIC","iPhone Pro Max Pack","📱",440000,880000), ("LEGENDARY","Luxury Watch","⌚",960000,1500000),
    ],
    "car_load": [
        ("COMMON","Комплект дисков","🛞",130000,260000), ("COMMON","Детейлинг-пакет","🚘",170000,340000),
        ("UNCOMMON","Мотоцикл","🏍️",310000,620000), ("RARE","Volkswagen Golf GTI","🚗",490000,980000),
        ("EPIC","BMW M3","🏎️",920000,1500000), ("LEGENDARY","Mercedes-AMG","🚘",1700000,3000000),
    ],
    "import_container": [
        ("COMMON","Партия одежды","👕",242900,485800), ("COMMON","Партия электроники","📦",300000,600000),
        ("UNCOMMON","MacBook Pack","💻",514300,1028600), ("RARE","iPhone Pack","📱",742900,1485800),
        ("EPIC","Porsche 911","🏎️",1357000,2500000), ("LEGENDARY","Range Rover","🚙",2571000,5000000),
    ],
    "black_market": [
        ("COMMON","Luxury Sneakers","👟",480000,720000), ("COMMON","Gold Accessory","💎",650000,900000),
        ("UNCOMMON","Rolex","⌚",1100000,1500000), ("RARE","Porsche 911","🏎️",1800000,2600000),
        ("EPIC","Mercedes G63","🚙",3200000,4500000), ("LEGENDARY","Lamborghini Huracan","🏎️",6000000,8500000),
        ("MYTHIC","Ferrari SF90","🏎️",12000000,18000000),
    ],
}

CONTAINER_RARITY_SCORE = {
    "COMMON": 0, "UNCOMMON": 1, "RARE": 2, "EPIC": 3, "LEGENDARY": 4, "MYTHIC": 5
}
CONTAINER_DAILY_QUESTS = {
    "open_one": {"name":"Открыть 1 контейнер","target":1,"reward":2_000},
    "sell_three": {"name":"Продать 3 предмета","target":3,"reward":3_000},
    "find_rare": {"name":"Найти RARE или выше","target":1,"reward":5_000},
}
CONTAINER_ECONOMY_TARGET_RTP = 1.05
CONTAINER_ECONOMY_WINDOW = 20

def ensure_container_tables_sync():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS container_purchases (
            id TEXT PRIMARY KEY, player_id INTEGER NOT NULL, container_id TEXT NOT NULL,
            price INTEGER NOT NULL, request_id TEXT UNIQUE NOT NULL, opened INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, opened_at INTEGER,
            FOREIGN KEY(player_id) REFERENCES players(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS container_inventory (
            id TEXT PRIMARY KEY, player_id INTEGER NOT NULL, purchase_id TEXT NOT NULL,
            name TEXT NOT NULL, icon TEXT NOT NULL, rarity TEXT NOT NULL, value INTEGER NOT NULL,
            sold INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, sold_at INTEGER,
            FOREIGN KEY(player_id) REFERENCES players(id), FOREIGN KEY(purchase_id) REFERENCES container_purchases(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS container_daily (
            player_id INTEGER NOT NULL, day_key TEXT NOT NULL, opened_count INTEGER NOT NULL DEFAULT 0,
            sold_count INTEGER NOT NULL DEFAULT 0, rare_found INTEGER NOT NULL DEFAULT 0,
            claimed_open_one INTEGER NOT NULL DEFAULT 0, claimed_sell_three INTEGER NOT NULL DEFAULT 0,
            claimed_find_rare INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(player_id, day_key), FOREIGN KEY(player_id) REFERENCES players(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS container_economy (
            player_id INTEGER PRIMARY KEY, opens INTEGER NOT NULL DEFAULT 0,
            spent INTEGER NOT NULL DEFAULT 0, payout INTEGER NOT NULL DEFAULT 0,
            loss_streak INTEGER NOT NULL DEFAULT 0, profit_streak INTEGER NOT NULL DEFAULT 0,
            luck_score REAL NOT NULL DEFAULT 0, updated_at INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(player_id) REFERENCES players(id)
        )
    """)
    conn.commit(); conn.close()

def _container_player_sync(tg_id: int) -> int:
    conn=get_db(); row=conn.execute("SELECT id FROM players WHERE tg_id=?",(int(tg_id),)).fetchone(); conn.close()
    return int(row["id"]) if row else int(get_or_create_player("tg",int(tg_id)))

def _container_clamp(v,lo,hi):
    return max(lo,min(hi,v))

def _container_pick_loot(container_id: str, player_id: int, cur) -> dict:
    """Adaptive, server-authoritative container payout controller.

    It uses the current container price, player-specific historical RTP, loss/profit
    streaks and luck to choose one of sampled candidates. This avoids the legacy
    all-container random pool where the most expensive container could return a tiny
    3k-ish margin, while preserving rare multi-x jackpots.
    """
    ensure_row = cur.execute("SELECT * FROM container_economy WHERE player_id=?",(player_id,)).fetchone()
    if not ensure_row:
        cur.execute("INSERT OR IGNORE INTO container_economy(player_id,updated_at) VALUES(?,?)",(player_id,int(time_module.time())))
        ensure_row=cur.execute("SELECT * FROM container_economy WHERE player_id=?",(player_id,)).fetchone()
    row=ensure_row
    opens=int(row["opens"] or 0); spent=int(row["spent"] or 0); payout=int(row["payout"] or 0)
    loss_streak=int(row["loss_streak"] or 0); profit_streak=int(row["profit_streak"] or 0); luck=float(row["luck_score"] or 0)
    price=int(CONTAINER_TYPES[container_id]["price"])
    pool=CONTAINER_LOOT_BY_TYPE[container_id]
    historical_rtp=payout/spent if spent>0 else CONTAINER_ECONOMY_TARGET_RTP
    correction=_container_clamp((CONTAINER_ECONOMY_TARGET_RTP-historical_rtp)*0.75,-0.12,0.18)
    pity=min(0.24,loss_streak*0.055)
    profit_penalty=min(0.08,profit_streak*0.018)
    target_mult=_container_clamp(CONTAINER_ECONOMY_TARGET_RTP+correction+pity-profit_penalty+luck*0.04,0.90,1.24)
    if loss_streak>=2: floor_mult=1.00
    elif loss_streak>=1: floor_mult=0.90
    else: floor_mult=0.0
    rng=random.SystemRandom(); candidates=[]
    for rarity,name,icon,min_v,max_v in pool:
        for _ in range(4):
            value=rng.randint(int(min_v),int(max_v)); ratio=value/max(1.0,price)
            if floor_mult and ratio<floor_mult: continue
            distance=abs(ratio-target_mult)
            rarity_bonus=CONTAINER_RARITY_SCORE.get(rarity,0)*0.018
            jitter=rng.random()*0.08
            score=(1.0/(0.035+distance))+rarity_bonus+jitter
            candidates.append((score,value,rarity,name,icon))
    if not candidates:
        for rarity,name,icon,min_v,max_v in pool:
            value=max(int(min_v),int(round(price*max(floor_mult,0.90))))
            value=min(value,int(max_v)); candidates.append((1.0/(0.035+abs(value/max(1.0,price)-target_mult)),value,rarity,name,icon))
    candidates.sort(key=lambda x:x[0],reverse=True)
    top=candidates[:min(4,len(candidates))]
    _,value,rarity,name,icon=top[rng.randrange(len(top))]
    effective_ratio=value/max(1.0,price)
    new_loss=loss_streak+1 if effective_ratio<1.0 else 0
    new_profit=profit_streak+1 if effective_ratio>=1.0 else 0
    new_luck=_container_clamp(luck+(0.035 if effective_ratio<1.0 else -0.025),-0.18,0.35)
    cur.execute("""UPDATE container_economy SET opens=opens+1, spent=spent+?, payout=payout+?,
        loss_streak=?, profit_streak=?, luck_score=?, updated_at=? WHERE player_id=?""",
        (price,int(value),new_loss,new_profit,new_luck,int(time_module.time()),player_id))
    return {"name":name,"icon":icon,"rarity":rarity,"value":int(value),
            "algorithm":{"target_rtp":round(target_mult,4),"historical_rtp":round(historical_rtp,4),"loss_streak":new_loss,"luck":round(new_luck,4)}}

def _container_day_key():
    return datetime.now().strftime("%Y-%m-%d")

def _container_daily_sync(cur, player_id: int):
    day = _container_day_key()
    cur.execute(
        "INSERT OR IGNORE INTO container_daily(player_id,day_key) VALUES(?,?)",
        (player_id, day)
    )
    return day

async def _container_activate_referral(tg_id: int, source: str):
    try:
        await activate_pending_referral(int(tg_id), source)
    except Exception as exc:
        print(f"[container referral] {exc}")

@app.get("/container/state")
async def container_state(tg_id: int):
    try:
        ensure_container_tables_sync()
        player_id = await get_player_id_by_tg(int(tg_id))
        if not player_id:
            player_id = await run_sync_db(get_or_create_player, "tg", int(tg_id))
        def _read():
            conn=get_db(); cur=conn.cursor()
            day=_container_day_key()
            cur.execute("INSERT OR IGNORE INTO container_daily(player_id,day_key) VALUES(?,?)",(player_id,day))
            row=cur.execute("SELECT * FROM container_daily WHERE player_id=? AND day_key=?",(player_id,day)).fetchone()
            prow=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
            inv=cur.execute("SELECT id,name,icon,rarity,value FROM container_inventory WHERE player_id=? AND sold=0 ORDER BY created_at DESC LIMIT 30",(player_id,)).fetchall()
            conn.commit(); conn.close()
            d=dict(row) if row else {}
            return {"balance":int(prow["balance"] if prow else 0),"daily":d,
                    "inventory":[dict(x) for x in inv],
                    "containers":CONTAINER_TYPES}
        return JSONResponse({"success":True,**await run_sync_db(_read)})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/container/buy")
async def container_buy(request: Request):
    try:
        data=await request.json()
        tg_id=int(data.get("tg_id") or data.get("userId") or 0)
        container_id=str(data.get("container_id") or "")
        request_id=str(data.get("request_id") or "").strip()[:128]
        if not tg_id or container_id not in CONTAINER_TYPES or not request_id:
            return JSONResponse({"success":False,"error":"Некорректные данные"},status_code=400)
        player_id=await get_player_id_by_tg(tg_id)
        if not player_id:
            player_id=await run_sync_db(get_or_create_player,"tg",tg_id)
        lock=player_action_locks.setdefault(f"container:{player_id}",asyncio.Lock())
        async with lock:
            async with db_lock:
                def _buy():
                    ensure_container_tables_sync()
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        dup=cur.execute("SELECT id FROM container_purchases WHERE request_id=?",(request_id,)).fetchone()
                        if dup:
                            prow=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                            conn.commit()
                            return {"purchase_id":dup["id"],"balance":int(prow["balance"])}
                        price=CONTAINER_TYPES[container_id]["price"]
                        prow=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                        balance=int(prow["balance"] if prow else 0)
                        if balance<price:
                            conn.rollback(); return {"error":"Недостаточно коинов"}
                        new_balance=balance-price
                        purchase_id=uuid.uuid4().hex
                        cur.execute("UPDATE players SET balance=? WHERE id=?",(new_balance,player_id))
                        cur.execute("""INSERT INTO container_purchases(id,player_id,container_id,price,request_id,created_at)
                                       VALUES(?,?,?,?,?,?)""",
                                    (purchase_id,player_id,container_id,price,request_id,int(time_module.time())))
                        conn.commit()
                        return {"purchase_id":purchase_id,"balance":new_balance,"price":price}
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                result=await asyncio.to_thread(_buy)
        if result.get("error"):
            return JSONResponse({"success":False,**result},status_code=400)
        await _container_activate_referral(tg_id,"container_buy")
        return JSONResponse({"success":True,**result})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/container/open")
async def container_open(request: Request):
    try:
        data=await request.json()
        tg_id=int(data.get("tg_id") or data.get("userId") or 0)
        purchase_id=str(data.get("purchase_id") or "")
        if not tg_id or not purchase_id:
            return JSONResponse({"success":False,"error":"Некорректные данные"},status_code=400)
        player_id=await get_player_id_by_tg(tg_id)
        if not player_id:
            return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
        lock=player_action_locks.setdefault(f"container:{player_id}",asyncio.Lock())
        async with lock:
            async with db_lock:
                def _open():
                    ensure_container_tables_sync()
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        p=cur.execute("SELECT * FROM container_purchases WHERE id=? AND player_id=?",(purchase_id,player_id)).fetchone()
                        if not p:
                            conn.rollback(); return {"error":"Покупка не найдена"}
                        if int(p["opened"]):
                            it=cur.execute("SELECT * FROM container_inventory WHERE purchase_id=?",(purchase_id,)).fetchone()
                            prow=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                            conn.commit()
                            return {"already":True,"balance":int(prow["balance"]), "item":dict(it) if it else None}
                        item=_container_pick_loot(p["container_id"],player_id,cur)
                        item_id=uuid.uuid4().hex
                        now=int(time_module.time())
                        cur.execute("UPDATE container_purchases SET opened=1,opened_at=? WHERE id=?",(now,purchase_id))
                        cur.execute("""INSERT INTO container_inventory(id,player_id,purchase_id,name,icon,rarity,value,created_at)
                                       VALUES(?,?,?,?,?,?,?,?)""",
                                    (item_id,player_id,purchase_id,item["name"],item["icon"],item["rarity"],item["value"],now))
                        day=_container_day_key()
                        cur.execute("""INSERT OR IGNORE INTO container_daily(player_id,day_key) VALUES(?,?)""",(player_id,day))
                        rare=1 if CONTAINER_RARITY_SCORE[item["rarity"]] >= 2 else 0
                        cur.execute("""UPDATE container_daily SET opened_count=opened_count+1,rare_found=rare_found+? WHERE player_id=? AND day_key=?""",(rare,player_id,day))
                        cur.execute("SELECT balance FROM players WHERE id=?",(player_id,))
                        balance=int(cur.fetchone()["balance"])
                        conn.commit()
                        return {"already":False,"balance":balance,"item":{**item,"id":item_id}}
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                result=await asyncio.to_thread(_open)
        if result.get("error"): return JSONResponse({"success":False,**result},status_code=400)
        if not result.get("already"):
            await _container_activate_referral(tg_id,"container_open")
            await run_sync_db(update_daily_quest, player_id, "open_case", 1)
            rarity=result["item"]["rarity"]
            if CONTAINER_RARITY_SCORE[rarity]>=2:
                await run_sync_db(update_daily_quest, player_id, "find_rare", 1)
        return JSONResponse({"success":True,**result})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/container/sell")
async def container_sell(request: Request):
    try:
        data=await request.json()
        tg_id=int(data.get("tg_id") or data.get("userId") or 0)
        item_id=str(data.get("item_id") or "")
        request_id=str(data.get("request_id") or uuid.uuid4().hex)
        if not tg_id or not item_id:
            return JSONResponse({"success":False,"error":"Некорректные данные"},status_code=400)
        player_id=await get_player_id_by_tg(tg_id)
        if not player_id: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
        lock=player_action_locks.setdefault(f"container:{player_id}",asyncio.Lock())
        async with lock:
            async with db_lock:
                def _sell():
                    ensure_container_tables_sync()
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        # idempotent: если item уже продан, возвращаем текущий баланс.
                        it=cur.execute("SELECT * FROM container_inventory WHERE id=? AND player_id=?",(item_id,player_id)).fetchone()
                        if not it: conn.rollback(); return {"error":"Предмет не найден"}
                        if int(it["sold"]):
                            prow=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                            conn.commit(); return {"already":True,"balance":int(prow["balance"])}
                        value=int(it["value"])
                        value=boost_referral_income(value, player_id)
                        now=int(time_module.time())
                        cur.execute("UPDATE container_inventory SET sold=1,sold_at=? WHERE id=?",(now,item_id))
                        cur.execute("UPDATE players SET balance=balance+?, total_earned=total_earned+?, stat_earned_today=stat_earned_today+? WHERE id=?",(value,value,value,player_id))
                        day=_container_day_key()
                        cur.execute("INSERT OR IGNORE INTO container_daily(player_id,day_key) VALUES(?,?)",(player_id,day))
                        cur.execute("UPDATE container_daily SET sold_count=sold_count+1 WHERE player_id=? AND day_key=?",(player_id,day))
                        prow=cur.execute("SELECT balance,total_earned FROM players WHERE id=?",(player_id,)).fetchone()
                        conn.commit()
                        return {"already":False,"value":value,"balance":int(prow["balance"]),"total_earned":int(prow["total_earned"])}
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                result=await asyncio.to_thread(_sell)
        if result.get("error"): return JSONResponse({"success":False,**result},status_code=400)
        return JSONResponse({"success":True,**result})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.get("/container/quests")
async def container_quests(tg_id: int):
    try:
        player_id=await get_player_id_by_tg(int(tg_id))
        if not player_id: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
        ensure_container_tables_sync()
        def _q():
            conn=get_db(); cur=conn.cursor(); day=_container_day_key()
            cur.execute("INSERT OR IGNORE INTO container_daily(player_id,day_key) VALUES(?,?)",(player_id,day))
            row=cur.execute("SELECT * FROM container_daily WHERE player_id=? AND day_key=?",(player_id,day)).fetchone()
            conn.commit(); conn.close(); d=dict(row)
            return [
                {"id":"open_one","name":CONTAINER_DAILY_QUESTS["open_one"]["name"],"progress":min(d["opened_count"],1),"target":1,"reward":2000,"claimed":bool(d["claimed_open_one"])},
                {"id":"sell_three","name":CONTAINER_DAILY_QUESTS["sell_three"]["name"],"progress":min(d["sold_count"],3),"target":3,"reward":3000,"claimed":bool(d["claimed_sell_three"])},
                {"id":"find_rare","name":CONTAINER_DAILY_QUESTS["find_rare"]["name"],"progress":min(d["rare_found"],1),"target":1,"reward":5000,"claimed":bool(d["claimed_find_rare"])},
            ]
        return JSONResponse({"success":True,"quests":await run_sync_db(_q)})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/container/quests/claim")
async def container_quest_claim(request: Request):
    try:
        data=await request.json(); tg_id=int(data.get("tg_id") or data.get("userId") or 0); quest_id=str(data.get("quest_id") or "")
        player_id=await get_player_id_by_tg(tg_id)
        if not player_id or quest_id not in CONTAINER_DAILY_QUESTS: return JSONResponse({"success":False,"error":"Некорректный запрос"},status_code=400)
        async with db_lock:
            def _claim():
                ensure_container_tables_sync()
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE"); day=_container_day_key()
                    cur.execute("INSERT OR IGNORE INTO container_daily(player_id,day_key) VALUES(?,?)",(player_id,day))
                    row=cur.execute("SELECT * FROM container_daily WHERE player_id=? AND day_key=?",(player_id,day)).fetchone()
                    q=CONTAINER_DAILY_QUESTS[quest_id]
                    progress={"open_one":int(row["opened_count"]),"sell_three":int(row["sold_count"]),"find_rare":int(row["rare_found"])}[quest_id]
                    flag={"open_one":"claimed_open_one","sell_three":"claimed_sell_three","find_rare":"claimed_find_rare"}[quest_id]
                    if progress<q["target"] or int(row[flag]): conn.rollback(); return {"error":"Квест ещё не готов"}
                    cur.execute(f"UPDATE container_daily SET {flag}=1 WHERE player_id=? AND day_key=?",(player_id,day))
                    cur.execute("UPDATE players SET balance=balance+?, total_earned=total_earned+?, stat_earned_today=stat_earned_today+? WHERE id=?",(q["reward"],q["reward"],q["reward"],player_id))
                    prow=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                    conn.commit(); return {"reward":q["reward"],"balance":int(prow["balance"])}
                except Exception: conn.rollback(); raise
                finally: conn.close()
            result=await asyncio.to_thread(_claim)
        if result.get("error"): return JSONResponse({"success":False,**result},status_code=400)
        return JSONResponse({"success":True,**result})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)



from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import parse_qsl, unquote_plus, unquote

@app.middleware("http")
async def api_prefix_compat(request:Request, call_next):
    path=request.scope.get("path","")
    if path.startswith("/api/") and path!="/api/health":
        original=path;request.scope["path"]=path[4:]
        try:return await call_next(request)
        finally:request.scope["path"]=original
    if path=="/api/health":
        request.scope["path"]="/health"
        try:return await call_next(request)
        finally:request.scope["path"]=path
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://ruslangodunov66-alt.github.io",
        "https://resellgame.bothost.tech",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== HTTP ОБРАБОТЧИКИ (FASTAPI) ====================
@app.get("/")
async def root():
    return JSONResponse({"message": "✅ Бот работает! Используйте /api/player для данных."})

@app.get("/health")
async def health():
    try:
        def _db_ping():
            conn=get_db()
            try: conn.execute("SELECT 1").fetchone(); return True
            finally: conn.close()
        ok=await run_sync_db(_db_ping)
        return JSONResponse({"ok":bool(ok),"service":"resell-api","ts":int(time_module.time())})
    except Exception as e:
        return JSONResponse({"ok":False,"service":"resell-api","error":str(e)},status_code=503)

@app.get("/api/health")
async def api_health():
    return await health()

@app.post("/game_result")
async def game_result(request: Request):
    try:
        data=await request.json()
        tg_id=data.get("userId") or data.get("user_id")
        result=str(data.get("result","")).lower().strip()
        bet=int(data.get("bet",0)); win=int(data.get("win",0)); game=str(data.get("game","unknown"))[:40]
        request_id=str(data.get("request_id") or data.get("round_id") or "").strip()[:128]
        if not tg_id or result not in {"win","lose"} or bet<0 or win<0 or (result=="lose" and bet<=0):
            return JSONResponse({"error":"Некорректные данные игры"},status_code=400)
        player_id=await get_player_id_by_tg(int(tg_id))
        if not player_id:
            player_id=await run_sync_db(get_or_create_player,"tg",int(tg_id))
        if not player_id:
            return JSONResponse({"error":"Player not found"},status_code=404)
        key=f"game:{request_id}" if request_id else _request_fingerprint("game_result",int(tg_id),game,result,bet,win,bucket_seconds=2)
        if not await run_sync_db(claim_request_once_sync,key,"game_result",player_id,86400):
            current=await run_sync_db(get_player_data,player_id) or {}
            return JSONResponse({"status":"duplicate","new_balance":int(current.get("balance",0) or 0),"game":game,"result":result},status_code=409)
        lock=player_action_locks.setdefault(f"tg:{int(player_id)}",asyncio.Lock())
        async with lock:
            async with db_lock:
                def _update():
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        row=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                        if not row:
                            conn.rollback(); return None
                        current=int(row["balance"] or 0)
                        if result=="win":
                            new_balance=current+win
                        else:
                            if current<bet:
                                conn.rollback(); return ("funds",current)
                            new_balance=current-bet
                        cur.execute("UPDATE players SET balance=?,casino_games_played=casino_games_played+1 WHERE id=?",(new_balance,player_id))
                        if result=="win":
                            cur.execute("UPDATE players SET casino_wins=casino_wins+1,casino_total_win=casino_total_win+? WHERE id=?",(win,player_id))
                        else:
                            cur.execute("UPDATE players SET casino_losses=casino_losses+1 WHERE id=?",(player_id,))
                        if bet>0: cur.execute("UPDATE players SET casino_total_bet=casino_total_bet+? WHERE id=?",(bet,player_id))
                        conn.commit(); return ("ok",new_balance)
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                res=await run_sync_db(_update)
        if res is None: return JSONResponse({"error":"Player not found"},status_code=404)
        if res[0]=="funds": return JSONResponse({"status":"rejected","error":"Недостаточно средств в казино","new_balance":res[1]},status_code=400)
        await activate_pending_referral(int(tg_id), "casino_game")
        return JSONResponse({"status":"ok","new_balance":res[1],"game":game,"result":result})
    except Exception as e:
        print(f"❌ Ошибка в /game_result: {e}")
        return JSONResponse({"error":str(e)},status_code=500)

@app.post("/buy-case")
async def buy_case(request: Request):
    try:
        data=await request.json(); tg_id=data.get("userId") or data.get("user_id"); amount=int(data.get("amount",0))
        request_id=str(data.get("request_id") or data.get("round_id") or "").strip()[:128]
        if not tg_id or amount<=0: return JSONResponse({"success":False,"error":"Invalid data"},status_code=400)
        player_id=await get_player_id_by_tg(int(tg_id))
        if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
        key=f"buy-case:{request_id}" if request_id else _request_fingerprint("buy_case",int(tg_id),amount,bucket_seconds=2)
        if not await run_sync_db(claim_request_once_sync,key,"buy-case",player_id,86400):
            return JSONResponse({"success":False,"duplicate":True,"error":"Повторный запрос уже обработан"},status_code=409)
        round_id=request_id or uuid.uuid4().hex
        lock=player_action_locks.setdefault(f"tg:{int(player_id)}",asyncio.Lock())
        async with lock:
            async with db_lock:
                def _buy():
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        open_row=cur.execute("SELECT round_id FROM case_rounds WHERE player_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",(player_id,)).fetchone()
                        if open_row: conn.rollback(); return ("open",open_row["round_id"])
                        cur.execute("UPDATE players SET balance=balance-? WHERE id=? AND balance>=?",(amount,player_id,amount))
                        if cur.rowcount!=1: conn.rollback(); return ("funds",None)
                        cur.execute("INSERT INTO case_rounds(round_id,player_id,stake,status,created_at,paid_amount) VALUES(?,?,?,?,?,0)",(round_id,player_id,amount,"open",int(time_module.time())))
                        bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone(); conn.commit(); return ("ok",int(bal["balance"] if bal else 0),round_id)
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                res=await run_sync_db(_buy)
        if res[0]=="open": return JSONResponse({"success":False,"error":"Сначала завершите текущий кейс","round_id":res[1]},status_code=409)
        if res[0]=="funds": return JSONResponse({"success":False,"error":"Недостаточно средств в казино"},status_code=400)
        await activate_pending_referral(int(tg_id), "case_purchase")
        return JSONResponse({"success":True,"new_balance":res[1],"round_id":res[2],"message":f"Кейс куплен за {amount}₽"})
    except Exception as e:
        print(f"❌ Ошибка в /buy-case: {e}"); return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/case-win")
async def case_win(request: Request):
    try:
        data=await request.json(); tg_id=data.get("userId") or data.get("user_id"); amount=int(data.get("amount",0))
        round_id=str(data.get("round_id") or data.get("request_id") or "").strip()[:128]
        if not tg_id or amount<=0: return JSONResponse({"success":False,"error":"Invalid data"},status_code=400)
        player_id=await get_player_id_by_tg(int(tg_id))
        if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
        lock=player_action_locks.setdefault(f"tg:{int(player_id)}",asyncio.Lock())
        async with lock:
            async with db_lock:
                def _win():
                    conn=get_db(); cur=conn.cursor()
                    try:
                        cur.execute("BEGIN IMMEDIATE")
                        if round_id: row=cur.execute("SELECT round_id,stake,status FROM case_rounds WHERE round_id=? AND player_id=?",(round_id,player_id)).fetchone()
                        else: row=cur.execute("SELECT round_id,stake,status FROM case_rounds WHERE player_id=? AND status='open' ORDER BY created_at DESC LIMIT 1",(player_id,)).fetchone()
                        if not row: conn.rollback(); return ("missing",None)
                        if row["status"]!="open": conn.rollback(); return ("paid",row["round_id"])
                        max_win=int(row["stake"])*100
                        if amount>max_win: conn.rollback(); return ("limit",int(row["stake"]))
                        cur.execute("UPDATE case_rounds SET status='paid',paid_amount=? WHERE round_id=? AND status='open'",(amount,row["round_id"]))
                        if cur.rowcount!=1: conn.rollback(); return ("paid",row["round_id"])
                        cur.execute("UPDATE players SET balance=balance+? WHERE id=?",(amount,player_id))
                        bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone(); conn.commit(); return ("ok",int(bal["balance"] if bal else 0),row["round_id"])
                    except Exception:
                        conn.rollback(); raise
                    finally: conn.close()
                res=await run_sync_db(_win)
        if res[0]=="missing": return JSONResponse({"success":False,"error":"Активный кейс не найден"},status_code=409)
        if res[0]=="paid": return JSONResponse({"success":False,"duplicate":True,"error":"Выигрыш уже начислен","round_id":res[1]},status_code=409)
        if res[0]=="limit": return JSONResponse({"success":False,"error":f"Выигрыш превышает лимит x100 для ставки {res[1]}₽"},status_code=400)
        return JSONResponse({"success":True,"new_balance":res[1],"round_id":res[2],"message":f"Выигрыш {amount}₽ начислен"})
    except Exception as e:
        print(f"❌ Ошибка в /case-win: {e}"); return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/deposit")
async def deposit(request: Request):
    try:
        data=await request.json(); tg_id=data.get("userId") or data.get("user_id")
        if not tg_id: return JSONResponse({"success":False,"error":"Invalid data"},status_code=400)
        player_id=await get_player_id_by_tg(int(tg_id))
        if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
        player=await run_sync_db(get_player_data,player_id) or {}
        balance=int(player.get("balance",0) or 0)
        return JSONResponse({"success":True,"balance":balance,"main_balance":balance,"message":"Используется единый баланс."})
    except Exception as e:
        return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.post("/withdraw")
async def withdraw(request: Request):
    try:
        data=await request.json(); tg_id=data.get("userId") or data.get("user_id")
        if not tg_id: return JSONResponse({"success":False,"error":"Invalid data"},status_code=400)
        player_id=await get_player_id_by_tg(int(tg_id))
        if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
        player=await run_sync_db(get_player_data,player_id) or {}
        balance=int(player.get("balance",0) or 0)
        return JSONResponse({"success":True,"balance":balance,"main_balance":balance,"message":"Используется единый баланс."})
    except Exception as e:
        print(f"Ошибка в /withdraw: {e}"); return JSONResponse({"success":False,"error":str(e)},status_code=500)

@app.get("/referrals/preview/{tg_id}")
async def referral_preview(tg_id: int, request: Request, referrer_id: str = ""):
    if not _verify_telegram_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    token=str(referrer_id or "").strip()
    inviter_tg=await run_sync_db(resolve_referrer_token,token) if token else None
    if not inviter_tg or int(inviter_tg)==int(tg_id):
        return JSONResponse({"success":True,"has_referrer":False})
    inviter_player_id=await get_player_id_by_tg(int(inviter_tg))
    inviter_player=await run_sync_db(get_player_data,inviter_player_id) if inviter_player_id else None
    if not inviter_player:
        return JSONResponse({"success":True,"has_referrer":False})
    return JSONResponse({"success":True,"has_referrer":True,"invited_by":{"id":int(inviter_tg),"nickname":str(inviter_player.get("nickname") or "Игрок")},"inviter_reward":REFERRAL_DIRECT_REWARD,"invitee_reward":REFERRAL_INVITEE_BONUS})

@app.post("/register/{tg_id}")
async def register_webapp(tg_id: int, request: Request):
    """Create the RESSELL profile from the Telegram Mini App.

    Registration is bound to the signed Telegram initData. A valid referral is
    activated in the same request, so both sides receive their registration reward
    immediately and exactly once.
    """
    if not _verify_telegram_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try:
        data=await request.json()
    except Exception:
        data={}
    nickname=str(data.get("nickname") or "").strip().lstrip("@").strip()
    shop_name=str(data.get("shop_name") or "").strip()
    referrer_id=str(data.get("referrer_id") or data.get("ref") or "").strip()
    if len(nickname)<2: return JSONResponse({"success":False,"error":"Минимум 2 символа!"},status_code=400)
    if len(nickname)>20: return JSONResponse({"success":False,"error":"Максимум 20 символов!"},status_code=400)
    if len(shop_name)<2: return JSONResponse({"success":False,"error":"Минимум 2 символа!"},status_code=400)
    if len(shop_name)>30: return JSONResponse({"success":False,"error":"Максимум 30 символов!"},status_code=400)

    player_id=await get_player_id_by_tg(tg_id)
    if not player_id:
        player_id=await run_sync_db(get_or_create_player,"tg",tg_id)
    if not player_id:
        return JSONResponse({"success":False,"error":"Не удалось создать профиль"},status_code=500)
    existing=await run_sync_db(find_user_by_nickname,nickname)
    if existing and int(existing["id"])!=int(player_id):
        return JSONResponse({"success":False,"error":"Этот никнейм уже занят"},status_code=400)
    ok,msg=await set_nickname(tg_id,nickname)
    if not ok: return JSONResponse({"success":False,"error":msg or "Не удалось сохранить никнейм"},status_code=400)
    ok,msg=await set_shop_name(tg_id,shop_name)
    if not ok: return JSONResponse({"success":False,"error":msg or "Не удалось сохранить название магазина"},status_code=400)
    language = str(data.get("language") or "ru").strip().lower()
    if language not in {"ru","en"}: language = "ru"
    def _save_language():
        conn=get_db(); conn.execute("UPDATE players SET language=? WHERE id=?",(language,int(player_id))); conn.commit(); conn.close()
    await run_sync_db(_save_language)

    incoming=referrer_id[4:] if referrer_id.startswith("ref_") else referrer_id
    if incoming:
        try:
            inviter_id=await run_sync_db(resolve_referrer_token,incoming)
            if inviter_id and int(inviter_id)!=int(tg_id):
                await run_sync_db(set_pending_referral,int(tg_id),int(inviter_id),"webapp_registration")
        except Exception as exc:
            print(f"⚠️ WebApp referral registration: {exc}")

    referral_result={"activated":False,"reason":"no_pending"}
    try:
        referral_result=await activate_pending_referral(int(tg_id),"webapp_registration", immediate=True)
    except Exception as exc:
        print(f"⚠️ Referral activation: {exc}")

    return JSONResponse({"success":True,"message":"Аккаунт RESSELL создан","nickname":nickname,"shop_name":shop_name,"referral":referral_result})

@app.middleware("http")
async def audit_and_ban_middleware(request:Request,call_next):
    # Match the previously working RESSELL behaviour: this global middleware
    # must NOT reject ordinary player GET requests based on Telegram initData.
    # Route-level checks remain untouched for sensitive operations.
    path=request.url.path
    target=None
    if not path.startswith('/admin/'):
        prefixes=(
            '/profile/','/hold/','/business/','/upgrades/','/passive/',
            '/quests/','/epoch/','/referrals/','/referral/','/engagement/',
            '/tycoon/','/avito/','/rcoin/'
        )
        for prefix in prefixes:
            if path.startswith(prefix):
                tail=path[len(prefix):].split('/')[0]
                if tail.isdigit(): target=int(tail)
                break
        if target and await run_sync_db(_is_banned_sync,target):
            return JSONResponse({"success":False,"error":"Аккаунт заблокирован администратором","banned":True},status_code=403)
    response=await call_next(request)
    try:
        if target and request.method in ('POST','PUT','PATCH') and response.status_code < 500:
            await audit(None,target,f"api:{request.method} {path.split('?')[0]}")
    except Exception:
        pass
    return response

@app.get("/auth/telegram-check/{tg_id}")
async def telegram_auth_check(tg_id:int, request:Request):
    ok,reason=_telegram_verify_reason(request,tg_id)
    return JSONResponse({"success":bool(ok),"authenticated":bool(ok),"reason":reason})

@app.get("/moderation/status/{tg_id}")
async def moderation_status(tg_id:int,request:Request):
    if not _verify_telegram_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    return JSONResponse({"success":True,**(await run_sync_db(_ban_status_sync,tg_id))})

@app.post("/moderation/appeal/{tg_id}")
async def moderation_appeal(tg_id:int,request:Request):
    if not _verify_telegram_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    text=str(data.get("text") or "").strip()
    if len(text)<20 or len(text)>2000: return JSONResponse({"success":False,"error":"Текст апелляции должен быть от 20 до 2000 символов."},status_code=400)
    r=await run_sync_db(_submit_ban_appeal_sync,tg_id,text)
    if not r.get("ok"): return JSONResponse({"success":False,"error":"Апелляция уже подана или аккаунт не заблокирован."},status_code=400)
    try: await bot.send_message(int(ADMIN_SUPER_ID),f"📝 Новая апелляция\nИгрок: <code>{int(tg_id)}</code>\nID: <code>{int(r['appeal_id'])}</code>\n\n{escape(text[:1800])}",parse_mode="HTML")
    except Exception: pass
    return JSONResponse({"success":True,**r})

@app.get("/admin/appeals/{admin_tg_id}")
async def admin_appeals(admin_tg_id:int,status:str="pending",limit:int=50):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    try:
        await run_sync_db(_ensure_moderation_schema_sync)
        rows=await run_sync_db(_admin_appeals_sync,status,min(max(int(limit),1),100))
        return JSONResponse({"success":True,"appeals":rows})
    except Exception as exc:
        print(f"[admin appeals] {exc}")
        return JSONResponse({"success":False,"error":"Не удалось загрузить обращения","detail":str(exc)[:500]},status_code=500)

@app.post("/admin/appeal/{admin_tg_id}/{appeal_id}/resolve")
async def admin_appeal_resolve(admin_tg_id:int,appeal_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    try: data=await request.json()
    except Exception: data={}
    r=await run_sync_db(_resolve_ban_appeal_sync,appeal_id,admin_tg_id,data.get("decision"),data.get("note"))
    if not r.get("ok"): return JSONResponse({"success":False,"error":"Не удалось обработать обращение."},status_code=400)
    try: await bot.send_message(int(r["tg_id"]),f"📨 Апелляция рассмотрена.\nРешение: {('разблокировка' if r['status']=='approved' else 'бан оставлен')}\n{escape(str(r.get('note') or ''))}",parse_mode="HTML")
    except Exception: pass
    await audit(admin_tg_id,r["tg_id"],"appeal_resolved",0,r["status"]); return JSONResponse({"success":True,**r})

# ==================== RCOIN WEB API ====================
def _normalize_ton_address(value: str) -> str:
    value = str(value or "").strip()
    if len(value) > 128: return ""
    if re.fullmatch(r"-?\d:[0-9a-fA-F]{64}", value): return value.lower()
    if re.fullmatch(r"[A-Za-z0-9_-]{48}", value): return value
    return ""

def _rcoin_status_sync(player_id: int) -> dict:
    conn = get_db()
    try:
        p = conn.execute("SELECT total_earned FROM players WHERE id=?", (player_id,)).fetchone()
        if not p: return {}
        total_earned = max(0, int(p["total_earned"] or 0))
        eligible_tokens = total_earned // RCOIN_POINTS_PER_TOKEN
        expected_raw = eligible_tokens * (10 ** RCOIN_DECIMALS)
        allocated = conn.execute("SELECT COALESCE(SUM(token_raw),0) raw FROM rcoin_ledger WHERE player_id=? AND action='allocated'", (player_id,)).fetchone()
        allocated_raw = max(0, int(allocated["raw"] or 0))
        if expected_raw > allocated_raw:
            now = int(time_module.time())
            delta_raw = expected_raw - allocated_raw
            delta_points = (delta_raw * RCOIN_POINTS_PER_TOKEN) // (10 ** RCOIN_DECIMALS)
            conn.execute("INSERT INTO rcoin_ledger(player_id,action,points,token_raw,reason,created_at) VALUES(?,?,?,?,?,?)", (player_id,"allocated",delta_points,delta_raw,"lifetime earned allocation",now))
            conn.commit(); allocated_raw = expected_raw
        claimed = conn.execute("SELECT COALESCE(SUM(token_raw),0) raw FROM rcoin_ledger WHERE player_id=? AND action='claimed'", (player_id,)).fetchone()
        claimed_raw = max(0, int(claimed["raw"] or 0))
        available_raw = max(0, allocated_raw - claimed_raw)
        wallet = conn.execute("SELECT wallet_address,network,verified,updated_at FROM rcoin_wallets WHERE player_id=?", (player_id,)).fetchone()
        scale = 10 ** RCOIN_DECIMALS
        return {"symbol":RCOIN_SYMBOL,"network":RCOIN_NETWORK,"testnet_only":bool(RCOIN_TESTNET_ONLY),"jetton_master":RCOIN_JETTON_MASTER,"decimals":RCOIN_DECIMALS,"points_per_token":RCOIN_POINTS_PER_TOKEN,"total_earned_points":total_earned,"allocated_raw":allocated_raw,"claimed_raw":claimed_raw,"available_raw":available_raw,"allocated_tokens":allocated_raw/scale,"claimed_tokens":claimed_raw/scale,"available_tokens":available_raw/scale,"wallet":dict(wallet) if wallet else None,"claim_enabled":False}
    finally: conn.close()

def _rcoin_wallet_connect_sync(player_id:int,address:str,network:str)->dict:
    address=_normalize_ton_address(address); network=str(network or "").strip().lower()
    if not address or network not in {"testnet","mainnet"}: return {"success":False,"error":"Некорректный TON-кошелёк или сеть"}
    if RCOIN_NETWORK == "testnet" and network != "testnet": return {"success":False,"error":"RCOIN сейчас работает только в Testnet"}
    now=int(time_module.time()); conn=get_db()
    try:
        conn.execute("""INSERT INTO rcoin_wallets(player_id,wallet_address,network,verified,connected_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET wallet_address=excluded.wallet_address,network=excluded.network,verified=0,updated_at=excluded.updated_at""",(player_id,address,network,0,now,now))
        conn.commit(); return {"success":True,"wallet":{"wallet_address":address,"network":network,"verified":False}}
    finally: conn.close()

@app.get("/tonconnect-manifest.json")
async def tonconnect_manifest():
    return JSONResponse({"url":BASE_WEBAPP_URL,"name":"RESSELL","iconUrl":f"{BASE_WEBAPP_URL.rstrip('/')}/rcoin-icon.svg"})

@app.get("/rcoin/status/{tg_id}")
async def rcoin_status(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: pid=await run_sync_db(get_or_create_player,"tg",tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    return JSONResponse({"success":True,**(await run_sync_db(_rcoin_status_sync,pid))})

@app.post("/rcoin/wallet/{tg_id}")
async def rcoin_wallet_connect(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try:data=await request.json()
    except Exception:data={}
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    result=await run_sync_db(_rcoin_wallet_connect_sync,pid,data.get("address"),data.get("network"))
    return JSONResponse(result,status_code=200 if result.get("success") else 400)

@app.get("/rcoin/history/{tg_id}")
async def rcoin_history(tg_id:int,request:Request,limit:int=30):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    limit=max(1,min(int(limit),100))
    def _read():
        conn=get_db()
        try:return [dict(r) for r in conn.execute("SELECT action,points,token_raw,reason,tx_hash,created_at FROM rcoin_ledger WHERE player_id=? ORDER BY id DESC LIMIT ?",(pid,limit)).fetchall()]
        finally:conn.close()
    return JSONResponse({"success":True,"history":await run_sync_db(_read)})


def _public_customization_from_conn(conn, player_id:int, total_sales:int=0) -> dict:
    equipped={"rhold":"era1_core","nick":"none","avatar":"none","badge":"none"}
    try:
        rows=conn.execute("SELECT skin_id FROM rhold_button_skins WHERE player_id=? AND skin_id LIKE 'equipped:%' ORDER BY purchased_at DESC",(int(player_id),)).fetchall()
        for row in rows:
            raw=str(row[0])
            if raw.startswith("equipped:rhold:"): equipped["rhold"]=raw.split(":",2)[2]
            elif raw.startswith("equipped:nick:"): equipped["nick"]=raw.split(":",2)[2]
            elif raw.startswith("equipped:avatar:"): equipped["avatar"]=raw.split(":",2)[2]
            elif raw.startswith("equipped:badge:"): equipped["badge"]=raw.split(":",2)[2]
    except Exception:
        pass
    catalog=_rhold_skin_catalog_map()
    def pack(slot):
        sid=equipped.get(slot) or "none"
        if sid in {"none",""}: return None
        item=catalog.get(sid) or {}
        return {
            "id":sid,"name":str(item.get("name") or sid),"slot":slot,
            "accent":str(item.get("accent") or "#b7ff6a"),
            "bg":str(item.get("bg") or "linear-gradient(145deg,#111,#080808)"),
            "border":str(item.get("border") or "rgba(255,255,255,.18)"),
            "glow":str(item.get("glow") or "rgba(183,255,106,.25)"),
            "symbol":str(item.get("symbol") or "R"),
            "reward_multiplier":float(item.get("reward_multiplier",1.0) or 1.0),
            "prefix":str(item.get("prefix") or item.get("name") or ""),
            "tier":str(item.get("tier") or item.get("min_sales") or ""),
        }
    return {"equipped":equipped,"rhold":pack("rhold"),"nick":pack("nick"),"avatar":pack("avatar"),"badge":pack("badge"),"rating":get_avito_rating(int(total_sales or 0))}


def _public_customization_sync(player_id:int) -> dict:
    conn=get_db()
    try:
        row=conn.execute("SELECT total_sales FROM players WHERE id=?",(int(player_id),)).fetchone()
        sales=int(row[0] or 0) if row else 0
        return _public_customization_from_conn(conn,player_id,sales)
    finally:
        conn.close()




def _resell_market_day_key() -> str:
    return datetime.now().strftime('%Y-%m-%d')

def _resell_black_market_for_day(day_key: str) -> list[dict]:
    seed = int(hashlib.sha256(f"resell:black-market:{day_key}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    pool = [dict(x) for x in RESSELL_BLACK_MARKET_POOL]
    rng.shuffle(pool)
    return pool[:4]

def _night_club_apply_tick_sync(conn, player_id: int, now: int) -> dict:
    row=conn.execute("SELECT * FROM night_clubs WHERE player_id=?",(int(player_id),)).fetchone()
    if not row:
        conn.execute("INSERT OR IGNORE INTO night_clubs(player_id,last_tick_at) VALUES(?,?)",(int(player_id),int(now)))
        row=conn.execute("SELECT * FROM night_clubs WHERE player_id=?",(int(player_id),)).fetchone()
    level=int(row['level'] or 0); last=int(row['last_tick_at'] or now)
    pending=int(row['pending_income'] or 0)
    total=int(row['total_income'] or 0)
    guests=int(row['guest_count'] or 0)
    reputation=int(row['reputation'] or 0)
    rate=0
    capacity=0
    if level:
        cfg=NIGHT_CLUB_LEVELS[min(level,len(NIGHT_CLUB_LEVELS))-1]
        rate=int(cfg['income_per_hour']); capacity=int(cfg['capacity']); reputation=int(cfg['reputation'])
    delta=max(0,min(now-last,7*24*3600))
    earned=int(rate*delta/3600)
    if earned>0:
        pending+=earned; total+=earned
    if level:
        # A stable guest count makes the venue feel alive without creating a second
        # mini-game. It is only display state.
        phase=int(now//300)
        guests=int(max(0,min(capacity,round(capacity*(0.48+0.40*((phase%17)/16))))))
    conn.execute("UPDATE night_clubs SET pending_income=?,total_income=?,last_tick_at=?,guest_count=?,reputation=? WHERE player_id=?",(pending,total,now,guests,reputation,int(player_id)))
    row=conn.execute("SELECT * FROM night_clubs WHERE player_id=?",(int(player_id),)).fetchone()
    return dict(row)

def _night_club_state_sync(player_id:int) -> dict:
    conn=get_db()
    try:
        state=_night_club_apply_tick_sync(conn,int(player_id),int(time_module.time()))
        styles=[]
        for style in NIGHT_CLUB_STYLES:
            styles.append(dict(style))
        level=int(state.get('level') or 0)
        cfg=NIGHT_CLUB_LEVELS[level-1] if level else None
        return {"level":level,"venue_name":cfg['name'] if cfg else "NO VENUE","income_per_hour":int(cfg['income_per_hour']) if cfg else 0,"capacity":int(cfg['capacity']) if cfg else 0,"guest_count":int(state.get('guest_count') or 0),"reputation":int(state.get('reputation') or 0),"pending_income":int(state.get('pending_income') or 0),"total_income":int(state.get('total_income') or 0),"venue_style":state.get('venue_style') or 'afterdark',"styles":styles,"next_level":NIGHT_CLUB_LEVELS[level] if level < len(NIGHT_CLUB_LEVELS) else None}
    finally:
        conn.commit(); conn.close()

def _resell_market_state_sync(player_id:int) -> dict:
    conn=get_db()
    try:
        owned={r['asset_id'] for r in conn.execute("SELECT asset_id FROM resell_market_assets WHERE player_id=?",(int(player_id),)).fetchall()}
        club=_night_club_apply_tick_sync(conn,int(player_id),int(time_module.time()))
        day=_resell_market_day_key()
        row=conn.execute("SELECT total_sales FROM players WHERE id=?",(int(player_id),)).fetchone()
        total_sales=int(row[0] or 0) if row else 0
        wealth_rows=[]
        for r in conn.execute("SELECT nickname,balance,total_earned,total_sales FROM players WHERE COALESCE(is_banned,0)=0 ORDER BY total_earned DESC LIMIT 10").fetchall():
            wealth_rows.append({"nickname":r[0] or "Игрок","balance":int(r[1] or 0),"total_earned":int(r[2] or 0),"total_sales":int(r[3] or 0)})
        status_levels=[(0,"DEALER"),(10,"VERIFIED"),(25,"PRO"),(50,"ELITE"),(100,"TITAN"),(250,"LEGEND"),(500,"WHALE")]
        status="DEALER"
        for threshold,name in status_levels:
            if total_sales>=threshold: status=name
        return {"owned":sorted(owned),"market_day":day,"black_market":_resell_black_market_for_day(day),"empire":RESSELL_EMPIRE_CATALOG,"collectibles":RESSELL_COLLECTIBLE_CATALOG,"collector_cars":RESSELL_COLLECTOR_CARS,"drops":RESSELL_DROP_CATALOG,"hall_of_fame":wealth_rows,"status":{"name":status,"total_sales":total_sales,"next":next((t for t,nm in status_levels if t>total_sales),None)},"nightclub":_night_club_state_sync_locked(conn,club)}
    finally:
        conn.commit(); conn.close()

def _night_club_state_sync_locked(conn, state:dict)->dict:
    level=int(state.get('level') or 0)
    cfg=NIGHT_CLUB_LEVELS[level-1] if level else None
    return {"level":level,"venue_name":cfg['name'] if cfg else "NO VENUE","income_per_hour":int(cfg['income_per_hour']) if cfg else 0,"capacity":int(cfg['capacity']) if cfg else 0,"guest_count":int(state.get('guest_count') or 0),"reputation":int(state.get('reputation') or 0),"pending_income":int(state.get('pending_income') or 0),"total_income":int(state.get('total_income') or 0),"venue_style":state.get('venue_style') or 'afterdark',"styles":[dict(x) for x in NIGHT_CLUB_STYLES],"next_level":NIGHT_CLUB_LEVELS[level] if level < len(NIGHT_CLUB_LEVELS) else None}

@app.get("/resell/market/{tg_id}")
async def resell_market_state(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    player=await run_sync_db(get_player_data,player_id) or {}
    state=await run_sync_db(_resell_market_state_sync,player_id)
    return JSONResponse({"success":True,"balance":int(player.get('balance',0) or 0),**state})

@app.post("/resell/market/{tg_id}/buy")
async def resell_market_buy(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    try: data=await request.json()
    except Exception: data={}
    asset_id=str(data.get('asset_id') or '').strip()
    if not asset_id: return JSONResponse({"success":False,"error":"Не выбран предмет"},status_code=400)
    all_items={x['id']:dict(x) for x in (RESSELL_EMPIRE_CATALOG+RESSELL_COLLECTIBLE_CATALOG+RESSELL_BLACK_MARKET_POOL)}
    all_items.update({f"collector_car:{x['id']}":{**dict(x),"id":f"collector_car:{x['id']}","collector_car_id":x['id']} for x in RESSELL_COLLECTOR_CARS})
    all_items.update({x['id']:dict(x) for x in RESSELL_DROP_CATALOG})
    all_items['private_club']={"id":"private_club","name":"PRIVATE CLUB","price":100_000_000,"description":"Доступ в закрытый RESSELL-клуб и новые лимитированные ротации.","accent":"#ffe36c"}
    item=all_items.get(asset_id)
    if not item: return JSONResponse({"success":False,"error":"Предмет больше недоступен"},status_code=404)
    # Black Market items are only buyable during the current daily rotation.
    if asset_id.startswith('bm_') and asset_id not in {x['id'] for x in _resell_black_market_for_day(_resell_market_day_key())}:
        return JSONResponse({"success":False,"error":"Этот лот уже ушёл с ротации"},status_code=400)
    async with db_lock:
        def _buy():
            conn=get_db(); cur=conn.cursor()
            try:
                cur.execute('BEGIN IMMEDIATE')
                if cur.execute('SELECT 1 FROM resell_market_assets WHERE player_id=? AND asset_id=?',(player_id,asset_id)).fetchone():
                    conn.rollback(); return ('owned',)
                bal=cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone(); balance=int(bal['balance'] if bal else 0)
                price=int(item.get('price') or 0)
                if asset_id.startswith('bm_') and price >= 180_000_000:
                    if not cur.execute('SELECT 1 FROM resell_market_assets WHERE player_id=? AND asset_id=?',(player_id,'private_club')).fetchone():
                        conn.rollback(); return ('club_locked',)
                if balance<price:
                    conn.rollback(); return ('funds',price,balance)
                # Empire is linear: a higher tier requires the previous one, so the
                # player never has two competing “HQ” systems.
                if asset_id in {x['id'] for x in RESSELL_EMPIRE_CATALOG}:
                    tier=int(item.get('tier') or 0)
                    if tier>1 and not cur.execute('SELECT 1 FROM resell_market_assets WHERE player_id=? AND asset_id=?',(player_id,RESSELL_EMPIRE_CATALOG[tier-2]['id'])).fetchone():
                        conn.rollback(); return ('locked',RESSELL_EMPIRE_CATALOG[tier-2]['name'])
                cur.execute('INSERT INTO resell_market_assets(player_id,asset_id,purchased_at) VALUES(?,?,?)',(player_id,asset_id,int(time_module.time())))
                reward_asset=str(item.get('reward_asset') or '')
                if reward_asset:
                    cur.execute('INSERT OR IGNORE INTO resell_market_assets(player_id,asset_id,purchased_at) VALUES(?,?,?)',(player_id,reward_asset,int(time_module.time())))
                cur.execute('UPDATE players SET balance=balance-? WHERE id=?',(price,player_id))
                newb=cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone()
                conn.commit(); return ('ok',int(newb['balance'] if newb else 0),reward_asset)
            except Exception:
                conn.rollback(); raise
            finally: conn.close()
        result=await run_sync_db(_buy)
    if result[0]=='owned': return JSONResponse({"success":False,"error":"Уже в твоей коллекции"},status_code=400)
    if result[0]=='club_locked': return JSONResponse({"success":False,"error":"Нужен PRIVATE CLUB"},status_code=400)
    if result[0]=='funds': return JSONResponse({"success":False,"error":f"Нужно {result[1]:,}₽","balance":result[2]},status_code=400)
    if result[0]=='locked': return JSONResponse({"success":False,"error":f"Сначала открой {result[1]}"},status_code=400)
    await run_sync_db(_engagement_add_xp_sync,player_id,80,'resell_market_buy')
    message=f"{item['name']} добавлен в коллекцию"
    if len(result)>2 and result[2]: message += f" · бонус: {result[2]}"
    return JSONResponse({"success":True,"balance":result[1],"message":message})

@app.post("/resell/nightclub/{tg_id}/upgrade")
async def resell_nightclub_upgrade(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    async with db_lock:
        def _up():
            conn=get_db(); cur=conn.cursor()
            try:
                cur.execute('BEGIN IMMEDIATE'); row=_night_club_apply_tick_sync(conn,player_id,int(time_module.time())); level=int(row.get('level') or 0)
                if level>=len(NIGHT_CLUB_LEVELS): conn.rollback(); return ('max',)
                cfg=NIGHT_CLUB_LEVELS[level]; bal=cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone(); balance=int(bal['balance'] if bal else 0)
                price=int(cfg['price'])
                if balance<price: conn.rollback(); return ('funds',price,balance)
                new_level=level+1
                cur.execute('INSERT INTO night_clubs(player_id,level,last_tick_at,guest_count,reputation) VALUES(?,?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET level=excluded.level,last_tick_at=excluded.last_tick_at,guest_count=excluded.guest_count,reputation=excluded.reputation',(player_id,new_level,int(time_module.time()),0,int(cfg['reputation'])))
                cur.execute('UPDATE players SET balance=balance-? WHERE id=?',(price,player_id))
                nb=cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone(); conn.commit(); return ('ok',new_level,int(nb['balance'] if nb else 0))
            except Exception: conn.rollback(); raise
            finally: conn.close()
        r=await run_sync_db(_up)
    if r[0]=='max': return JSONResponse({"success":False,"error":"Ночной клуб уже максимального уровня"},status_code=400)
    if r[0]=='funds': return JSONResponse({"success":False,"error":f"Нужно {r[1]:,}₽","balance":r[2]},status_code=400)
    await run_sync_db(_engagement_add_xp_sync,player_id,120,'nightclub_upgrade')
    return JSONResponse({"success":True,"level":r[1],"balance":r[2],"message":"Уровень ночного клуба повышен"})

@app.post("/resell/nightclub/{tg_id}/collect")
async def resell_nightclub_collect(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    async with db_lock:
        def _collect():
            conn=get_db()
            try:
                cur=conn.cursor(); cur.execute('BEGIN IMMEDIATE'); row=_night_club_apply_tick_sync(conn,player_id,int(time_module.time())); amount=int(row.get('pending_income') or 0)
                if amount<=0: conn.rollback(); return (0,int(cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone()['balance']))
                bal=cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone(); newb=int(bal['balance'] if bal else 0)+amount
                cur.execute('UPDATE players SET balance=balance+? WHERE id=?',(amount,player_id)); cur.execute('UPDATE night_clubs SET pending_income=0 WHERE player_id=?',(player_id,)); conn.commit(); return (amount,newb)
            except Exception: conn.rollback(); raise
            finally: conn.close()
        amount,new_balance=await run_sync_db(_collect)
    if amount>0:
        await run_sync_db(_engagement_add_xp_sync,player_id,40,'nightclub_collect')
    return JSONResponse({"success":True,"collected":amount,"balance":new_balance,"message":f"+{amount:,} ₽" if amount else "Пока нечего забирать"})

@app.post("/resell/nightclub/{tg_id}/style")
async def resell_nightclub_style(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    try: data=await request.json()
    except Exception: data={}
    style_id=str(data.get('style_id') or 'afterdark')
    style=next((x for x in NIGHT_CLUB_STYLES if x['id']==style_id),None)
    if not style: return JSONResponse({"success":False,"error":"Неизвестный стиль клуба"},status_code=400)
    async with db_lock:
        def _style():
            conn=get_db(); cur=conn.cursor()
            try:
                cur.execute('BEGIN IMMEDIATE'); row=_night_club_apply_tick_sync(conn,player_id,int(time_module.time())); level=int(row.get('level') or 0)
                if level<=0: conn.rollback(); return ('locked',)
                owned = style_id=='afterdark' or cur.execute('SELECT 1 FROM resell_market_assets WHERE player_id=? AND asset_id=?',(player_id,'club_style_'+style_id)).fetchone()
                if not owned:
                    price=int(style['price']); bal=cur.execute('SELECT balance FROM players WHERE id=?',(player_id,)).fetchone(); balance=int(bal['balance'] if bal else 0)
                    if balance<price: conn.rollback(); return ('funds',price,balance)
                    cur.execute('INSERT INTO resell_market_assets(player_id,asset_id,purchased_at) VALUES(?,?,?)',(player_id,'club_style_'+style_id,int(time_module.time())))
                    cur.execute('UPDATE players SET balance=balance-? WHERE id=?',(price,player_id))
                cur.execute('UPDATE night_clubs SET venue_style=? WHERE player_id=?',(style_id,player_id)); conn.commit(); return ('ok',style_id)
            except Exception: conn.rollback(); raise
            finally: conn.close()
        r=await run_sync_db(_style)
    if r[0]=='locked': return JSONResponse({"success":False,"error":"Сначала открой сам ночной клуб"},status_code=400)
    if r[0]=='funds': return JSONResponse({"success":False,"error":f"Нужно {r[1]:,}₽","balance":r[2]},status_code=400)
    return JSONResponse({"success":True,"style_id":r[1]})

@app.get("/profile/{tg_id}")
async def profile(tg_id: int, request:Request):
    # Read-only bootstrap endpoint: the Mini App already sends initData when available.
    # Do not block the initial profile load when Telegram WebView has not populated
    # initData yet; mutation endpoints remain protected by the verifier.
    try:
        player_id = await get_player_id_by_tg(tg_id)
        if not player_id:
            player_id = await run_sync_db(get_or_create_player, "tg", tg_id)
        if not player_id:
            return JSONResponse({"success":False,"error":"Player not found"}, status_code=404)
        player = await run_sync_db(get_player_data, player_id)
    except Exception as e:
        print(f"[PROFILE] DB/API error for {tg_id}: {e}")
        return JSONResponse({"success":False,"error":"Временная ошибка базы данных"}, status_code=503)
    if not player:
        return JSONResponse({"error": "Player not found"}, status_code=404)

    # ----- ПАССИВНЫЙ ДОХОД И БИЗНЕСЫ -----
    # 1. Недвижимость
    house_id = player.get("house", "room")
    house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
    house_income_hour = int(house.get("income_per_hour", 0) or 0)
    house_income_day = house_income_hour * 24

    # 2. Автомобиль (текущий)
    car_id = player.get("current_car", "none")
    car = next((c for c in CARS if c["id"] == car_id), None)
    car_income_day = (car["income_per_hour"] * 24) if car else 0

    # 3. Таксопарк
    taxopark = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark.get("level")), TAXOPARK_LEVELS[0])
    taxopark_income_day = taxopark_level["income_per_car"] * 24 * len(taxopark.get("cars", []))

    # 4. Магазины (все, которые куплены)
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
    shop_rows = cursor.fetchall()
    conn.close()
    shops_income_day = 0
    shop_names = []
    for row in shop_rows:
        shop = next((s for s in SHOP_LEVELS if s["id"] == row["shop_id"]), None)
        if shop:
            shops_income_day += shop["income_per_hour"] * 24
            shop_names.append(f"{shop['name']} (+{shop['income_per_hour']*24}₽/день)")

    # 5. Майнинг-фермы
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT rig_type, daily_income FROM mining_rigs WHERE player_id = ? AND status = 'active'", (player_id,))
    mining_rows = cursor.fetchall()
    conn.close()
    mining_income_day = sum(row["daily_income"] for row in mining_rows)
    mining_names = [f"{MINING_RIGS[row['rig_type']]['name']} (+{row['daily_income']}₽/день)" for row in mining_rows]

    # Собираем бизнесы
    businesses = []
    if house_income_day > 0:
        businesses.append({
            "name": house["name"],
            "icon": "🏠",
            "type": "Недвижимость",
            "income_per_day": house_income_day,
            "income_per_hour": house_income_hour
        })
    if car_income_day > 0:
        businesses.append({
            "name": car["name"],
            "icon": "🚗",
            "type": "Автомобиль",
            "income_per_day": car_income_day
        })
    if taxopark_income_day > 0:
        businesses.append({
            "name": f"Таксопарк ({taxopark_level['name']})",
            "icon": "🚕",
            "type": "Таксопарк",
            "income_per_day": taxopark_income_day
        })
    if shops_income_day > 0:
        businesses.append({
            "name": f"Магазины ({len(shop_rows)} шт.)",
            "icon": "🏪",
            "type": "Магазины",
            "income_per_day": shops_income_day
        })
    if mining_income_day > 0:
        businesses.append({
            "name": f"Майнинг ({len(mining_rows)} ферм)",
            "icon": "🖥️",
            "type": "Майнинг",
            "income_per_day": mining_income_day
        })

    hourly_income, hourly_breakdown = await run_sync_db(get_hourly_income, player_id)
    total_passive_per_day = hourly_income * 24
    for src, val in hourly_breakdown.items():
        if src == "house": house_income_day = int(val * 24)
        elif src == "car": car_income_day = int(val * 24)
        elif src == "taxopark": taxopark_income_day = int(val * 24)
        elif src == "shops": shops_income_day = int(val * 24)
        elif src == "mining": mining_income_day = int(val * 24)
    pending_passive, _, pending_breakdown = await get_pending_income(player_id)
    quest_payload = await run_sync_db(get_quest_payload, player_id)

    # Средняя прибыль с продажи (если есть продажи)
    total_sales = player.get("total_sales", 0)
    total_profit = player.get("total_profit", 0)
    if total_sales > 0:
        avg_profit_per_sale = total_profit // total_sales
    else:
        avg_profit_per_sale = 500  # значение по умолчанию

    # Рекомендация
    recommendation = ""
    if total_passive_per_day > 0 and avg_profit_per_sale > 0:
        sales_needed = (total_passive_per_day + avg_profit_per_sale - 1) // avg_profit_per_sale  # округление вверх
        recommendation = (
            f"📊 <strong>Рекомендация:</strong><br>"
            f"Чтобы заработать <strong>{total_passive_per_day:,}₽</strong> пассивного дохода, "
            f"вам нужно продать примерно <strong>{sales_needed}</strong> товаров "
            f"(при средней прибыли {avg_profit_per_sale:,}₽ за продажу)."
            f"{' Попробуйте увеличить оборот или улучшить бизнес.' if sales_needed > 20 else ' Отличный результат, вы на верном пути!'}"
        )
    else:
        recommendation = (
            "💡 <strong>Совет:</strong><br>"
            "Инвестируйте в бизнесы, чтобы получать пассивный доход. Каждый новый актив увеличивает ваш ежедневный заработок."
        )

    business_info = {
        "businesses": businesses,
        "total_per_day": total_passive_per_day,
        "total_per_hour": hourly_income,
        "average_profit_per_sale": avg_profit_per_sale,
        "recommendation": recommendation,
        "pending_collect": pending_passive,
        "pending_breakdown": pending_breakdown,
        "hourly_breakdown": hourly_breakdown,
        "last_income_collect": int(player.get("last_income_collect", 0) or 0),
    }

    # ----- Остальные данные -----
    skin_id = player.get("skin", "default")
    skin = next((s for s in SKINS if s["id"] == skin_id), SKINS[0])
    rep_level = get_rep_level(player.get("total_sales", 0))

    nickname_value = str(player.get("nickname") or "")
    shop_value = str(player.get("shop_name") or "")
    registration_complete = bool(nickname_value and shop_value and not nickname_value.startswith("Игрок_") and shop_value != "Моя лавка")
    return JSONResponse({
        "registration_complete": registration_complete,
        "registration_required": not registration_complete,
        "nickname": nickname_value or "Торгаш",
        "balance": player.get("balance", 0),
        "balance": player.get("balance", 0),
        "total_earned": player.get("total_earned", 0),
        "total_sales": player.get("total_sales", 0),
        "total_profit": player.get("total_profit", 0),
        "items_sold": player.get("items_sold", 0),
        "stat_earned_today": player.get("stat_earned_today", 0),
        "stat_sold_today": player.get("stat_sold_today", 0),
        "reputation_level": rep_level,
        "skin": {
            "id": skin_id,
            "name": skin.get("name", "Новичок"),
            "emoji": skin.get("emoji", "👤")
        },
        "epoch_progress": get_epoch_state(player)["progress"],
        "epoch": get_epoch_state(player),
        "business_info": business_info,
        "quests": quest_payload,
        "engagement": await run_sync_db(_engagement_snapshot_sync, player_id, int(time_module.time())),
        "rcoin": await run_sync_db(_rcoin_status_sync, player_id),
        "customization": await run_sync_db(_public_customization_sync, player_id),
        "profile_version": 5
    })

@app.get("/quests/{tg_id}")
async def quests(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        player_id = await run_sync_db(get_or_create_player, "tg", tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
    payload = await run_sync_db(get_quest_payload, player_id)
    return JSONResponse({"success": True, **payload})

@app.post("/quests/claim/{tg_id}")
async def claim_quest_reward(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try:
        data = await request.json()
    except Exception:
        data = {}
    quest_id = data.get("quest_id")
    if quest_id not in PERMANENT_QUESTS:
        return JSONResponse({"success": False, "error": "Можно забирать только постоянные награды"}, status_code=400)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
    async with db_lock:
        result = await run_sync_db(claim_permanent_quest_sync, player_id, quest_id)
    if not result.get("success"):
        return JSONResponse(result, status_code=400)
    if result.get("success"):
        await activate_pending_referral(int(tg_id), "quest_claim")
    return JSONResponse({**result, "quests": await run_sync_db(get_quest_payload, player_id)})

@app.post("/passive/collect/{tg_id}")
async def collect_passive_webapp(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
    pending, hourly, breakdown = await collect_pending_income(player_id)
    player = await run_sync_db(get_player_data, player_id)
    if int(pending) > 0:
        await activate_pending_referral(int(tg_id), "passive_collect")
    return JSONResponse({"success": True, "collected": int(pending), "hourly": int(hourly), "breakdown": breakdown, "balance": int(player.get("balance", 0) if player else 0)})

# ==================== RESSELL ENGAGEMENT ENGINE V3 ====================
def _engagement_level_requirement(level:int) -> int:
    return int(round(120 * (max(1,int(level)) ** 1.32)))

def _engagement_progress_sync(player_id:int) -> dict:
    conn=get_db(); cur=conn.cursor()
    try:
        row=cur.execute("SELECT * FROM player_progress WHERE player_id=?",(player_id,)).fetchone()
        if not row:
            now=int(time_module.time())
            cur.execute("INSERT OR IGNORE INTO player_progress(player_id,xp,level,login_streak,last_login_cycle,last_checkin_at,referral_streak,updated_at) VALUES(?,?,?,?,?,?,?,?)",(player_id,0,1,0,"",0,0,now))
            row=cur.execute("SELECT * FROM player_progress WHERE player_id=?",(player_id,)).fetchone()
        return dict(row)
    finally: conn.close()

def _engagement_touch_login_sync(player_id:int, now:int) -> dict:
    cycle=_rfarm_cycle_key(int(now))
    prev=_rfarm_cycle_key(int(now)-86400)
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row=cur.execute("SELECT login_streak,last_login_cycle FROM player_progress WHERE player_id=?",(player_id,)).fetchone()
        if not row:
            cur.execute("INSERT INTO player_progress(player_id,login_streak,last_login_cycle,updated_at) VALUES(?,?,?,?)",(player_id,1,cycle,now))
        else:
            last=str(row["last_login_cycle"] or ""); old=max(0,int(row["login_streak"] or 0))
            streak=old if last==cycle else (old+1 if last==prev else 1)
            cur.execute("UPDATE player_progress SET login_streak=?,last_login_cycle=?,updated_at=? WHERE player_id=?",(max(1,streak),cycle,now,player_id))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally: conn.close()
    return _engagement_progress_sync(player_id)

def _engagement_add_xp_sync(player_id:int, xp:int, event_name:str="action") -> dict:
    xp=max(0,int(xp)); conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row=cur.execute("SELECT xp,level FROM player_progress WHERE player_id=?",(player_id,)).fetchone()
        if not row:
            current=0; level=1
            cur.execute("INSERT INTO player_progress(player_id,xp,level,updated_at) VALUES(?,?,?,?)",(player_id,0,1,int(time_module.time())))
        else:
            current=max(0,int(row["xp"] or 0)); level=max(1,int(row["level"] or 1))
        current+=xp; ups=0
        while current>=_engagement_level_requirement(level):
            current-=_engagement_level_requirement(level); level+=1; ups+=1
            if ups>=50: break
        cur.execute("UPDATE player_progress SET xp=?,level=?,updated_at=? WHERE player_id=?",(current,level,int(time_module.time()),player_id))
        cur.execute("INSERT OR IGNORE INTO player_metrics(player_id) VALUES(?)",(player_id,))
        cur.execute("UPDATE player_metrics SET xp_events=xp_events+1 WHERE player_id=?",(player_id,))
        conn.commit()
        return {"xp":current,"level":level,"level_ups":ups,"xp_added":xp,"next_xp":_engagement_level_requirement(level)}
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def _daily_checkin_reward(streak:int) -> tuple[int,int]:
    rewards=[5000,7500,10000,15000,20000,30000,50000]; xps=[40,50,60,70,80,100,140]
    i=min(max(int(streak)-1,0),6); return rewards[i],xps[i]

def _engagement_snapshot_sync(player_id:int, now:int) -> dict:
    prog=_engagement_touch_login_sync(player_id,now); level=max(1,int(prog.get("level") or 1)); xp=max(0,int(prog.get("xp") or 0)); req=_engagement_level_requirement(level)
    conn=get_db()
    try:
        row=conn.execute("SELECT * FROM player_metrics WHERE player_id=?",(player_id,)).fetchone()
        return {"level":level,"xp":xp,"xp_to_next":max(0,req-xp),"xp_required":req,"streak":max(1,int(prog.get("login_streak") or 1)),"last_login_cycle":prog.get("last_login_cycle") or "","last_checkin_at":int(prog.get("last_checkin_at") or 0),"metrics":dict(row) if row else {}}
    finally: conn.close()

def _claim_daily_checkin_sync(player_id:int, now:int):
    cycle=_rfarm_cycle_key(int(now))
    prev=_rfarm_cycle_key(int(now)-86400)
    conn=get_db(); cur=conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        row=cur.execute("SELECT login_streak,last_login_cycle,last_checkin_at FROM player_progress WHERE player_id=?",(player_id,)).fetchone()
        if not row:
            streak=1; last_checkin=0
            cur.execute("INSERT INTO player_progress(player_id,login_streak,last_login_cycle,last_checkin_at,updated_at) VALUES(?,?,?,?,?)",(player_id,1,cycle,0,now))
        else:
            last_cycle=str(row["last_login_cycle"] or ""); streak=max(1,int(row["login_streak"] or 1)); last_checkin=int(row["last_checkin_at"] or 0)
            if last_cycle not in {cycle,prev}: streak=1
        if last_checkin and _rfarm_cycle_key(last_checkin)==cycle:
            conn.rollback(); return {"status":"already","reward":0,"xp":0,"streak":streak}
        reward,xp=_daily_checkin_reward(streak)
        cur.execute("UPDATE players SET balance=balance+?,total_earned=total_earned+? WHERE id=?",(reward,reward,player_id))
        cur.execute("UPDATE player_progress SET login_streak=?,last_login_cycle=?,last_checkin_at=?,updated_at=? WHERE player_id=?",(streak,cycle,now,now,player_id))
        conn.commit(); return {"status":"claimed","reward":reward,"xp":xp,"streak":streak}
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

@app.get("/engagement/{tg_id}")
async def engagement_snapshot(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: pid=await run_sync_db(get_or_create_player,"tg",tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    now=int(time_module.time()); snap=await run_sync_db(_engagement_snapshot_sync,pid,now); last=int(snap.get("last_checkin_at") or 0)
    available=(not last) or _rfarm_cycle_key(last)!=_rfarm_cycle_key(now); reward,xp=_daily_checkin_reward(int(snap.get("streak") or 1))
    return JSONResponse({"success":True,**snap,"checkin":{"available":available,"reward":reward,"xp":xp},"now":now})

@app.post("/engagement/checkin/{tg_id}")
async def engagement_checkin(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id): return JSONResponse({"success":False,"error":"Не найден Telegram ID"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    async with player_action_locks.setdefault(f"engagement:{pid}",asyncio.Lock()):
        async with db_lock:
            result=await run_sync_db(_claim_daily_checkin_sync,pid,int(time_module.time()))
            xp_result=await run_sync_db(_engagement_add_xp_sync,pid,int(result.get("xp",0)),"daily_checkin") if result["status"]=="claimed" else await run_sync_db(_engagement_progress_sync,pid)
    player=await run_sync_db(get_player_data,pid) or {}
    return JSONResponse({"success":True,"already":result["status"]=="already","reward":int(result["reward"]),"xp":int(result["xp"]),"streak":int(result["streak"]),"balance":int(player.get("balance",0) or 0),"progress":xp_result})

@app.get("/leaderboard/wealth")
async def leaderboard_wealth(limit: int = 10, userId: Optional[int] = None, mode: str = "wealth"):
    """Forbes RESell leaderboard."""
    limit = max(1, min(int(limit), 50))
    mode_key = str(mode or "wealth").lower().strip()
    if mode_key not in {"wealth", "earned", "today", "referrals", "fleet"}:
        mode_key = "wealth"

    def _get_wealth_leaderboard():
        conn = get_db()
        try:
            players = conn.execute(
                "SELECT id,tg_id,nickname,balance,car_collection,house,total_earned,stat_earned_today "
                "FROM players"
            ).fetchall()

            shop_map = {}
            for row in conn.execute("SELECT player_id,shop_id FROM user_shops"):
                shop_map.setdefault(int(row["player_id"]), []).append(row["shop_id"])

            ref_map = {}
            for row in conn.execute(
                "SELECT inviter_tg_id,COUNT(*) AS c FROM referral_relations "
                "WHERE reward_paid=1 GROUP BY inviter_tg_id"
            ):
                ref_map[int(row["inviter_tg_id"])] = int(row["c"] or 0)

            result = []
            for p in players:
                pid = int(p["id"])
                nickname = p["nickname"] or f"Игрок {p['tg_id']}"
                balance = int(p["balance"] or 0)

                raw_collection = p["car_collection"]
                try:
                    collection = (
                        json.loads(raw_collection)
                        if isinstance(raw_collection, str)
                        else (raw_collection or [])
                    )
                except Exception:
                    collection = []
                if not isinstance(collection, list):
                    collection = []

                cars_count = len(collection)
                cars_value = 0
                for cid in collection:
                    car = next((c for c in CARS if c.get("id") == cid), None)
                    if car:
                        cars_value += int(car.get("price", 0) or 0)

                house = next(
                    (h for h in HOUSES if h["id"] == (p["house"] or "room")),
                    HOUSES[0],
                )
                house_value = int(house.get("price", 0) or 0)

                shops_count = 0
                shops_value = 0
                for sid in shop_map.get(pid, []):
                    shop = next(
                        (x for x in SHOP_LEVELS if x.get("id") == sid), None
                    )
                    if shop:
                        shops_count += 1
                        shops_value += int(shop.get("price", 0) or 0)

                result.append({
                    "tg_id": int(p["tg_id"] or 0),
                    "nickname": nickname,
                    "wealth": balance + cars_value + house_value + shops_value,
                    "balance": balance,
                    "cars_count": cars_count,
                    "shops_count": shops_count,
                    "earned": int(p["total_earned"] or 0),
                    "today": int(p["stat_earned_today"] or 0),
                    "referrals": int(ref_map.get(int(p["tg_id"]), 0)),
                    "customization": _public_customization_from_conn(conn,pid,int(p["total_earned"] or 0)),
                })

            sort_field = {
                "wealth": "wealth",
                "earned": "earned",
                "today": "today",
                "referrals": "referrals",
                "fleet": "cars_count",
            }.get(mode_key, "wealth")

            result.sort(
                key=lambda x: (
                    int(x.get(sort_field, 0) or 0),
                    int(x.get("wealth", 0) or 0),
                    str(x.get("nickname", "")),
                ),
                reverse=True,
            )

            self_rank = None
            self_entry = None
            if userId is not None:
                target_id = int(userId)
                for idx, entry in enumerate(result, 1):
                    if int(entry.get("tg_id") or 0) == target_id:
                        self_rank = idx
                        self_entry = entry
                        break

            return {
                "rows": result[:limit],
                "self_rank": self_rank,
                "self_entry": self_entry,
                "total_players": len(result),
            }
        finally:
            conn.close()

    try:
        data = await run_sync_db(_get_wealth_leaderboard)
        return JSONResponse({
            "success": True,
            "leaderboard": data["rows"],
            "self_rank": data["self_rank"],
            "self_entry": data["self_entry"],
            "total_players": data["total_players"],
            "source": "forbes",
            "mode": mode_key,
            "mode_label": {
                "wealth":"КАПИТАЛ",
                "earned":"ЗАРАБОТАНО",
                "today":"СЕГОДНЯ",
                "referrals":"РЕФЕРАЛЫ",
                "fleet":"АВТОПАРК",
            }.get(mode_key, "КАПИТАЛ"),
        })
    except Exception as exc:
        print(f"[leaderboard_wealth] error: {exc}")
        return JSONResponse({
            "success": False,
            "leaderboard": [],
            "self_rank": None,
            "self_entry": None,
            "total_players": 0,
            "source": "forbes",
            "mode": mode_key,
            "mode_label": {
                "wealth":"КАПИТАЛ",
                "earned":"ЗАРАБОТАНО",
                "today":"СЕГОДНЯ",
                "referrals":"РЕФЕРАЛЫ",
                "fleet":"АВТОПАРК",
            }.get(mode_key, "КАПИТАЛ"),
            "error": "Не удалось загрузить лидерборд",
        }, status_code=200)


@app.post("/epoch/claim/{tg_id}")
async def claim_epoch_reward(tg_id: int):
    """Выдать одну неполученную награду за каждую завершённую эпоху."""
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        player_id = await run_sync_db(get_or_create_player, "tg", tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)

    async with db_lock:
        player = await run_sync_db(get_player_data, player_id)
        if not player:
            return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
        state = get_epoch_state(player)
        try:
            claimed = set(int(x) for x in json.loads(player.get("epoch_claimed", "[]") or "[]"))
        except Exception:
            claimed = set()

        available = [e for e in RESELL_EPOCHS if e["id"] in state.get("claimable_epochs", []) and e["id"] not in claimed]
        if not available:
            return JSONResponse({"success": True, "reward": 0, "message": "Новых наград пока нет", "epoch": state})

        reward_total = sum(int(e["reward"]) for e in available)
        claimed.update(e["id"] for e in available)
        new_balance = int(player.get("balance", 0) or 0) + reward_total
        await run_sync_db(update_player_data, player_id, {
            "balance": new_balance,
            "epoch_claimed": json.dumps(sorted(claimed), ensure_ascii=False),
        })

    player = await run_sync_db(get_player_data, player_id)
    await activate_pending_referral(int(tg_id), "epoch_claim")
    return JSONResponse({
        "success": True,
        "reward": reward_total,
        "claimed_epochs": [e["id"] for e in available],
        "balance": new_balance,
        "epoch": get_epoch_state(player),
    })


@app.post("/race/create")
async def race_create(request: Request):
    data = await request.json()
    tg_id = data.get("userId")
    car_id = data.get("carId")
    bet = data.get("bet", 10000)

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)

    player = get_player_data(player_id)
    if not player:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)

    if player.get("balance", 0) < bet:
        return JSONResponse({"success": False, "error": "Недостаточно средств"}, status_code=400)

    # Генерируем код комнаты (6 цифр)
    room_code = str(random.randint(100000, 999999))
    async with races_lock:
        # Убедимся, что код не занят
        while room_code in active_races:
            room_code = str(random.randint(100000, 999999))
        # Списываем ставку
        update_player_data(player_id, {"balance": player["balance"] - bet})
        active_races[room_code] = {
            "creator_id": player_id,
            "opponent_id": None,
            "creator_car": car_id,
            "opponent_car": None,
            "bet": bet,
            "prize_pool": bet,
            "status": "waiting",
            "phase": 0,
            "creator_score": 0,
            "opponent_score": 0,
            "creator_x": 0,
            "creator_z": 0,
            "creator_angle": 0,
            "opponent_x": 0,
            "opponent_z": 0,
            "opponent_angle": 0,
            "created_at": time_module.time()
        }
    await activate_pending_referral(int(tg_id), "race_create")
    return JSONResponse({"success": True, "roomCode": room_code})

@app.post("/race/join")
async def race_join(request: Request):
    data = await request.json()
    tg_id = data.get("userId")
    room_code = data.get("roomCode")
    car_id = data.get("carId")

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)

    async with races_lock:
        race = active_races.get(room_code)
        if not race:
            return JSONResponse({"success": False, "error": "Комната не найдена"}, status_code=404)
        if race["status"] != "waiting":
            return JSONResponse({"success": False, "error": "Гонка уже началась"}, status_code=400)
        if race["creator_id"] == player_id:
            return JSONResponse({"success": False, "error": "Вы создатель комнаты"}, status_code=400)

        player = get_player_data(player_id)
        if not player:
            return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
        if player.get("balance", 0) < race["bet"]:
            return JSONResponse({"success": False, "error": "Недостаточно средств"}, status_code=400)

        # Списываем ставку
        update_player_data(player_id, {"balance": player["balance"] - race["bet"]})
        race["opponent_id"] = player_id
        race["opponent_car"] = car_id
        race["prize_pool"] = race["bet"] * 2
        race["status"] = "active"
        race["phase"] = 1

    await activate_pending_referral(int(tg_id), "race_join")
    return JSONResponse({"success": True, "roomCode": room_code})

@app.get("/referral/generate")
async def referral_generate(request: Request):
    tg_id = request.query_params.get('tg_id')
    if not tg_id:
        return JSONResponse({"error": "No tg_id"}, status_code=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return JSONResponse({"error": "Invalid tg_id"}, status_code=400)

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"error": "Player not found"}, status_code=404)

    ref_code = gen_ref(tg_id)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"
    return JSONResponse({"link": link})

@app.get("/referral/users")
async def referral_users(request: Request):
    tg_id = request.query_params.get('tg_id')
    if not tg_id:
        return JSONResponse({"error": "No tg_id"}, status_code=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return JSONResponse({"error": "Invalid tg_id"}, status_code=400)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"error": "Player not found"}, status_code=404)
    def _users():
        conn = get_db()
        rows = conn.execute("SELECT invitee_tg_id, activated_at FROM referral_relations WHERE inviter_tg_id=? AND reward_paid=1 ORDER BY activated_at DESC", (tg_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    rows = await run_sync_db(_users)
    users=[]
    for row in rows:
        invitee_player_id = await get_player_id_by_tg(int(row["invitee_tg_id"]))
        player = await run_sync_db(get_player_data, invitee_player_id) if invitee_player_id else None
        users.append({"id": int(row["invitee_tg_id"]), "nickname": player.get("nickname", f"ID:{row['invitee_tg_id']}") if player else "Неизвестный", "tg_id": int(row["invitee_tg_id"]), "activated_at": int(row["activated_at"] or 0)})
    return JSONResponse({"users": users})

@app.get("/referral/income")
async def referral_income(request: Request):
    tg_id = request.query_params.get('tg_id')
    if not tg_id:
        return JSONResponse({"error": "No tg_id"}, status_code=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return JSONResponse({"error": "Invalid tg_id"}, status_code=400)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"error": "Player not found"}, status_code=404)
    def _calc():
        conn = get_db()
        rows = conn.execute("SELECT r.invitee_tg_id FROM referral_relations r JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? AND r.reward_paid=1 AND p.is_banned=0", (tg_id,)).fetchall()
        conn.close()
        total_hourly=0
        count = len(rows)
        referral_passive_percent = get_referral_passive_percent(count)
        for row in rows:
            invitee_id = get_player_id_by_tg_sync(int(row["invitee_tg_id"]))
            if invitee_id:
                hourly,_ = get_hourly_income(invitee_id, include_referrals=False)
                total_hourly += int(hourly * referral_passive_percent / 100)
        return count, total_hourly, referral_passive_percent
    count, hourly, referral_passive_percent = await run_sync_db(_calc)
    return JSONResponse({"count": count, "hourly_income": hourly, "daily_income": hourly*24, "passive_percent": referral_passive_percent})

def _friends_list_sync(player_id:int):
    conn=get_db()
    try:
        rows=conn.execute(
            """SELECT p.id,p.tg_id,p.nickname,p.shop_name,p.balance,p.total_sales,p.total_profit,p.total_earned,
                      p.reputation_score,p.car_collection,p.current_car,p.house,p.taxopark,
                      COALESCE((SELECT COUNT(*) FROM user_shops us WHERE us.player_id=p.id),0) AS shop_count,
                      COALESCE((SELECT COUNT(*) FROM mining_rigs mr WHERE mr.player_id=p.id AND mr.status='active'),0) AS mining_count,
                      COALESCE((SELECT last_seen_at FROM player_security ps WHERE ps.player_id=p.id),0) AS last_seen_at
               FROM friends f
               JOIN players p ON p.id=f.friend_id
              WHERE f.player_id=?
              ORDER BY p.nickname COLLATE NOCASE""",
            (int(player_id),)
        ).fetchall()
        out=[]
        now=int(time_module.time())
        for r in rows:
            try:
                garage_raw=json.loads(r["car_collection"] or "[]")
                garage_count=len([x for x in garage_raw if x and str(x).lower() not in {"none","null"}]) if isinstance(garage_raw,list) else 0
            except Exception:
                garage_count=0
            try:
                taxi_raw=json.loads(r["taxopark"] or "{}")
                taxi_cars=taxi_raw.get("cars",[]) if isinstance(taxi_raw,dict) else []
                taxi_count=len(taxi_cars) if isinstance(taxi_cars,list) else 0
                taxi_active=bool(taxi_count or str(taxi_raw.get("level") or "none")!="none") if isinstance(taxi_raw,dict) else False
            except Exception:
                taxi_count=0; taxi_active=False
            house_active=str(r["house"] or "room") != "room"
            business_count=int(r["shop_count"] or 0)+int(r["mining_count"] or 0)+(1 if house_active else 0)+(1 if taxi_active else 0)
            last_seen=int(r["last_seen_at"] or 0)
            item={
                "id":int(r["id"]),
                "tg_id":int(r["tg_id"] or 0),
                "nickname":str(r["nickname"] or "Игрок"),
                "shop_name":str(r["shop_name"] or "Без магазина"),
                "balance":int(r["balance"] or 0),
                "total_sales":int(r["total_sales"] or 0),
                "total_profit":int(r["total_profit"] or 0),
                "total_earned":int(r["total_earned"] or 0),
                "reputation_score":int(r["reputation_score"] or 0),
                "business_count":business_count,
                "shop_count":int(r["shop_count"] or 0),
                "mining_count":int(r["mining_count"] or 0),
                "car_count":garage_count,
                "taxi_car_count":taxi_count,
                "current_car":str(r["current_car"] or "none"),
                "taxi_active":taxi_active,
                "last_seen_at":last_seen,
                "recently_active":bool(last_seen and now-last_seen <= 15*60),
            }
            item["customization"]=_public_customization_from_conn(conn,int(r["id"]),int(r["total_sales"] or 0))
            out.append(item)
        return out
    finally:
        conn.close()

def _add_friend_sync(player_id:int, friend_tg_id:int):
    conn=get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        me=conn.execute("SELECT id,tg_id,nickname,shop_name FROM players WHERE id=?",(int(player_id),)).fetchone()
        friend=conn.execute("SELECT id,tg_id,nickname,shop_name FROM players WHERE tg_id=?",(int(friend_tg_id),)).fetchone()
        if not me or not friend:
            conn.rollback(); return {"success":False,"error":"Игрок не найден"}
        if int(friend["id"])==int(me["id"]):
            conn.rollback(); return {"success":False,"error":"Нельзя добавить самого себя"}
        conn.execute("INSERT OR IGNORE INTO friends(player_id,friend_id) VALUES(?,?)",(int(me["id"]),int(friend["id"])))
        conn.execute("INSERT OR IGNORE INTO friends(player_id,friend_id) VALUES(?,?)",(int(friend["id"]),int(me["id"])))
        conn.commit()
        return {"success":True,"friend":{"id":int(friend["id"]),"tg_id":int(friend["tg_id"] or 0),"nickname":str(friend["nickname"] or "Игрок"),"shop_name":str(friend["shop_name"] or "Без магазина")},"already":False}
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()

@app.get("/friends/{tg_id}")
async def friends_list(tg_id:int, request:Request):
    if not _verify_telegram_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    friends=await run_sync_db(_friends_list_sync,pid)
    return JSONResponse({"success":True,"friends":friends,"count":len(friends)})

@app.post("/friends/add/{tg_id}")
async def friends_add(tg_id:int, request:Request):
    if not _verify_telegram_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try:
        data=await request.json()
    except Exception:
        data={}
    friend_tg_id=data.get("friend_tg_id") or data.get("tg_id") or data.get("friendId")
    try:
        friend_tg_id=int(friend_tg_id)
    except Exception:
        return JSONResponse({"success":False,"error":"Некорректный Telegram ID друга"},status_code=400)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    result=await run_sync_db(_add_friend_sync,pid,friend_tg_id)
    if not result.get("success"):
        return JSONResponse(result,status_code=400)
    return JSONResponse(result)

@app.get("/friends/search/{tg_id}")
async def friends_search(tg_id:int, request:Request, q:str=""):
    if not _verify_telegram_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    query=str(q or "").strip().lstrip("@").lower()
    if len(query)<2: return JSONResponse({"success":True,"players":[]})
    def _search():
        conn=get_db()
        try:
            rows=conn.execute("""SELECT id,tg_id,nickname,shop_name,balance,total_earned,total_sales,total_profit,reputation_score FROM players
                               WHERE id<>? AND is_banned=0 AND LOWER(nickname) LIKE ? ORDER BY nickname COLLATE NOCASE LIMIT 12""",(int(pid),f"%{query}%")).fetchall()
            existing={int(r[0]) for r in conn.execute("SELECT friend_id FROM friends WHERE player_id=?",(int(pid),)).fetchall()}
            out=[]
            for r in rows:
                item={"id":int(r[0]),"tg_id":int(r[1] or 0),"nickname":str(r[2] or "Игрок"),"shop_name":str(r[3] or "Без магазина"),"balance":int(r[4] or 0),"total_earned":int(r[5] or 0),"total_sales":int(r[6] or 0),"total_profit":int(r[7] or 0),"reputation_score":int(r[8] or 0),"is_friend":int(r[0]) in existing}
                item["customization"]=_public_customization_from_conn(conn,int(r[0]),int(r[6] or 0))
                out.append(item)
            return out
        finally: conn.close()
    return JSONResponse({"success":True,"players":await run_sync_db(_search)})

@app.post("/friends/signal/{tg_id}")
async def friends_signal(tg_id:int, request:Request):
    if not _verify_telegram_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    try: friend_tg_id=int(data.get("friend_tg_id") or 0)
    except Exception: friend_tg_id=0
    pid=await get_player_id_by_tg(tg_id)
    friend_pid=await get_player_id_by_tg(friend_tg_id) if friend_tg_id else 0
    if not pid or not friend_pid: return JSONResponse({"success":False,"error":"Друг не найден"},status_code=404)
    now=int(time_module.time()); day_key=_rfarm_cycle_key(now)
    def _signal():
        conn=get_db();
        try:
            rel=conn.execute("SELECT 1 FROM friends WHERE player_id=? AND friend_id=?",(int(pid),int(friend_pid))).fetchone()
            if not rel: return {"success":False,"error":"Можно поддерживать только друзей"}
            conn.execute("BEGIN IMMEDIATE")
            exists=conn.execute("SELECT 1 FROM friend_signals WHERE player_id=? AND friend_id=? AND day_key=?",(int(pid),int(friend_pid),day_key)).fetchone()
            if exists: conn.rollback(); return {"success":True,"already":True,"xp":0}
            conn.execute("INSERT INTO friend_signals(player_id,friend_id,day_key,created_at) VALUES(?,?,?,?)",(int(pid),int(friend_pid),day_key,now))
            conn.commit(); return {"success":True,"already":False,"xp":10}
        except Exception: conn.rollback(); raise
        finally: conn.close()
    result=await run_sync_db(_signal)
    if not result.get("success"): return JSONResponse(result,status_code=400)
    if not result.get("already"):
        await run_sync_db(_engagement_add_xp_sync,pid,10,"friend_signal")
        await run_sync_db(_engagement_add_xp_sync,friend_pid,10,"friend_signal_received")
    return JSONResponse({**result,"message":"Сигнал отправлен","recipient_tg_id":friend_tg_id})

@app.get("/hold/skins/{tg_id}")
async def rhold_skins_get(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    def _load():
        conn=get_db()
        try:
            row=conn.execute("SELECT balance,total_earned,total_sales FROM players WHERE id=?",(int(pid),)).fetchone()
            if not row: return None
            balance=int(row[0] or 0); total_sales=int(row[2] or 0)
            owned={str(r[0]) for r in conn.execute(
                "SELECT skin_id FROM rhold_button_skins WHERE player_id=? AND skin_id NOT LIKE 'equipped:%'",(int(pid),)
            ).fetchall()}
            equipped_rows=conn.execute(
                "SELECT skin_id FROM rhold_button_skins WHERE player_id=? AND skin_id LIKE 'equipped:%'",(int(pid),)
            ).fetchall()
            equipped={"rhold":"era1_core","nick":"none","avatar":"none","badge":"none"}
            for r in equipped_rows:
                raw=str(r[0])
                if raw.startswith("equipped:rhold:"): equipped["rhold"]=raw.split(":",2)[2]
                elif raw.startswith("equipped:nick:"): equipped["nick"]=raw.split(":",2)[2]
                elif raw.startswith("equipped:avatar:"): equipped["avatar"]=raw.split(":",2)[2]
                elif raw.startswith("equipped:badge:"): equipped["badge"]=raw.split(":",2)[2]
            active=int(conn.execute(
                "SELECT COUNT(*) FROM referral_relations r JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? AND r.reward_paid=1 AND COALESCE(p.is_banned,0)=0",(int(tg_id),)
            ).fetchone()[0] or 0)
            era=_cosmetic_unlocked_era_from_total_earned(int(row[1] or 0))
            unlocked_era=era
            rating=get_avito_rating(total_sales)
            return {"balance":balance,"unlocked_era":unlocked_era,"active_friends":active,"owned":sorted(owned),"equipped":equipped,"total_sales":total_sales,"rating":rating}
        finally: conn.close()
    state=await run_sync_db(_load)
    if not state: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    cat=[]
    for skin in RHOLD_BUTTON_SKINS:
        item=dict(skin)
        if item.get("legacy"):
            continue
        kind=str(item.get("kind") or "")
        unlock_method=str(item.get("unlock_method") or "era")
        if unlock_method=="stars":
            unlocked=True; reason=f"{int(item.get('stars_price',0))} ⭐"
        else:
            need_era=int(item.get("unlock_era",1) or 1)
            unlocked=state["unlocked_era"]>=need_era
            reason=f"ERA {need_era}"
        owned=item["id"] in state["owned"] or (item["id"]=="v28_base_signal" and state["unlocked_era"]>=1)
        slot=str(item.get("slot") or ("rhold" if kind in ("era","premium","network","rhold") else kind))
        item.update({"owned":owned,"unlocked":bool(unlocked),"lock_reason":reason,"slot":slot,
                     "equipped":state["equipped"].get(slot)==item["id"],"min_sales":int(item.get("min_sales",0) or 0),
                     "unlock_method":unlock_method,"stars_price":int(item.get("stars_price",0) or 0)})
        cat.append(item)
    return JSONResponse({"success":True,"skins":cat,"equipped":state["equipped"].get("rhold","era1_core"),
                         "equipped_slots":state["equipped"],"unlocked_era":state["unlocked_era"],
                         "active_friends":state["active_friends"],"balance":state["balance"],
                         "total_sales":state["total_sales"],"rating":state["rating"]})

@app.post("/hold/skins/{tg_id}/buy")
async def rhold_skins_buy(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    skin_id=str(data.get("skin_id") or "").strip(); skin=_rhold_skin_catalog_map().get(skin_id)
    if not skin: return JSONResponse({"success":False,"error":"Скин не найден"},status_code=404)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    def _buy():
        conn=get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT balance,total_earned,total_sales FROM players WHERE id=?",(int(pid),)).fetchone()
            if not row: conn.rollback(); return {"success":False,"error":"Player not found"}
            balance=int(row[0] or 0); sales=int(row[2] or 0)
            if conn.execute("SELECT 1 FROM rhold_button_skins WHERE player_id=? AND skin_id=?",(int(pid),skin_id)).fetchone():
                conn.rollback(); return {"success":True,"already":True,"balance":balance,"skin_id":skin_id}
            era=_cosmetic_unlocked_era_from_total_earned(int(row[1] or 0))
            unlock_method=str(skin.get("unlock_method") or "era")
            if unlock_method=="stars":
                conn.rollback(); return {"success":False,"error":"Этот предмет покупается через Telegram Stars","stars_price":int(skin.get("stars_price",0) or 0)}
            need_era=int(skin.get("unlock_era",1) or 1)
            if not skin.get("legacy") and era<need_era:
                conn.rollback(); return {"success":False,"error":f"Открой ERA {need_era}","need_era":need_era,"unlocked_era":era}
            if skin.get("legacy"):
                kind=str(skin.get("kind") or "")
                if kind=="era" and int(skin.get("era",1))>era:
                    conn.rollback(); return {"success":False,"error":f"Открой ERA {int(skin.get('era'))} через прогресс эпохи"}
                active=int(conn.execute("SELECT COUNT(*) FROM referral_relations r JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? AND r.reward_paid=1 AND COALESCE(p.is_banned,0)=0",(int(tg_id),)).fetchone()[0] or 0)
                if kind=="network" and active<int(skin.get("min_friends",0) or 0):
                    conn.rollback(); return {"success":False,"error":f"Нужно {int(skin.get('min_friends'))} активных друзей"}
                min_sales=int(skin.get("min_sales",0) or 0)
                if min_sales and sales<min_sales:
                    conn.rollback(); return {"success":False,"error":f"Нужно {min_sales} продаж на Авито","need_sales":min_sales,"sales":sales}
                price=int(skin.get("price",0) or 0)
            else:
                price=0
            if price and balance<price:
                conn.rollback(); return {"success":False,"error":f"Нужно {price:,} ₽","balance":balance}
            if price: conn.execute("UPDATE players SET balance=balance-? WHERE id=?",(price,int(pid)))
            conn.execute("INSERT INTO rhold_button_skins(player_id,skin_id,purchased_at) VALUES(?,?,?)",(int(pid),skin_id,int(time_module.time())))
            conn.commit(); return {"success":True,"balance":balance-price,"skin_id":skin_id,"charged":price}
        except Exception: conn.rollback(); raise
        finally: conn.close()
    return JSONResponse(await run_sync_db(_buy))

@app.post("/hold/skins/{tg_id}/stars-invoice")
async def rhold_stars_invoice(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    skin_id=str(data.get("skin_id") or "").strip()
    skin=_rhold_skin_catalog_map().get(skin_id)
    product=RHOLD_STAR_PRODUCTS.get(skin_id)
    if not skin or not product:
        return JSONResponse({"success":False,"error":"Это не Stars-товар"},status_code=400)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    owned=await run_sync_db(lambda: bool(get_db().execute("SELECT 1 FROM rhold_button_skins WHERE player_id=? AND skin_id=?",(int(pid),skin_id)).fetchone()))
    if owned: return JSONResponse({"success":False,"error":"Уже приобретено"},status_code=400)
    payload=f"rhold_star:{skin_id}:{int(tg_id)}"
    try:
        from aiogram.types import LabeledPrice
        invoice_url=await bot.create_invoice_link(
            title=product["title"],
            description=product["description"],
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=product["title"],amount=int(product["stars"]))],
            provider_token="",
        )
        return JSONResponse({"success":True,"invoice_url":invoice_url,"stars":int(product["stars"]),"skin_id":skin_id})
    except Exception as exc:
        print(f"[STARS] invoice error skin={skin_id}: {type(exc).__name__}: {exc}")
        return JSONResponse({"success":False,"error":"Не удалось создать оплату Stars"},status_code=503)

@dp.pre_checkout_query()
async def pre_checkout_stars(query):
    try:
        payload=str(query.invoice_payload or "")
        if not payload.startswith("rhold_star:"):
            await query.answer(ok=False,error_message="Платёж RESSELL не распознан")
            return
        _,skin_id,tg_id=payload.split(":",2)
        valid=skin_id in RHOLD_STAR_PRODUCTS and str(query.from_user.id)==str(tg_id)
        await query.answer(ok=valid,error_message=None if valid else "Платёж не подтверждён")
    except Exception as exc:
        print(f"[STARS] pre_checkout error: {type(exc).__name__}: {exc}")
        try: await query.answer(ok=False,error_message="Платёж временно недоступен")
        except Exception: pass

@dp.message(F.successful_payment)
async def successful_stars_payment(message: types.Message):
    payment=message.successful_payment
    try:
        payload=str(payment.invoice_payload or "")
        if not payload.startswith("rhold_star:"): return
        parts=payload.split(":",2)
        if len(parts)!=3: return
        _,skin_id,tg_id=parts
        if str(message.from_user.id)!=str(tg_id) or skin_id not in RHOLD_STAR_PRODUCTS: return
        pid=await get_player_id_by_tg(int(tg_id))
        if not pid: return
        def _grant():
            conn=get_db()
            try:
                conn.execute("INSERT OR IGNORE INTO rhold_button_skins(player_id,skin_id,purchased_at) VALUES(?,?,?)",(int(pid),skin_id,int(time_module.time())))
                conn.commit()
            finally: conn.close()
        await run_sync_db(_grant)
        print(f"[STARS] granted skin={skin_id} tg_id={tg_id} stars={payment.total_amount}")
    except Exception as exc:
        print(f"[STARS] grant error: {type(exc).__name__}: {exc}")

@app.post("/hold/skins/{tg_id}/equip")
async def rhold_skins_equip(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    skin_id=str(data.get("skin_id") or "").strip(); skin=_rhold_skin_catalog_map().get(skin_id)
    if not skin: return JSONResponse({"success":False,"error":"Скин не найден"},status_code=404)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    kind=str(skin.get("kind") or "")
    slot=str(skin.get("slot") or ("rhold" if kind in ("era","premium","network") else kind))
    def _equip():
        conn=get_db()
        try:
            row=conn.execute("SELECT balance,total_sales FROM players WHERE id=?",(int(pid),)).fetchone()
            if not row: return {"success":False,"error":"Player not found"}
            owned = skin_id=="era1_core" or bool(conn.execute("SELECT 1 FROM rhold_button_skins WHERE player_id=? AND skin_id=?",(int(pid),skin_id)).fetchone())
            if not owned: return {"success":False,"error":"Сначала открой этот предмет в магазине"}
            conn.execute("DELETE FROM rhold_button_skins WHERE player_id=? AND skin_id LIKE ?",(int(pid),f"equipped:{slot}:%"))
            conn.execute("INSERT OR REPLACE INTO rhold_button_skins(player_id,skin_id,purchased_at) VALUES(?,?,?)",(int(pid),f"equipped:{slot}:{skin_id}",int(time_module.time())))
            conn.commit(); return {"success":True,"equipped":skin_id,"slot":slot}
        finally: conn.close()
    return JSONResponse(await run_sync_db(_equip))

@app.get("/referrals/{tg_id}")
async def referrals_status(tg_id: int):
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        player_id = await run_sync_db(get_or_create_player, "tg", tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
    def _status():
        conn = get_db()
        rels = conn.execute("SELECT r.invitee_tg_id,r.activated_at,r.reward_paid,COALESCE(p.is_banned,0) is_banned FROM referral_relations r LEFT JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? ORDER BY r.activated_at DESC", (tg_id,)).fetchall()
        incoming = conn.execute("SELECT inviter_tg_id FROM referral_relations WHERE invitee_tg_id=?", (tg_id,)).fetchone()
        pending = conn.execute("SELECT inviter_tg_id FROM referral_pending WHERE invitee_tg_id=?", (tg_id,)).fetchone()
        milestone_rows = conn.execute("SELECT target,reward FROM referral_milestones WHERE player_id=? ORDER BY target", (player_id,)).fetchall()
        conn.close()
        return rels, incoming, pending, milestone_rows
    rels, incoming, pending, milestone_rows = await run_sync_db(_status)
    active = len([r for r in rels if int(r["reward_paid"] or 0) == 1 and int(r["is_banned"] or 0) == 0])
    inviter_tg = int(incoming["inviter_tg_id"]) if incoming else (int(pending["inviter_tg_id"]) if pending else None)
    inviter = None
    if inviter_tg:
        inviter_player_id = await get_player_id_by_tg(inviter_tg)
        inviter_player = await run_sync_db(get_player_data, inviter_player_id) if inviter_player_id else None
        if inviter_player:
            inviter = {"id": inviter_tg, "nickname": inviter_player.get("nickname", "Друг"), "pending": bool(pending and not incoming)}
    milestone_earned = sum(int(r["reward"] or 0) for r in milestone_rows)
    next_target = next((x["target"] for x in REFERRAL_MILESTONES if x["target"] > active), 0)
    boost_multiplier = 1.0
    for target,mult in REFERRAL_BOOST_TIERS:
        if active>=target: boost_multiplier=mult
        else: break
    title=get_referral_title(active)
    referral_passive_percent = get_referral_passive_percent(active)
    milestones = [{"target":m["target"],"reward":f"+{m['reward']:,} ₽","title":m["title"],"sub":f"{m['target']} активных друзей","extra":f"+{m['reward']:,} ₽"} for m in REFERRAL_MILESTONES]
    return JSONResponse({"success": True, "active": active, "total": len(rels), "earned": active * REFERRAL_DIRECT_REWARD + milestone_earned, "pending": 0, "direct_reward": REFERRAL_DIRECT_REWARD, "passive_percent": referral_passive_percent, "passive_days": 0, "boost_multiplier": boost_multiplier, "referral_title": title, "invitee_bonus": REFERRAL_INVITEE_BONUS, "next_target": next_target, "invited_by": inviter, "pending_activation": bool(pending and not incoming), "invite_link": f"https://t.me/{BOT_USERNAME}?start=ref_{tg_id}", "milestones": milestones})

@app.post("/referrals/attach/{tg_id}")
async def referrals_attach(tg_id: int, request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    token = data.get("referrer_id") or data.get("ref") or data.get("startapp")
    inviter_tg = await run_sync_db(resolve_referrer_token, str(token or ""))
    if not inviter_tg or int(inviter_tg) == int(tg_id):
        return JSONResponse({"success": False, "error": "Некорректный или собственный реферальный код"}, status_code=400)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        player_id = await run_sync_db(get_or_create_player, "tg", tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Пользователь не зарегистрирован"}, status_code=404)
    attached = await run_sync_db(set_pending_referral, int(tg_id), int(inviter_tg), "webapp")
    pending = await run_sync_db(get_pending_referral, int(tg_id))
    return JSONResponse({"success": True, "pending": bool(pending), "activated": False, "inviter_tg_id": int(pending or inviter_tg), "message": "Реферал сохранён. Бонус активируется после первого реального действия." if attached else "Реферал уже сохранён."})

@app.post("/referrals/claim/{tg_id}")
async def referrals_claim_compat(tg_id: int):
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS cnt FROM referral_relations WHERE inviter_tg_id=? AND reward_paid=1",(tg_id,)).fetchone()
    conn.close()
    active = int(row["cnt"] if row else 0)
    return JSONResponse({"success":True,"reward":0,"referral":{"active":active,"pending":0,"earned":active*REFERRAL_DIRECT_REWARD},"message":"Награды за активных друзей начисляются автоматически."})


# Legacy route names kept as thin aliases so old frontend builds do not crash.
async def referrals_get(tg_id: int):
    return await referrals_status(tg_id)


async def referrals_claim(tg_id: int, request: Request):
    return await referrals_claim_compat(tg_id)

# ==================== R-FARM: SERVER-AUTHORITATIVE ====================
def _rfarm_cycle_key(ts: int) -> str:
    """Trading day for R-Farm: every day starts at 12:00 Moscow time (UTC+3)."""
    from datetime import datetime, timedelta, timezone
    msk = timezone(timedelta(hours=3))
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(msk)
    if dt.hour < 12:
        dt -= timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def _rfarm_current_reward(elapsed: float, target_duration: float, target_reward: int) -> int:
    elapsed = max(0.0, min(float(elapsed), float(target_duration)))
    target_duration = max(0.1, float(target_duration))
    target_reward = max(HOLD_REWARD_MIN, min(HOLD_REWARD_MAX * 8, int(target_reward)))
    # The player sees the amount accumulating, but never sees the hidden target.
    progress = elapsed / target_duration
    return int(round(target_reward * progress))


def _rfarm_status_sync(player_id: int, now: int):
    conn=get_db(); cur=conn.cursor()
    try:
        row=cur.execute(
            "SELECT session_id,started_at,last_completed_at,total_claims,target_reward,target_duration "
            "FROM hold_sessions WHERE player_id=?",(player_id,)
        ).fetchone()
        if not row:
            return {"session_id":None,"started_at":0,"last_completed_at":0,"total_claims":0,"target_reward":0,"target_duration":HOLD_DURATION_SECONDS}
        return dict(row)
    finally:
        conn.close()


def _rfarm_ready(last_completed_at: int, now: int) -> bool:
    # No rolling 24h timer: readiness is determined only by the current Moscow 12:00 cycle.
    return _rfarm_cycle_key(now) != _rfarm_cycle_key(last_completed_at) if last_completed_at else True

def _rfarm_next_reset_ts(now: int) -> int:
    from datetime import datetime, timedelta, timezone
    msk=timezone(timedelta(hours=3))
    dt=datetime.fromtimestamp(int(now),tz=timezone.utc).astimezone(msk)
    reset=dt.replace(hour=12,minute=0,second=0,microsecond=0)
    if dt >= reset: reset += timedelta(days=1)
    return int(reset.timestamp())


def _equipped_rhold_style_sync(conn, player_id:int) -> dict:
    try:
        row=conn.execute("SELECT skin_id FROM rhold_button_skins WHERE player_id=? AND skin_id LIKE 'equipped:rhold:%' ORDER BY purchased_at DESC LIMIT 1",(int(player_id),)).fetchone()
        skin_id=str(row[0]).split(":",2)[2] if row else "era1_core"
    except Exception:
        skin_id="era1_core"
    skin=_rhold_skin_catalog_map().get(skin_id) or _rhold_skin_catalog_map().get("era1_core") or {}
    mult=max(1.0,float(skin.get("reward_multiplier",1.0) or 1.0))
    return {"id":skin_id,"name":str(skin.get("name") or skin_id),"accent":str(skin.get("accent") or "#b7ff6a"),"multiplier":mult,"tier":str(skin.get("tier") or "BASE")}


@app.get("/hold/status/{tg_id}")
async def hold_status(tg_id: int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id): return JSONResponse({"success":False,"error":"Не найден Telegram ID"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    now=time_module.time()
    row=await run_sync_db(_rfarm_status_sync,player_id,int(now))
    def _style_read():
        conn=get_db()
        try: return _equipped_rhold_style_sync(conn,player_id)
        finally: conn.close()
    rhold_style=await run_sync_db(_style_read)
    session_id=row.get("session_id")
    started=int(row.get("started_at") or 0)
    target_duration=max(HOLD_RANDOM_MIN_SECONDS,min(HOLD_RANDOM_MAX_SECONDS,int(row.get("target_duration") or HOLD_DURATION_SECONDS)))
    elapsed=max(0.0,now-started) if session_id and started else 0.0
    current_reward=_rfarm_current_reward(elapsed,target_duration,int(row.get("target_reward") or HOLD_REWARD_MIN)) if session_id else 0
    progress=(elapsed/target_duration) if session_id and target_duration else 0.0
    last=int(row.get("last_completed_at") or 0)
    ready=_rfarm_ready(last,now) and not session_id
    reset_ts=_rfarm_next_reset_ts(now)
    cooldown_until=0 if ready else reset_ts
    cooldown_remaining=max(0,cooldown_until-now) if cooldown_until else 0
    # Once the hidden stop moment is reached, the client is told to finalize.
    auto_complete=bool(session_id and elapsed>=target_duration)
    return JSONResponse({
        "success":True,"ready":ready,"session_id":session_id,"started_at":started,
        "active_elapsed":elapsed,"active_remaining":max(0,target_duration-elapsed),
        "duration":HOLD_DURATION_SECONDS,
        "progress":max(0.0,min(1.0,progress)),
        "current_reward":current_reward,
        "auto_complete":auto_complete,
        "last_completed_at":last,"cycle_key":_rfarm_cycle_key(now),
        "cooldown_until":cooldown_until,
        "cooldown_remaining":cooldown_remaining,
        "base_reward_min":HOLD_REWARD_MIN,"base_reward_max":HOLD_REWARD_MAX * int(round(rhold_style.get("multiplier",1.0) or 1.0)),
        "reward_multiplier":rhold_style.get("multiplier",1.0),"rhold_style":rhold_style,
        "claims":int(row.get("total_claims") or 0)
    })


@app.post("/hold/start/{tg_id}")
async def hold_start(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id): return JSONResponse({"success":False,"error":"Не найден Telegram ID"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    now=time_module.time(); sid=uuid.uuid4().hex
    # Reward is determined by the equipped R-HOLD at the exact moment the session starts.
    # Changing cosmetics during a running hold cannot retroactively change its payout.
    def _start_style_read():
        conn=get_db()
        try: return _equipped_rhold_style_sync(conn,player_id)
        finally: conn.close()
    rhold_style=await run_sync_db(_start_style_read)
    reward_multiplier=max(1.0,float(rhold_style.get("multiplier",1.0) or 1.0))
    target_reward=random.randint(HOLD_REWARD_MIN,HOLD_REWARD_MAX) * reward_multiplier
    target_reward=int(round(target_reward))
    target_duration=HOLD_DURATION_SECONDS
    lock=player_action_locks.setdefault(f"hold:{player_id}",asyncio.Lock())
    async with lock:
        async with db_lock:
            def _start():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    row=cur.execute("SELECT session_id,last_completed_at FROM hold_sessions WHERE player_id=?",(player_id,)).fetchone()
                    if row and row["session_id"]:
                        conn.rollback(); return ("active",row["session_id"])
                    last=int(row["last_completed_at"] or 0) if row else 0
                    if not _rfarm_ready(last,now):
                        conn.rollback(); return ("cooldown",_rfarm_cycle_key(now))
                    cur.execute("""INSERT INTO hold_sessions(player_id,session_id,started_at,last_completed_at,total_claims,target_reward,target_duration)
                        VALUES(?,?,?,?,0,?,?)
                        ON CONFLICT(player_id) DO UPDATE SET session_id=excluded.session_id,started_at=excluded.started_at,
                        target_reward=excluded.target_reward,target_duration=excluded.target_duration""",
                        (player_id,sid,now,last,target_reward,target_duration))
                    conn.commit(); return ("started",sid)
                except Exception:
                    conn.rollback(); raise
                finally: conn.close()
            result=await run_sync_db(_start)
    if result[0]=="active": return JSONResponse({"success":False,"error":"У тебя уже идёт R-Farm","session_id":result[1]},status_code=409)
    if result[0]=="cooldown": return JSONResponse({"success":False,"error":"R-Farm станет доступен после 12:00 МСК следующего цикла"},status_code=429)
    return JSONResponse({"success":True,"session_id":result[1],"started_at":now,"duration":HOLD_DURATION_SECONDS,"min_reward":HOLD_REWARD_MIN,"max_reward":HOLD_REWARD_MAX})


@app.post("/hold/cancel/{tg_id}")
async def hold_cancel(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id): return JSONResponse({"success":False,"error":"Не найден Telegram ID"},status_code=401)

    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    try: data=await request.json()
    except Exception: data={}
    sid=str(data.get("session_id") or "")
    def _cancel():
        conn=get_db(); cur=conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            if sid:
                cur.execute("UPDATE hold_sessions SET session_id=NULL,started_at=0,target_reward=0,target_duration=? WHERE player_id=? AND session_id=?",(HOLD_DURATION_SECONDS,player_id,sid))
            else:
                cur.execute("UPDATE hold_sessions SET session_id=NULL,started_at=0,target_reward=0,target_duration=? WHERE player_id=?",(HOLD_DURATION_SECONDS,player_id))
            conn.commit(); return cur.rowcount
        except Exception: conn.rollback(); raise
        finally: conn.close()
    await run_sync_db(_cancel)
    return JSONResponse({"success":True})


@app.post("/hold/complete/{tg_id}")
async def hold_complete(tg_id:int, request:Request):
    if not _verify_hold_and_checkin_request(request,tg_id): return JSONResponse({"success":False,"error":"Не найден Telegram ID"},status_code=401)

    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    try: data=await request.json()
    except Exception: data={}
    session_id=str(data.get("session_id") or "")
    now=time_module.time()
    lock=player_action_locks.setdefault(f"hold:{player_id}",asyncio.Lock())
    async with lock:
        async with db_lock:
            def _complete():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    row=cur.execute("SELECT session_id,started_at,last_completed_at,total_claims,target_reward,target_duration FROM hold_sessions WHERE player_id=?",(player_id,)).fetchone()
                    if not row or not row["session_id"] or row["session_id"]!=session_id:
                        conn.rollback(); return ("invalid",)
                    last=int(row["last_completed_at"] or 0)
                    if not _rfarm_ready(last,now):
                        conn.rollback(); return ("cooldown",)
                    started=float(row["started_at"] or 0); target_duration=max(HOLD_RANDOM_MIN_SECONDS,min(HOLD_RANDOM_MAX_SECONDS,int(row["target_duration"] or HOLD_DURATION_SECONDS)))
                    elapsed=max(0.0,now-started)
                    # Releasing early pays the exact server-calculated amount accumulated so far.
                    reward=_rfarm_current_reward(min(elapsed,target_duration),target_duration,int(row["target_reward"] or HOLD_REWARD_MIN))
                    # Exactly the displayed server reward is what gets credited. No referral multiplier is applied here.
                    cur.execute("UPDATE players SET balance=balance+?,total_earned=total_earned+? WHERE id=?",(reward,reward,player_id))
                    cur.execute("UPDATE hold_sessions SET session_id=NULL,started_at=0,last_completed_at=?,total_claims=total_claims+1,target_reward=0,target_duration=? WHERE player_id=?",(now,HOLD_DURATION_SECONDS,player_id))
                    bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                    conn.commit(); return ("ok",reward,int(bal["balance"] if bal else 0),elapsed,target_duration)
                except Exception: conn.rollback(); raise
                finally: conn.close()
            result=await run_sync_db(_complete)
    if result[0]=="invalid": return JSONResponse({"success":False,"error":"Сессия не найдена или уже завершена"},status_code=409)
    if result[0]=="cooldown": return JSONResponse({"success":False,"error":"R-Farm уже использован в этом цикле"},status_code=429)
    await run_sync_db(update_daily_quest,player_id,"farm_once",1)
    await run_sync_db(_engagement_add_xp_sync,player_id,20,"farm_complete")
    await activate_pending_referral(int(tg_id),"hold_complete")
    reset_ts=_rfarm_next_reset_ts(int(now))
    return JSONResponse({"success":True,"reward":result[1],"balance":result[2],"elapsed":result[3],"stop_duration":result[4],"cycle_key":_rfarm_cycle_key(now),"cooldown":max(0,reset_ts-int(now)),"cooldown_remaining":max(0,reset_ts-int(now)),"cooldown_until":reset_ts})


# ==================== PRIVATE ADMIN API ====================
def _admin_player_sync(tg_id:int):
    conn=get_db()
    row=conn.execute("SELECT id,tg_id,nickname,shop_name,balance,day,total_sales,total_profit,total_earned,items_sold,created_at,is_banned,warning_count FROM players WHERE tg_id=?",(int(tg_id),)).fetchone()
    conn.close()
    return dict(row) if row else None

def _admin_search_sync(q:str, limit:int=30):
    conn=get_db(); q=str(q or '').strip(); like=f"%{q}%"
    if q.isdigit():
        rows=conn.execute("SELECT id,tg_id,nickname,shop_name,balance,is_banned,warning_count,total_earned,total_sales FROM players WHERE tg_id=? OR id=? LIMIT ?",(int(q),int(q),limit)).fetchall()
    else:
        rows=conn.execute("SELECT id,tg_id,nickname,shop_name,balance,is_banned,warning_count,total_earned,total_sales FROM players WHERE nickname LIKE ? OR shop_name LIKE ? ORDER BY id DESC LIMIT ?",(like,like,limit)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def _admin_logs_sync(target_tg_id:int=None, limit:int=100):
    conn=get_db()
    if target_tg_id:
        rows=conn.execute("SELECT id,actor_tg_id,target_tg_id,action,amount,details,created_at FROM audit_logs WHERE target_tg_id=? ORDER BY id DESC LIMIT ?",(int(target_tg_id),limit)).fetchall()
    else:
        rows=conn.execute("SELECT id,actor_tg_id,target_tg_id,action,amount,details,created_at FROM audit_logs ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    conn.close(); return [dict(r) for r in rows]

def _admin_cars_sync(player_id:int):
    p=get_player_data(player_id) or {}; owned=list(p.get('car_collection',[]) or [])
    return [{"id":c["id"],"name":c["name"],"price":c["price"],"owned":c["id"] in owned} for c in CARS]

@app.get("/admin/me/{admin_tg_id}")
async def admin_me(admin_tg_id:int):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    def _admins():
        conn=get_db(); rows=[dict(r) for r in conn.execute("SELECT tg_id,added_by,active,created_at FROM admin_users WHERE active=1 ORDER BY created_at").fetchall()]; conn.close(); return rows
    admins=await run_sync_db(_admins)
    return JSONResponse({"success":True,"super_admin":int(admin_tg_id)==int(ADMIN_SUPER_ID),"admins":admins})

@app.get("/admin/players/{admin_tg_id}")
async def admin_players(admin_tg_id:int, q:str="", limit:int=30):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    rows=await run_sync_db(_admin_search_sync,q,min(max(int(limit),1),100))
    return JSONResponse({"success":True,"players":rows})

@app.get("/admin/player/{admin_tg_id}/{target_tg_id}")
async def admin_player(admin_tg_id:int,target_tg_id:int):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    p=await run_sync_db(_admin_player_sync,target_tg_id)
    if not p: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    pid=int(p["id"])
    shops=await run_sync_db(lambda: [dict(r) for r in get_db().execute("SELECT shop_id FROM user_shops WHERE player_id=?",(pid,)).fetchall()])
    cars=await run_sync_db(_admin_cars_sync,pid)
    logs=await run_sync_db(_admin_logs_sync,target_tg_id,80)
    security=await run_sync_db(_ban_status_sync,target_tg_id)
    catalog=[{"id":x.get("id"),"name":x.get("name"),"price":int(x.get("price",0)),"income_per_hour":int(x.get("income_per_hour",0))} for x in SHOP_LEVELS if x.get("id") and x.get("id")!="none"]
    skins=[{"id":x.get("id"),"name":x.get("name"),"price":int(x.get("price",0))} for x in SKINS]
    return JSONResponse({"success":True,"player":p,"security":security,"shops":shops,"cars":cars,"catalog":catalog,"skins":skins,"logs":logs})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/balance")
async def admin_give_balance(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    data=await request.json(); amount=int(data.get("amount",0)); reason=str(data.get("reason") or "Админское начисление")
    if amount==0: return JSONResponse({"success":False,"error":"Сумма не может быть 0"},status_code=400)
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    p=await run_sync_db(get_player_data,pid); old=int((p or {}).get('balance',0)); new=old+amount
    if new<0: return JSONResponse({"success":False,"error":"Баланс не может быть отрицательным"},status_code=400)
    await run_sync_db(update_player_data,pid,{"balance":new})
    await audit(admin_tg_id,target_tg_id,"admin_balance",amount,reason)
    return JSONResponse({"success":True,"balance":new})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/car")
async def admin_give_car(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    data=await request.json(); car_id=str(data.get("car_id") or ""); car=next((c for c in CARS if c["id"]==car_id),None)
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid or not car: return JSONResponse({"success":False,"error":"Игрок или машина не найдены"},status_code=404)
    p=await run_sync_db(get_player_data,pid) or {}; cars=list(p.get('car_collection',[]) or [])
    if car_id not in cars: cars.append(car_id)
    await run_sync_db(update_player_data,pid,{"car_collection":cars})
    await audit(admin_tg_id,target_tg_id,"admin_car",int(car.get('price',0)),f"Выдана машина: {car_id}")
    return JSONResponse({"success":True,"car_id":car_id})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/business")
async def admin_give_business(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    data=await request.json(); shop_id=str(data.get("shop_id") or ""); shop=next((x for x in SHOP_LEVELS if x.get("id")==shop_id and x.get("id")!="none"),None)
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid or not shop: return JSONResponse({"success":False,"error":"Игрок или бизнес не найдены"},status_code=404)
    conn=get_db()
    exists=conn.execute("SELECT 1 FROM user_shops WHERE player_id=? AND shop_id=?",(pid,shop_id)).fetchone()
    if exists: conn.close(); return JSONResponse({"success":False,"error":"У игрока уже есть этот бизнес"},status_code=400)
    now=int(time_module.time())
    # Используем ту же таблицу/схему, что и обычная покупка.
    cols=[r[1] for r in conn.execute("PRAGMA table_info(user_shops)").fetchall()]
    try:
        if 'purchase_time' in cols and 'maintenance_paid_until' in cols:
            conn.execute("INSERT INTO user_shops(player_id,shop_id,purchase_price,purchase_time,maintenance_paid_until) VALUES(?,?,?,?,?)",(pid,shop_id,0,now,now+30*86400))
        elif 'purchase_time' in cols:
            conn.execute("INSERT INTO user_shops(player_id,shop_id,purchase_price,purchase_time) VALUES(?,?,?,?)",(pid,shop_id,0,now))
        else:
            conn.execute("INSERT INTO user_shops(player_id,shop_id,purchase_price) VALUES(?,?,?)",(pid,shop_id,0))
        conn.commit()
    except Exception as e:
        conn.close(); return JSONResponse({"success":False,"error":f"Не удалось выдать бизнес: {e}"},status_code=400)
    conn.close(); await audit(admin_tg_id,target_tg_id,"admin_business",0,f"Выдан бизнес: {shop_id}")
    return JSONResponse({"success":True,"shop_id":shop_id})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/skin")
async def admin_give_skin(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    data=await request.json(); skin_id=str(data.get("skin_id") or ""); skin=next((x for x in SKINS if x.get("id")==skin_id),None)
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid or not skin: return JSONResponse({"success":False,"error":"Игрок или скин не найдены"},status_code=404)
    conn=get_db(); conn.execute("INSERT OR IGNORE INTO skins(player_id,skin_id,equipped) VALUES(?,?,0)",(pid,skin_id)); conn.commit(); conn.close()
    await audit(admin_tg_id,target_tg_id,"admin_skin",0,f"Выдан скин: {skin_id}")
    return JSONResponse({"success":True,"skin_id":skin_id})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/warning")
async def admin_warning(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    data=await request.json(); reason=str(data.get("reason") or "Нарушение правил")
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    def _warn():
        conn=get_db(); conn.execute("UPDATE players SET warning_count=COALESCE(warning_count,0)+1 WHERE id=?",(pid,)); row=conn.execute("SELECT warning_count FROM players WHERE id=?",(pid,)).fetchone(); conn.commit(); conn.close(); return int(row["warning_count"] or 0)
    count=await run_sync_db(_warn); await audit(admin_tg_id,target_tg_id,"admin_warning",0,reason)
    try: await bot.send_message(target_tg_id,f"⚠️ <b>Предупреждение RESSELL</b>\n\nПричина: {reason}\nВсего предупреждений: {count}",parse_mode="HTML")
    except Exception: pass
    return JSONResponse({"success":True,"warning_count":count})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/ban")
async def admin_ban(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    if int(target_tg_id)==int(ADMIN_SUPER_ID): return JSONResponse({"success":False,"error":"Нельзя заблокировать владельца"},status_code=400)
    data=await request.json(); reason=str(data.get("reason") or "Нарушение правил")
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    await run_sync_db(update_player_data,pid,{"is_banned":1}); await audit(admin_tg_id,target_tg_id,"admin_ban",0,reason)
    try: await bot.send_message(target_tg_id,f"⛔ <b>Аккаунт заблокирован</b>\n\nПричина: {reason}",parse_mode="HTML")
    except Exception: pass
    return JSONResponse({"success":True,"banned":True})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/unban")
async def admin_unban(admin_tg_id:int,target_tg_id:int,request:Request):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    data=await request.json(); reason=str(data.get("reason") or "Блокировка снята")
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    await run_sync_db(update_player_data,pid,{"is_banned":0}); await audit(admin_tg_id,target_tg_id,"admin_unban",0,reason)
    return JSONResponse({"success":True,"banned":False})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/reset")
async def admin_reset_player(admin_tg_id:int, target_tg_id:int, request:Request):
    """Полный сброс аккаунта из приватной админ-панели.

    После сброса старые referral_relations/referral_pending тоже удаляются,
    поэтому тот же Telegram ID можно заново пригласить по реферальной ссылке.
    """
    if not await admin_allowed(admin_tg_id):
        return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    target_tg_id=int(target_tg_id)
    if target_tg_id==int(ADMIN_SUPER_ID):
        return JSONResponse({"success":False,"error":"Нельзя удалить аккаунт владельца"},status_code=400)
    try:
        result=await run_sync_db(reset_player_account_sync,target_tg_id)
        await audit(admin_tg_id,target_tg_id,"admin_reset",0,"Полный сброс аккаунта, включая реферальные связи")
        return JSONResponse({"success":True,**result,"message":"Аккаунт полностью сброшен. Пользователь сможет пройти регистрацию заново."})
    except Exception as e:
        print(f"[ADMIN RESET] {target_tg_id}: {e}")
        return JSONResponse({"success":False,"error":"Не удалось полностью сбросить аккаунт"},status_code=500)

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/rfarm-reset")
async def admin_reset_rfarm(admin_tg_id:int,target_tg_id:int):
    if not await admin_allowed(admin_tg_id):
        return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    pid=await get_player_id_by_tg(target_tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    def _reset():
        conn=get_db();cur=conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute("UPDATE hold_sessions SET last_completed_at=0,session_id=NULL,started_at=0,target_reward=0,target_duration=? WHERE player_id=?",(HOLD_DURATION_SECONDS,pid))
            if cur.rowcount==0:
                cur.execute("INSERT INTO hold_sessions(player_id,session_id,started_at,last_completed_at,total_claims,target_reward,target_duration) VALUES(?,?,?,?,?,?,?)",(pid,None,0,0,0,0,HOLD_DURATION_SECONDS))
            conn.commit();return True
        except Exception:conn.rollback();raise
        finally:conn.close()
    await run_sync_db(_reset)
    await audit(admin_tg_id,target_tg_id,"rfarm_reset",0,"Администратор снял CD R-Farm")
    return JSONResponse({"success":True,"message":"CD R-Farm снят. Игрок может запустить новый раунд."})

@app.get("/admin/player/{admin_tg_id}/{target_tg_id}/logs")
async def admin_player_logs(admin_tg_id:int,target_tg_id:int,limit:int=150):
    if not await admin_allowed(admin_tg_id): return JSONResponse({"success":False,"error":"Нет доступа"},status_code=403)
    return JSONResponse({"success":True,"logs":await run_sync_db(_admin_logs_sync,target_tg_id,min(max(limit,1),300))})

@app.post("/admin/player/{admin_tg_id}/{target_tg_id}/admin")
async def admin_set_admin(admin_tg_id:int,target_tg_id:int,request:Request):
    if int(admin_tg_id)!=int(ADMIN_SUPER_ID): return JSONResponse({"success":False,"error":"Только владелец может управлять администраторами"},status_code=403)
    data=await request.json(); enabled=bool(data.get('enabled',True))
    if target_tg_id==ADMIN_SUPER_ID: return JSONResponse({"success":False,"error":"Владелец всегда администратор"},status_code=400)
    def _set():
        conn=get_db()
        if enabled: conn.execute("INSERT INTO admin_users(tg_id,added_by,active,created_at) VALUES(?,?,1,?) ON CONFLICT(tg_id) DO UPDATE SET active=1,added_by=excluded.added_by",(target_tg_id,admin_tg_id,int(time_module.time())))
        else: conn.execute("UPDATE admin_users SET active=0 WHERE tg_id=?",(target_tg_id,))
        conn.commit(); conn.close()
    await run_sync_db(_set); await audit(admin_tg_id,target_tg_id,"admin_role",0,"Выдана админка" if enabled else "Админка снята")
    return JSONResponse({"success":True,"admin":enabled})

# ==================== RESSELL TYCOON MINI APP API ====================
# These endpoints expose the existing game logic to the Mini App. All money,
# validation and database mutations remain server-side.

@app.get("/tycoon/bank/{tg_id}")
async def tycoon_bank(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success":False,"error":"Вы не зарегистрированы"},status_code=404)
    player = await run_sync_db(get_player_data, player_id)
    now=int(time_module.time())
    def _read():
        conn=get_db()
        deps=conn.execute("SELECT id,amount,start_time,duration_days,interest_rate,status FROM deposits WHERE player_id=? ORDER BY id DESC",(player_id,)).fetchall()
        loans=conn.execute("SELECT id,amount,interest_rate,start_time,due_date,status,paid_amount FROM loans WHERE player_id=? ORDER BY id DESC",(player_id,)).fetchall()
        conn.close()
        return [dict(x) for x in deps],[dict(x) for x in loans]
    deps,loans=await run_sync_db(_read)
    for d in deps:
        d["return_amount"]=int(d["amount"]*(1+d["interest_rate"]/100))
        d["remaining_seconds"]=max(0,int(d["start_time"]+d["duration_days"]*86400-now)) if d["status"]=="active" else 0
        d["ready"]=d["status"]=="active" and d["remaining_seconds"]<=0
    for l in loans:
        l["return_amount"]=int(l["amount"]*(1+l["interest_rate"]/100))
        l["remaining_seconds"]=max(0,int(l["due_date"]-now)) if l["status"]=="active" else 0
    max_loan=await calculate_max_loan(player)
    return JSONResponse({"success":True,"balance":int(player.get("balance",0) or 0),"deposits":deps,"loans":loans,"max_loan":int(max_loan),"deposit_min":10000,"deposit_max":10000000})

@app.post("/tycoon/bank/{tg_id}/deposit")
async def tycoon_open_deposit(tg_id:int,request:Request):
    try: data=await request.json()
    except Exception: data={}
    days=int(data.get("days") or 0); amount=int(data.get("amount") or 0)
    rates={1:2,3:5,7:10}
    rate=rates.get(days)
    if not rate: return JSONResponse({"success":False,"error":"Неверный срок депозита"},status_code=400)
    if amount<10000 or amount>10000000: return JSONResponse({"success":False,"error":"Сумма депозита от 10 000 до 10 000 000 ₽"},status_code=400)
    pid=await get_player_id_by_tg(tg_id)
    player=await run_sync_db(get_player_data,pid) if pid else None
    if not player: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    if int(player.get("balance",0))<amount: return JSONResponse({"success":False,"error":"Недостаточно средств"},status_code=400)
    now=int(time_module.time())
    async with db_lock:
        conn=get_db()
        conn.execute("UPDATE players SET balance=balance-? WHERE id=?",(amount,pid))
        conn.execute("INSERT INTO deposits(player_id,amount,start_time,duration_days,interest_rate,status) VALUES(?,?,?,?,?,'active')",(pid,amount,now,days,rate))
        conn.commit(); conn.close()
    fresh=await run_sync_db(get_player_data,pid) or {}
    return JSONResponse({"success":True,"message":f"Депозит на {amount:,} ₽ открыт на {days} дн. под {rate}%","balance":int(fresh.get("balance",0) or 0)})

@app.post("/tycoon/bank/{tg_id}/loan")
async def tycoon_take_loan(tg_id:int,request:Request):
    try:
        data=await request.json()
    except Exception:
        data={}
    amount=int(data.get("amount") or 0)
    if amount<10000 or amount>1000000:
        return JSONResponse({"success":False,"error":"Кредит от 10 000 до 1 000 000 ₽"},status_code=400)

    pid=await get_player_id_by_tg(tg_id)
    player=await run_sync_db(get_player_data,pid) if pid else None
    if not player:
        return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)

    max_loan=await calculate_max_loan(player)
    if amount>max_loan:
        return JSONResponse({"success":False,"error":f"Банк одобряет максимум {max_loan:,} ₽"},status_code=400)

    now=int(time_module.time())
    due=now+2*86400
    rate=5.0

    lock=player_action_locks.setdefault(f"loan:{pid}",asyncio.Lock())
    async with lock:
        async with db_lock:
            def _take():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    active=cur.execute(
                        "SELECT id FROM loans WHERE player_id=? AND status='active' LIMIT 1",
                        (pid,)
                    ).fetchone()
                    if active:
                        conn.rollback()
                        return ("active",)

                    row=cur.execute("SELECT balance FROM players WHERE id=?",(pid,)).fetchone()
                    if not row:
                        conn.rollback()
                        return ("missing",)

                    cur.execute(
                        "UPDATE players SET balance=balance+? WHERE id=?",
                        (amount,pid)
                    )
                    cur.execute(
                        """INSERT INTO loans(
                            player_id,amount,interest_rate,start_time,due_date,status
                        ) VALUES(?,?,?,?,?,'active')""",
                        (pid,amount,rate,now,due)
                    )
                    fresh=cur.execute("SELECT balance FROM players WHERE id=?",(pid,)).fetchone()
                    conn.commit()
                    return ("ok",int(fresh["balance"] if fresh else 0))
                except Exception:
                    conn.rollback()
                    raise
                finally:
                    conn.close()

            result=await run_sync_db(_take)

    if result[0]=="active":
        return JSONResponse({"success":False,"error":"У вас уже есть активный кредит"},status_code=400)
    if result[0]=="missing":
        return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)

    return JSONResponse({
        "success":True,
        "message":f"Кредит {amount:,} ₽ одобрен",
        "balance":result[1]
    })


@app.post("/tycoon/bank/{tg_id}/repay")
async def tycoon_repay_loan(tg_id:int,request:Request):
    try: data=await request.json()
    except Exception: data={}
    loan_id=int(data.get("loan_id") or 0); amount=int(data.get("amount") or 0)
    pid=await get_player_id_by_tg(tg_id); player=await run_sync_db(get_player_data,pid) if pid else None
    if not player: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    conn=get_db(); loan=conn.execute("SELECT amount,interest_rate,status FROM loans WHERE id=? AND player_id=?",(loan_id,pid)).fetchone(); conn.close()
    if not loan or loan["status"]!='active': return JSONResponse({"success":False,"error":"Активный кредит не найден"},status_code=404)
    due=int(loan["amount"]*(1+loan["interest_rate"]/100))
    if amount<due: return JSONResponse({"success":False,"error":f"Для полного погашения нужно {due:,} ₽"},status_code=400)
    if int(player.get("balance",0))<amount: return JSONResponse({"success":False,"error":"Недостаточно средств"},status_code=400)
    over=amount-due
    async with db_lock:
        conn=get_db(); conn.execute("UPDATE players SET balance=balance-?+? WHERE id=?",(amount,over,pid)); conn.execute("UPDATE loans SET status='closed',paid_amount=? WHERE id=?",(due,loan_id)); conn.commit(); conn.close()
    fresh=await run_sync_db(get_player_data,pid) or {}
    return JSONResponse({"success":True,"message":f"Кредит погашен. Переплата {over:,} ₽ возвращена.","balance":int(fresh.get("balance",0) or 0)})


# ==================== TYCOON AUTO API ====================
# Frontend /tycoon/cars/* endpoints.  Kept separate from the taxi engine.
@app.get("/tycoon/cars/{tg_id}")
async def tycoon_cars(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    player=await run_sync_db(get_player_data,pid) or {}
    collection=list(player.get("car_collection",[]) or [])
    stats=list(player.get("garage_car_stats",[]) or [])
    now=int(time_module.time())
    while len(stats)<len(collection):
        stats.append({"mileage":0.0,"wear":0.0,"total_income":0,"updated_at":now})
    garage=[]
    for i,car_id in enumerate(collection):
        car=next((c for c in CARS if c.get("id")==car_id),None)
        if not car: continue
        st=stats[i] if isinstance(stats[i],dict) else {}
        garage.append({**car,"instance_index":i,"wear":max(0.0,min(100.0,float(st.get("wear",0) or 0))),
                       "mileage":float(st.get("mileage",0) or 0),"total_income":int(st.get("total_income",0) or 0),
                       "updated_at":float(st.get("updated_at") or now),
                       "in_taxopark":i in _taxi_indices(_safe_taxopark(player.get("taxopark")),collection)})
    current_id=player.get("current_car","none")
    current=next((c for c in CARS if c.get("id")==current_id),None)
    return JSONResponse({"success":True,"balance":int(player.get("balance",0) or 0),"cars":CARS,"garage":garage,
                         "current":current,"current_car":current_id})

@app.post("/tycoon/cars/{tg_id}/buy")
async def tycoon_cars_buy(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    car_id=str(data.get("car_id") or "")
    car=next((c for c in CARS if c.get("id")==car_id),None)
    if not car:return JSONResponse({"success":False,"error":"Машина не найдена"},status_code=404)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    async with db_lock:
        conn=get_db()
        try:
            cur=conn.cursor();cur.execute("BEGIN IMMEDIATE")
            row=cur.execute("SELECT balance,car_collection,garage_car_stats,current_car FROM players WHERE id=?",(pid,)).fetchone()
            if not row:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
            balance=int(row["balance"] or 0)
            if balance<int(car["price"]):
                return JSONResponse({"success":False,"error":f"Недостаточно денег! Нужно {int(car['price']):,} ₽","balance":balance},status_code=400)
            try: collection=json.loads(row["car_collection"] or "[]")
            except Exception: collection=[]
            try: stats=json.loads(row["garage_car_stats"] or "[]")
            except Exception: stats=[]
            if not isinstance(collection,list):collection=[]
            if not isinstance(stats,list):stats=[]
            now=int(time_module.time()); collection.append(car_id)
            stats.append({"mileage":0.0,"wear":0.0,"total_income":0,"updated_at":now})
            current=row["current_car"] or "none"
            if not current or current=="none":current=car_id
            newbal=balance-int(car["price"])
            cur.execute("UPDATE players SET balance=?,car_collection=?,garage_car_stats=?,current_car=? WHERE id=?",
                        (newbal,json.dumps(collection,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),current,pid))
            conn.commit()
        except Exception:
            conn.rollback();raise
        finally: conn.close()
    return JSONResponse({"success":True,"message":f"✅ {car['name']} куплена!","balance":newbal})

@app.post("/tycoon/cars/{tg_id}/set-current")
async def tycoon_cars_set_current(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try:data=await request.json()
    except Exception:data={}
    car_id=str(data.get("car_id") or "")
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    player=await run_sync_db(get_player_data,pid) or {}
    if car_id not in list(player.get("car_collection",[]) or []):
        return JSONResponse({"success":False,"error":"У вас нет этой машины!"},status_code=400)
    async with db_lock:
        conn=get_db();conn.execute("UPDATE players SET current_car=? WHERE id=?",(car_id,pid));conn.commit();conn.close()
    car=next((c for c in CARS if c.get("id")==car_id),None)
    return JSONResponse({"success":True,"message":f"✅ {car['name'] if car else car_id} теперь ваша текущая машина!"})

@app.post("/tycoon/cars/{tg_id}/repair")
async def tycoon_cars_repair(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try:data=await request.json()
    except Exception:data={}
    try:idx=int(data.get("instance_index"))
    except Exception:idx=-1
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    async with db_lock:
        conn=get_db()
        try:
            cur=conn.cursor();cur.execute("BEGIN IMMEDIATE")
            row=cur.execute("SELECT balance,car_collection,garage_car_stats FROM players WHERE id=?",(pid,)).fetchone()
            if not row:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
            try:collection=json.loads(row["car_collection"] or "[]"); stats=json.loads(row["garage_car_stats"] or "[]")
            except Exception:collection=[];stats=[]
            if idx<0 or idx>=len(collection):return JSONResponse({"success":False,"error":"Автомобиль не найден в гараже"},status_code=404)
            while len(stats)<len(collection):stats.append({"mileage":0.0,"wear":0.0,"total_income":0,"updated_at":int(time_module.time())})
            st=stats[idx] if isinstance(stats[idx],dict) else {}
            wear=max(0.0,min(100.0,float(st.get("wear",0) or 0)))
            if wear<=0:return JSONResponse({"success":False,"error":"Автомобиль уже исправен"},status_code=400)
            car=next((c for c in CARS if c.get("id")==collection[idx]),None)
            if not car:return JSONResponse({"success":False,"error":"Машина не найдена"},status_code=404)
            cost=max(500,int(round(int(car.get("price",0))*0.025*wear/100.0)))
            balance=int(row["balance"] or 0)
            if balance<cost:return JSONResponse({"success":False,"error":f"Недостаточно денег! Нужно {cost:,} ₽","balance":balance},status_code=400)
            st.update({"wear":0.0,"updated_at":int(time_module.time())});stats[idx]=st
            newbal=balance-cost
            cur.execute("UPDATE players SET balance=?,garage_car_stats=? WHERE id=?",(newbal,json.dumps(stats,ensure_ascii=False),pid))
            conn.commit()
        except Exception:
            conn.rollback();raise
        finally:conn.close()
    return JSONResponse({"success":True,"message":f"✅ {car['name']} отремонтирована","balance":newbal})

@app.get("/tycoon/mining/{tg_id}")
async def tycoon_mining(tg_id:int):
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    player=await run_sync_db(get_player_data,pid) or {}
    def _read():
        conn=get_db(); rows=conn.execute("SELECT id,rig_type,daily_income,price,purchase_time,status FROM mining_rigs WHERE player_id=? AND status='active' ORDER BY id DESC",(pid,)).fetchall(); conn.close(); return [dict(x) for x in rows]
    rigs=await run_sync_db(_read)
    hourly=sum(int(x["daily_income"])//24 for x in rigs)
    return JSONResponse({"success":True,"balance":int(player.get("balance",0) or 0),"rigs":rigs,"catalog":[{"id":k,**v} for k,v in MINING_RIGS.items()],"daily_income":hourly*24,"hourly_income":hourly})

@app.post("/tycoon/mining/{tg_id}/buy")
async def tycoon_buy_mining(tg_id:int,request:Request):
    try: data=await request.json()
    except Exception: data={}
    rig_type=str(data.get("rig_type") or "").strip(); rig=MINING_RIGS.get(rig_type)
    if not rig: return JSONResponse({"success":False,"error":"Ферма не найдена"},status_code=404)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    lock=player_action_locks.setdefault(f"mining:{pid}",asyncio.Lock())
    async with lock:
        async with db_lock:
            def _buy():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    row=cur.execute("SELECT balance FROM players WHERE id=?",(pid,)).fetchone()
                    if not row:return ("missing",)
                    balance=int(row["balance"] or 0); price=int(rig["price"] or 0)
                    if balance<price:return ("funds",price,balance)
                    now=int(time_module.time())
                    cur.execute("UPDATE players SET balance=balance-? WHERE id=?",(price,pid))
                    cur.execute("INSERT INTO mining_rigs(player_id,rig_type,hash_rate,daily_income,price,purchase_time,status) VALUES(?,?,?,?,?,?,?)",(pid,rig_type,0,int(rig["daily_income"]),price,now,"active"))
                    newbal=cur.execute("SELECT balance FROM players WHERE id=?",(pid,)).fetchone()
                    conn.commit(); return ("ok",int(newbal["balance"] if newbal else balance-price))
                except Exception:
                    conn.rollback(); raise
                finally: conn.close()
            try: result=await run_sync_db(_buy)
            except Exception as exc:
                print(f"[TYCOON][MINING] buy failed tg={tg_id}: {exc}")
                return JSONResponse({"success":False,"error":"Не удалось купить майнинг-ферму. Попробуйте ещё раз."},status_code=500)
    if result[0]=="missing":return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    if result[0]=="funds":return JSONResponse({"success":False,"error":f"Недостаточно средств. Нужно {result[1]:,} ₽","balance":result[2]},status_code=400)
    await audit(tg_id,tg_id,"mining_buy",-int(rig["price"]),f"Куплена ферма {rig_type}")
    return JSONResponse({"success":True,"message":f"{rig['name']} куплена. +{rig['daily_income']:,} ₽/день","balance":result[1]})

@app.get("/tycoon/property/{tg_id}")
async def tycoon_property(tg_id:int):
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    player=await run_sync_db(get_player_data,pid) or {}
    current_id=player.get("house","room")
    current=next((h for h in HOUSES if h["id"]==current_id),HOUSES[0])
    return JSONResponse({"success":True,"balance":int(player.get("balance",0) or 0),"current":current,"houses":HOUSES})

@app.post("/tycoon/property/{tg_id}/buy")
async def tycoon_buy_property(tg_id:int,request:Request):
    try: data=await request.json()
    except Exception: data={}
    house_id=str(data.get("house_id") or "")
    pid=await get_player_id_by_tg(tg_id); player=await run_sync_db(get_player_data,pid) if pid else None
    house=next((h for h in HOUSES if h["id"]==house_id),None)
    if not player or not house: return JSONResponse({"success":False,"error":"Недвижимость не найдена"},status_code=404)
    current=next((h for h in HOUSES if h["id"]==player.get("house","room")),HOUSES[0])
    diff=int(house["price"])-int(current["price"]); balance=int(player.get("balance",0) or 0)
    if diff<0: return JSONResponse({"success":False,"error":"Можно перейти только на более дорогую недвижимость"},status_code=400)
    if diff==0: return JSONResponse({"success":False,"error":"У вас уже эта недвижимость"},status_code=400)
    if balance<diff: return JSONResponse({"success":False,"error":f"Нужно доплатить {diff:,} ₽"},status_code=400)
    async with db_lock:
        conn=get_db(); conn.execute("UPDATE players SET balance=balance-?,house=? WHERE id=?",(diff,house_id,pid)); conn.commit(); conn.close()
    fresh=await run_sync_db(get_player_data,pid) or {}
    return JSONResponse({"success":True,"message":f"{house['name']} приобретена","balance":int(fresh.get("balance",0) or 0)})

@app.post("/tycoon/property/{tg_id}/sell")
async def tycoon_sell_property(tg_id:int):
    pid=await get_player_id_by_tg(tg_id); player=await run_sync_db(get_player_data,pid) if pid else None
    if not player: return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    current=next((h for h in HOUSES if h["id"]==player.get("house","room")),HOUSES[0])
    if current["id"]=="room": return JSONResponse({"success":False,"error":"Базовое жильё продать нельзя"},status_code=400)
    refund=int(current["price"])
    async with db_lock:
        conn=get_db(); conn.execute("UPDATE players SET balance=balance+?,house='room' WHERE id=?",(refund,pid)); conn.commit(); conn.close()
    fresh=await run_sync_db(get_player_data,pid) or {}
    return JSONResponse({"success":True,"message":f"Недвижимость продана за {refund:,} ₽","balance":int(fresh.get("balance",0) or 0)})

# ==================== TAXI UPGRADE SYSTEM ====================
TAXI_UPGRADE_CONFIG = {
    "drivers": {"title": "Водители", "bonus": 0.08, "max": 5, "costs": [100_000, 180_000, 320_000, 560_000, 900_000]},
    "advertising": {"title": "Реклама", "bonus": 0.06, "max": 5, "costs": [80_000, 150_000, 270_000, 470_000, 750_000]},
    "dispatch": {"title": "Диспетчеризация", "bonus": 0.04, "max": 5, "costs": [60_000, 110_000, 200_000, 350_000, 600_000]},
}

def _safe_taxi_upgrades(raw=None):
    raw=raw or {}
    out={}
    for key in TAXI_UPGRADE_CONFIG:
        try: out[key]=max(0,min(int(TAXI_UPGRADE_CONFIG[key]["max"]),int(raw.get(key,0) or 0)))
        except Exception: out[key]=0
    return out

def _taxi_upgrades_for_player_sync(player_id:int):
    conn=get_db()
    try:
        row=conn.execute("SELECT drivers_level,advertising_level,dispatch_level FROM taxi_upgrades WHERE player_id=?",(player_id,)).fetchone()
        return _safe_taxi_upgrades({
            "drivers": row["drivers_level"] if row else 0,
            "advertising": row["advertising_level"] if row else 0,
            "dispatch": row["dispatch_level"] if row else 0,
        })
    finally: conn.close()

def _taxi_income_multiplier(upgrades):
    u=_safe_taxi_upgrades(upgrades)
    return 1.0 + sum(float(TAXI_UPGRADE_CONFIG[k]["bonus"]) * int(u[k]) for k in TAXI_UPGRADE_CONFIG)

# ==================== TAXI ECONOMY — BUSINESS-STYLE ENGINE ====================
# The Taxopark intentionally has its OWN collection cursor, exactly like the
# Business Center has players.last_income_collect.  No per-car pending ledger.
TAXI_REF_PRICE_FOR_WEAR = 22500.0
TAXI_CHEAPEST_WEAR_HOURS = 3.0

def _taxi_wear_duration_hours(price:int)->float:
    p=max(1.0,float(price or 0))
    return max(3.0,TAXI_CHEAPEST_WEAR_HOURS*(p/TAXI_REF_PRICE_FOR_WEAR)**0.25)

def _taxi_wear_per_hour(price:int)->float:
    return 100.0/_taxi_wear_duration_hours(price)

def _taxi_repair_cost(price:int, wear:float)->int:
    p=max(0,int(price or 0)); w=max(0.0,min(100.0,float(wear or 0)))
    return 0 if w<=0 else max(250,int(round(p*0.0125*w/100.0)))


def _taxi_materialize_shared_state(stats, owned, indices, now, legacy_start=0):
    """Materialize live wear from an immutable line stint.

    line_started_at and wear_before are never moved by refreshes. Legacy records
    use the Taxi collection cursor or their old stat timestamp as a migration
    anchor instead of silently starting from the moment of the first refresh.
    """
    stats = _taxi_prepare_stats(stats, owned, now)
    changed = False

    for raw_idx in indices or []:
        try:
            idx = int(raw_idx)
        except Exception:
            continue
        if idx < 0 or idx >= len(owned) or idx >= len(stats):
            continue

        car = _taxi_car(idx, owned)
        if not car:
            continue
        st = stats[idx] if isinstance(stats[idx], dict) else {}

        try:
            wear = max(0.0, min(100.0, float(st.get("wear", 0) or 0)))
        except Exception:
            wear = 0.0
        try:
            mileage = max(0.0, float(st.get("mileage", 0) or 0))
        except Exception:
            mileage = 0.0
        try:
            total_income = max(0, int(st.get("total_income", 0) or 0))
        except Exception:
            total_income = 0

        try:
            line_start = int(
                st.get("line_started_at")
                or st.get("taxi_last_tick_at")
                or 0
            )
        except Exception:
            line_start = 0

        if line_start <= 0:
            for candidate in (
                legacy_start,
                st.get("updated_at", 0),
                st.get("created_at", 0),
            ):
                try:
                    candidate_i = int(candidate or 0)
                except Exception:
                    candidate_i = 0
                if candidate_i > 0:
                    line_start = candidate_i
                    break
            if line_start <= 0:
                line_start = int(now)

        baseline_missing = (
            not st.get("line_started_at")
            or "wear_before" not in st
            or "mileage_before" not in st
            or "income_before" not in st
        )
        if baseline_missing:
            st["line_started_at"] = int(line_start)
            st["taxi_last_tick_at"] = int(line_start)
            st["wear_before"] = wear
            st["mileage_before"] = mileage
            st["income_before"] = total_income
            changed = True

        try:
            base_wear = max(
                0.0,
                min(100.0, float(st.get("wear_before", wear) or 0)),
            )
        except Exception:
            base_wear = wear
        try:
            base_mileage = max(
                0.0,
                float(st.get("mileage_before", mileage) or 0),
            )
        except Exception:
            base_mileage = mileage

        rate = _taxi_wear_per_hour(int(car.get("price", 0) or 0))
        elapsed_hours = max(
            0.0, (now - int(st["line_started_at"])) / 3600.0
        )
        break_hours = (
            max(0.0, (100.0 - base_wear) / rate)
            if rate > 0 else 0.0
        )
        working_hours = min(elapsed_hours, break_hours)

        current_wear = min(
            100.0, base_wear + working_hours * rate
        )
        # Wear is monotonic while a taxi is on the line. A refresh/reload
        # must never make an already materialized value smaller. Repairs are
        # explicit and reset wear_before/line_started_at, so they still work.
        stored_wear = max(0.0, min(100.0, float(wear)))
        if st.get("line_started_at") and "wear_before" in st:
            current_wear = max(current_wear, stored_wear)
        current_mileage = (
            base_mileage
            + working_hours
            * max(0.0, float(car.get("speed_bonus", 0) or 0))
            * 0.1
        )
        stored_mileage = max(0.0, float(mileage))
        current_mileage = max(current_mileage, stored_mileage)
        broken = current_wear >= 100.0

        if (
            abs(wear - current_wear) > 1e-8
            or abs(mileage - current_mileage) > 1e-8
            or bool(st.get("is_broken")) != broken
            or int(st.get("updated_at") or 0) != int(now)
        ):
            st["wear"] = round(current_wear, 6)
            st["mileage"] = round(current_mileage, 4)
            st["is_broken"] = bool(broken)
            st["updated_at"] = int(now)
            st["broken_at"] = (
                int(round(
                    int(st["line_started_at"]) + break_hours * 3600.0
                ))
                if broken else None
            )
            changed = True

        stats[idx] = st

    return stats, 0, changed




def _taxi_pending_from_state(stats, owned, indices, start_at, end_at, multiplier=1.0):
    """Exact Taxi income over [start_at, end_at]."""
    start = int(start_at or 0)
    end = int(end_at or time_module.time())
    if start <= 0 or end <= start:
        return 0

    total = 0.0
    for raw_idx in indices or []:
        try:
            idx = int(raw_idx)
        except Exception:
            continue
        if idx < 0 or idx >= len(owned) or idx >= len(stats):
            continue
        car = _taxi_car(idx, owned)
        if not car:
            continue
        st = stats[idx] if isinstance(stats[idx], dict) else {}

        try:
            line_start = int(st.get("line_started_at") or st.get("taxi_last_tick_at") or start)
        except Exception:
            line_start = start
        try:
            base_wear = max(
                0.0,
                min(100.0, float(st.get("wear_before", st.get("wear", 0)) or 0)),
            )
        except Exception:
            base_wear = 0.0

        rate = _taxi_wear_per_hour(int(car.get("price", 0) or 0))
        if rate <= 0:
            continue
        break_at = float(line_start) + max(0.0, (100.0 - base_wear) / rate) * 3600.0
        active_start = max(float(start), float(line_start))
        active_end = min(float(end), break_at)
        if active_end <= active_start:
            continue

        total += (
            (active_end - active_start) / 3600.0
            * float(car.get("income_per_hour", 0) or 0)
            * float(multiplier or 1.0)
        )
    return max(0, int(total))

def _taxi_pending_shared_from_player(player, last_collect_at, now):
    owned = _safe_json_list(player.get("car_collection"))
    stats = _safe_car_stats(
        player.get("garage_car_stats"), len(owned), int(now or time_module.time())
    )
    tax = _safe_taxopark(player.get("taxopark"))
    indices = _taxi_indices(tax, owned)
    return _taxi_pending_from_state(
        stats, owned, indices,
        int(last_collect_at or 0),
        int(now or time_module.time()),
        _taxi_multiplier_for_player(int(player.get("id") or 0)),
    )

def _taxi_pending_from_cursor_state(stats, owned, indices, last_collect_at, now, multiplier=1.0):
    return _taxi_pending_from_state(stats, owned, indices, last_collect_at, now, multiplier)

def _taxi_pending_from_cursor(stats, owned, indices, last_collect_at, now, multiplier=1.0):
    """Compatibility reader for Business Center only.
    Same Business formula: hourly rate * elapsed seconds / 3600.
    The actual Taxopark endpoint uses _taxi_state_from_row below.
    """
    start=int(last_collect_at or 0); end=int(now or time_module.time())
    if start<=0 or end<=start: return 0
    total=0.0
    for idx in indices or []:
        try:i=int(idx)
        except Exception:continue
        if i<0 or i>=len(owned) or i>=len(stats):continue
        car=_taxi_car(i,owned)
        if not car:continue
        st=stats[i] if isinstance(stats[i],dict) else {}
        line=int(st.get('line_started_at') or st.get('taxi_last_tick_at') or 0)
        if line<=0: continue
        wear=float(st.get('wear',0) or 0)
        if wear>=100.0 or bool(st.get('is_broken')): continue
        rate=_taxi_wear_per_hour(int(car.get('price',0) or 0))
        base=max(0.0,min(100.0,wear))
        break_at=line+(100.0-base)/rate*3600.0
        active_start=max(float(start),float(line)); active_end=min(float(end),float(break_at))
        if active_end>active_start:
            total += (active_end-active_start)/3600.0*float(car.get('income_per_hour',0) or 0)*float(multiplier or 1.0)
    return max(0,int(total))


def _taxi_pending_income_sync(player: dict, since: int = 0, until: int = 0) -> int:
    tax = _safe_taxopark(player.get("taxopark"))
    start = int(
        since
        or tax.get("last_collect_at")
        or player.get("last_income_collect")
        or 0
    )
    end = int(until or time_module.time())
    owned = _safe_json_list(player.get("car_collection"))
    stats = _safe_car_stats(player.get("garage_car_stats"), len(owned), end)
    indices = _taxi_indices(tax, owned)
    return _taxi_pending_from_state(
        stats, owned, indices, start, end,
        _taxi_multiplier_for_player(int(player.get("id") or 0)),
    )


def _taxi_indices(tax:dict, owned:list)->list:
    raw=tax.get('car_instance_indices') or []
    out=[]
    for x in raw:
        try: i=int(x)
        except Exception: continue
        if 0<=i<len(owned) and i not in out: out.append(i)
    if out: return out
    used={}
    for cid in (tax.get('cars') or []):
        n=used.get(cid,0); used[cid]=n+1
        matches=[i for i,x in enumerate(owned) if x==cid]
        if n<len(matches): out.append(matches[n])
    return out

def _taxi_car(idx, owned):
    if idx<0 or idx>=len(owned): return None
    cid=owned[idx]
    return next((c for c in CARS if c.get('id')==cid),None)

def _taxi_multiplier_for_player_conn(conn, pid:int)->float:
    try:
        row=conn.execute("SELECT drivers_level,advertising_level,dispatch_level FROM taxi_upgrades WHERE player_id=?",(int(pid),)).fetchone()
        u=_safe_taxi_upgrades({"drivers":row["drivers_level"] if row else 0,"advertising":row["advertising_level"] if row else 0,"dispatch":row["dispatch_level"] if row else 0})
        mult=_taxi_income_multiplier(u)
        pl=conn.execute("SELECT tg_id FROM players WHERE id=?",(int(pid),)).fetchone()
        tg_id=int(pl["tg_id"] or 0) if pl else 0
        if tg_id:
            rr=conn.execute("SELECT COUNT(*) AS c FROM referral_relations r JOIN players p ON p.tg_id=r.invitee_tg_id WHERE r.inviter_tg_id=? AND r.reward_paid=1 AND COALESCE(p.is_banned,0)=0",(tg_id,)).fetchone()
            active=int(rr["c"] if rr else 0)
            ref_mult=1.0
            for target,m in REFERRAL_BOOST_TIERS:
                if active>=target: ref_mult=m
                else: break
            mult*=ref_mult
        return max(0.0,float(mult))
    except Exception:
        return 1.0

def _taxi_multiplier_for_player(pid:int)->float:
    try:
        m=_taxi_income_multiplier(_taxi_upgrades_for_player_sync(pid))
        m*=float(get_referral_boost_multiplier(pid) or 1.0)
        return max(0.0,m)
    except Exception:
        return 1.0

def _taxi_prepare_stats(stats, owned, now):
    stats=list(stats or [])
    while len(stats)<len(owned):
        stats.append({'mileage':0.0,'wear':0.0,'total_income':0,'updated_at':now,'is_broken':False})
    return stats

def _taxi_load_persistent_stats(conn, player_id:int, owned:list, legacy_raw=None, now:int=0):
    """Read authoritative Taxi state without mutating SQLite on refresh."""
    now=int(now or time_module.time()); owned=list(owned or [])
    legacy=_safe_car_stats(legacy_raw or '[]',len(owned),now)
    rows=conn.execute(
        'SELECT instance_index,car_id,wear,mileage,total_income,line_started_at,taxi_last_tick_at,wear_before,mileage_before,income_before,updated_at,is_broken,broken_at FROM taxi_vehicle_state WHERE player_id=? ORDER BY instance_index',
        (int(player_id),)
    ).fetchall()
    by_idx={int(r['instance_index']):r for r in rows}
    by_car={}
    for r in rows: by_car.setdefault(str(r['car_id'] or ''),[]).append(r)
    used=set(); stats=[]
    for idx,cid in enumerate(owned):
        r=by_idx.get(idx)
        if r is not None and str(r['car_id'] or '')!=str(cid or ''): r=None
        if r is None:
            for cand in by_car.get(str(cid or ''),[]):
                key=(int(cand['instance_index']),str(cand['car_id'] or ''))
                if key not in used: r=cand; break
        if r is not None:
            used.add((int(r['instance_index']),str(r['car_id'] or '')))
            stats.append({
                'mileage':float(r['mileage'] or 0),'wear':float(r['wear'] or 0),
                'total_income':int(r['total_income'] or 0),
                'line_started_at':int(r['line_started_at'] or 0),
                'taxi_last_tick_at':int(r['taxi_last_tick_at'] or 0),
                'wear_before':float(r['wear_before'] or 0),
                'mileage_before':float(r['mileage_before'] or 0),
                'income_before':int(r['income_before'] or 0),
                'updated_at':int(r['updated_at'] or now),
                'is_broken':bool(r['is_broken']),'broken_at':r['broken_at']})
        else:
            st=dict(legacy[idx] if idx<len(legacy) and isinstance(legacy[idx],dict) else {})
            line=int(st.get('line_started_at') or st.get('taxi_last_tick_at') or st.get('updated_at') or 0)
            stats.append({
                'mileage':float(st.get('mileage',0) or 0),'wear':float(st.get('wear',0) or 0),
                'total_income':int(st.get('total_income',0) or 0),'line_started_at':line,
                'taxi_last_tick_at':int(st.get('taxi_last_tick_at') or line),
                'wear_before':float(st.get('wear_before',st.get('wear',0)) or 0),
                'mileage_before':float(st.get('mileage_before',st.get('mileage',0)) or 0),
                'income_before':int(st.get('income_before',st.get('total_income',0)) or 0),
                'updated_at':int(st.get('updated_at') or now),
                'is_broken':bool(st.get('is_broken')),'broken_at':st.get('broken_at')})
    return stats

def _taxi_save_persistent_stats(conn, player_id:int, owned:list, stats:list):
    """Bulk upsert Taxi state; caller owns transaction."""
    rows=[]
    now=int(time_module.time())
    for idx,cid in enumerate(owned or []):
        st=stats[idx] if idx<len(stats) and isinstance(stats[idx],dict) else {}
        rows.append((int(player_id),idx,str(cid or ''),float(st.get('wear',0) or 0),float(st.get('mileage',0) or 0),int(st.get('total_income',0) or 0),int(st.get('line_started_at') or 0),int(st.get('taxi_last_tick_at') or 0),float(st.get('wear_before',st.get('wear',0)) or 0),float(st.get('mileage_before',st.get('mileage',0)) or 0),int(st.get('income_before',st.get('total_income',0)) or 0),int(st.get('updated_at') or now),1 if bool(st.get('is_broken')) else 0,st.get('broken_at')))
    if rows:
        conn.executemany("""
            INSERT INTO taxi_vehicle_state
            (player_id,instance_index,car_id,wear,mileage,total_income,line_started_at,taxi_last_tick_at,wear_before,mileage_before,income_before,updated_at,is_broken,broken_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(player_id,instance_index) DO UPDATE SET
              car_id=excluded.car_id,wear=excluded.wear,mileage=excluded.mileage,total_income=excluded.total_income,
              line_started_at=excluded.line_started_at,taxi_last_tick_at=excluded.taxi_last_tick_at,
              wear_before=excluded.wear_before,mileage_before=excluded.mileage_before,income_before=excluded.income_before,
              updated_at=excluded.updated_at,is_broken=excluded.is_broken,broken_at=excluded.broken_at
        """,rows)
    if owned:
        conn.execute('DELETE FROM taxi_vehicle_state WHERE player_id=? AND instance_index>=?',(int(player_id),len(owned)))
    else:
        conn.execute('DELETE FROM taxi_vehicle_state WHERE player_id=?',(int(player_id),))

def _taxi_persist_checkpoint(conn,pid,owned,stats):
    _taxi_save_persistent_stats(conn,pid,owned,stats)
    conn.execute('UPDATE players SET garage_car_stats=? WHERE id=?',(json.dumps(stats,ensure_ascii=False),int(pid)))


def _row_value(row, key, default=None):
    try:
        if row is None:
            return default
        try:
            return row[key]
        except Exception:
            return dict(row).get(key, default)
    except Exception:
        return default


def _taxi_state_from_row(row, pid:int, now:int, persistent_stats=None):
    tax = _safe_taxopark(_row_value(row, "taxopark", None))
    owned = _safe_json_list(_row_value(row, "car_collection", None))
    stats = _taxi_prepare_stats(
        persistent_stats if persistent_stats is not None else _safe_car_stats(_row_value(row, "garage_car_stats", None), len(owned), now),
        owned, now
    )
    indices = _taxi_indices(tax, owned)

    business_cursor = int(_row_value(row, "last_income_collect", 0) or 0)
    taxi_cursor = int(tax.get("last_collect_at") or 0)
    if taxi_cursor <= 0:
        taxi_cursor = business_cursor if business_cursor > 0 else now
        tax["last_collect_at"] = taxi_cursor

    mult = _taxi_multiplier_for_player(pid)
    stats, _, changed = _taxi_materialize_shared_state(
        stats, owned, indices, now, legacy_start=taxi_cursor
    )

    pending = max(0, int(tax.get("pending_carry", 0) or 0))
    hourly = 0.0
    garage = []

    for i, cid in enumerate(owned):
        car = _taxi_car(i, owned)
        st = stats[i] if i < len(stats) and isinstance(stats[i], dict) else {}
        if not car:
            continue

        in_line = i in indices
        price = int(car.get("price", 0) or 0)
        wear = max(0.0, min(100.0, float(st.get("wear", 0) or 0)))
        rate = _taxi_wear_per_hour(price)
        broken = wear >= 100.0

        if in_line and not broken:
            hourly += float(car.get("income_per_hour", 0) or 0) * mult

        garage.append({
            **car,
            "instance_index": i,
            "wear": round(wear, 6),
            "mileage": float(st.get("mileage", 0) or 0),
            "total_income": int(st.get("total_income", 0) or 0),
            "updated_at": int(st.get("updated_at") or now),
            "line_started_at": int(st.get("line_started_at") or 0),
            "wear_rate_per_hour": rate,
            "wear_duration_hours": _taxi_wear_duration_hours(price),
            "is_broken": bool(broken),
            "in_taxopark": in_line,
        })

    pending += _taxi_pending_from_state(
        stats, owned, indices, taxi_cursor, now, multiplier=mult
    )

    return (
        tax,
        owned,
        indices,
        stats,
        garage,
        int(round(hourly)),
        max(0, int(round(pending))),
        changed,
        mult,
        taxi_cursor,
    )





def _taxi_current_hourly_from_state(stats, owned, indices, multiplier):
    now=int(time_module.time()); mult=max(0.0,float(multiplier or 1.0)); total=0.0
    for raw_idx in indices or []:
        try: idx=int(raw_idx)
        except Exception: continue
        if idx<0 or idx>=len(owned) or idx>=len(stats): continue
        car=_taxi_car(idx,owned)
        if not car: continue
        st=stats[idx] if isinstance(stats[idx],dict) else {}
        line=int(st.get('line_started_at') or st.get('taxi_last_tick_at') or 0)
        base=max(0.0,min(100.0,float(st.get('wear_before',st.get('wear',0)) or 0)))
        rate=_taxi_wear_per_hour(int(car.get('price',0) or 0))
        live=base + ((now-line)/3600.0*rate if line>0 and rate>0 else 0.0)
        live=min(100.0,max(live,float(st.get('wear',0) or 0)))
        if live<100.0: total+=float(car.get('income_per_hour',0) or 0)*mult
    return max(0,int(round(total)))

def _taxi_current_hourly_sync(player: dict, income_multiplier: float = 1.0) -> int:
    """Return current live hourly Taxi income. Wear is time-derived."""
    try:
        now = int(time_module.time())
        tax = _safe_taxopark(player.get("taxopark"))
        owned = _safe_json_list(player.get("car_collection"))
        indices = _taxi_indices(tax, owned)
        if player.get('id'):
            conn=get_db()
            try:
                stats=_taxi_load_persistent_stats(conn,int(player.get('id')),owned,player.get('garage_car_stats'),now)
            finally:
                conn.close()
        else:
            stats = _safe_car_stats(player.get("garage_car_stats"), len(owned), now)

        taxi_cursor = int(tax.get("last_collect_at") or 0)
        if taxi_cursor <= 0:
            taxi_cursor = int(player.get("last_income_collect", 0) or 0)

        mult = max(0.0, float(income_multiplier or 1.0))
        total = 0.0

        for raw_idx in indices:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx >= len(owned) or idx >= len(stats):
                continue

            car = _taxi_car(idx, owned)
            if not car:
                continue
            st = stats[idx] if isinstance(stats[idx], dict) else {}

            line_start = int(
                st.get("line_started_at")
                or st.get("taxi_last_tick_at")
                or taxi_cursor
                or now
            )
            try:
                base_wear = max(
                    0.0,
                    min(
                        100.0,
                        float(st.get("wear_before", st.get("wear", 0)) or 0),
                    ),
                )
            except Exception:
                base_wear = 0.0

            rate = _taxi_wear_per_hour(int(car.get("price", 0) or 0))
            live_wear = base_wear
            if rate > 0:
                live_wear = min(
                    100.0,
                    base_wear
                    + max(0.0, (now - line_start) / 3600.0) * rate,
                )

            if live_wear >= 100.0:
                continue
            total += float(car.get("income_per_hour", 0) or 0) * mult

        return max(0, int(round(total)))
    except Exception:
        return 0


def _taxi_sync_player_row(row, pid: int, now: int):
    """Compatibility adapter for the older 8-value Taxopark collector contract."""
    tax, owned, indices, stats, _garage, hourly, pending, changed, mult, _cursor = _taxi_state_from_row(row, pid, now)
    return tax, owned, indices, stats, hourly, pending, changed, mult


def _taxi_commit_state(cur, pid: int, tax: dict, stats: list):
    cur.execute(
        "UPDATE players SET taxopark=?,garage_car_stats=? WHERE id=?",
        (json.dumps(tax, ensure_ascii=False), json.dumps(stats, ensure_ascii=False), int(pid)),
    )


def _taxi_get_indices(tax: dict, owned: list) -> list:
    return _taxi_indices(tax, owned)


def _taxi_full_multiplier(player_id: int, base: float = 1.0) -> float:
    try:
        return max(0.0, float(base or 1.0)) * max(0.0, float(get_referral_boost_multiplier(int(player_id)) or 1.0))
    except Exception:
        return max(0.0, float(base or 1.0))

def _taxi_save(conn,pid,tax,stats,owned=None):
    if owned is None:
        row=conn.execute('SELECT car_collection FROM players WHERE id=?',(int(pid),)).fetchone()
        owned=_safe_json_list(row['car_collection'] if row else '[]')
    _taxi_save_persistent_stats(conn,pid,owned,stats)
    conn.execute('UPDATE players SET taxopark=?,garage_car_stats=? WHERE id=?',
                 (json.dumps(tax,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),pid))

# ==================== TYCOON TAXOPARK API ====================
@app.get("/tycoon/taxopark/{tg_id}")
async def tycoon_taxopark(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)

    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute(
                        'SELECT balance,last_income_collect,taxopark,car_collection,garage_car_stats '
                        'FROM players WHERE id=?',(pid,)
                    ).fetchone()
                    if not row:return None

                    now=int(time_module.time())
                    owned0=_safe_json_list(row['car_collection'])
                    persistent=_taxi_load_persistent_stats(conn,pid,owned0,row['garage_car_stats'],now)
                    result=_taxi_state_from_row(row,pid,now,persistent_stats=persistent)
                    tax,owned,indices,stats,garage,hourly,pending,changed,mult,cursor=result
                    if changed:
                        _taxi_persist_checkpoint(conn,pid,owned,stats)
                    conn.commit()
                    return int(row['balance'] or 0),tax,garage,hourly,pending,mult,now,cursor
                except Exception:
                    conn.rollback();raise
                finally:conn.close()

            data=await run_sync_db(tx)

    if not data:
        return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)

    balance,tax,garage,hourly,pending,mult,now,cursor=data
    level=next((x for x in TAXOPARK_LEVELS if x.get('id')==tax.get('level')),TAXOPARK_LEVELS[0])
    park=[c for c in garage if c['in_taxopark']]
    broken=sum(1 for c in park if c['is_broken'])
    repair=sum(
        _taxi_repair_cost(int(c.get('price',0) or 0),float(c.get('wear',0) or 0))
        for c in park if float(c.get('wear',0) or 0)>0
    )

    return JSONResponse({
        'success':True,
        'server_time':now,
        'balance':balance,
        'taxopark':tax,
        'level':level,
        'levels':TAXOPARK_LEVELS,
        'garage':garage,
        'service_at':int(tax.get('last_service_at') or 0),
        'upgrades':_taxi_upgrades_for_player_sync(pid),
        'upgrade_config':TAXI_UPGRADE_CONFIG,
        'hourly_profit':int(hourly),
        'total_passive_per_hour':int(hourly),
        'multiplier':mult,
        'pending_profit':int(pending),
        'taxi_pending_collect':int(pending),
        'broken_cars':broken,
        'line_cars':len(park),
        'broken_ratio':broken/len(park) if park else 0.0,
        'total_repair_cost':repair,
        'taxi_elapsed_seconds':max(0,now-int(cursor or now)),
        'taxi_debug_cursor':int(cursor),
        'taxi_debug_line_cars':len(park),
        'taxi_debug_pending_carry':int(tax.get('pending_carry',0) or 0),
    })

@app.post("/tycoon/taxopark/{tg_id}/buy")
async def tycoon_taxopark_buy(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    try:data=await request.json()
    except Exception:data={}
    level_id=str(data.get('level_id') or '')
    level=next((x for x in TAXOPARK_LEVELS if x.get('id')==level_id and x.get('id')!='none'),None)
    if not level:return JSONResponse({'success':False,'error':'Уровень таксопарка не найден'},status_code=400)
    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute('SELECT balance,taxopark FROM players WHERE id=?',(pid,)).fetchone()
                    if not row:return ('missing',)
                    balance=int(row['balance'] or 0);tax=_safe_taxopark(row['taxopark']);current=str(tax.get('level') or 'none')
                    ids=[x['id'] for x in TAXOPARK_LEVELS]
                    if current==level_id:return ('same',)
                    if current in ids and ids.index(level_id)<=ids.index(current):return ('downgrade',)
                    if balance<int(level['price']):return ('funds',int(level['price']),balance)
                    now=int(time_module.time())
                    newtax=dict(tax);newtax.update({'level':level_id,'cars':list(tax.get('cars') or [])[:int(level['slots'])],
                        'car_instance_indices':[int(x) for x in (tax.get('car_instance_indices') or [])[:int(level['slots'])]],
                        'last_service_at':int(tax.get('last_service_at') or now),'last_collect_at':int(tax.get('last_collect_at') or row['last_income_collect'] or now), 'pending_carry':int(tax.get('pending_carry') or 0)})
                    cur.execute('UPDATE players SET balance=balance-?,taxopark=? WHERE id=?',(int(level['price']),json.dumps(newtax,ensure_ascii=False),pid))
                    cur.execute("UPDATE user_taxoparks SET status='replaced' WHERE player_id=? AND status='active'",(pid,))
                    cur.execute("INSERT INTO user_taxoparks(player_id,level_id,purchase_price,last_payment,status,paid_until) VALUES(?,?,?,?,?,?)",(pid,level_id,int(level['price']),now,'active',0))
                    conn.commit();return ('ok',balance-int(level['price']))
                except Exception:conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(tx)
    if result[0]=='missing':return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    if result[0]=='same':return JSONResponse({'success':False,'error':'У вас уже этот таксопарк'},status_code=400)
    if result[0]=='downgrade':return JSONResponse({'success':False,'error':'Можно покупать только более дорогой уровень'},status_code=400)
    if result[0]=='funds':return JSONResponse({'success':False,'error':f'Недостаточно средств. Нужно {result[1]:,} ₽.','balance':result[2]},status_code=400)
    return JSONResponse({'success':True,'message':f'{level["name"]} куплен.','balance':result[1]})

@app.post("/tycoon/taxopark/{tg_id}/sell")
async def tycoon_taxopark_sell(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)

    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute(
                        'SELECT balance,last_income_collect,taxopark,car_collection,garage_car_stats FROM players WHERE id=?',
                        (pid,)
                    ).fetchone()
                    if not row:return ('missing',)

                    now=int(time_module.time())
                    tax=_safe_taxopark(row['taxopark'])
                    level_id=str(tax.get('level') or 'none')
                    level=next((x for x in TAXOPARK_LEVELS if x.get('id')==level_id),None)
                    if not level or level_id=='none':
                        return ('empty',int(row['balance'] or 0),0)

                    owned=_safe_json_list(row['car_collection'])
                    stats=_taxi_load_persistent_stats(conn,pid,owned,row['garage_car_stats'],now)
                    indices=_taxi_indices(tax,owned)
                    taxi_cursor=int(tax.get('last_collect_at') or row['last_income_collect'] or now)
                    stats,_,_=_taxi_materialize_shared_state(
                        stats,owned,indices,now,legacy_start=taxi_cursor
                    )
                    carry=max(0,int(tax.get('pending_carry',0) or 0))
                    carry+=_taxi_pending_from_state(
                        stats,owned,indices,taxi_cursor,now,_taxi_multiplier_for_player(pid)
                    )

                    payout=int(round(int(level.get('price',0) or 0)*0.70))
                    balance=int(row['balance'] or 0)+payout
                    newtax={
                        'level':'none','cars':[],'car_instance_indices':[],
                        'last_service_at':0,'last_collect_at':now,'pending_carry':0
                    }
                    cur.execute(
                        'UPDATE players SET balance=?,taxopark=?,garage_car_stats=? WHERE id=?',
                        (balance,json.dumps(newtax,ensure_ascii=False),
                         json.dumps(stats,ensure_ascii=False),pid)
                    )
                    cur.execute(
                        "UPDATE user_taxoparks SET status='sold' WHERE player_id=? AND status='active'",
                        (pid,)
                    )
                    conn.commit()
                    return ('ok',balance,payout,carry)
                except Exception:
                    conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(tx)

    if result[0]=='missing':
        return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    if result[0]=='empty':
        return JSONResponse({'success':False,'error':'У вас нет активного таксопарка'},status_code=400)
    return JSONResponse({
        'success':True,
        'message':f'Таксопарк продан за 70% стоимости: {result[2]:,} ₽. Машины остались в гараже.',
        'balance':result[1],
        'payout':result[2]
    })

@app.post("/tycoon/taxopark/{tg_id}/add-car")
async def tycoon_taxopark_add_car(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    try:data=await request.json()
    except Exception:data={}
    car_id=str(data.get('car_id') or '')
    try:instance_index=int(data.get('instance_index'))
    except Exception:instance_index=-1

    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute(
                        'SELECT last_income_collect,taxopark,car_collection,garage_car_stats FROM players WHERE id=?',
                        (pid,)
                    ).fetchone()
                    if not row:return ('missing',)

                    now=int(time_module.time())
                    tax=_safe_taxopark(row['taxopark'])
                    owned=_safe_json_list(row['car_collection'])
                    stats=_taxi_prepare_stats(
                        _taxi_load_persistent_stats(conn,pid,owned,row['garage_car_stats'],now),
                        owned,now
                    )
                    level=next((x for x in TAXOPARK_LEVELS if x['id']==tax.get('level')),TAXOPARK_LEVELS[0])
                    indices=_taxi_indices(tax,owned)
                    if int(level['slots'])<=0:return ('no_park',)
                    if len(indices)>=int(level['slots']):return ('full',int(level['slots']))

                    idx=instance_index if 0<=instance_index<len(owned) else next(
                        (i for i,x in enumerate(owned) if x==car_id and i not in indices),-1
                    )
                    if idx<0 or owned[idx]!=car_id:return ('not_owned',)
                    if idx in indices:return ('already',)

                    if level['id']=='elite':
                        car=_taxi_car(idx,owned)
                        if not car or int(car.get('price',0))<500000:return ('premium',)

                    now=int(time_module.time())
                    taxi_cursor=int(tax.get('last_collect_at') or 0)
                    if taxi_cursor<=0:
                        taxi_cursor=int(row['last_income_collect'] or now)
                    tax['last_collect_at']=taxi_cursor

                    st=stats[idx]
                    current_wear=max(0.0,min(100.0,float(st.get('wear',0) or 0)))
                    st.update({
                        'line_started_at':now,
                        'taxi_last_tick_at':now,
                        'updated_at':now,
                        'wear':current_wear,
                        'wear_before':current_wear,
                        'mileage_before':float(st.get('mileage',0) or 0),
                        'income_before':int(st.get('total_income',0) or 0),
                        'is_broken':False,
                        'broken_at':None,
                    })

                    cars=list(tax.get('cars') or [])
                    cars.append(car_id)
                    indices.append(idx)
                    tax['cars']=cars
                    tax['car_instance_indices']=indices

                    _taxi_save(conn,pid,tax,stats);conn.commit()
                    return ('ok',)
                except Exception:
                    conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(tx)

    errors={
        'missing':'Игрок не найден',
        'no_park':'Сначала купите таксопарк',
        'not_owned':'Экземпляр автомобиля не найден в гараже',
        'already':'Эта машина уже на линии',
        'premium':'Для элитного таксопарка нужна премиум-машина от 500 000 ₽.',
    }
    if result[0] in errors:
        return JSONResponse({'success':False,'error':errors[result[0]]},status_code=400)
    if result[0]=='full':
        return JSONResponse({'success':False,'error':f'Нет мест. Максимум {result[1]} авто.'},status_code=400)
    return JSONResponse({'success':True,'message':'Машина добавлена на линию.'})

@app.post("/tycoon/taxopark/{tg_id}/remove-car")
async def tycoon_taxopark_remove_car(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    try:data=await request.json()
    except Exception:data={}
    try:instance_index=int(data.get('instance_index'))
    except Exception:instance_index=-1
    car_id=str(data.get('car_id') or '')

    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute(
                        'SELECT last_income_collect,taxopark,car_collection,garage_car_stats FROM players WHERE id=?',
                        (pid,)
                    ).fetchone()
                    if not row:return ('missing',)

                    now=int(time_module.time())
                    tax=_safe_taxopark(row['taxopark']);owned=_safe_json_list(row['car_collection'])
                    stats=_taxi_prepare_stats(_taxi_load_persistent_stats(conn,pid,owned,row['garage_car_stats'],now),owned,now)
                    indices=_taxi_indices(tax,owned)

                    pos=indices.index(instance_index) if instance_index in indices else -1
                    if pos<0 and car_id in (tax.get('cars') or []):
                        pos=(tax.get('cars') or []).index(car_id)
                    if pos<0:return ('absent',)

                    taxi_cursor=int(tax.get('last_collect_at') or row['last_income_collect'] or now)
                    stats,_,_=_taxi_materialize_shared_state(
                        stats,owned,indices,now,legacy_start=taxi_cursor
                    )
                    carry=max(0,int(tax.get('pending_carry',0) or 0))
                    carry+=_taxi_pending_from_state(
                        stats,owned,indices,taxi_cursor,now,_taxi_multiplier_for_player(pid)
                    )
                    tax['pending_carry']=carry
                    tax['last_collect_at']=now

                    indices.pop(pos)
                    cars=list(tax.get('cars') or [])
                    removed=cars.pop(pos) if pos<len(cars) else None
                    tax['cars']=cars;tax['car_instance_indices']=indices

                    _taxi_save(conn,pid,tax,stats);conn.commit()
                    return ('ok',removed)
                except Exception:
                    conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(tx)

    if result[0]=='missing':return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    if result[0]=='absent':return JSONResponse({'success':False,'error':'Этой машины нет на линии'},status_code=400)
    return JSONResponse({'success':True,'message':'Машина снята с линии.'})

@app.post("/tycoon/taxopark/{tg_id}/maintenance")
async def tycoon_taxopark_maintenance(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)

    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute(
                        'SELECT balance,last_income_collect,taxopark,car_collection,garage_car_stats FROM players WHERE id=?',
                        (pid,)
                    ).fetchone()
                    if not row:return ('missing',)

                    now=int(time_module.time())
                    persistent=_taxi_load_persistent_stats(conn,pid,_safe_json_list(row['car_collection']),row['garage_car_stats'],now)
                    tax,owned,indices,stats,garage,hourly,_pending,_changed,mult,cursor=_taxi_state_from_row(row,pid,now,persistent_stats=persistent)

                    carry=max(0,int(tax.get('pending_carry',0) or 0))
                    carry+=_taxi_pending_from_state(
                        stats,owned,indices,cursor,now,_taxi_multiplier_for_player(pid)
                    )
                    tax['pending_carry']=carry
                    tax['last_collect_at']=now

                    total=sum(
                        _taxi_repair_cost(int(c.get('price',0) or 0),float(c.get('wear',0) or 0))
                        for c in garage
                        if c['in_taxopark'] and float(c.get('wear',0) or 0)>0
                    )
                    balance=int(row['balance'] or 0)
                    if total>balance:return ('funds',total,balance)

                    repaired=0
                    for i in indices:
                        if 0<=i<len(stats):
                            current_m=float(stats[i].get('mileage',0) or 0)
                            current_inc=int(stats[i].get('total_income',0) or 0)
                            stats[i].update({
                                'wear':0.0,'is_broken':False,'broken_at':None,
                                'line_started_at':now,'taxi_last_tick_at':now,'updated_at':now,
                                'wear_before':0.0,'mileage_before':current_m,'income_before':current_inc
                            })
                            repaired+=1

                    tax['last_service_at']=now
                    # The dedicated taxi_vehicle_state table is authoritative for
                    # wear/mileage/income. Keep it in sync with the repair operation;
                    # otherwise the next refresh would reload the old wear and make
                    # the maintenance button appear to do nothing.
                    _taxi_save_persistent_stats(conn,pid,owned,stats)
                    cur.execute(
                        'UPDATE players SET balance=?,taxopark=?,garage_car_stats=? WHERE id=?',
                        (balance-total,json.dumps(tax,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),pid)
                    )
                    conn.commit();return ('ok',balance-total,total,repaired)
                except Exception:
                    conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(tx)

    if result[0]=='missing':return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    if result[0]=='funds':return JSONResponse({'success':False,'error':f'Недостаточно средств. Нужно {result[1]:,} ₽.','balance':result[2]},status_code=400)
    return JSONResponse({'success':True,'message':f'Обслужено машин: {result[3]}. Списано {result[2]:,} ₽.','balance':result[1],'charged':result[2]})

@app.post("/tycoon/taxopark/{tg_id}/collect-profit")
async def tycoon_taxopark_collect_profit(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request, tg_id):
        return JSONResponse({'success': False, 'error': 'Недействительная сессия Telegram'}, status_code=401)
    pid = await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({'success': False, 'error': 'Игрок не найден'}, status_code=404)

    # This button collects ONLY the Taxopark ledger.
    # players.last_income_collect is never advanced here.
    collected, balance, taxi_hourly, server_time = await collect_taxopark_income(pid)
    return JSONResponse({
        'success': True,
        'collected': int(collected),
        'taxopark_collected': int(collected),
        'balance': int(balance or 0),
        'total_per_hour': int(taxi_hourly),
        'hourly_profit': int(taxi_hourly),
        'server_time': int(server_time or time_module.time()),
        'breakdown': {'taxopark': int(collected)},
        'message': f'Зачислено +{int(collected):,} ₽' if collected > 0 else 'Пока нечего забирать',
    })


@app.post("/tycoon/taxopark/{tg_id}/repair-car")
async def tycoon_taxopark_repair_car(tg_id:int,request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({'success':False,'error':'Недействительная сессия Telegram'},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    try:data=await request.json()
    except Exception:data={}
    try:idx=int(data.get('instance_index'))
    except Exception:idx=-1

    lock=player_action_locks.setdefault(f'taxi:{pid}',asyncio.Lock())
    async with lock:
        async with db_lock:
            def tx():
                conn=get_db()
                try:
                    cur=conn.cursor();cur.execute('BEGIN IMMEDIATE')
                    row=cur.execute(
                        'SELECT balance,last_income_collect,taxopark,car_collection,garage_car_stats FROM players WHERE id=?',
                        (pid,)
                    ).fetchone()
                    if not row:return ('missing',)

                    now=int(time_module.time())
                    tax=_safe_taxopark(row['taxopark'])
                    owned=_safe_json_list(row['car_collection'])
                    stats=_taxi_prepare_stats(_taxi_load_persistent_stats(conn,pid,owned,row['garage_car_stats'],now),owned,now)
                    indices=_taxi_indices(tax,owned)
                    if idx not in indices:return ('absent',)

                    taxi_cursor=int(tax.get('last_collect_at') or row['last_income_collect'] or now)
                    stats,_,_=_taxi_materialize_shared_state(
                        stats,owned,indices,now,legacy_start=taxi_cursor
                    )
                    carry=max(0,int(tax.get('pending_carry',0) or 0))
                    carry+=_taxi_pending_from_state(
                        stats,owned,indices,taxi_cursor,now,_taxi_multiplier_for_player(pid)
                    )
                    tax['pending_carry']=carry
                    tax['last_collect_at']=now

                    car=_taxi_car(idx,owned);st=stats[idx]
                    wear=max(0.0,min(100.0,float(st.get('wear',0) or 0)))
                    if wear<=0:return ('clean',int(row['balance'] or 0))

                    cost=_taxi_repair_cost(int(car.get('price',0) if car else 0),wear)
                    bal=int(row['balance'] or 0)
                    if cost>bal:return ('funds',cost,bal)

                    mileage=float(st.get('mileage',0) or 0)
                    income=int(st.get('total_income',0) or 0)
                    st.update({
                        'wear':0.0,'is_broken':False,'broken_at':None,
                        'line_started_at':now,'taxi_last_tick_at':now,'updated_at':now,
                        'wear_before':0.0,'mileage_before':mileage,'income_before':income
                    })
                    stats[idx]=st

                    cur.execute(
                        'UPDATE players SET balance=?,taxopark=?,garage_car_stats=? WHERE id=?',
                        (bal-cost,json.dumps(tax,ensure_ascii=False),json.dumps(stats,ensure_ascii=False),pid)
                    )
                    conn.commit();return ('ok',bal-cost,cost)
                except Exception:
                    conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(tx)

    if result[0]=='missing':return JSONResponse({'success':False,'error':'Игрок не найден'},status_code=404)
    if result[0]=='absent':return JSONResponse({'success':False,'error':'Эта машина не стоит на линии'},status_code=400)
    if result[0]=='clean':return JSONResponse({'success':True,'message':'Автомобиль исправен.','balance':result[1],'charged':0})
    if result[0]=='funds':return JSONResponse({'success':False,'error':f'Недостаточно средств. Нужно {result[1]:,} ₽.','balance':result[2]},status_code=400)
    return JSONResponse({'success':True,'message':'Автомобиль отремонтирован.','balance':result[1],'charged':result[2]})

@app.get("/tycoon/taxopark/{tg_id}/upgrades")
async def tycoon_taxopark_upgrades(tg_id:int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    u=await run_sync_db(_taxi_upgrades_for_player_sync,pid)
    return JSONResponse({"success":True,"upgrades":u,"config":TAXI_UPGRADE_CONFIG,"multiplier":_taxi_income_multiplier(u)})

@app.post("/tycoon/taxopark/{tg_id}/upgrade")
async def tycoon_taxopark_upgrade(tg_id:int,request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    try:data=await request.json()
    except Exception:data={}
    key=str(data.get("upgrade") or "").strip().lower()
    cfg=TAXI_UPGRADE_CONFIG.get(key)
    if not cfg:return JSONResponse({"success":False,"error":"Неизвестное улучшение"},status_code=400)
    lock=player_action_locks.setdefault(f"taxi:{pid}",asyncio.Lock())
    async with lock:
        async with db_lock:
            def _buy():
                conn=get_db();cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    row=cur.execute("SELECT balance FROM players WHERE id=?",(pid,)).fetchone()
                    if not row:return ("missing",)
                    urow=cur.execute("SELECT drivers_level,advertising_level,dispatch_level FROM taxi_upgrades WHERE player_id=?",(pid,)).fetchone()
                    u=_safe_taxi_upgrades({"drivers":urow["drivers_level"] if urow else 0,"advertising":urow["advertising_level"] if urow else 0,"dispatch":urow["dispatch_level"] if urow else 0})
                    level=int(u[key])
                    if level>=int(cfg["max"]):return ("max",)
                    cost=int(cfg["costs"][level]);balance=int(row["balance"] or 0)
                    if balance<cost:return ("funds",cost,balance)
                    u[key]=level+1
                    cur.execute("INSERT INTO taxi_upgrades(player_id,drivers_level,advertising_level,dispatch_level) VALUES(?,?,?,?) ON CONFLICT(player_id) DO UPDATE SET drivers_level=excluded.drivers_level,advertising_level=excluded.advertising_level,dispatch_level=excluded.dispatch_level",(pid,u["drivers"],u["advertising"],u["dispatch"]))
                    newbal=balance-cost
                    cur.execute("UPDATE players SET balance=? WHERE id=?",(newbal,pid))
                    conn.commit();return ("ok",newbal,cost,u)
                except Exception:conn.rollback();raise
                finally:conn.close()
            result=await run_sync_db(_buy)
    if result[0]=="missing":return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    if result[0]=="max":return JSONResponse({"success":False,"error":"Максимальный уровень"},status_code=400)
    if result[0]=="funds":return JSONResponse({"success":False,"error":f"Нужно {result[1]:,} ₽","balance":result[2]},status_code=400)
    return JSONResponse({"success":True,"message":f"{cfg['title']}: уровень {result[3][key]}.","balance":result[1],"charged":result[2],"upgrades":result[3],"multiplier":_taxi_income_multiplier(result[3])})

@app.get("/referrals/status/{tg_id}")
async def referrals_status_alias(tg_id:int):
    return await referrals_get(tg_id)

@app.get("/referral/{tg_id}")
async def referral_status_alias(tg_id:int):
    return await referrals_get(tg_id)

@app.post("/referral/attach/{tg_id}")
async def referral_attach_alias(tg_id:int, request:Request):
    return await referrals_attach(tg_id,request)

@app.post("/referral/claim/{tg_id}")
async def referral_claim_alias(tg_id:int, request:Request):
    return await referrals_claim(tg_id,request)

@app.post("/referrals/activate/{tg_id}")
async def referrals_activate_alias(tg_id:int, request:Request):
    try: data=await request.json()
    except Exception: data={}
    token=data.get("referrer_id") or data.get("referrerId") or data.get("ref_code") or data.get("token")
    if token is None:return JSONResponse({"success":True,"activated":False})
    pid=await get_player_id_by_tg(tg_id)
    if not pid:return JSONResponse({"success":False,"error":"Игрок не найден"},status_code=404)
    inviter=await run_sync_db(find_user_by_ref_code,str(token))
    if inviter and int(inviter)!=int(tg_id):
        def _p():
            conn=get_db();conn.execute("INSERT OR IGNORE INTO referral_pending(invitee_tg_id,inviter_tg_id,created_at,source) VALUES(?,?,?,?)",(int(tg_id),int(inviter),int(time_module.time()),"webapp"));conn.commit();conn.close()
        await run_sync_db(_p)
        return JSONResponse({"success":True,"activated":True,"inviter_tg_id":int(inviter)})
    return JSONResponse({"success":True,"activated":False})

def _web_chat_payload(chat: dict) -> dict:
    """Serialize an internal Avito chat to the stable frontend contract."""
    chat = chat if isinstance(chat, dict) else {}
    history = chat.get("history") if isinstance(chat.get("history"), list) else []
    last_message = ""
    for msg in reversed(history):
        if isinstance(msg, dict) and msg.get("content"):
            last_message = str(msg.get("content"))
            break

    market_price = max(1, int(chat.get("price", 0) or 1))
    current_offer = max(1, int(chat.get("offer", market_price) or market_price))
    if current_offer == market_price:
        base = market_price
        choices = [
            {"label": "Быстрая сделка · −10%", "price": max(1, int(round(base * 0.90))), "risk": 5},
            {"label": "Цена рынка", "price": base, "risk": 20},
            {"label": "Попробовать дороже · +10%", "price": max(1, int(round(base * 1.10))), "risk": 55},
        ]
    else:
        midpoint = max(1, int(round(((current_offer + market_price) / 2) / 100.0) * 100))
        choices = [
            {"label": "Быстрая сделка", "price": current_offer, "risk": 8},
            {"label": "Компромисс", "price": midpoint, "risk": 25},
            {"label": "Держать цену", "price": market_price, "risk": 48},
        ]
    seen=set(); unique_choices=[]
    for c in choices:
        key=int(c["price"])
        if key not in seen:
            seen.add(key); unique_choices.append(c)

    return {
        "chat_key": str(chat.get("chat_key") or ""),
        "buyer_id": int(chat.get("buyer_id", 0) or 0),
        "item": str(chat.get("item") or "Товар"),
        "item_uid": str(chat.get("item_uid") or ""),
        "message": last_message or "Клиент ждёт ответа.",
        "offer": current_offer,
        "price": market_price,
        "phase": int(chat.get("phase", 1) or 1),
        "round": int(chat.get("round", 1) or 1),
        "max_rounds": int(chat.get("max_rounds", 5) or 5),
        "trust": int(chat.get("trust", 50) or 50),
        "unread": bool(chat.get("unread")),
        "finished": bool(chat.get("finished")),
        "retry_available": bool(chat.get("retry_available")),
        "can_find_new_buyer": bool(chat.get("retry_available")),
        "last_activity_at": float(chat.get("last_activity_at", 0) or 0),
        "choices": unique_choices[:3],
    }


@app.get("/avito/{tg_id}")
async def avito_state(tg_id: int, request: Request):
    pid = await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({"success": False, "error": "Игрок не найден"}, status_code=404)
    player = await run_sync_db(ensure_inventory_uids_sync, pid, await run_sync_db(get_player_data, pid)) or {}
    player = await run_sync_db(ensure_market_state_sync, pid, player)
    # The market state builder stores the current event on the player.
    # Older builds forgot to bind it locally here, so the next line that
    # checked ``if event`` raised NameError and /avito returned HTTP 500.
    event = player.get("current_event") or None
    suppliers = await get_supplier_items(pid, player)
    suppliers = sorted(suppliers, key=lambda x: (float(x.get("demand", 1)), float(x.get("margin_pct", 0))), reverse=True)[:30]
    async with chats_lock:
        chats = [_web_chat_payload(v) for v in active_chats.values() if v.get("user_id") == pid and not v.get("finished")]
    chats.sort(key=lambda x: float(x.get("last_activity_at", 0) or 0), reverse=True)
    unread_count = sum(1 for x in chats if x.get("unread"))
    async with published_lock:
        pub = published_items.get(pid)
        published = None
        if pub:
            published = {"item": pub.get("item"), "description": pub.get("description", ""), "quality": pub.get("quality", 0), "chat": _web_chat_payload(next((v for v in active_chats.values() if v.get("chat_key") == pub.get("item_uid") and v.get("user_id") == pid), {})) if False else None}
    demand = player.get("market_demand") or {}
    top = sorted(demand.items(), key=lambda x: x[1], reverse=True)
    top3 = top[:3]
    low3 = sorted(demand.items(), key=lambda x: x[1])[:3]
    avg_demand = (sum(float(v) for v in demand.values()) / max(1, len(demand))) if demand else 1.0
    competition = "high" if avg_demand >= 1.15 else ("low" if avg_demand <= 0.85 else "mid")
    conditions = []
    if event:
        conditions.append({"id":"event","icon":"⚡","title":"Событие рынка","text":str(event.get("text") or "Рынок изменился")})
    conditions.append({"id":f"competition_{competition}","icon":"🔥" if competition=="high" else ("🟢" if competition=="low" else "⚖️"),"title":"Конкуренция высокая" if competition=="high" else ("Конкуренция ниже обычного" if competition=="low" else "Конкуренция стабильная"),"text":"Больше продавцов — цены сильнее конкурируют." if competition=="high" else ("Меньше продавцов — легче удерживать цену." if competition=="low" else "Рынок без резких перекосов.")})
    if top3:
        conditions.append({"id":"hot_categories","icon":"📈","title":"Горячий спрос","text":"".join([]) + ", ".join(f"{k} ×{float(v):.2f}" for k,v in top3)})
    if low3:
        conditions.append({"id":"cold_categories","icon":"📉","title":"Слабый спрос","text":", ".join(f"{k} ×{float(v):.2f}" for k,v in low3)})
    all_demand=[{"category":k,"multiplier":round(float(v),2)} for k,v in top]
    return JSONResponse({
        "success": True,
        "balance": int(player.get("balance", 0) or 0),
        "inventory": player.get("inventory", []),
        "suppliers": suppliers,
        "published": published,
        "chats": chats,
        "unread_count": unread_count,
        "shop_name": str(player.get("shop_name") or "Без названия"),
        "reputation": {"total_sales": int(player.get("total_sales", 0) or 0), "total_profit": int(player.get("total_profit", 0) or 0), "rating": get_avito_rating(int(player.get("total_sales", 0) or 0)), "level": get_rep_level(int(player.get("total_sales", 0) or 0))},
        "demand": {"hot": [{"category": k, "multiplier": round(float(v), 2)} for k, v in top3], "all": all_demand, "cold": [{"category": k, "multiplier": round(float(v), 2)} for k,v in low3]},
        "market_event": event,
        "market_conditions": conditions,
        "market_cycle_key": player.get("market_cycle_key"),
    })

@app.post("/avito/{tg_id}/buy")
async def avito_buy(tg_id: int, request: Request):
    data = await request.json()
    result = await api_call(tg_id, "buy_from_supplier", {"item_id": data.get("item_id")})
    if not result.get("success"):
        return JSONResponse({"success": False, "error": result.get("message", "Не удалось купить товар")}, status_code=400)
    return JSONResponse({"success": True, **result})

@app.post("/avito/{tg_id}/publish")
async def avito_publish(tg_id: int, request: Request):
    data = await request.json()
    description = str(data.get("description") or "").strip()[:1000]
    result = await api_call(tg_id, "publish_item", {"item_uid": data.get("item_uid"), "description": description})
    if not result.get("success"):
        return JSONResponse({"success": False, "error": result.get("message", "Не удалось опубликовать товар")}, status_code=400)
    return JSONResponse({"success": True, **result})

@app.post("/avito/{tg_id}/unpublish")
async def avito_unpublish(tg_id: int, request: Request):
    result = await api_call(tg_id, "unpublish_item")
    if not result.get("success"):
        return JSONResponse({"success": False, "error": result.get("message", "Не удалось снять объявление")}, status_code=400)
    return JSONResponse({"success": True, **result})

@app.post("/avito/{tg_id}/chat")
async def avito_chat(tg_id: int, request: Request):
    pid = await get_player_id_by_tg(tg_id)
    if not pid:
        return JSONResponse({"success": False, "error": "Игрок не найден"}, status_code=404)
    data = await request.json()
    chat_key = str(data.get("chat_key") or "")
    chat_action = str(data.get("action") or "").strip().lower()
    # Frontend aliases are accepted to keep old/new Avito clients compatible.
    chat_action = {
        # Новые кнопки Avito
        "discuss_price": "answer", "discuss": "answer", "talk": "answer",
        "choice": "answer", "reply": "answer", "send_choice": "answer",
        "answer_choice": "answer", "chat_answer": "answer",
        # Старые/альтернативные названия кнопки цены
        "make_offer": "price", "offer": "price", "send_price": "price",
        "choose_price": "price", "price_choice": "price", "select_price": "price",
        "set_price": "price", "send_offer": "price", "confirm_price": "price",
        "find_new_buyer": "new_buyer", "retry": "new_buyer",
        "newbuyer": "new_buyer",
    }.get(chat_action, chat_action)

    # Совместимость со старыми версиями фронтенда:
    # если действие пришло с ценой — это предложение цены;
    # если пришёл индекс варианта — это ответ в диалоге.
    if chat_action not in {"read", "answer", "price", "new_buyer"}:
        if data.get("price") is not None:
            chat_action = "price"
        elif data.get("choice_idx") is not None or data.get("choice") is not None:
            chat_action = "answer"
    async with chats_lock:
        chat = active_chats.get(chat_key)
        if not chat or (chat.get("finished") and chat_action != "new_buyer") or chat.get("user_id") != pid:
            return JSONResponse({"success": False, "error": "Чат не найден или уже завершён"}, status_code=404)
        if chat_action == "read":
            chat["unread"] = False
            chat["last_activity_at"] = time_module.time()
            return JSONResponse({"success": True, "chat": _web_chat_payload(chat)})
        if chat_action == "answer":
            chat["unread"] = False
            chat["last_activity_at"] = time_module.time()
            choice_raw = data.get("choice_idx", data.get("choice", 0))
            choice_idx = max(0, min(2, int(choice_raw or 0)))
            old_phase = int(chat.get("phase", 1)); chat["round"] = int(chat.get("round", 1)) + 1
            chat["trust"] = min(100, int(chat.get("trust", 50)) + ({0:10,1:8,2:5}.get(choice_idx,5)))
            if chat["round"] >= 3:
                chat["phase"] = 5
                client = CLIENT_TYPES[chat["client_type"]]
                wait_phrase = chat.get("dialogue", {}).get("final_prompt") or random.choice(client["phrases"].get("wait", ["Давайте обсудим цену."]))
                chat.setdefault("history", []).append({"role":"assistant","content":wait_phrase})
                return JSONResponse({"success": True, "finished": False, "chat": _web_chat_payload(chat), "message": wait_phrase})
            new_phase = old_phase + 1 if old_phase < 4 else 4
            chat["phase"] = new_phase
            client = CLIENT_TYPES[chat["client_type"]]; dialogue = chat.get("dialogue") or {}
            if new_phase <= 4 and len(dialogue.get("phases", [])) >= new_phase:
                client_msg = dialogue["phases"][new_phase-1].format(item=chat["item"], price=f"{chat['price']:,}", offer=f"{chat['offer']:,}")
            else:
                phase_key = ["greet","state_reaction","delivery_reaction","reason_reaction"][new_phase-1]
                client_msg = random.choice(client["phrases"].get(phase_key,["Продолжим."])).replace("{price}",str(chat["price"])).replace("{offer}",str(chat["offer"])).replace("{item}",chat["item"])
            chat.setdefault("history", []).append({"role":"assistant","content":client_msg})
            return JSONResponse({"success": True, "finished": False, "chat": _web_chat_payload(chat), "message": client_msg})
        if chat_action == "price":
            chat["unread"] = False
            chat["last_activity_at"] = time_module.time()
            chosen_price = max(1, int(data.get("price", 0) or 0)); risk = max(1, min(95, int(data.get("risk", 25) or 25)))
            chat["offer"] = chosen_price
            client = CLIENT_TYPES[chat["client_type"]]
            if random.randint(1, 100) > risk:
                answer = chat.get("dialogue", {}).get("final_agree") or random.choice(client["phrases"].get("agree", ["Хорошо, беру!"]))
                if isinstance(answer, list): answer = random.choice(answer)
                answer = answer.replace("{price}", f"{chosen_price:,}")
                chat.setdefault("history", []).append({"role":"assistant","content":answer})
            else:
                answer = chat.get("dialogue", {}).get("final_decline") or random.choice(client["phrases"].get("decline", ["Дорого, не буду брать."]))
                if isinstance(answer, list): answer = random.choice(answer)
                chat.setdefault("history", []).append({"role":"assistant","content":answer})
                chat["finished"] = True
                chat["unread"] = False
                chat["retry_available"] = True
                # Чат сохраняем как завершённый черновик, чтобы кнопка
                # «Найти нового покупателя» могла использовать тот же товар.
                out = {"success": True, "finished": True, "sold": False, "can_find_new_buyer": True, "chat": _web_chat_payload(chat), "message": answer}
                return JSONResponse(out)
        if chat_action == "new_buyer":
            # Текущий покупатель отказался: сохраняем объявление и сразу ищем нового.
            pub = published_items.get(pid)
            item_obj = dict(chat.get("item_obj") or {})
            if not item_obj and pub:
                item_obj = dict(pub.get("item") or {})
            if not item_obj:
                return JSONResponse({"success": False, "error": "Товар для нового покупателя не найден"}, status_code=400)
            old_uid = str(chat.get("item_uid") or item_obj.get("uid") or "")
            active_chats.pop(chat_key, None)
            buyer_id = random.randint(10000, 99999)
            while any(str(v.get("buyer_id")) == str(buyer_id) for v in active_chats.values()):
                buyer_id = random.randint(10000, 99999)
            item_uid = str(item_obj.get("uid") or old_uid or item_obj.get("name"))
            client_type=random.choices(["normal","skeptic","trader"],weights=[55,30,15],k=1)[0]
            price=max(1,int(item_obj.get("market_price",1)))
            if client_type=="trader": offer=max(100,int(price*random.uniform(.72,.90))); offer=(offer//100)*100+99
            elif client_type=="skeptic": offer=max(100,int(price*random.uniform(.88,.98)))
            else: offer=price
            pool=[d for d in CLIENT_DIALOGUES if d["client_type"]==client_type] or CLIENT_DIALOGUES
            seed=int(hashlib.sha256(f"dialog:{pid}:{item_uid}:{int(time_module.time())}:{buyer_id}".encode()).hexdigest()[:12],16)
            scenario=pool[seed%len(pool)]
            msg=scenario["phases"][0].format(item=item_obj["name"],price=f"{price:,}",offer=f"{offer:,}")
            new_key=f"{pid}_{buyer_id}_{uuid.uuid4().hex[:8]}"
            active_chats[new_key]={"user_id":pid,"buyer_id":buyer_id,"client_type":client_type,"item":item_obj["name"],"item_uid":item_uid,"price":price,"offer":offer,"round":1,"max_rounds":5,"finished":False,"phase":1,"trust":50,"dialogue":scenario,"history":[{"role":"assistant","content":msg}],"chat_key":new_key,"item_obj":item_obj,"created_at":time_module.time(),"unread":True,"last_activity_at":time_module.time()}
            return JSONResponse({"success":True,"finished":False,"sold":False,"new_buyer":True,"chat":_web_chat_payload(active_chats[new_key]),"message":msg})
        elif chat_action != "price":
            return JSONResponse({"success": False, "error": "Неизвестное действие чата"}, status_code=400)
    # complete_sale_universal берёт item_obj и безопасно удаляет один экземпляр товара
    sale = await complete_sale_universal(chat, pid)
    if not sale.get("success"):
        return JSONResponse({"success": False, "error": sale.get("message", "Не удалось завершить сделку")}, status_code=400)
    return JSONResponse({"success": True, "finished": True, "sold": True, "balance": int((await run_sync_db(get_player_data, pid) or {}).get("balance", 0) or 0), "message": sale.get("message", "Сделка закрыта")})

@app.get("/tycoon/media/{file_id}")
async def tycoon_media(file_id:str):
    # Telegram file_id stays on the server. The browser only sees this proxy URL.
    try:
        f=await bot.get_file(file_id)
        if not f.file_path: return Response(status_code=404)
        token=str(BOT_TOKEN)
        url=f"https://api.telegram.org/file/bot{token}/{f.file_path}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url,timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status!=200: return Response(status_code=404)
                data=await r.read()
                ctype=r.headers.get("Content-Type","image/jpeg")
                return Response(content=data,media_type=ctype,headers={"Cache-Control":"public,max-age=86400"})
    except Exception as e:
        print(f"TYCOON MEDIA ERROR: {e}")
        return Response(status_code=404)


# ==================== RESSELL BUSINESS CONTROL API ====================
@app.get("/business/{tg_id}")
async def business_state(tg_id: int, request: Request):
    """Полное состояние бизнесов для RESSELL Mini App."""
    if not _verify_tycoon_webapp_request(request,tg_id):
        return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return JSONResponse({"success": False, "error": "Player not found"}, status_code=404)

    def _state():
        conn = get_db()
        rows = conn.execute(
            "SELECT id, shop_id, purchase_price, purchased_at, last_payment, paid_until, status "
            "FROM user_shops WHERE player_id=? ORDER BY id ASC", (player_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    rows = await run_sync_db(_state)
    catalog = []
    for shop in SHOP_LEVELS:
        if shop.get("id") == "none":
            continue
        catalog.append({
            "id": shop["id"], "name": shop["name"], "price": int(shop["price"]),
            "income_per_hour": int(shop["income_per_hour"]),
            "income_per_day": int(shop["income_per_hour"] * 24),
            "sell_price": int(shop["price"] * 0.7)
        })

    businesses=[]
    for row in rows:
        shop=next((x for x in SHOP_LEVELS if x["id"]==row["shop_id"]), None)
        if not shop: continue
        now=int(time_module.time())
        paid_until=int(row.get("paid_until") or 0)
        debt_due=max(0, int(get_maintenance_cost_shop(int(row.get("purchase_price") or shop["price"])))) if row.get("status")=="active" else 0
        businesses.append({
            "instance_id": int(row["id"]), "id": shop["id"], "name": shop["name"],
            "price": int(shop["price"]), "purchase_price": int(row.get("purchase_price") or shop["price"]),
            "income_per_hour": int(shop["income_per_hour"]), "income_per_day": int(shop["income_per_hour"]*24),
            "sell_price": int(shop["price"]*0.7), "status": row.get("status") or "active",
            "paid_until": paid_until, "maintenance_cost": debt_due,
            "maintenance_days_left": max(0, int((paid_until-now)/86400)) if paid_until else 0
        })

    pending, hourly, breakdown = await get_pending_income(player_id)
    # Keep a named pending breakdown so the Mini App can show the taxopark as
    # a first-class business without inventing a second collection mechanism.
    pending_breakdown = {k:int(v) for k,v in breakdown.items()}
    debt = await calculate_total_debt(player_id)
    taxi_hourly = int((breakdown.get("taxopark",0) if breakdown else 0))
    return JSONResponse({
        "success": True,
        "balance": int(player.get("balance",0) or 0),
        "businesses": businesses,
        "catalog": catalog,
        "pending_collect": int(pending),
        "total_per_hour": int(hourly),
        "total_per_day": int(hourly*24),
        "hourly_breakdown": breakdown,
        "pending_breakdown": pending_breakdown,
        "taxi_business": {"hourly_income":taxi_hourly,"pending_collect":int(pending_breakdown.get("taxopark",0) if pending_breakdown else 0)},
        "maintenance_debt": int(debt),
        "legacy_shop_level": player.get("shop_level","none")
    })

@app.post("/business/{tg_id}/buy")
async def business_buy(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    shop_id=str(data.get("shop_id") or "")
    if not shop_id: return JSONResponse({"success":False,"error":"Не выбран бизнес"},status_code=400)
    result=await handle_action(PlayerAction(platform="tg", platform_id=tg_id, action="buy_shop_multiple", data={"shop_id":shop_id}))
    if not result or not result.get("success"):
        return JSONResponse({"success":False,"error":(result or {}).get("message","Не удалось купить бизнес")},status_code=400)
    return JSONResponse(result)

@app.post("/business/{tg_id}/sell")
async def business_sell(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    try: data=await request.json()
    except Exception: data={}
    shop_id=str(data.get("shop_id") or "")
    if not shop_id: return JSONResponse({"success":False,"error":"Не выбран бизнес"},status_code=400)
    result=await handle_action(PlayerAction(platform="tg", platform_id=tg_id, action="sell_shop", data={"shop_id":shop_id}))
    if not result or not result.get("success"):
        return JSONResponse({"success":False,"error":(result or {}).get("message","Не удалось продать бизнес")},status_code=400)
    return JSONResponse(result)

@app.post("/business/{tg_id}/collect")
async def business_collect(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    collected,hourly,breakdown=await collect_pending_income(player_id)
    fresh=await run_sync_db(get_player_data,player_id) or {}
    return JSONResponse({"success":True,"collected":int(collected),"balance":int(fresh.get("balance",0) or 0),"total_per_hour":int(hourly),"breakdown":breakdown})

@app.post("/business/{tg_id}/maintenance")
async def business_maintenance(tg_id: int, request: Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    success,msg=await pay_all_debt(player_id)
    fresh=await run_sync_db(get_player_data,player_id) or {}
    if not success: return JSONResponse({"success":False,"error":msg,"balance":int(fresh.get("balance",0) or 0)},status_code=400)
    return JSONResponse({"success":True,"message":msg,"balance":int(fresh.get("balance",0) or 0)})

@app.get("/upgrades/{tg_id}")
async def upgrades_status(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    levels=await run_sync_db(get_upgrade_state,player_id); items=[]
    for key,cfg in UPGRADE_CARDS.items():
        level=int(levels.get(key,0)); costs=cfg["costs"]; maxed=level>=len(costs)
        items.append({"id":key,"name":cfg["name"],"icon":cfg["icon"],"description":cfg["description"],"level":level,"max_level":len(costs),"cost":None if maxed else costs[level],"income_per_level":cfg["income_per_level"],"hold_bonus_per_level":cfg["hold_bonus_per_level"]})
    return JSONResponse({"success":True,"upgrades":items,"hourly_income":await run_sync_db(get_upgrade_income,player_id)})

@app.post("/upgrades/{tg_id}/buy")
async def upgrade_buy(tg_id:int, request:Request):
    try: data=await request.json()
    except Exception: data={}
    upgrade_id=str(data.get("upgrade_id") or ""); cfg=UPGRADE_CARDS.get(upgrade_id)
    if not cfg: return JSONResponse({"success":False,"error":"Неизвестное улучшение"},status_code=400)
    player_id=await get_player_id_by_tg(tg_id)
    if not player_id: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    lock=player_action_locks.setdefault(f"upgrade:{player_id}",asyncio.Lock())
    async with lock:
        async with db_lock:
            def _buy():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("BEGIN IMMEDIATE")
                    row=cur.execute("SELECT level FROM webapp_upgrades WHERE player_id=? AND upgrade_id=?",(player_id,upgrade_id)).fetchone()
                    level=int(row["level"]) if row else 0; costs=cfg["costs"]
                    if level>=len(costs): conn.rollback(); return ("max",)
                    cost=int(costs[level]); bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                    if not bal or int(bal["balance"] or 0)<cost: conn.rollback(); return ("funds",cost,int(bal["balance"] if bal else 0))
                    if row: cur.execute("UPDATE webapp_upgrades SET level=? WHERE player_id=? AND upgrade_id=?",(level+1,player_id,upgrade_id))
                    else: cur.execute("INSERT INTO webapp_upgrades(player_id,upgrade_id,level) VALUES(?,?,1)",(player_id,upgrade_id))
                    cur.execute("UPDATE players SET balance=balance-? WHERE id=?",(cost,player_id))
                    new_bal=cur.execute("SELECT balance FROM players WHERE id=?",(player_id,)).fetchone()
                    conn.commit(); return ("ok",level+1,int(new_bal["balance"] if new_bal else 0))
                except Exception: conn.rollback(); raise
                finally: conn.close()
            result=await run_sync_db(_buy)
    if result[0]=="max": return JSONResponse({"success":False,"error":"Улучшение уже на максимальном уровне"},status_code=400)
    if result[0]=="funds": return JSONResponse({"success":False,"error":f"Нужно {result[1]:,}₽","balance":result[2]},status_code=400)
    await run_sync_db(_engagement_add_xp_sync,player_id,50,"upgrade_buy")
    await activate_pending_referral(int(tg_id), "upgrade_buy")
    return JSONResponse({"success":True,"level":result[1],"balance":result[2],"hourly_income":await run_sync_db(get_upgrade_income,player_id)})

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПОКЕРА ====================

def create_deck():
    suits = ['♠', '♥', '♦', '♣']
    ranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']
    deck = [{'rank': r, 'suit': s, 'val': i+2} for i, r in enumerate(ranks) for s in suits]
    random.shuffle(deck)
    return deck

def hand_rank(cards):
    from collections import Counter
    vals = sorted([c['val'] for c in cards], reverse=True)
    suits = [c['suit'] for c in cards]
    is_flush = len(set(suits)) == 1
    is_straight = False
    if len(set(vals)) == 5:
        if max(vals) - min(vals) == 4:
            is_straight = True
        elif set(vals) == {14,5,4,3,2}:
            is_straight = True
            vals = [5,4,3,2,1]
    count = Counter(vals)
    freq = sorted(count.values(), reverse=True)
    if is_flush and is_straight and max(vals) == 14:
        return (9, vals)
    if is_flush and is_straight:
        return (8, vals)
    if freq[0] == 4:
        return (7, vals)
    if freq[0] == 3 and freq[1] == 2:
        return (6, vals)
    if is_flush:
        return (5, vals)
    if is_straight:
        return (4, vals)
    if freq[0] == 3:
        return (3, vals)
    if freq[0] == 2 and freq[1] == 2:
        return (2, vals)
    if freq[0] == 2:
        return (1, vals)
    return (0, vals)

def compare_hands(hand1, hand2):
    rank1, vals1 = hand_rank(hand1)
    rank2, vals2 = hand_rank(hand2)
    if rank1 != rank2:
        return rank1 - rank2
    for a, b in zip(vals1, vals2):
        if a != b:
            return a - b
    return 0

def get_bot_action(hand, community, pot, current_bet, bot_type, stage, stack):
    if not hand:
        return 'fold', 0
    rank, _ = hand_rank(hand + community)
    strength = rank
    if stage == 'preflop':
        pair = hand[0]['val'] == hand[1]['val']
        high = max(c['val'] for c in hand)
        if pair:
            strength = 3
        elif high >= 12:
            strength = 2
        else:
            strength = 1
    rand = random.random()
    if bot_type == 'tight':
        if strength < 3:
            return 'fold', 0
        elif strength < 5:
            if rand < 0.3:
                return 'call', current_bet
            else:
                return 'fold', 0
        else:
            if rand < 0.6:
                return 'raise', min(stack, current_bet*2)
            else:
                return 'call', current_bet
    elif bot_type == 'aggressive':
        if strength < 2:
            if rand < 0.3:
                return 'call', current_bet
            else:
                return 'fold', 0
        elif strength < 4:
            if rand < 0.4:
                return 'call', current_bet
            else:
                return 'raise', min(stack, current_bet*2)
        else:
            if rand < 0.6:
                return 'raise', min(stack, current_bet*3)
            else:
                return 'call', current_bet
    else:  # balanced
        if strength < 2:
            if rand < 0.2:
                return 'call', current_bet
            else:
                return 'fold', 0
        elif strength < 4:
            if rand < 0.5:
                return 'call', current_bet
            else:
                return 'raise', min(stack, current_bet*2)
        else:
            if rand < 0.7:
                return 'raise', min(stack, current_bet*2)
            else:
                return 'call', current_bet

# ==================== ЭНДПОИНТЫ ПОКЕРА ====================

@app.post("/poker/start")
async def poker_start(request: Request):
    import time
    start_time = time.perf_counter()
    print(f"[POKER START] request received at {start_time}")

    try:
        data = await request.json()
        tg_id = data.get('userId') or data.get('user_id')
        buy_in = int(data.get('buyIn', data.get('bet', 100)))
        bot_count = int(data.get('botCount', 3))
        if bot_count < 2 or bot_count > 5:
            bot_count = 3
        if buy_in < 10:
            return JSONResponse({"error": "Минимальная ставка 10"}, status_code=400)

        player_id = await get_player_id_by_tg(tg_id)
        if not player_id:
            return JSONResponse({"error": "Player not found"}, status_code=404)

        # ----- АВТОМАТИЧЕСКАЯ ОЧИСТКА ЗАВИСШИХ ИГР (как в /case-win) -----
        async with db_lock:
            conn = get_db()
            cursor = conn.cursor()
            try:
                # Удаляем игры, которые висят дольше 10 минут (600 секунд)
                cursor.execute('''
                    DELETE FROM poker_hands 
                    WHERE game_id IN (
                        SELECT id FROM poker_games 
                        WHERE player_id = ? 
                        AND status = 'active' 
                        AND (strftime('%s', 'now') - created_at) > 600
                    )
                ''', (player_id,))
                cursor.execute('''
                    DELETE FROM poker_games 
                    WHERE player_id = ? 
                    AND status = 'active' 
                    AND (strftime('%s', 'now') - created_at) > 600
                ''', (player_id,))
                conn.commit()
            except Exception as e:
                print(f"[POKER START] Ошибка очистки: {e}")
            finally:
                conn.close()
        # ----- КОНЕЦ БЛОКА -----

        async with db_lock:
            conn = get_db()
            cursor = conn.cursor()
            try:
                # Проверка активной игры уже после очистки
                cursor.execute('SELECT id FROM poker_games WHERE player_id = ? AND status = "active"', (player_id,))
                if cursor.fetchone():
                    conn.close()
                    return JSONResponse({"error": "У вас уже есть активная игра"}, status_code=400)

                player = get_player_data(player_id)
                if not player:
                    conn.close()
                    return JSONResponse({"error": "Player not found"}, status_code=404)
                if player['balance'] < buy_in:
                    conn.close()
                    return JSONResponse({"error": "Недостаточно средств"}, status_code=400)

                bot_names = [
                    {'name': 'Джеймс Уильямс', 'type': 'tight', 'avatar': '👔'},
                    {'name': 'Майкл Стоун', 'type': 'aggressive', 'avatar': '😎'},
                    {'name': 'Алекс Риверс', 'type': 'balanced', 'avatar': '🧢'},
                    {'name': 'Виктор Блэк', 'type': 'aggressive', 'avatar': '🎩'},
                    {'name': 'Даниэль Кинг', 'type': 'balanced', 'avatar': '🕶️'}
                ]
                selected_bots = random.sample(bot_names, bot_count)

                all_players = [{'seat': 0, 'player_id': player_id, 'bot_id': None, 'is_bot': False,
                                'name': player.get('nickname', 'Вы'), 'avatar': '👤', 'stack': buy_in}]
                for i, bot in enumerate(selected_bots, start=1):
                    all_players.append({
                        'seat': i,
                        'player_id': None,
                        'bot_id': f"bot_{i}_{int(time.time())}",
                        'is_bot': True,
                        'name': bot['name'],
                        'avatar': bot['avatar'],
                        'bot_type': bot['type'],
                        'stack': buy_in * 2
                    })

                deck = create_deck()
                hands = {}
                for p in all_players:
                    hands[p['seat']] = [deck.pop(), deck.pop()]

                community = []
                pot = 0
                game_id = f"poker_{int(time.time())}_{random.randint(1000,9999)}"
                now = int(time.time())

                cursor.execute('''
                    INSERT INTO poker_games (id, player_id, status, stage, pot, community_cards, deck, buy_in, created_at, updated_at, payout_done, current_turn)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (game_id, player_id, 'active', 'preflop', pot, json.dumps(community), json.dumps(deck), buy_in, now, now, 0, 0))

                for p in all_players:
                    cursor.execute('''
                        INSERT INTO poker_hands (game_id, seat_number, player_id, bot_id, name, avatar, is_bot, bot_type, cards, stack, current_bet, total_bet, folded, all_in)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        game_id, p['seat'], p['player_id'], p['bot_id'],
                        p['name'], p['avatar'],
                        1 if p['is_bot'] else 0,
                        p.get('bot_type', ''),
                        json.dumps(hands[p['seat']]),
                        p['stack'], 0, 0, 0, 0
                    ))

                new_balance = player['balance'] - buy_in
                cursor.execute("UPDATE players SET balance = ? WHERE id = ?", (new_balance, player_id))

                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

        state = {
            'gameId': game_id,
            'status': 'active',
            'stage': 'preflop',
            'pot': 0,
            'communityCards': [],
            'playerCards': hands[0],
            'players': []
        }
        for p in all_players:
            state['players'].append({
                'id': p['player_id'] if not p['is_bot'] else p['bot_id'],
                'seat': p['seat'],
                'name': p['name'],
                'avatar': p['avatar'],
                'isBot': p['is_bot'],
                'stack': p['stack'],
                'isActive': True,
                'bet': 0,
                'cards': hands[p['seat']] if p['seat'] == 0 else None
            })
        state['availableActions'] = {
            'fold': True,
            'check': True,
            'call': False,
            'raise': True,
            'allIn': True
        }

        elapsed = time.perf_counter() - start_time
        print(f"[POKER START] response ready, elapsed={elapsed:.3f}s")
        return JSONResponse({'success': True, 'gameId': game_id, 'balance': new_balance, 'state': state})

    except Exception as e:
        print(f"[POKER START] ERROR: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/poker/action")
async def poker_action(request: Request):
    try:
        data = await request.json()
        game_id = data.get('gameId')
        tg_id = data.get('userId') or data.get('user_id')
        action = data.get('action')
        amount = int(data.get('amount', 0))
        if not game_id or not tg_id:
            return JSONResponse({"error": "Missing data"}, status_code=400)

        player_id = await get_player_id_by_tg(tg_id)
        if not player_id:
            return JSONResponse({"error": "Player not found"}, status_code=404)

        async with db_lock:
            conn = get_db()
            cursor = conn.cursor()
            try:
                # 1. Проверяем игру
                cursor.execute('SELECT * FROM poker_games WHERE id = ? AND status = "active"', (game_id,))
                game_row = cursor.fetchone()
                if not game_row:
                    return JSONResponse({"error": "Game not found or already finished"}, status_code=404)
                game = dict(game_row)
                community = json.loads(game['community_cards'])
                pot = game['pot']
                stage = game['stage']
                current_turn = game.get('current_turn', 0)
                deck = json.loads(game['deck'])

                # 2. Получаем всех игроков
                cursor.execute('SELECT * FROM poker_hands WHERE game_id = ?', (game_id,))
                hands_rows = cursor.fetchall()
                players = []
                for row in hands_rows:
                    p = dict(row)
                    p['cards'] = json.loads(p['cards'])
                    players.append(p)

                # 3. Находим игрока
                player = next((p for p in players if p['player_id'] == player_id and not p['is_bot']), None)
                if not player:
                    return JSONResponse({"error": "Player not in game"}, status_code=404)

                # 4. Проверяем ход
                if current_turn != player['seat_number']:
                    return JSONResponse({"error": "Сейчас не ваш ход"}, status_code=400)

                # 5. Обрабатываем действие игрока
                max_bet = max((p['current_bet'] for p in players if not p['folded']), default=0)
                call_amount = max_bet - player['current_bet']

                if action == 'fold':
                    cursor.execute('UPDATE poker_hands SET folded = 1 WHERE game_id = ? AND seat_number = ?', (game_id, player['seat_number']))
                elif action == 'check':
                    if call_amount > 0:
                        return JSONResponse({"error": "Нельзя чекнуть, нужно уравнять ставку"}, status_code=400)
                elif action == 'call':
                    if call_amount == 0:
                        pass
                    elif call_amount > player['stack']:
                        return JSONResponse({"error": "Недостаточно фишек"}, status_code=400)
                    else:
                        new_stack = player['stack'] - call_amount
                        cursor.execute('UPDATE poker_hands SET stack = ?, current_bet = current_bet + ?, total_bet = total_bet + ? WHERE game_id = ? AND seat_number = ?',
                                       (new_stack, call_amount, call_amount, game_id, player['seat_number']))
                        pot += call_amount
                        cursor.execute('UPDATE poker_games SET pot = ? WHERE id = ?', (pot, game_id))
                elif action == 'raise':
                    if amount <= 0:
                        return JSONResponse({"error": "Сумма должна быть больше 0"}, status_code=400)
                    if amount > player['stack']:
                        return JSONResponse({"error": "Недостаточно фишек"}, status_code=400)
                    min_raise = max_bet * 2 if max_bet > 0 else game['buy_in'] * 2
                    if amount < min_raise:
                        return JSONResponse({"error": f"Минимальное повышение: {min_raise}"}, status_code=400)
                    new_stack = player['stack'] - amount
                    cursor.execute('UPDATE poker_hands SET stack = ?, current_bet = current_bet + ?, total_bet = total_bet + ? WHERE game_id = ? AND seat_number = ?',
                                   (new_stack, amount, amount, game_id, player['seat_number']))
                    pot += amount
                    cursor.execute('UPDATE poker_games SET pot = ? WHERE id = ?', (pot, game_id))
                elif action == 'all_in':
                    all_in_amount = player['stack']
                    cursor.execute('UPDATE poker_hands SET stack = 0, current_bet = current_bet + ?, total_bet = total_bet + ?, all_in = 1 WHERE game_id = ? AND seat_number = ?',
                                   (all_in_amount, all_in_amount, game_id, player['seat_number']))
                    pot += all_in_amount
                    cursor.execute('UPDATE poker_games SET pot = ? WHERE id = ?', (pot, game_id))
                else:
                    return JSONResponse({"error": "Invalid action"}, status_code=400)

                # Переключаем ход на следующего человека
                cursor.execute('''
                    SELECT seat_number FROM poker_hands
                    WHERE game_id = ? AND folded = 0 AND is_bot = 0
                    ORDER BY seat_number
                ''', (game_id,))
                human_players = cursor.fetchall()
                next_seat = None
                for row in human_players:
                    if row['seat_number'] > current_turn:
                        next_seat = row['seat_number']
                        break
                if next_seat is None and human_players:
                    next_seat = human_players[0]['seat_number']

                if next_seat is not None:
                    cursor.execute('UPDATE poker_games SET current_turn = ? WHERE id = ?', (next_seat, game_id))
                    current_turn = next_seat

                # =============================================================
                #  АВТОМАТИЧЕСКИЙ ХОД БОТОВ (ЦИКЛ)
                # =============================================================
                max_bot_iterations = 30
                while max_bot_iterations > 0:
                    max_bot_iterations -= 1
                    cursor.execute('SELECT * FROM poker_hands WHERE game_id = ? AND seat_number = ?', (game_id, current_turn))
                    hand_row = cursor.fetchone()
                    if not hand_row:
                        break
                    hand = dict(hand_row)

                    if hand['is_bot'] and not hand['folded'] and hand['stack'] > 0:
                        bot_type = hand.get('bot_type', 'balanced')
                        community_cards = json.loads(game['community_cards']) if game['community_cards'] else []
                        hand_cards = json.loads(hand['cards'])
                        max_bet = max((p['current_bet'] for p in players if not p['folded']), default=0)
                        stack = hand['stack']
                        stage = game['stage']

                        bot_action, bot_amount = get_bot_action(hand_cards, community_cards, pot, max_bet, bot_type, stage, stack)

                        if bot_action == 'fold':
                            cursor.execute('UPDATE poker_hands SET folded = 1 WHERE game_id = ? AND seat_number = ?', (game_id, hand['seat_number']))
                        elif bot_action == 'check':
                            pass
                        elif bot_action == 'call':
                            call_amt = max_bet - hand['current_bet']
                            if call_amt > 0 and call_amt <= stack:
                                new_stack = stack - call_amt
                                cursor.execute('UPDATE poker_hands SET stack = ?, current_bet = current_bet + ?, total_bet = total_bet + ? WHERE game_id = ? AND seat_number = ?',
                                               (new_stack, call_amt, call_amt, game_id, hand['seat_number']))
                                pot += call_amt
                                cursor.execute('UPDATE poker_games SET pot = ? WHERE id = ?', (pot, game_id))
                        elif bot_action == 'raise':
                            raise_amt = min(bot_amount, stack)
                            if raise_amt > 0:
                                new_stack = stack - raise_amt
                                cursor.execute('UPDATE poker_hands SET stack = ?, current_bet = current_bet + ?, total_bet = total_bet + ? WHERE game_id = ? AND seat_number = ?',
                                               (new_stack, raise_amt, raise_amt, game_id, hand['seat_number']))
                                pot += raise_amt
                                cursor.execute('UPDATE poker_games SET pot = ? WHERE id = ?', (pot, game_id))

                        # Обновляем список игроков после хода бота
                        cursor.execute('SELECT * FROM poker_hands WHERE game_id = ?', (game_id,))
                        players = [dict(row) for row in cursor.fetchall()]

                        # Проверка на окончание игры
                        active_players = [p for p in players if not p['folded'] and p['stack'] > 0]
                        if len(active_players) <= 1:
                            break

                        # Переключаем ход на следующего активного
                        active_seats = sorted([p['seat_number'] for p in active_players])
                        idx = active_seats.index(hand['seat_number']) if hand['seat_number'] in active_seats else 0
                        next_seat = active_seats[(idx + 1) % len(active_seats)]
                        cursor.execute('UPDATE poker_games SET current_turn = ? WHERE id = ?', (next_seat, game_id))
                        current_turn = next_seat
                        cursor.execute('SELECT * FROM poker_games WHERE id = ?', (game_id,))
                        game = dict(cursor.fetchone())
                    else:
                        # Ход человека – выходим из цикла
                        break

                # =============================================================
                #  ПРОВЕРКА ОКОНЧАНИЯ ПОСЛЕ ВСЕХ ХОДОВ
                # =============================================================
                cursor.execute('SELECT COUNT(*) FROM poker_hands WHERE game_id = ? AND folded = 0', (game_id,))
                active_count = cursor.fetchone()[0]
                if active_count <= 1:
                    winner_row = cursor.execute('SELECT * FROM poker_hands WHERE game_id = ? AND folded = 0', (game_id,)).fetchone()
                    if winner_row:
                        if winner_row['player_id'] == player_id:
                            win_amount = pot
                            cursor.execute('UPDATE poker_games SET status = "finished", payout_done = 1 WHERE id = ? AND payout_done = 0', (game_id,))
                            if cursor.rowcount == 1:
                                player_data = get_player_data(player_id)
                                if player_data:
                                    new_balance = player_data['balance'] + win_amount
                                    cursor.execute("UPDATE players SET balance = ? WHERE id = ?", (new_balance, player_id))
                                else:
                                    new_balance = 0
                            else:
                                player_data = get_player_data(player_id)
                                new_balance = player_data['balance'] if player_data else 0
                            conn.commit()
                            conn.close()
                            return JSONResponse({'success': True, 'winnerId': player_id, 'winAmount': win_amount, 'balance': new_balance})
                        else:
                            cursor.execute('UPDATE poker_games SET status = "finished", payout_done = 1 WHERE id = ? AND payout_done = 0', (game_id,))
                            conn.commit()
                            conn.close()
                            return JSONResponse({'success': True, 'winnerId': winner_row['player_id'] or winner_row['bot_id'], 'winAmount': 0})

                # Проверка, все ли уравняли ставки (переход на следующую улицу)
                cursor.execute('''
                    SELECT COUNT(DISTINCT current_bet) FROM poker_hands
                    WHERE game_id = ? AND folded = 0 AND stack > 0
                ''', (game_id,))
                distinct_bets = cursor.fetchone()[0]

                if distinct_bets <= 1 and stage != 'showdown':
                    community = json.loads(game['community_cards'])
                    deck = json.loads(game['deck'])

                    if stage == 'preflop':
                        community.extend([deck.pop(), deck.pop(), deck.pop()])
                        new_stage = 'flop'
                    elif stage == 'flop':
                        community.append(deck.pop())
                        new_stage = 'turn'
                    elif stage == 'turn':
                        community.append(deck.pop())
                        new_stage = 'river'
                    elif stage == 'river':
                        new_stage = 'showdown'
                    else:
                        new_stage = stage

                    cursor.execute('''
                        UPDATE poker_games SET stage = ?, community_cards = ?, deck = ?
                        WHERE id = ?
                    ''', (new_stage, json.dumps(community), json.dumps(deck), game_id))
                    cursor.execute('UPDATE poker_hands SET current_bet = 0 WHERE game_id = ?', (game_id,))
                    first = cursor.execute('SELECT seat_number FROM poker_hands WHERE game_id = ? AND folded = 0 ORDER BY seat_number LIMIT 1', (game_id,)).fetchone()
                    if first:
                        cursor.execute('UPDATE poker_games SET current_turn = ? WHERE id = ?', (first['seat_number'], game_id))
                    conn.commit()
                    stage = new_stage
                else:
                    conn.commit()

                # Формируем ответ
                state = {
                    'gameId': game_id,
                    'status': 'active',
                    'stage': stage,
                    'pot': pot,
                    'communityCards': community,
                    'playerCards': json.loads(player['cards']),
                    'players': []
                }
                cursor.execute('SELECT * FROM poker_hands WHERE game_id = ?', (game_id,))
                all_hands = cursor.fetchall()
                for h in all_hands:
                    state['players'].append({
                        'id': h['player_id'] if not h['is_bot'] else h['bot_id'],
                        'seat': h['seat_number'],
                        'name': h['name'],
                        'avatar': h['avatar'],
                        'isBot': bool(h['is_bot']),
                        'isActive': not bool(h['folded']),
                        'cards': json.loads(h['cards']) if (not h['is_bot'] and h['player_id'] == player_id) else None,
                        'stack': h['stack'],
                        'bet': h['current_bet']
                    })
                state['availableActions'] = {
                    'fold': True,
                    'check': True,
                    'call': call_amount > 0,
                    'raise': True,
                    'allIn': player['stack'] > 0
                }
                conn.close()
                return JSONResponse({'success': True, 'state': state})

            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

    except Exception as e:
        print(f"[POKER ACTION] ERROR: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/poker/state/{game_id}")
async def get_poker_state(game_id: str, request: Request):
    tg_id = request.query_params.get('userId')
    if not tg_id:
        return JSONResponse({"error": "No userId"}, status_code=400)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"error": "Player not found"}, status_code=404)

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT * FROM poker_games WHERE id = ?', (game_id,))
        game_row = cursor.fetchone()
        if not game_row:
            conn.close()
            return JSONResponse({"error": "Game not found"}, status_code=404)
        game = dict(game_row)
        community = json.loads(game['community_cards']) if game['community_cards'] else []

        cursor.execute('SELECT * FROM poker_hands WHERE game_id = ?', (game_id,))
        hands_rows = cursor.fetchall()
        players = []
        for row in hands_rows:
            p = dict(row)
            try:
                p['cards'] = json.loads(p['cards']) if p['cards'] else []
            except:
                p['cards'] = []
            players.append(p)

        player_hand = next((p for p in players if p['player_id'] == player_id), None)
        state = {
            'gameId': game_id,
            'status': game['status'],
            'stage': game['stage'],
            'pot': game['pot'],
            'communityCards': community,
            'playerCards': json.loads(player_hand['cards']) if player_hand and player_hand['cards'] else [],
            'players': []
        }
        for p in players:
            state['players'].append({
                'id': p['player_id'] if not p['is_bot'] else p['bot_id'],
                'seat': p['seat_number'],
                'name': p['name'],
                'avatar': p['avatar'],
                'isBot': bool(p['is_bot']),
                'isActive': not bool(p['folded']),
                'cards': json.loads(p['cards']) if (not p['is_bot'] and p['player_id'] == player_id and p['cards']) else None,
                'stack': p['stack'],
                'bet': p['current_bet']
            })
        # Если игра активна – добавить доступные действия
        if game['status'] == 'active':
            turn = game.get('current_turn', 0)
            player_turn = False
            if player_hand:
                player_turn = (turn == player_hand['seat_number']) and not player_hand['folded']
            state['availableActions'] = {
                'fold': player_turn,
                'check': player_turn,
                'call': player_turn,
                'raise': player_turn,
                'allIn': player_turn
            }
        conn.close()
        return JSONResponse({'success': True, 'state': state})
    except Exception as e:
        conn.close()
        print(f"[POKER STATE] ERROR: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

async def reset_daily_quests_at_noon():
    """На 12:00 переключает цикл. cycle_key также защищает от повторного начисления между рестартами."""
    while True:
        now=datetime.now(); target=now.replace(hour=12,minute=0,second=0,microsecond=0)
        if now>=target: target+=timedelta(days=1)
        await asyncio.sleep(max(1,(target-now).total_seconds()))
        cycle=market_cycle_key(datetime.now())
        async with db_lock:
            def _reset():
                conn=get_db(); cur=conn.cursor()
                try:
                    cur.execute("UPDATE daily_quests SET progress=0,completed=0,cycle_key=?,last_updated=?",(cycle,datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                    conn.commit()
                except Exception:
                    conn.rollback(); raise
                finally: conn.close()
            await run_sync_db(_reset)
        print(f"✅ Ежедневный цикл квестов обновлён: {cycle}")

@app.get("/poker/active/{tg_id}")
async def poker_active(tg_id: int):
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return JSONResponse({"error": "Player not found"}, status_code=404)

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id FROM poker_games WHERE player_id = ? AND status = "active"', (player_id,))
        row = cursor.fetchone()
        if row:
            return JSONResponse({'success': True, 'hasActiveGame': True, 'gameId': row['id']})
        else:
            return JSONResponse({'success': True, 'hasActiveGame': False})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()

@app.post("/claim-reward")
async def claim_reward(request: Request):
    try:
        data = await request.json()
        tg_id = data.get('userId') or data.get('user_id')
        reward_type = data.get('type')   # 'skin' или 'car'
        reward_id = data.get('id')
        if not tg_id or not reward_type or not reward_id:
            return JSONResponse({"success": False, "error": "Missing data"})
        player_id = await get_player_id_by_tg(int(tg_id))
        if not player_id:
            return JSONResponse({"success": False, "error": "Player not found"})
        async with db_lock:
            conn = get_db()
            cursor = conn.cursor()
            if reward_type == 'skin':
                # Проверяем существование скина
                skin = next((s for s in SKINS if s["id"] == reward_id), None)
                if not skin:
                    conn.close()
                    return JSONResponse({"success": False, "error": "Skin not found"})
                cursor.execute("SELECT 1 FROM skins WHERE player_id = ? AND skin_id = ?", (player_id, reward_id))
                if cursor.fetchone():
                    conn.close()
                    return JSONResponse({"success": False, "error": "Skin already owned"})
                cursor.execute("INSERT INTO skins (player_id, skin_id, equipped) VALUES (?, ?, 0)", (player_id, reward_id))
                conn.commit()
                conn.close()
                return JSONResponse({"success": True, "message": "Skin added"})
            elif reward_type == 'car':
                car = next((c for c in CARS if c["id"] == reward_id), None)
                if not car:
                    conn.close()
                    return JSONResponse({"success": False, "error": "Car not found"})
                cursor.execute("SELECT car_collection FROM players WHERE id = ?", (player_id,))
                row = cursor.fetchone()
                if not row:
                    conn.close()
                    return JSONResponse({"success": False, "error": "Player not found"})
                collection = json.loads(row['car_collection']) if row['car_collection'] else []
                if reward_id in collection:
                    conn.close()
                    return JSONResponse({"success": False, "error": "Car already owned"})
                collection.append(reward_id)
                cursor.execute("UPDATE players SET car_collection = ? WHERE id = ?", (json.dumps(collection), player_id))
                conn.commit()
                conn.close()
                return JSONResponse({"success": True, "message": "Car added"})
            else:
                conn.close()
                return JSONResponse({"success": False, "error": "Invalid reward type"})
    except Exception as e:
        print(f"Ошибка в /claim-reward: {e}")
        return JSONResponse({"success": False, "error": str(e)})

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, room_code: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(room_code, []).append(websocket)

    def disconnect(self, room_code: str, websocket: WebSocket):
        if room_code in self.active_connections:
            self.active_connections[room_code].remove(websocket)
            if not self.active_connections[room_code]:
                del self.active_connections[room_code]

    async def broadcast(self, room_code: str, message: str, exclude: WebSocket = None):
        if room_code not in self.active_connections:
            return
        for conn in self.active_connections[room_code]:
            if conn != exclude:
                try:
                    await conn.send_text(message)
                except:
                    pass

manager = ConnectionManager()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "web_app_data"])

def run_bot():
    asyncio.run(main())


# ==================== RESSELL V33 UNLOCK SNAPSHOT ====================
def _unlock_snapshot_sync(player_id:int)->dict:
    p=get_player_data(player_id) or {}
    epoch=get_epoch_state(p)
    sales=int(p.get("total_sales",0) or 0)
    thresholds=[10,25,50,100,250,500]
    reached=[x for x in thresholds if sales>=x]
    return {"total_sales":sales,"total_earned":int(p.get("total_earned",0) or 0),"epoch_current":int(epoch.get("current_epoch",1) or 1),"epoch_completed":list(epoch.get("completed_ids",[]) or []),"epoch_claimed":list(epoch.get("claimed_ids",[]) or []),"sales_reached":reached,"balance":int(p.get("balance",0) or 0)}

@app.get("/unlocks/{tg_id}")
async def unlock_snapshot(tg_id:int, request:Request):
    if not _verify_tycoon_webapp_request(request,tg_id): return JSONResponse({"success":False,"error":"Недействительная сессия Telegram"},status_code=401)
    pid=await get_player_id_by_tg(tg_id)
    if not pid: return JSONResponse({"success":False,"error":"Player not found"},status_code=404)
    return JSONResponse({"success":True,**(await run_sync_db(_unlock_snapshot_sync,pid))})

