# unified_bot.py - ПОЛНЫЙ СЕРВЕР + ТЕЛЕГРАМ БОТ ДЛЯ RESELL TYCOON
# Улучшенный интерфейс: страницы меню, разделение по категориям
# Все функции сохранены (гонки, скины, аукцион, трейдинг, таксопарк, разбор поставок, друзья, рефералы и т.д.)

import asyncio
import threading
import sqlite3
import json
import random
import hashlib
import time as time_module
import re
import aiohttp
import asyncio
import random
import time
import json
import threading
from pyngrok import ngrok
from aiohttp import web
from datetime import datetime
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

# --- Настройки для генерации краш-точки ---
# Вероятность того, что множитель не улетит далеко
CRASH_BASE = 0.9

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

API_TOKEN = os.getenv("BOT_TOKEN")
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
    {"id": "room", "name": "🏚 Комната в общаге", "price": 0, "income_bonus": 0, "description": "Бесплатное жильё.", "image_url": "AgACAgIAAxkBAAIYY2oTU26AUdnboAxd2xOOoa02oIo7AAL3ImsbWuiYSKh9uXShrqquAQADAgADeQADOwQ"},
    {"id": "flat", "name": "🏢 Квартира", "price": 10000, "income_bonus": 150, "description": "Уютная квартира. +150₽/день.", "image_url": "AgACAgIAAxkBAAIBeGn3hGvVcFktYFQJP-YNnKti48v1AAKYGWsbUNy4SzN3yqU-dPZwAQADAgADeQADOwQ"},
    {"id": "house", "name": "🏠 Одноэтажный дом", "price": 35000, "income_bonus": 400, "description": "Дом с гаражом. +400₽/день.", "image_url": "AgACAgIAAxkBAAIBemn3hKeq-IxdQ6l6jB7sD10pQPbHAAKUGGsbaAW5S4jG5ecluTqMAQADAgADeQADOwQ"},
    {"id": "villa", "name": "🏰 Богатая вилла", "price": 100000, "income_bonus": 1200, "description": "Вилла с бассейном. +1200₽/день.", "image_url": "AgACAgIAAxkBAAIBfGn3hME0a5rsH1wos1Qyy1AhsYAnAAKVGGsbaAW5SzyFR-E8--65AQADAgADeQADOwQ"},
    {"id": "yacht", "name": "🛥 Яхта", "price": 250000, "income_bonus": 3000, "description": "Яхта у причала. +3000₽/день.", "image_url": "AgACAgIAAxkBAAIBfmn3hNlqZXeSCAxLTetoN0kJMG4RAAKWGGsbaAW5SxNdXNthpgjFAQADAgADeQADOwQ"},
    {"id": "skyscraper", "name": "🏙 Небоскрёб", "price": 3000000, "income_bonus": 20000, "description": "Небоскрёб в центре города. +20 000₽/день.", "image_url": "AgACAgIAAxkBAAIOGGn80IpHo9UQDHb2EhlAp6cOqCp8AAItF2sb59XpS_EAAVDuV6ZpTwEAAwIAA3kAAzsE"},
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

TAXOPARK_LEVELS = [
    {"id": "none", "name": "Нет таксопарка", "price": 0, "slots": 0, "income_per_car": 0},
    {"id": "small", "name": "🚕 Маленький таксопарк", "price": 500000, "slots": 3, "income_per_car": 5000},
    {"id": "medium", "name": "🚖 Средний таксопарк", "price": 2000000, "slots": 7, "income_per_car": 8000},
    {"id": "large", "name": "🚗 Крупный таксопарк", "price": 10000000, "slots": 15, "income_per_car": 12000},
    {"id": "elite", "name": "👑 Элитный таксопарк", "price": 50000000, "slots": 30, "income_per_car": 20000},
]

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
    # старые события
    {"text": "📰 Хайп на джинсы!", "cat": "👖 Джинсы", "mult": 1.5},
    {"text": "📰 Куртки в цене!", "cat": "🧥 Куртки", "mult": 1.4},
    {"text": "📰 Кроссовки в тренде!", "cat": "👟 Кроссы", "mult": 1.5},
    {"text": "📰 Джинсы падают.", "cat": "👖 Джинсы", "mult": 0.6},
    # новые
    {"text": "🌧 Дождливая погода – продажи дождевиков и курток растут!", "cat": "🧥 Куртки", "mult": 1.3},
    {"text": "❄ Снегопад – спрос на тёплые куртки и обувь!", "cat": "🧥 Куртки", "mult": 1.4},
    {"text": "🔄 Обновление Авито – новые алгоритмы, комиссия снижена!", "cat": None, "mult": 1.2, "global": True},  # глобальный бонус
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
    "sell_3": {
        "name": "📦 Продавец дня",
        "description": "Продать 3 товара",
        "target": 3,
        "reward_money": 5_000,
    },
    "earn_50k": {
        "name": "💰 Прибыльный день",
        "description": "Заработать 50 000₽ за день (продажи + пассивный доход)",
        "target": 50_000,
        "reward_money": 10_000,
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
    "trade_win": {
        "name": "📈 Успешный трейдер",
        "description": "Выиграть в POCKET OPTION",
        "target": 1,
        "reward_money": 5_000,
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
}

TRADING_ITEMS = {
    "👖 Джинсы": {"name": "Джинсы", "base_price": 500, "volatility": 0.15},
    "👕 Футболки": {"name": "Футболки", "base_price": 300, "volatility": 0.12},
    "🧥 Куртки": {"name": "Куртки", "base_price": 800, "volatility": 0.18},
    "👟 Кроссовки": {"name": "Кроссовки", "base_price": 600, "volatility": 0.20},
    "🧢 Кепки": {"name": "Кепки", "base_price": 200, "volatility": 0.10},
}

MINING_RIGS = {
    "small": {"name": "🖥 Малая ферма", "price": 50000, "daily_income": 3000},
    "medium": {"name": "🖥🖥 Средняя ферма", "price": 200000, "daily_income": 15000},
    "large": {"name": "🖥🖥🖥 Крупная ферма", "price": 1000000, "daily_income": 100000},
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
supplier_stock = {"items": [], "last_update": 0}
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
pending_inviter = {}  # {user_id: inviter_id}
last_bot_message = {}
pending_messages = defaultdict(list)
supplier_lock = asyncio.Lock()
supply_drop_lock = asyncio.Lock()
active_mines_games = {}      # {user_id: game_data}
player_luck = {}
crash_active_bets = {}  # {player_id: {"amount": int, "crash_point": float, "timestamp": float}}
crash_active_bets = {}

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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
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
    
    # Таблица скинов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS skins (
            player_id INTEGER, skin_id TEXT, equipped INTEGER DEFAULT 0,
            PRIMARY KEY (player_id, skin_id)
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
    
    conn.commit()
    conn.close()

def upgrade_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
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
    cursor.execute("PRAGMA table_info(user_taxoparks)")
    cols_tax = [c[1] for c in cursor.fetchall()]
    if "purchase_price" not in cols_tax:
        cursor.execute("ALTER TABLE user_taxoparks ADD COLUMN purchase_price INTEGER DEFAULT 0")
    
    # Таблица для таксопарков (если не существует)
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
    
    # Добавляем колонку casino_balance (для баланса казино)
    if "casino_balance" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_balance INTEGER DEFAULT 0")

    # Статистика казино для игроков
    if "casino_games_played" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_games_played INTEGER DEFAULT 0")
    if "casino_total_bet" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_total_bet INTEGER DEFAULT 0")
    if "casino_total_win" not in existing_cols:
        cursor.execute("ALTER TABLE players ADD COLUMN casino_total_win INTEGER DEFAULT 0")
    
    # --- Статистика казино (победы/поражения) ---
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
    conn = sqlite3.connect(DB_PATH, timeout=60)  # увеличен таймаут
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=60000")   # ждать до 60 секунд при блокировке
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
    cursor.execute(f"INSERT INTO players ({field}, nickname, shop_name) VALUES (?, ?, ?)",
                   (platform_id, nickname, "Моя лавка"))
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
        for field in ['inventory', 'car_collection', 'taxopark', 'market_demand', 'skin_inventory', 'trading_portfolio']:
            if field in data and data[field]:
                try:
                    data[field] = json.loads(data[field])
                except:
                    pass
        return data
    return None

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

def update_player_data(player_id: int, data: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    fields = []
    values = []
    for key, value in data.items():
        fields.append(f"{key} = ?")
        if isinstance(value, (list, dict)):
            values.append(json.dumps(value, ensure_ascii=False))
        else:
            values.append(value)
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

def check_and_update_achievement(player_id: int, achievement_id: str, current_value: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT progress, completed FROM achievements WHERE player_id = ? AND achievement_id = ?", (player_id, achievement_id))
    row = cursor.fetchone()
    if row and row["completed"]:
        conn.close()
        return None
    progress = row["progress"] if row else 0
    target = ACHIEVEMENTS[achievement_id]["target"]
    if current_value > progress:
        progress = min(current_value, target)
        cursor.execute("INSERT OR REPLACE INTO achievements (player_id, achievement_id, progress, completed, completed_at) VALUES (?, ?, ?, ?, ?)",
                       (player_id, achievement_id, progress, 1 if progress >= target else 0,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S") if progress >= target else None))
        conn.commit()
        if progress >= target and (not row or not row["completed"]):
            reward = ACHIEVEMENTS[achievement_id]["reward_money"]
            player = get_player_data(player_id)      # синхронный вызов
            if player:
                new_balance = player["balance"] + reward
                update_player_data(player_id, {"balance": new_balance})  # синхронный вызов
                conn.close()
                return {"achievement": achievement_id, "reward": reward, "balance": new_balance}
    conn.close()
    return None

def update_daily_quest(player_id: int, quest_id: str, increment: int = 1):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT progress, completed, last_updated FROM daily_quests WHERE player_id = ? AND quest_id = ?", (player_id, quest_id))
    row = cursor.fetchone()
    today = datetime.now().date().isoformat()
    if row and row["last_updated"] and row["last_updated"].split()[0] != today:
        progress = 0
        completed = 0
    else:
        progress = row["progress"] if row else 0
        completed = row["completed"] if row else 0
    if completed:
        conn.close()
        return None
    target = DAILY_QUESTS[quest_id]["target"]
    new_progress = min(progress + increment, target)
    completed_flag = 1 if new_progress >= target else 0
    cursor.execute("INSERT OR REPLACE INTO daily_quests (player_id, quest_id, progress, completed, last_updated) VALUES (?, ?, ?, ?, ?)",
                   (player_id, quest_id, new_progress, completed_flag, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    if completed_flag == 1 and (row is None or not row["completed"]):
        reward = DAILY_QUESTS[quest_id]["reward_money"]
        player = get_player_data(player_id)      # синхронный вызов
        if player:
            new_balance = player["balance"] + reward
            update_player_data(player_id, {"balance": new_balance})  # синхронный вызов
            return {"quest": quest_id, "reward": reward, "balance": new_balance}
    return None

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
    cursor.execute("SELECT skin_id, equipped FROM skins WHERE player_id = ?", (player_id,))
    rows = cursor.fetchall()
    conn.close()
    skins = []
    for row in rows:
        skin_info = next((s for s in SKINS if s["id"] == row['skin_id']), None)
        if skin_info:
            skins.append({"id": row['skin_id'], "name": skin_info["name"], "emoji": skin_info["emoji"], "equipped": bool(row['equipped'])})
    return skins

def equip_skin(player_id: int, skin_id: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE skins SET equipped = 0 WHERE player_id = ?", (player_id,))
        cursor.execute("UPDATE skins SET equipped = 1 WHERE player_id = ? AND skin_id = ?", (player_id, skin_id))
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
def generate_supplier_items():
    # Без блокировки – вызывается только из check_supplier_update, который уже находится внутри блокировки
    items = []
    for _ in range(random.randint(6, 10)):
        rarities = list(SUPPLIER_ITEM_RARITIES.keys())
        weights = [SUPPLIER_ITEM_RARITIES[r]["chance"] for r in rarities]
        rarity = random.choices(rarities, weights=weights, k=1)[0]
        rd = SUPPLIER_ITEM_RARITIES[rarity]
        base = random.choice(BASE_ITEMS)
        mp = int(base["base_price"] * random.uniform(rd["price_mult_min"], rd["price_mult_max"]))
        bp = int(mp * random.uniform(0.6, 0.85))
        items.append({
            "id": random.randint(10000, 99999),
            "name": f"{rd['color']} {base['cat']} {base['name']}",
            "cat": base["cat"],
            "buy_price": bp,
            "market_price": mp,
            "rarity": rarity,
            "rarity_color": rd["color"],
            "end_time": time_module.time() + random.randint(300, 900)
        })
    supplier_stock["items"] = items
    supplier_stock["last_update"] = time_module.time()

def check_supplier_update():
    # Без блокировки – вызывается только из контекста, где supplier_lock уже захвачен
    if time_module.time() - supplier_stock.get("last_update", 0) >= 300 or not supplier_stock.get("items"):
        generate_supplier_items()
        return True
    if supplier_stock.get("items"):
        supplier_stock["items"] = [i for i in supplier_stock["items"] if i["end_time"] > time_module.time()]
    return False

async def get_supplier_items():
    # Без блокировки – вызывающий должен обеспечить синхронизацию
    check_supplier_update()
    return supplier_stock.get("items", [])

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

async def fetch_stock_price(symbol: str):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    quote = data.get("Global Quote", {})
                    price_str = quote.get("05. price")
                    change_pct_str = quote.get("10. change percent", "0%")
                    if price_str:
                        price_usd = float(price_str)
                        usd_rate = await get_usd_rub_rate()
                        price_rub = int(price_usd * usd_rate)
                        change_pct = float(change_pct_str.replace("%", ""))
                        return price_rub, change_pct
    except Exception as e:
        print(f"Ошибка получения цены {symbol}: {e}")
    return None, None

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
async def start_chat_for_item(seller_id: int, buyer_id: int, item: dict, pub: dict) -> dict:
    async with chats_lock:
        for key, chat in active_chats.items():
            if chat.get("user_id") == seller_id and not chat.get("finished") and chat.get("item") == item["name"]:
                return {"success": False, "message": "Чат уже существует"}
        client_type = random.choices(["normal", "skeptic", "trader"], weights=[60, 25, 15], k=1)[0]
        price = item["market_price"]
        if client_type == "trader":
            discount = random.uniform(0.7, 0.9)
            offer = int(price * discount)
            offer = (offer // 100) * 100 + 99
            if offer < 100:
                offer = price // 2
        else:
            offer = price
        client = CLIENT_TYPES[client_type]
        msg = random.choice(client["phrases"]["greet"]).format(item=item["name"], price=price, offer=offer)
        chat_key = f"{seller_id}_{buyer_id}_{int(time_module.time())}"
        active_chats[chat_key] = {
            "user_id": seller_id, "buyer_id": buyer_id, "client_type": client_type,
            "item": item["name"], "price": price, "offer": offer,
            "round": 1, "max_rounds": client["max_rounds"], "finished": False,
            "phase": 1,
            "trust": 50,
            "history": [{"role": "assistant", "content": msg}],
            "chat_key": chat_key, "item_obj": item,   # <-- ЗДЕСЬ ДОЛЖНА БЫТЬ ЗАПЯТАЯ!
            "created_at": time_module.time()
        }
        return {"success": True, "message": msg, "buyer_id": buyer_id, "offer": offer, "chat_key": chat_key}

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

def daily_event():
    if random.random() < 0.6:
        return random.choice(MARKET_EVENTS)
    return None

def apply_event(player: Dict[str, Any], event: Dict[str, Any]):
    if event and event.get("cat"):
        market_demand = player.get("market_demand", {})
        if event["cat"] in market_demand:
            market_demand[event["cat"]] = max(0.3, min(3.0, market_demand[event["cat"]] * event["mult"]))
            update_player_data(player["id"], {"market_demand": market_demand})

def fmt_demand(player: Dict[str, Any]) -> str:
    market_demand = player.get("market_demand", {})
    lines = []
    for cat, mult in market_demand.items():
        if mult >= 1.5:
            emoji = "🔥"
        elif mult >= 1.2:
            emoji = "📈"
        elif mult >= 0.8:
            emoji = "➡️"
        elif mult >= 0.5:
            emoji = "📉"
        else:
            emoji = "💀"
        lines.append(f"{emoji} {cat}: x{mult:.1f}")
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

def get_hourly_income(player_id: int):
    player = get_player_data(player_id)   # синхронный вызов
    if not player:
        return 0, {}
    house_id = player.get("house", "room")
    house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
    house_income_per_hour = house["income_bonus"] // 24
    car_id = player.get("current_car", "none")
    car = next((c for c in CARS if c["id"] == car_id), None)
    car_income_per_hour = car["income_per_hour"] if car else 0
    taxopark = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark.get("level")), TAXOPARK_LEVELS[0])
    taxopark_income_per_hour = taxopark_level["income_per_car"] * len(taxopark.get("cars", []))
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
    shop_rows = cursor.fetchall()
    conn.close()
    shops_income_per_hour = 0
    for row in shop_rows:
        shop = next((s for s in SHOP_LEVELS if s["id"] == row["shop_id"]), None)
        if shop:
            shops_income_per_hour += shop["income_per_hour"]
    
    breakdown = {
        "house": house_income_per_hour,
        "car": car_income_per_hour,
        "taxopark": taxopark_income_per_hour,
        "shops": shops_income_per_hour
    }
    total = sum(breakdown.values())
    return total, breakdown

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

async def pay_shop_maintenance(player_id: int, shop_id: str, shop_price: int):
    def _sync():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, last_payment, paid_until FROM user_shops "
            "WHERE player_id = ? AND shop_id = ? AND status = 'active'",
            (player_id, shop_id)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Магазин не найден или уже изъят."
        now = int(time_module.time())
        cost = get_maintenance_cost_shop(shop_price)
        conn2 = get_db()
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT balance FROM players WHERE id = ?", (player_id,))
        bal_row = cursor2.fetchone()
        if not bal_row or bal_row['balance'] < cost:
            conn2.close()
            conn.close()
            return False, f"Недостаточно средств! Нужно {cost}₽."
        new_balance = bal_row['balance'] - cost
        new_paid_until = max(now, row['paid_until']) + 30 * 86400
        cursor.execute(
            "UPDATE user_shops SET last_payment = ?, paid_until = ? WHERE id = ?",
            (now, new_paid_until, row['id'])
        )
        cursor2.execute("UPDATE players SET balance = ? WHERE id = ?", (new_balance, player_id))
        conn.commit()
        conn2.commit()
        conn.close()
        conn2.close()
        return True, f"Обслуживание оплачено на 30 дней. Списано {cost}₽."
    
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
    def _sync():
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, last_payment, paid_until FROM user_taxoparks "
            "WHERE player_id = ? AND level_id = ? AND status = 'active'",
            (player_id, level_id)
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return False, "Таксопарк не найден или изъят."
        now = int(time_module.time())
        cost = get_maintenance_cost_taxopark(price)
        conn2 = get_db()
        cursor2 = conn2.cursor()
        cursor2.execute("SELECT balance FROM players WHERE id = ?", (player_id,))
        bal_row = cursor2.fetchone()
        if not bal_row or bal_row['balance'] < cost:
            conn2.close()
            conn.close()
            return False, f"Недостаточно средств! Нужно {cost}₽."
        new_balance = bal_row['balance'] - cost
        new_paid_until = max(now, row['paid_until']) + 30 * 86400
        cursor.execute(
            "UPDATE user_taxoparks SET last_payment = ?, paid_until = ? WHERE id = ?",
            (now, new_paid_until, row['id'])
        )
        cursor2.execute("UPDATE players SET balance = ? WHERE id = ?", (new_balance, player_id))
        conn.commit()
        conn2.commit()
        conn.close()
        conn2.close()
        return True, f"Обслуживание таксопарка оплачено на 30 дней. Списано {cost}₽."
    
    return await run_sync_db(_sync)

async def get_pending_income(player_id: int):
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return 0, 0, {}
    now = int(time_module.time())
    last = player.get("last_income_collect", 0)
    if last == 0:
        await run_sync_db(update_player_data, player_id, {"last_income_collect": now})
        return 0, 0, {}
    hourly, breakdown = await run_sync_db(get_hourly_income, player_id)
    if hourly <= 0:
        return 0, hourly, breakdown
    diff_seconds = now - last
    hours_passed = diff_seconds / 3600
    pending = int(hourly * hours_passed)
    pending_breakdown = {src: int(val * hours_passed) for src, val in breakdown.items()}
    return pending, hourly, pending_breakdown

async def collect_pending_income(player_id: int):
    pending, hourly, breakdown = await get_pending_income(player_id)
    if pending <= 0:
        return 0, hourly, {}
    async with db_lock:
        await add_income(player_id, pending, source="passive")
        now = int(time_module.time())
        await run_sync_db(update_player_data, player_id, {"last_income_collect": now})
    return pending, hourly, breakdown

def get_rep_level(sales: int) -> str:
    if sales == 0: return "🆕 Новичок"
    elif sales < 5: return "🔰 Начинающий"
    elif sales < 15: return "⭐ Проверенный"
    elif sales < 50: return "🏅 Надёжный"
    elif sales < 100: return "👑 Профессионал"
    elif sales < 250: return "💎 Легенда"
    else: return "🌟 Бог Авито"

def gen_ref(user_id):
    return hashlib.md5(str(user_id).encode()).hexdigest()[:8]

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

async def collect_income(player: Dict[str, Any]) -> int:
    house_id = player.get("house", "room")
    house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
    house_income = house["income_bonus"]
    shop_level_id = player.get("shop_level", "none")
    shop_level = next((s for s in SHOP_LEVELS if s["id"] == shop_level_id), SHOP_LEVELS[0])
    shop_income = shop_level["income_per_hour"]
    car_id = player.get("current_car", "none")
    car = next((c for c in CARS if c["id"] == car_id), None)
    car_income = car["income_per_hour"] if car and car["income_per_hour"] > 0 else 0
    taxopark_data = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark_data.get("level")), TAXOPARK_LEVELS[0])
    taxopark_income = taxopark_level["income_per_car"] * len(taxopark_data.get("cars", []))
    total_income = house_income + shop_income + car_income + taxopark_income
    if total_income > 0:
        balance = player.get("balance", 0)
        async with db_lock:
            await run_sync_db(update_player_data, player["id"], {"balance": balance + total_income})
    return total_income

async def collect_daily_income(player_id: int) -> Tuple[int, int]:
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return 0, 0
    now = int(time_module.time())
    last = player.get("last_daily_collect", 0)
    if last == 0:
        await run_sync_db(update_player_data, player_id, {"last_daily_collect": now})
        return 0, 0
    days_passed = (now - last) // 86400
    if days_passed <= 0:
        return 0, 0
    # ... расчёт дохода (без изменений, но используйте синхронные вызовы внутри)
    house_id = player.get("house", "room")
    house = next((h for h in HOUSES if h["id"] == house_id), HOUSES[0])
    house_income = house["income_bonus"]
    shop_level_id = player.get("shop_level", "none")
    shop = next((s for s in SHOP_LEVELS if s["id"] == shop_level_id), SHOP_LEVELS[0])
    shop_income = shop["income_per_hour"] * 24
    car_id = player.get("current_car", "none")
    car = next((c for c in CARS if c["id"] == car_id), None)
    car_income = car["income_per_hour"] * 24 if car else 0
    taxopark_data = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark_data.get("level")), TAXOPARK_LEVELS[0])
    taxopark_income = taxopark_level["income_per_car"] * 24 * len(taxopark_data.get("cars", []))
    daily_income = house_income + shop_income + car_income + taxopark_income
    total_income = daily_income * days_passed

    await add_income(player_id, total_income, source="passive")
    async with db_lock:
        await run_sync_db(update_player_data, player_id, {"last_daily_collect": now, "day": player.get("day", 1) + days_passed})
    return days_passed, total_income

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================
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
        cursor.execute("SELECT player_id, daily_income FROM mining_rigs WHERE status = 'active'")
        rigs = cursor.fetchall()
        for rig in rigs:
            hourly = rig['daily_income'] // 24
            cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (hourly, rig['player_id']))
        conn.commit()
        conn.close()
    while True:
        await asyncio.sleep(3600)
        async with db_lock:
            await asyncio.to_thread(_sync_mining)

async def check_business_expiry():
    def _sync_business():
        conn = get_db()
        cursor = conn.cursor()
        now = int(time_module.time())
        # Магазины – изъятие, если paid_until < now
        cursor.execute(
            "SELECT id, player_id, shop_id, purchase_price, paid_until FROM user_shops "
            "WHERE status = 'active' AND paid_until > 0 AND ? > paid_until",
            (now,)
        )
        expired_shops = cursor.fetchall()
        for row in expired_shops:
            cursor.execute("UPDATE user_shops SET status = 'seized' WHERE id = ?", (row['id'],))
            refund = int(row['purchase_price'] * 0.7)
            cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (refund, row['player_id']))
        # Таксопарки
        cursor.execute(
            "SELECT id, player_id, level_id, purchase_price, paid_until FROM user_taxoparks "
            "WHERE status = 'active' AND paid_until > 0 AND ? > paid_until",
            (now,)
        )
        expired_taxoparks = cursor.fetchall()
        for row in expired_taxoparks:
            cursor.execute("UPDATE user_taxoparks SET status = 'seized' WHERE id = ?", (row['id'],))
            refund = int(row['purchase_price'] * 0.7)
            cursor.execute("UPDATE players SET balance = balance + ? WHERE id = ?", (refund, row['player_id']))
        conn.commit()
        conn.close()
        return expired_shops, expired_taxoparks
    while True:
        await asyncio.sleep(86400)
        async with db_lock:
            expired_shops, expired_taxoparks = await asyncio.to_thread(_sync_business)
        for row in expired_shops:
            player = await run_sync_db(get_player_data, row['player_id'])
            if player and player.get('tg_id'):
                await bot.send_message(player['tg_id'], f"⚠️ Ваш магазин «{row['shop_id']}» изъят государством за неуплату. Возвращено {int(row['purchase_price'] * 0.7)}₽.")
        for row in expired_taxoparks:
            player = await run_sync_db(get_player_data, row['player_id'])
            if player and player.get('tg_id'):
                await bot.send_message(player['tg_id'], f"⚠️ Ваш таксопарк «{row['level_id']}» изъят за неуплату. Возвращено {int(row['purchase_price'] * 0.7)}₽.")

async def auction_loop():
    while True:
        await asyncio.sleep(60)
        now = time_module.time()
        async with auction_lock:
            for i, lot in enumerate(auction_items[:]):
                if lot.get("active", True) and lot["end_time"] <= now:
                    lot["active"] = False
                    if lot["bidder_id"]:
                        winner = await run_sync_db(get_player_data, lot["bidder_id"])
                        if winner:
                            inv = winner.get("inventory", [])
                            inv.append(lot["item"])
                            await run_sync_db(update_player_data, lot["bidder_id"], {"inventory": inv})
                            try:
                                winner_tg = winner.get("tg_id")
                                if winner_tg:
                                    await bot.send_message(winner_tg, f"🎉 Вы выиграли аукцион! Товар {lot['item']['name']} добавлен в инвентарь.")
                            except:
                                pass
                    seller = await run_sync_db(get_player_data, lot["seller_id"])
                    if seller:
                        # Добавляем блокировку БД
                        async with db_lock:
                            await run_sync_db(update_player_data, lot["seller_id"], {"balance": seller.get("balance", 0) + lot["current_bid"]})
                        try:
                            seller_tg = seller.get("tg_id")
                            if seller_tg:
                                await bot.send_message(seller_tg, f"💰 Ваш лот {lot['item']['name']} продан на аукционе за {lot['current_bid']}₽!")
                        except:
                            pass
                    auction_items.pop(i)

async def handle_action(action: PlayerAction):
    player_id = await run_sync_db(get_or_create_player, action.platform, action.platform_id)
    player = await run_sync_db(get_player_data, player_id)
    if not player:
        return {"success": False, "message": "Player not found"}
    
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
  
    elif action == "crash_bet":
        try:
            amount = data.get("amount", 0)
            if amount < 10 or amount > 5000:
                return

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return

            if player.get("casino_balance", 0) < amount:
                return

            async with db_lock:
                new_casino = player["casino_balance"] - amount
                await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в crash_bet: {e}")
        return

    elif action == "crash_cashout":
        try:
            multiplier = data.get("multiplier", 1.0)
            win_amount = data.get("win_amount", 0)
            if win_amount <= 0:
                return

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return

            async with db_lock:
                new_casino = player["casino_balance"] + win_amount
                await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в crash_cashout: {e}")
        return

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
        income = await collect_income(player)
        day = player.get("day", 1)
        new_day = day + 1
        
        market_demand = player.get("market_demand", {})
        for cat in CATEGORIES:
            if cat in market_demand:
                market_demand[cat] = max(0.3, min(3.0, market_demand[cat] * random.uniform(0.85, 1.15)))
        
        event = daily_event()
        if event and event.get("cat") and event["cat"] in market_demand:
            market_demand[event["cat"]] = max(0.3, min(3.0, market_demand[event["cat"]] * event["mult"]))
        
        inventory = player.get("inventory", [])
        if inventory and random.random() < 0.2:
            for item in inventory:
                item["market_price"] = int(item["market_price"] * random.uniform(0.7, 0.95))
        
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {
                "day": new_day,
                "market_demand": market_demand,
                "inventory": inventory,
                "current_event": event
            })
        
        player = await run_sync_db(get_player_data, player_id)
        return {
            "success": True,
            "message": f"День {new_day}, доход: {income}₽",
            "day": new_day,
            "balance": player.get("balance", 0),
            "income": income
        }
    
    elif action.action == "get_demand":
        market_demand = player.get("market_demand", {})
        return {"success": True, "demand": market_demand, "formatted": fmt_demand(player)}
    
    # ---------- ПОСТАВЩИКИ ----------
    elif action.action == "get_suppliers":
        async with supplier_lock:
            items = await get_supplier_items()
        return {"success": True, "suppliers": items}
    
    elif action.action == "buy_from_supplier":
        item_id = action.data.get("item_id")
        async with supplier_lock:
            check_supplier_update()
            items = supplier_stock.get("items", [])
            item = next((i for i in items if i["id"] == item_id), None)
            if not item:
                return {"success": False, "message": "Товар уже купили или время истекло!"}
            balance = player.get("balance", 0)
            if balance < item["buy_price"]:
                return {"success": False, "message": f"❌ Недостаточно денег! Нужно {item['buy_price']}₽"}
            inventory = player.get("inventory", [])
            inventory.append({
                "name": item["name"],
                "cat": item["cat"],
                "buy_price": item["buy_price"],
                "market_price": item["market_price"]
            })
            async with db_lock:
                await run_sync_db(update_player_data, player_id, {
                    "balance": balance - item["buy_price"],
                    "inventory": inventory
                })
            supplier_stock["items"] = [i for i in supplier_stock["items"] if i["id"] != item_id]
        return {"success": True, "message": f"✅ Куплен {item['name']} за {item['buy_price']}₽", "balance": balance - item["buy_price"]}

    # ---------- ИНВЕНТАРЬ ----------
    elif action.action == "get_inventory":
        return {"success": True, "inventory": player.get("inventory", [])}
    
    elif action.action == "publish_item":
        item_idx = action.data.get("item_idx")
        description = action.data.get("description", "")
        inventory = player.get("inventory", [])
        if item_idx >= len(inventory):
            return {"success": False, "message": "Товар не найден"}
        item = inventory[item_idx]
        quality = rate_description(description)
        quality_bonus = get_quality_bonus(quality)
        async with published_lock:
            published_items[player_id] = {
                "item": item.copy(),
                "description": description,
                "quality": quality,
                "created_at": time_module.time()
            }
        buyer_id = random.randint(10000, 99999)
        result = await start_chat_for_item(player_id, buyer_id, item, published_items[player_id])
        return {
            "success": True,
            "message": f"📢 ОПУБЛИКОВАНО!\n📦 {item['name']}\n💰 {item['market_price']}₽\n📝 Качество: {quality_bonus['name']} ({quality}/10)\n⏳ Покупатель уже написал!\n\n{result.get('message', '')}",
            "buyer_id": buyer_id,
            "chat_key": result.get("chat_key")
        }
    
    elif action.action == "get_published_item":
        pub = published_items.get(player_id)
        if not pub:
            return {"success": False, "message": "Нет активных объявлений"}
        return {"success": True, "item": pub["item"], "quality": pub.get("quality", 0)}
    
    elif action.action == "unpublish_item":
        async with published_lock:
            if player_id in published_items:
                del published_items[player_id]
        return {"success": True, "message": "Объявление снято с публикации"}
    
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
            car_collection = player.get("car_collection", [])
            car_collection.append(car_id)
            new_balance = balance - car["price"]
            # ⬇️ ЗАМЕНА: update_player_data → await run_sync_db
            await run_sync_db(update_player_data, player_id, {"balance": new_balance, "car_collection": car_collection})
            
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
            # Вставка
            cursor.execute(
                "INSERT INTO user_shops (player_id, shop_id, purchase_price) VALUES (?, ?, ?)",
                (player_id, shop_id, shop["price"])
            )
            # Обновление баланса
            cursor.execute("UPDATE players SET balance = balance - ? WHERE id = ?", (shop["price"], player_id))
            conn.commit()
            # Получение общего количества
            cursor.execute("SELECT COUNT(*) as cnt FROM user_shops WHERE player_id = ?", (player_id,))
            total_shops = cursor.fetchone()["cnt"]
            # Получение типов
            cursor.execute("SELECT DISTINCT shop_id FROM user_shops WHERE player_id = ?", (player_id,))
            owned = {row["shop_id"] for row in cursor.fetchall()}
            conn.close()
            return True, {"total_shops": total_shops, "owned": owned, "new_balance": balance - shop["price"]}

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
            await run_sync_db(update_player_data, player_id, {"balance": balance - level["price"], "taxopark": {"level": level_id, "cars": taxopark.get("cars", [])}})
            # Добавляем запись в user_taxoparks
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_taxoparks (player_id, level_id, purchase_price, last_payment) VALUES (?, ?, ?, ?)",
                (player_id, level_id, level["price"], int(time_module.time()))
            )
            conn.commit()
            conn.close()
        return {"success": True, "message": f"✅ {level['name']} куплен!", "balance": balance - level["price"]}
    
    elif action.action == "add_car_to_taxopark":
        car_id = action.data.get("car_id")
        taxopark = player.get("taxopark", {"level": "none", "cars": []})
        level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark.get("level")), TAXOPARK_LEVELS[0])
        if level["slots"] == 0:
            return {"success": False, "message": "Купите таксопарк сначала!"}
        if len(taxopark.get("cars", [])) >= level["slots"]:
            return {"success": False, "message": f"Нет мест! Максимум {level['slots']} авто."}
        car_collection = player.get("car_collection", [])
        total_owned = car_collection.count(car_id)
        in_park = taxopark.get("cars", []).count(car_id)
        if in_park >= total_owned:
            return {"success": False, "message": "Купите ещё такую машину в автосалоне!"}
        if level["id"] == "elite":
            car = next((c for c in CARS if c["id"] == car_id), None)
            if car and car["price"] < 500000:
                return {"success": False, "message": "Элитный таксопарк — только премиум-авто (от 500 000₽)!"}
        async with db_lock:
            cars = taxopark.get("cars", [])
            cars.append(car_id)
            await run_sync_db(update_player_data, player_id, {"taxopark": {"level": taxopark.get("level"), "cars": cars}})
        return {"success": True, "message": "✅ Машина добавлена в таксопарк!"}
    
    elif action.action == "remove_car_from_taxopark":
        car_id = action.data.get("car_id")
        taxopark = player.get("taxopark", {"level": "none", "cars": []})
        async with db_lock:
            cars = taxopark.get("cars", [])
            if car_id not in cars:
                return {"success": False, "message": "Этой машины нет в таксопарке"}
            cars.remove(car_id)
            await run_sync_db(update_player_data, player_id, {"taxopark": {"level": taxopark.get("level"), "cars": cars}})
        return {"success": True, "message": "✅ Машина убрана из таксопарка"}
    
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
                if skin["price"] > 0:
                    cursor.execute("UPDATE players SET balance = ? WHERE id = ?", (balance - skin["price"], player_id))
                cursor.execute("INSERT OR IGNORE INTO skins (player_id, skin_id, equipped) VALUES (?, ?, 0)", (player_id, skin_id))
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
        skin = next((s for s in SKINS if s["id"] == skin_id), None)
        if not skin:
            return {"success": False, "message": "Скин не найден"}
        # Проверяем, есть ли скин у игрока
        player_skins = await run_sync_db(get_skins, player_id)
        if skin_id not in [s["id"] for s in player_skins]:
            return {"success": False, "message": "У вас нет этого скина"}
        # Экипируем
        await run_sync_db(equip_skin, player_id, skin_id)
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
            await run_sync_db(update_player_data, player_id, {"balance": balance - race["bet"]})
        async with races_lock:
            race = active_races[race_id]  # повторно получаем на случай изменений
            if race["status"] != "wait":  # повторная проверка
                # возврат денег? лучше вернуть
                async with db_lock:
                    await run_sync_db(update_player_data, player_id, {"balance": balance})
                return {"success": False, "message": "Гонка уже началась!"}
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
        to_player_id = action.data.get("to_player_id")
        amount = action.data.get("amount", 0)
        if amount < 100:
            return {"success": False, "message": "Минимальная сумма перевода: 100₽"}
        balance = player.get("balance", 0)
        if balance < amount:
            return {"success": False, "message": f"Недостаточно денег! У вас: {balance}₽"}
        to_player = await run_sync_db(get_player_data, to_player_id)
        if not to_player:
            return {"success": False, "message": "Получатель не найден"}
        async with db_lock:
            await run_sync_db(update_player_data, player_id, {"balance": balance - amount})
            await run_sync_db(update_player_data, to_player_id, {"balance": to_player.get("balance", 0) + amount})
        return {"success": True, "message": f"✅ Переведено {amount}₽", "balance": balance - amount}
    
    # ---------- АУКЦИОН ----------
    elif action.action == "get_auction_items":
        async with auction_lock:
            active_items = [item for item in auction_items if item.get("active", True)]
        return {"success": True, "auction_items": active_items}
    
    elif action.action == "add_auction_item":
        item_idx = action.data.get("item_idx")
        start_price = action.data.get("start_price", 0)
        inventory = player.get("inventory", [])
        if item_idx >= len(inventory):
            return {"success": False, "message": "Товар не найден"}
        async with db_lock:
            item = inventory.pop(item_idx)
            await run_sync_db(update_player_data, player_id, {"inventory": inventory})
        async with auction_lock:
            auction_items.append({
                "seller_id": player_id,
                "item": item,
                "start_price": start_price if start_price > 0 else item["market_price"],
                "current_bid": start_price if start_price > 0 else item["market_price"],
                "bidder_id": None,
                "end_time": time_module.time() + 3600,
                "active": True
            })
        return {"success": True, "message": "✅ Лот выставлен на аукцион!"}
    
    elif action.action == "bid_auction":
        async with db_lock:
            item_index = action.data.get("item_index")
            bid = action.data.get("bid", 0)
            if item_index >= len(auction_items):
                return {"success": False, "message": "Лот не найден"}
            async with auction_lock:
                item = auction_items[item_index]
                if not item.get("active", True):
                    return {"success": False, "message": "Этот лот уже завершён"}
                if item["seller_id"] == player_id:
                    return {"success": False, "message": "Нельзя ставить на свой лот!"}
                min_bid = int(item["current_bid"] * 1.1)
                if bid < min_bid:
                    return {"success": False, "message": f"Минимальная ставка: {min_bid}₽"}
                balance = player.get("balance", 0)
                if balance < bid:
                    return {"success": False, "message": f"Недостаточно денег! Нужно {bid}₽"}
                if item["bidder_id"]:
                    prev_bidder = item["bidder_id"]
                    prev_player = await run_sync_db(get_player_data, prev_bidder)  # <-- ИСПРАВЛЕНО
                    if prev_player:
                        await run_sync_db(update_player_data, prev_bidder, {"balance": prev_player.get("balance", 0) + item["current_bid"]})  # <-- ИСПРАВЛЕНО
                await run_sync_db(update_player_data, player_id, {"balance": balance - bid})  # <-- ИСПРАВЛЕНО
                item["current_bid"] = bid
                item["bidder_id"] = player_id
                return {"success": True, "message": f"✅ Ставка {bid}₽ принята!", "balance": balance - bid}
    
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
                    "shops_count": 0,
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
            [InlineKeyboardButton(text="🎮 МИНИ-ИГРЫ", callback_data="minigames_menu", style=ButtonStyle.PRIMARY)],  # <-- кнопка здесь
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
def get_chat_keyboard(chat: dict) -> InlineKeyboardMarkup:
    phase = chat.get("phase", 1)
    client_type = chat.get("client_type", "normal")
    price = chat.get("price", 0)
    
    # Фразы для КНОПОК продавца (что он может ответить)
    phrases_db = {
        1: {  # Приветствие
            "normal": ["Здравствуйте!", "Добрый день!", "Приветствую!"],
            "skeptic": ["Здравствуйте, давайте обсудим цену", "Добрый день, цена обсуждаема", "Привет, могу предложить скидку"],
            "trader": ["Здравствуйте, давайте торговаться", "Привет, сделайте встречное предложение", "Добрый день, готов к торгу"]
        },
        2: {  # Вопрос о состоянии
            "normal": ["Отличное состояние", "Хорошее, как новое", "Есть мелкие нюансы, но цена низкая"],
            "skeptic": ["Почти идеальное", "Нормальное, без дефектов", "Требует внимания, но дешёво"],
            "trader": ["Отличное, могу показать фото", "Хорошее, скидку дадите?", "Состояние на 4 из 5"]
        },
        3: {  # Вопрос о доставке
            "normal": ["Быстрая доставка", "Можем встретиться в центре", "Отправлю почтой за 1-2 дня"],
            "skeptic": ["Доставка за мой счёт", "Самовывоз из метро", "Перешлю СДЭКом"],
            "trader": ["Доставка бесплатно при покупке", "Встретимся у метро", "Отправлю сегодня"]
        },
        4: {  # Причина продажи
            "normal": ["Новое купил, это лишнее", "Не подошло по размеру", "Просто продаю"],
            "skeptic": ["Не пользуюсь, лежит без дела", "Деньги нужны срочно", "Надоело, хочу обновить"],
            "trader": ["Закупка новая, отдаю по закупке", "Лишнее из гардероба", "Хочу обновить коллекцию"]
        },
        5: {  # Финальный торг
            "normal": ["✅ Согласен на вашу цену", "💰 Давайте {price}₽", "🚫 Отказываюсь от сделки"],
            "skeptic": ["Хорошо, убедили – беру!", "Давайте по {price}₽, идёт?", "Дорого, ищу другое"],
            "trader": ["За {offer}₽ забираю", "Могу предложить {counter}₽", "Нет, не пойдёт"]
        }
    }
    
    if phase not in phrases_db:
        phase = 5
    
    phrases = phrases_db[phase].get(client_type, phrases_db[phase]["normal"])
    random.shuffle(phrases)
    
    # Для финального этапа подставляем цену и предложение в текст кнопок
    if phase == 5:
        offer_price = chat.get('offer', price)
        formatted_phrases = []
        for text in phrases:
            text = text.replace('{price}', str(price))
            text = text.replace('{offer}', str(offer_price))
            text = text.replace('{counter}', str(price))
            formatted_phrases.append(text)
        phrases = formatted_phrases
    
    buttons = []
    chat_key_raw = chat['chat_key']
    
    # Обычные кнопки-ответы (3 штуки)
    for text in phrases[:3]:
        callback_data = f"chat_answer;{chat_key_raw};{phase}"
        buttons.append([InlineKeyboardButton(text=text, callback_data=callback_data)])
    
    # Кнопка "Продать за цену покупателя" – на любом этапе
    sell_button = InlineKeyboardButton(
        text=f"✅ Продать по рыночной цене ({price}₽)",
        callback_data=f"chat_sell;{chat_key_raw}"
    )
    buttons.append([sell_button])
    
    # Кнопка "Своя цена" только на финальном этапе
    if phase == 5:
        custom_button = InlineKeyboardButton(
            text="✍️ Предложить свою цену",
            callback_data=f"chat_custom;{chat_key_raw}"
        )
        buttons.append([custom_button])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
    # Постоянные квесты (достижения)
    for aid, info in ACHIEVEMENTS.items():
        prog = ach.get(aid, {}).get("progress", 0)
        completed = ach.get(aid, {}).get("completed", False)
        target = info["target"]
        if completed:
            status = "✅"
        else:
            status = f"{prog}/{target}"
        text += f"{status} {info['name']}\n   {info['description']}\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "📅 <b>ЕЖЕДНЕВНЫЕ ЗАДАНИЯ</b>\n"
    for qid, qinfo in DAILY_QUESTS.items():
        prog = quests.get(qid, {}).get("progress", 0)
        completed = quests.get(qid, {}).get("completed", False)
        target = qinfo["target"]
        if completed:
            status = "✅ +{}₽".format(qinfo["reward_money"])
        else:
            status = f"⚡ {prog}/{target}"
        text += f"{status} {qinfo['name']}\n   {qinfo['description']}\n\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await safe_callback_answer(callback)

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

@dp.callback_query(lambda c: c.data == "pay_maintenance_list")
async def pay_maintenance_list_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT shop_id, purchase_price FROM user_shops WHERE player_id = ? AND status = 'active'", (player_id,))
    shops = cursor.fetchall()
    cursor.execute("SELECT level_id, purchase_price FROM user_taxoparks WHERE player_id = ? AND status = 'active'", (player_id,))
    taxoparks = cursor.fetchall()
    conn.close()
    
    if not shops and not taxoparks:
        await callback.message.answer("У вас нет активных бизнесов для оплаты обслуживания.")
        await safe_callback_answer(callback)
        return
    
    text = "💸 <b>ОПЛАТА ОБСЛУЖИВАНИЯ БИЗНЕСА</b>\n\n"
    kb = []
    for shop in shops:
        cost = get_maintenance_cost_shop(shop['purchase_price'])
        text += f"🏪 Магазин {shop['shop_id']} — {cost}₽/мес\n"
        kb.append([InlineKeyboardButton(text=f"Оплатить магазин {shop['shop_id']} ({cost}₽)", callback_data=f"pay_shop_{shop['shop_id']}")])
    for tax in taxoparks:
        cost = get_maintenance_cost_taxopark(tax['purchase_price'])
        text += f"🚕 Таксопарк {tax['level_id']} — {cost}₽/мес\n"
        kb.append([InlineKeyboardButton(text=f"Оплатить таксопарк {tax['level_id']} ({cost}₽)", callback_data=f"pay_taxopark_{tax['level_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="balance_details")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=reply_markup)
    await safe_callback_answer(callback)

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
    webapp_url = f"https://ruslangodunov66-alt.github.io/resellcrash/casino.html?userId={user_id}"
    
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
    webapp_url = f"https://ruslangodunov66-alt.github.io/resellcrash/crash.html?userId={user_id}"
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

@dp.callback_query(lambda c: c.data.startswith("pay_shop_"))
async def pay_shop_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    shop_id = callback.data.split("_")[2]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT purchase_price FROM user_shops WHERE player_id = ? AND shop_id = ? AND status = 'active'", (player_id, shop_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        await safe_callback_answer(callback, "Магазин не найден", show_alert=True)
        return
    
    # Обернуть в блокировку БД
    async with db_lock:
        success, msg = await pay_shop_maintenance(player_id, shop_id, row['purchase_price'])
    
    await safe_delete_message(callback.message)
    await callback.message.answer(msg, parse_mode="HTML", reply_markup=menu_kb())
    if success:
        await unified_profit_callback(callback)
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("pay_taxopark_"))
async def pay_taxopark_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    level_id = callback.data.split("_")[2]
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT purchase_price FROM user_taxoparks WHERE player_id = ? AND level_id = ? AND status = 'active'", (player_id, level_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        await safe_callback_answer(callback, "Таксопарк не найден", show_alert=True)
        return
    
    async with db_lock:
        success, msg = await pay_taxopark_maintenance(player_id, level_id, row['purchase_price'])
    
    await safe_delete_message(callback.message)
    await callback.message.answer(msg, parse_mode="HTML", reply_markup=menu_kb())
    if success:
        await unified_profit_callback(callback)
    await safe_callback_answer(callback)

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

@dp.callback_query(lambda c: c.data == "deposit_menu")
async def deposit_menu_callback(callback: CallbackQuery):
    text = (
        "📅 <b>ДЕПОЗИТЫ</b>\n\n"
        "Выберите срок вклада:\n\n"
        "• 1 день — 2% доход\n"
        "• 3 дня — 5% доход\n"
        "• 7 дней — 10% доход\n\n"
        "Сумма депозита от 10 000 до 10 000 000₽.\n"
        "Проценты начисляются в конце срока."
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
async def api_call(user_id: int, action: str, data: dict = None) -> dict:
    req_action = PlayerAction(platform="tg", platform_id=user_id, action=action, data=data or {})
    try:
        return await handle_action(req_action)
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
        # Существующий игрок – показываем меню
        player = await run_sync_db(get_player_data, player_id)
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

    # 2. Только для новых игроков – реферальная ссылка
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]
        inviter_id = await run_sync_db(find_user_by_ref_code, ref_code)
        if inviter_id and inviter_id != user_id:
            pending_inviter[user_id] = inviter_id
            await message.answer(
                "🎁 <b>РЕФЕРАЛЬНАЯ ССЫЛКА АКТИВИРОВАНА!</b>\n\n"
                "После регистрации ты получишь <b>+50 000₽</b> стартового бонуса,\n"
                "а твой друг получит <b>+80 000₽</b>.",
                parse_mode="HTML"
            )

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
        async with db_lock:
            cursor.execute("DELETE FROM referrals WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM skins WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM friends WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM learning WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM players WHERE id = ?", (player_id,))
            conn.commit()
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

    # --- ВЫДАЧА РЕФЕРАЛЬНЫХ БОНУСОВ ---
    if user_id in pending_inviter:
        inviter_id = pending_inviter.pop(user_id)
        # Получаем внутренний ID нового игрока
        player_id = await get_player_id_by_tg(user_id)
        if player_id:
            async with db_lock:
                # Начисляем бонус новому игроку (15 000₽ на casino_balance) – оставляем как было
                new_player = await run_sync_db(get_player_data, player_id)
                if new_player:
                    new_casino_balance = new_player.get("casino_balance", 0) + 15000
                    await run_sync_db(update_player_data, player_id, {
                        "casino_balance": new_casino_balance
                    })
                    print(f"✅ Реферальный бонус новому игроку {user_id}: +15000₽ на казино")

        # Начисляем бонус пригласившему по новым правилам
        inviter_player_id = await get_player_id_by_tg(inviter_id)
        if inviter_player_id:
            async with db_lock:
                # 1. Добавляем нового игрока в список приглашённых
                ref_data = await run_sync_db(get_referral_data, inviter_player_id)
                invited = ref_data.get("invited", [])
                if user_id not in invited:
                    invited.append(user_id)
                    await run_sync_db(update_referral_data, inviter_player_id, {
                        "invited": invited,
                        "bonus_claimed": False  # флаг пока не используется, но оставим
                    })

                # 2. Рассчитываем бонус
                count = len(invited)
                base_bonus = count * 20000
                bonus_15 = (count // 15) * 150000
                total_bonus = base_bonus + bonus_15
                if total_bonus > 450000:
                    total_bonus = 450000

                # 3. Начисляем на баланс пригласившего
                inviter_data = await run_sync_db(get_player_data, inviter_player_id)
                if inviter_data:
                    new_balance = inviter_data['balance'] + total_bonus
                    new_total_earned = inviter_data.get('total_earned', 0) + total_bonus
                    await run_sync_db(update_player_data, inviter_player_id, {
                        "balance": new_balance,
                        "total_earned": new_total_earned
                    })
                    print(f"✅ Реферальный бонус пригласившему {inviter_id}: +{total_bonus}₽")

                    # Отправляем уведомление пригласившему
                    try:
                        await bot.send_message(
                            inviter_id,
                            f"🎉 Новый реферал! Вы получили бонус {total_bonus} ₽.\n"
                            f"👥 Всего приглашено: {count} чел.\n"
                            f"🧾 База: {base_bonus} ₽\n"
                            f"🎁 Бонус за 15+: {bonus_15} ₽\n"
                            f"💎 Итого: {total_bonus} ₽",
                            parse_mode="HTML"
                        )
                    except:
                        pass

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

    # Доход от ОДНОГО магазина (shop_level) – для совместимости со старым кодом,
    # но теперь у нас могут быть куплены несколько магазинов через user_shops,
    # поэтому посчитаем доход от ВСЕХ магазинов за день.
    # Для этого используем get_hourly_income, а затем умножим на 24.
    hourly, _ = await run_sync_db(get_hourly_income, player_id)
    total_income_day = hourly * 24

    # Доход от автомобиля (за день)
    car_id = player.get("current_car", "none")
    car = next((c for c in CARS if c["id"] == car_id), None)
    car_income_day = (car["income_per_hour"] * 24) if car else 0

    # Доход от таксопарка (за день)
    taxopark = player.get("taxopark", {"level": "none", "cars": []})
    taxopark_level = next((l for l in TAXOPARK_LEVELS if l["id"] == taxopark.get("level")), TAXOPARK_LEVELS[0])
    taxopark_income_day = taxopark_level["income_per_car"] * 24 * len(taxopark.get("cars", []))

    # Доход от всех магазинов (через user_shops) за день
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

    # ---- 2. Накопленный доход ----
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

    # Список купленных магазинов (кратко)
    if shops_list:
        text += f"\n📦 <b>Ваши магазины ({len(shops_list)} шт.):</b>\n" + "\n".join(shops_list) + "\n"
        text += f"<i>Продать магазин — вернётся 70% его стоимости.</i>\n"
    else:
        text += "\n📦 <b>У вас нет магазинов.</b> Купите первый!\n"

    # ---- 4. Клавиатура ----
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 ЗАБРАТЬ ПРИБЫЛЬ", callback_data="collect_income", style=ButtonStyle.SUCCESS)],
        [InlineKeyboardButton(text="🏪 КУПИТЬ МАГАЗИН", callback_data="buy_shop_entry", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="🏪 ПРОДАТЬ МАГАЗИН", callback_data="sell_shop_list", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text="💸 ОПЛАТИТЬ ОБСЛУЖИВАНИЕ", callback_data="pay_maintenance_list", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]
    ])

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
    user_id = callback.from_user.id
    res = await api_call(user_id, "get_suppliers")
    if not res.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    items = res.get("suppliers", [])
    if not items:
        await safe_delete_message(callback.message)
        await callback.message.answer("🏭 <b>ПОСТАВЩИКИ</b>\n\nТовары обновляются...", parse_mode="HTML")
        await safe_callback_answer(callback)
        return
    text = "🏭 <b>ПОСТАВЩИКИ</b>\n<i>Обновление каждые 5 мин.</i>\n\n"
    kb = []
    for it in items[:8]:
        tl = max(0, int(it.get("end_time", 0) - time_module.time()))
        mins = tl // 60
        text += f"{it.get('rarity_color', '⬜')} {it.get('name')} — {it.get('buy_price')}₽ ({mins}м)\n"
        kb.append([InlineKeyboardButton(text=f"🛒 {it.get('name')[:30]} - {it.get('buy_price')}₽", callback_data=f"buy_{it.get('id')}")])
    kb.append([InlineKeyboardButton(text="🔄 ОБНОВИТЬ", callback_data="buy_menu")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("buy_") and c.data.split("_")[1].isdigit())
async def buy_item_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    item_id = int(callback.data.split("_")[1])
    r = await api_call(user_id, "buy_from_supplier", {"item_id": item_id})
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

# ---------- ИНВЕНТАРЬ ----------
@dp.callback_query(lambda c: c.data == "inventory_menu")
async def inventory_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_inventory")
    if not r.get("success"):
        await safe_callback_answer(callback, "Ошибка", show_alert=True)
        return
    inv = r.get("inventory", [])
    if not inv:
        await safe_delete_message(callback.message)
        await callback.message.answer("📦 <b>ИНВЕНТАРЬ ПУСТ</b>\n\nКупи товары у поставщиков! 👇", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏭 ЗАКУП", callback_data="buy_menu")], [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]))
        await safe_callback_answer(callback)
        return
    text = "📦 <b>ИНВЕНТАРЬ</b>\n\n"
    kb = []
    for i, it in enumerate(inv):
        text += f"{i+1}. {it.get('name')}\n   Закуп: {it.get('buy_price')}₽ | Рынок: ~{it.get('market_price')}₽\n\n"
        kb.append([InlineKeyboardButton(text=f"📢 ОПУБЛИКОВАТЬ: {it.get('name')[:25]}", callback_data=f"publish_{i}")])
        kb.append([InlineKeyboardButton(text=f"🔨 НА АУКЦИОН: {it.get('name')[:20]}", callback_data=f"auction_sell_item_{i}")])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

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
    user_id = callback.from_user.id
    item_idx = int(callback.data.split("_")[1])
    await state.update_data(publish_item_idx=item_idx)
    await state.set_state(Form.waiting_for_description)
    await safe_delete_message(callback.message)
    await callback.message.answer("✍️ <b>ОПИШИ ТОВАР</b>\n\nНапиши описание в чат (чем подробнее, тем выше шанс продажи)", parse_mode="HTML")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_description))
async def handle_description(message: Message, state: FSMContext):
    user_id = message.from_user.id
    desc = message.text.strip()
    data = await state.get_data()
    item_idx = data.get("publish_item_idx", 0)
    r = await api_call(user_id, "publish_item", {"item_idx": item_idx, "description": desc})
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
    skin_id = callback.data.split("_")[2]
    r = await api_call(user_id, "equip_skin", {"skin_id": skin_id})
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
    text = ("🎮 <b>МИНИ-ИГРЫ</b>\n\n"
            "📦 <b>РАЗБЕРИ ПОСТАВКУ</b>\n💰 Цена: 10 000₽\n"
            "🎁 Секретный бокс от поставщика\n🔄 Шанс найти вещь: 40%\n\n"
            "📊 <b>POCKET OPTION</b>\n💵 Торгуй криптовалютами\n📈 Угадывай направление и получай до 250%\n\n"
            "🏎 <b>ГОНКИ</b>\n⚡ Гоняй с друзьями на своих машинах\n\n"
            "🎰 <b>КАЗИНО</b>\n🃏 Слоты, блэкджек, рулетка – испытай удачу!")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 РАЗОБРАТЬ ПОСТАВКУ (10 000₽)", callback_data="start_supply")],
        [InlineKeyboardButton(text="📊 ТРЕЙДИНГ", callback_data="trading_menu")],
        [InlineKeyboardButton(text="🏎 ГОНКИ", callback_data="race_menu")],
        [InlineKeyboardButton(text="🎰 КАЗИНО", callback_data="casino_new")],
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

@dp.callback_query(lambda c: c.data.startswith("chat_answer;") or c.data.startswith("chat_custom;") or c.data.startswith("chat_sell;"))
async def chat_answer_callback(callback: CallbackQuery, state: FSMContext):
    tg_id = callback.from_user.id
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        await safe_callback_answer(callback, "Вы не зарегистрированы. Напишите /start", show_alert=True)
        return

    parts = callback.data.split(";")
    if parts[0] == "chat_answer":
        action = "answer"
        chat_key = parts[1]
    elif parts[0] == "chat_custom":
        action = "custom"
        chat_key = parts[1]
    elif parts[0] == "chat_sell":
        action = "sell"
        chat_key = parts[1]
    else:
        return

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

    if action == "custom":
        await state.update_data(chat_key=chat_key)
        await state.set_state(Form.waiting_for_chat_price)
        await callback.message.answer("✍️ Введите вашу цену (только число):")
        await safe_callback_answer(callback)
        return

    if action == "sell":
        original_offer = chat.get("offer")
        chat["offer"] = chat["price"]
        await callback.message.answer(f"✅ Продажа по рыночной цене {chat['price']}₽!")
        await complete_sale_universal(chat, player_id, callback=callback)
        chat["offer"] = original_offer
        return

    # Обычный ответ – повышаем доверие
    old_phase = chat["phase"]
    chat["round"] += 1
    chat["trust"] = min(100, chat["trust"] + 10)

    # Проверяем, достаточно ли раундов или доверия для завершения
    if chat["round"] >= 4 or chat["trust"] >= 80:
        client = CLIENT_TYPES[chat["client_type"]]
        if chat["trust"] >= 70:
            answer = random.choice(client["phrases"].get("agree", ["Ладно, беру!"])).replace("{price}", str(chat["offer"]))
            await callback.message.answer(f"👤 Покупатель: {answer}")
            await complete_sale_universal(chat, player_id, callback=callback)
            return   # <-- этот return уже есть? проверьте
        else:
            answer = random.choice(client["phrases"].get("decline", ["Нет, не убедили."]))
            chat["finished"] = True
            chat_key = chat['chat_key']
            async with chats_lock:
                if chat_key in active_chats:
                    del active_chats[chat_key]
            await callback.message.answer(f"👤 Покупатель: {answer}")
            await callback.message.answer("Диалог завершён.")
            await safe_callback_answer(callback)
            return   # <-- ЭТОТ RETURN НУЖНО ДОБАВИТЬ
    else:
        # Переход к следующей фазе
        new_phase = old_phase + 1 if old_phase < 5 else 5
        chat["phase"] = new_phase
        client = CLIENT_TYPES[chat["client_type"]]
        phase_key = ["greet", "state_reaction", "delivery_reaction", "reason_reaction", "wait"][new_phase-1] if new_phase <= 4 else "wait"
        if phase_key in client["phrases"]:
            client_msg = random.choice(client["phrases"][phase_key]).replace("{price}", str(chat["price"])).replace("{offer}", str(chat["offer"])).replace("{item}", chat["item"])
        else:
            client_msg = "Продолжим."
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

    async with db_lock:
        player = await run_sync_db(get_player_data, player_id)
        if not player:
            need_error = True
            error_msg = "❌ Игрок не найден."
        else:
            inventory = player.get("inventory", [])
            sold_item = None

            # ----- ТОЧНЫЙ ПОИСК ПО item_obj (сохраняется в чате) -----
            item_obj = chat.get("item_obj")
            if item_obj:
                target_name = item_obj.get("name")
                for i, inv in enumerate(inventory):
                    if inv.get("name") == target_name:
                        sold_item = inventory.pop(i)
                        break
            else:
                # fallback для старых чатов
                for i, inv in enumerate(inventory):
                    if chat["item"] in inv.get("name", ""):
                        sold_item = inventory.pop(i)
                        break

            if not sold_item:
                need_error = True
                error_msg = "❌ Товар не найден в инвентаре."
            else:
                final_price = chat["offer"]
                profit = final_price - sold_item["buy_price"]
                total_sales = player.get("total_sales", 0) + 1
                total_profit = player.get("total_profit", 0) + profit
                new_balance = player.get("balance", 0) + final_price
                new_total_earned = player.get("total_earned", 0) + profit
                stat_earned_today = player.get("stat_earned_today", 0) + profit
                stat_sold_today = player.get("stat_sold_today", 0) + 1

                await run_sync_db(update_player_data, player_id, {
                    "balance": new_balance,
                    "inventory": inventory,
                    "total_sales": total_sales,
                    "total_profit": total_profit,
                    "total_earned": new_total_earned,
                    "items_sold": total_sales,
                    "stat_earned_today": stat_earned_today,
                    "stat_sold_today": stat_sold_today
                })

                await run_sync_db(check_and_update_achievement, player_id, "millionaire", new_total_earned)
                await run_sync_db(check_and_update_achievement, player_id, "seller", total_sales)
                await run_sync_db(update_daily_quest, player_id, "sell_3", 1)
                await run_sync_db(update_daily_quest, player_id, "earn_50k", profit)
                await run_sync_db(add_sale_record, player_id, chat.get("buyer_id", 0), sold_item["name"], final_price)

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
        await bot.send_message(player_id, msg_text, parse_mode="HTML", reply_markup=menu_kb)

# ---------- АУКЦИОН ----------
@dp.callback_query(lambda c: c.data == "auction_menu")
async def auction_menu_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    r = await api_call(user_id, "get_auction_items")
    items = r.get("auction_items", []) if r.get("success") else []
    if not items:
        text = "🔨 <b>АУКЦИОН</b>\n\nНет активных лотов."
        kb = [[InlineKeyboardButton(text="📤 ВЫСТАВИТЬ", callback_data="auction_sell")], [InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")]]
        await safe_delete_message(callback.message)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await safe_callback_answer(callback)
        return
    text = "🔨 <b>АУКЦИОН</b>\n\n"
    kb = []
    for idx, it in enumerate(items):
        tl = max(0, int(it.get("end_time", 0) - time_module.time()))
        h, m = divmod(tl, 3600)
        text += f"📦 Лот #{idx+1}: {it.get('item', {}).get('name', '?')}\n💰 {it.get('current_bid', 0)}₽\n⏳ {int(h)}ч {int(m)}м\n\n"
        if it.get("seller_id") != user_id:
            kb.append([InlineKeyboardButton(text=f"💰 СТАВИТЬ (мин. {int(it.get('current_bid',0)*1.1)}₽)", callback_data=f"auction_bid_{idx}", style=ButtonStyle.SUCCESS)])
    kb.append([InlineKeyboardButton(text="📤 ВЫСТАВИТЬ", callback_data="auction_sell", style=ButtonStyle.PRIMARY)])
    kb.append([InlineKeyboardButton(text="🔙 В МЕНЮ", callback_data="back_to_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data == "auction_sell")
async def auction_sell_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    inv_res = await api_call(user_id, "get_inventory")
    inv = inv_res.get("inventory", []) if inv_res.get("success") else []
    if not inv:
        await safe_callback_answer(callback, "Нет товаров для выставления", show_alert=True)
        return
    text = "📤 <b>ВЫБЕРИ ТОВАР ДЛЯ АУКЦИОНА</b>\n\n"
    kb = []
    for i, it in enumerate(inv):
        kb.append([InlineKeyboardButton(text=f"📦 {it.get('name')} (~{it.get('market_price')}₽)", callback_data=f"auction_sell_item_{i}", style=ButtonStyle.PRIMARY)])
    kb.append([InlineKeyboardButton(text="🔙 НАЗАД", callback_data="auction_menu")])
    await safe_delete_message(callback.message)
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await safe_callback_answer(callback)

@dp.callback_query(lambda c: c.data.startswith("auction_sell_item_"))
async def auction_sell_item(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    item_idx = int(callback.data.split("_")[3])
    await state.update_data(auction_item_idx=item_idx)
    await state.set_state(Form.waiting_for_auction_price)
    await callback.message.answer("✍️ Введи начальную цену для лота (или 0 для рыночной):")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_auction_price))
async def handle_auction_price(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        price = int(message.text.strip())
    except:
        await message.answer("❌ Введи число.")
        return
    data = await state.get_data()
    item_idx = data.get("auction_item_idx")
    r = await api_call(user_id, "add_auction_item", {"item_idx": item_idx, "start_price": price})
    if r.get("success"):
        await message.answer("✅ Лот выставлен на аукцион!")
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка')}")
    await state.clear()
    await message.answer("✅ Операция выполнена.\nИспользуйте кнопку 🔨 АУКЦИОН в главном меню, чтобы продолжить.")

@dp.callback_query(lambda c: c.data.startswith("auction_bid_"))
async def auction_bid_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    item_index = int(callback.data.split("_")[2])
    await state.update_data(auction_index=item_index)
    await state.set_state(Form.waiting_for_auction_bid)   # ← изменено
    await callback.message.answer("✍️ Введи сумму ставки (минимальная ставка +10% от текущей цены):")
    await safe_callback_answer(callback)

@dp.message(StateFilter(Form.waiting_for_auction_bid))
async def handle_auction_bid(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        bid = int(message.text.strip())
        if bid <= 0:
            raise ValueError
    except:
        await message.answer("❌ Введите положительное число.")
        return

    data = await state.get_data()
    item_index = data.get("auction_index")
    if item_index is None:
        await message.answer("❌ Ошибка, начните заново.")
        await state.clear()
        return

    r = await api_call(user_id, "bid_auction", {"item_index": item_index, "bid": bid})
    if r.get("success"):
        await message.answer(f"✅ {r.get('message')}\n💰 Ваш баланс: {r.get('balance', 0):,}₽", parse_mode="HTML")
    else:
        await message.answer(f"❌ {r.get('message', 'Ошибка')}")
    await state.clear()

# ---------- ДРУЗЬЯ ----------
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
        {"id": 3, "title": "📖 Как заработать пассивный доход", "reward": 1000, "text": "Купи магазин, машину или таксопарк."},
        {"id": 4, "title": "📖 Как участвовать в гонках", "reward": 500, "text": "Создай или присоединись к гонке в мини-играх."},
        {"id": 5, "title": "📖 Как торговать на бирже", "reward": 500, "text": "Сделай ставку в POCKET OPTION."},
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
    rewards = {1: 500, 2: 500, 3: 1000, 4: 500, 5: 500}
    reward = rewards.get(lesson_id, 500)
    r = await api_call(user_id, "complete_lesson", {"lesson_id": lesson_id, "reward": reward})
    if r.get("success"):
        await callback.message.answer(
            f"🎉 Урок пройден! +{reward}₽",
            reply_markup=menu_kb()
        )
    else:
        await safe_callback_answer(callback, r.get("message", "Ошибка"), show_alert=True)
    await safe_callback_answer(callback)

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

        async with db_lock:
            cursor.execute("DELETE FROM players WHERE id = ?", (player_id,))
            cursor.execute("DELETE FROM referrals WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM skins WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM friends WHERE player_id = ?", (player_id,))
            cursor.execute("DELETE FROM learning WHERE player_id = ?", (player_id,))
            conn.commit()
        await message.answer(f"✅ Игрок '{identifier}' сброшен.")
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
    chat["offer"] = price
    chat["phase"] = 5
    client = CLIENT_TYPES[chat["client_type"]]
    if price <= chat["price"] * 0.9:
        answer = random.choice(client["phrases"].get("agree", ["Хорошо, беру!"])).replace("{price}", str(price))
        await message.answer(f"👤 Покупатель: {answer}")
        player_id = await get_player_id_by_tg(user_id)
        if player_id:
            await complete_sale_universal(chat, player_id, message=message)
        else:
            await message.answer("❌ Ошибка: игрок не найден")
    else:
        answer = random.choice(client["phrases"].get("decline", ["Дорого, не буду брать."]))
        chat["finished"] = True
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
        now = time_module.time()
        async with races_lock:
            for race_id, race in list(active_races.items()):
                # Проверяем только активные гонки (не ожидающие и не завершённые)
                if race.get("status") not in ("wait", "finished", "draw") and now - race.get("last_action_time", now) > 90:
                    creator_id = race["creator"]
                    opponent_id = race["opponent"]
                    bet = race["bet"]
                    async with db_lock:
                        creator = await run_sync_db(get_player_data, creator_id)
                        opponent = await run_sync_db(get_player_data, opponent_id)
                        if creator:
                            await run_sync_db(update_player_data, creator_id, {"balance": creator["balance"] + bet})
                        if opponent:
                            await run_sync_db(update_player_data, opponent_id, {"balance": opponent["balance"] + bet})
                    # Уведомления
                    creator_data = await run_sync_db(get_player_data, creator_id)
                    opponent_data = await run_sync_db(get_player_data, opponent_id)
                    if creator_data and creator_data.get("tg_id"):
                        await bot.send_message(creator_data["tg_id"], "⏰ Гонка отменена из-за неактивности соперника. Ставка возвращена.")
                    if opponent_data and opponent_data.get("tg_id"):
                        await bot.send_message(opponent_data["tg_id"], "⏰ Гонка отменена из-за неактивности. Ставка возвращена.")
                    del active_races[race_id]

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

    # ---------- CRASH ----------
    if action == "crash_result":
        try:
            win = data.get("win", False)
            bet = data.get("bet", 0)
            multiplier = data.get("multiplier", 1.0)
            if bet < 10 or bet > 5000:
                await respond_to_webapp({"error": "Некорректная ставка"})
                return
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                await respond_to_webapp({"error": "Игрок не найден"})
                return
            if win:
                win_amount = int(bet * multiplier)
                if player.get("casino_balance", 0) < bet:
                    await respond_to_webapp({"error": "Недостаточно средств"})
                    return
                async with db_lock:
                    new_casino = player["casino_balance"] - bet + win_amount
                    await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
                await respond_to_webapp({"action": "crash_result", "win": True, "new_balance": new_casino})
            else:
                if player.get("casino_balance", 0) < bet:
                    await respond_to_webapp({"error": "Недостаточно средств"})
                    return
                async with db_lock:
                    new_casino = player["casino_balance"] - bet
                    await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
                await respond_to_webapp({"action": "crash_result", "win": False, "new_balance": new_casino})
        except Exception as e:
            await respond_to_webapp({"error": str(e)})
        return

    elif action == "crash_session":
        try:
            total_profit = data.get("total_profit", 0)
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if total_profit > 0:
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
            elif total_profit < 0:
                if player["balance"] < -total_profit:
                    return
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        except Exception as e:
            print(f"Ошибка в crash_session: {e}")
        return

    # ---------- БЛЭКДЖЕК ----------
    elif action == "blackjack_win":
        try:
            win_amount = data.get("win", 0)
            bet = data.get("bet", 0)
            if win_amount <= 0 or bet <= 0:
                return

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return

            async with db_lock:
                new_casino = player.get("casino_balance", 0) + win_amount
                await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в blackjack_win: {e}")
        return

    elif action == "blackjack_lose":
        try:
            bet = data.get("bet", 0)
            if bet <= 0:
                return

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            # Ставка уже списана оптимистично, ничего не делаем
        except Exception as e:
            print(f"Ошибка в blackjack_lose: {e}")
        return

    elif action == "blackjack_push":
        try:
            bet = data.get("bet", 0)
            if bet <= 0:
                return

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return

            async with db_lock:
                new_casino = player.get("casino_balance", 0) + bet
                await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в blackjack_push: {e}")
        return

    elif action == "blackjack_session":
        try:
            total_profit = data.get("total_profit", 0)
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if total_profit > 0:
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
            elif total_profit < 0:
                if player["balance"] < -total_profit:
                    return
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        except Exception as e:
            print(f"Ошибка в blackjack_session: {e}")
        return

    # ---------- СЛОТЫ ----------
    elif action == "slots_result":
        try:
            result = data.get("result")
            bet = data.get("bet", 0)
            win = data.get("win", 0)

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return

            if result == "win":
                async with db_lock:
                    new_casino = player.get("casino_balance", 0) + win
                    await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в slots_result: {e}")
        return

    elif action == "slots_session":
        try:
            total_profit = data.get("total_profit", 0)
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if total_profit > 0:
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
            elif total_profit < 0:
                if player["balance"] < -total_profit:
                    return
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        except Exception as e:
            print(f"Ошибка в slots_session: {e}")
        return

    # ---------- РУЛЕТКА ----------
    elif action == "win" and data.get("game") == "roulette":
        try:
            win_amount = data.get("win", 0)
            bet = data.get("bet", 0)
            if win_amount <= 0 or bet <= 0:
                return
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if player.get("casino_balance", 0) < bet:
                return
            async with db_lock:
                new_casino = player["casino_balance"] - bet + win_amount
                await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в roulette win: {e}")
        return

    elif action == "lose" and data.get("game") == "roulette":
        try:
            bet = data.get("bet", 0)
            if bet <= 0:
                return
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if player.get("casino_balance", 0) < bet:
                return
            async with db_lock:
                new_casino = player["casino_balance"] - bet
                await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в roulette lose: {e}")
        return

    elif action in ("roulette_session", "roulette_session_close"):
        try:
            total_profit = data.get("total_profit", 0)
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if total_profit > 0:
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
            elif total_profit < 0:
                if player["balance"] < -total_profit:
                    return
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        except Exception as e:
            print(f"Ошибка в roulette_session: {e}")
        return

    # ---------- МАЙНС ----------
    elif action == "mines_result":
        try:
            result = data.get("result")
            bet = data.get("bet", 0)
            win = data.get("win", 0)

            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return

            if result == "win":
                async with db_lock:
                    new_casino = player.get("casino_balance", 0) + win
                    await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})
        except Exception as e:
            print(f"Ошибка в mines_result: {e}")
        return

    elif action == "mines_session":
        try:
            total_profit = data.get("total_profit", 0)
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return
            if total_profit > 0:
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
            elif total_profit < 0:
                if player["balance"] < -total_profit:
                    return
                async with db_lock:
                    new_balance = player["balance"] + total_profit
                    await run_sync_db(update_player_data, player_id, {"balance": new_balance})
        except Exception as e:
            print(f"Ошибка в mines_session: {e}")
        return

    # ---------- ПОПОЛНЕНИЕ / ВЫВОД ----------
    elif action in ("deposit", "deposit_to_casino"):
        try:
            amount = data.get("amount", 0)
            if amount <= 0:
                await message.answer("❌ Сумма должна быть больше 0")
                return
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                await message.answer("❌ Игрок не найден")
                return
            if player.get("balance", 0) < amount:
                await message.answer("❌ Недостаточно средств на балансе бота!")
                return
            async with db_lock:
                new_balance = player["balance"] - amount
                new_casino = player.get("casino_balance", 0) + amount
                await run_sync_db(update_player_data, player_id, {
                    "balance": new_balance,
                    "casino_balance": new_casino
                })
            await message.answer(f"✅ Пополнение на {amount}₽ выполнено!\n💰 Новый баланс казино: {new_casino}₽")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
        return

    # ---------- ВЫВОД СРЕДСТВ ИЗ КАЗИНО НА ОСНОВНОЙ БАЛАНС ----------
    elif action == "withdraw":
        try:
            amount = data.get("amount", 0)
            if amount <= 0:
                await message.answer("❌ Сумма должна быть больше 0")
                return
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                await message.answer("❌ Игрок не найден")
                return
            casino_balance = player.get("casino_balance", 0)
            if casino_balance < amount:
                await message.answer(f"❌ Недостаточно средств в казино! Доступно: {casino_balance}₽")
                return
            async with db_lock:
                new_casino = casino_balance - amount
                new_main_balance = player.get("balance", 0) + amount
                await run_sync_db(update_player_data, player_id, {
                    "casino_balance": new_casino,
                    "balance": new_main_balance
                })
            await message.answer(f"✅ Вывод {amount}₽ выполнен!\n💰 Новый баланс казино: {new_casino}₽")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")
        return

    elif action == "profile":
        # Профиль теперь запрашивается через HTTP-эндпоинт /profile/{tg_id}
        # Этот обработчик больше не нужен.
        return

    # ---------- РЕФЕРАЛЫ ----------
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

    elif action == "view_referral_income":
        try:
            player_id = await get_player_id_by_tg(user_id)
            if not player_id:
                await message.answer("❌ Вы не зарегистрированы.")
                return
            ref_data = await run_sync_db(get_referral_data, player_id)
            invited = ref_data.get("invited", [])
            count = len(invited)
            income = count * 20000
            bonus = (count // 15) * 150000
            total = income + bonus
            text = (
                f"💰 <b>Ваш реферальный доход</b>\n\n"
                f"👥 Приглашено: {count} чел.\n"
                f"🧾 По 20 000₽ за каждого: {income:,} ₽\n"
                f"🎁 Бонус за каждые 15 чел: {bonus:,} ₽\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>Итого:</b> {total:,} ₽"
            )
            await message.answer(text, parse_mode="HTML")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {str(e)}")

    # ---------- ЗАПРОС БАЛАНСА ----------
    elif action == "get_balance":
        player = await run_sync_db(get_player_data, player_id)
        if player:
            if message.web_app_data and message.web_app_data.id:
                await bot.answer_web_app_query(
                    message.web_app_data.id,
                    result=InlineQueryResultArticle(
                        id='balance',
                        title='Баланс',
                        type='article',
                        input_message_content=InputTextMessageContent(
                            message_text=json.dumps({"balance": player.get("casino_balance", 0)}),
                            parse_mode=None
                        )
                    ),
                    cache_time=0
                )
            else:
                await message.answer(f"💰 Ваш баланс в казино: {player.get('casino_balance', 0)}₽")
        else:
            await message.answer("❌ Игрок не найден")
        return

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
async def check_casino_balance(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    user_id = message.from_user.id
    player_id = await get_player_id_by_tg(user_id)
    if not player_id:
        await message.answer("❌ Игрок не найден")
        return
    player = await run_sync_db(get_player_data, player_id)
    if player:
        casino_bal = player.get("casino_balance", 0)
        await message.answer(f"💰 Ваш casino_balance в БД: {casino_bal}₽")
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

async def handle_balance(request):
    tg_id = request.match_info.get('tg_id')
    if not tg_id:
        return web.json_response({"error": "No tg_id"}, status=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return web.json_response({"error": "Invalid tg_id"}, status=400)
    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return web.json_response({"error": "Player not found"}, status=404)
    player = get_player_data(player_id)
    if not player:
        return web.json_response({"error": "Player not found"}, status=404)
    # ВОЗВРАЩАЕМ casino_balance, а не balance
    return web.json_response({"balance": player.get("casino_balance", 0)})

async def handle_options(request):
    return web.Response(headers={
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    })

async def handle_profile(request):
    tg_id = request.match_info.get('tg_id')
    if not tg_id:
        return web.json_response({"error": "No tg_id"}, status=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return web.json_response({"error": "Invalid tg_id"}, status=400)

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return web.json_response({"error": "Player not found"}, status=404)

    player = get_player_data(player_id)
    if not player:
        return web.json_response({"error": "Player not found"}, status=404)

    # Получаем статистику
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            casino_games_played,
            casino_wins,
            casino_losses,
            casino_total_bet,
            casino_total_win
        FROM players WHERE id = ?
    """, (player_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        games_played = row[0] or 0
        wins = row[1] or 0
        losses = row[2] or 0
        total_bet = row[3] or 0
        total_win = row[4] or 0
    else:
        games_played = wins = losses = total_bet = total_win = 0

    net_profit = total_win - total_bet
    winrate = round((wins / games_played * 100), 1) if games_played > 0 else 0

    profile_data = {
        "nickname": player.get('nickname', 'Игрок'),
        "balance": player.get('balance', 0),
        "casino_balance": player.get('casino_balance', 0),
        "total_earned": player.get('total_earned', 0),
        "games_played": games_played,
        "wins": wins,
        "losses": losses,
        "total_bet": total_bet,
        "total_win": total_win,
        "net_profit": net_profit,
        "winrate": winrate
    }
    return web.json_response(profile_data)

async def handle_game_result(request):
    """Принимает результат игры и обновляет casino_balance в БД"""
    try:
        data = await request.json()
        tg_id = data.get('userId')
        game = data.get('game')
        result = data.get('result')  # 'win' или 'lose'
        bet = data.get('bet', 0)
        win_amount = data.get('win', 0)

        if not tg_id:
            return web.json_response({"error": "No userId"}, status=400)

        player_id = await get_player_id_by_tg(tg_id)
        if not player_id:
            return web.json_response({"error": "Player not found"}, status=404)

        async with db_lock:
            player = await run_sync_db(get_player_data, player_id)
            if not player:
                return web.json_response({"error": "Player not found"}, status=404)

            current_casino = player.get("casino_balance", 0)

            if result == "win":
                new_casino = current_casino + win_amount
            else:
                # При проигрыше ставка уже списана локально, но для надёжности можно не менять баланс
                # или убедиться, что баланс корректен (локально он уже уменьшен)
                new_casino = current_casino  # ничего не делаем

            await run_sync_db(update_player_data, player_id, {"casino_balance": new_casino})

            return web.json_response({
                "status": "ok",
                "new_balance": new_casino,
                "game": game,
                "result": result
            })
    except Exception as e:
        print(f"Ошибка в handle_game_result: {e}")
        return web.json_response({"error": str(e)}, status=500)

async def handle_referral_generate(request):
    """Возвращает реферальную ссылку для пользователя"""
    tg_id = request.query.get('tg_id')
    if not tg_id:
        return web.json_response({"error": "No tg_id"}, status=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return web.json_response({"error": "Invalid tg_id"}, status=400)

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return web.json_response({"error": "Player not found"}, status=404)

    # Генерируем реферальную ссылку
    ref_code = gen_ref(tg_id)  # функция gen_ref уже есть в боте
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{ref_code}"
    return web.json_response({"link": link})

async def handle_referral_users(request):
    """Возвращает список приглашённых пользователей"""
    tg_id = request.query.get('tg_id')
    if not tg_id:
        return web.json_response({"error": "No tg_id"}, status=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return web.json_response({"error": "Invalid tg_id"}, status=400)

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return web.json_response({"error": "Player not found"}, status=404)

    ref_data = await run_sync_db(get_referral_data, player_id)
    invited = ref_data.get("invited", [])
    # Получаем никнеймы приглашённых
    users = []
    for invited_id in invited:
        # invited_id – это tg_id? В вашей БД в invited хранятся user_id? Проверим.
        # Судя по коду, в invited добавляется user_id (внутренний ID), но для отображения лучше взять tg_id или nickname.
        # В вашем коде при добавлении реферала (add_referral) используется new_player_id (внутренний ID), а в get_referral_data возвращается список этих ID.
        # Надо получить tg_id или nickname для каждого.
        # Проще: пройдём по списку и для каждого получим данные.
        player = await run_sync_db(get_player_data, invited_id)
        if player:
            users.append({
                "id": invited_id,
                "nickname": player.get("nickname", f"ID:{player.get('tg_id', invited_id)}"),
                "tg_id": player.get("tg_id")
            })
        else:
            users.append({"id": invited_id, "nickname": "Неизвестный", "tg_id": None})
    return web.json_response({"users": users})

async def handle_referral_income(request):
    """Возвращает общий доход от рефералов"""
    tg_id = request.query.get('tg_id')
    if not tg_id:
        return web.json_response({"error": "No tg_id"}, status=400)
    try:
        tg_id = int(tg_id)
    except ValueError:
        return web.json_response({"error": "Invalid tg_id"}, status=400)

    player_id = await get_player_id_by_tg(tg_id)
    if not player_id:
        return web.json_response({"error": "Player not found"}, status=404)

    ref_data = await run_sync_db(get_referral_data, player_id)
    invited = ref_data.get("invited", [])
    count = len(invited)
    income = count * 20000
    # Бонус за каждые 15 человек
    bonus = (count // 15) * 150000
    total = income + bonus
    return web.json_response({
        "count": count,
        "income": income,
        "bonus": bonus,
        "total": total
    })

async def start_web_server_async():
    try:
        print("🔄 Запуск веб-сервера на порту 8080...")
        app = web.Application()
        app.router.add_get('/balance/{tg_id}', handle_balance)
        app.router.add_options('/balance/{tg_id}', handle_options)
        app.router.add_get('/profile/{tg_id}', handle_profile)
        app.router.add_options('/profile/{tg_id}', handle_options)
        app.router.add_post('/game_result', handle_game_result)
        app.router.add_options('/game_result', handle_options)  # для CORS
        app.router.add_get('/referral/generate', handle_referral_generate)
        app.router.add_get('/referral/users', handle_referral_users)
        app.router.add_get('/referral/income', handle_referral_income)
        app.router.add_options('/referral/generate', handle_options)
        app.router.add_options('/referral/users', handle_options)
        app.router.add_options('/referral/income', handle_options)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', 8080)
        await site.start()
        print("✅ Веб-сервер запущен на порту 8080")

        # ngrok больше не используется – закомментировано
        # ngrok.set_auth_token("3FGqkYWVafZ98IL0LKhTKrMYbii_2v5ZN878Y3UrXXxMHKtdc")
        # ngrok.set_ngrok_path("/usr/local/bin/ngrok")
        # public_url = ngrok.connect(8080)
        # print(f"✅ ngrok туннель: {public_url}")
        # with open("/tmp/ngrok_url.txt", "w") as f:
        #     f.write(public_url)
        # admin_tg_id = ADMIN_ID
        # try:
        #     await bot.send_message(admin_tg_id, f"🔗 ngrok URL: {public_url}\nИспользуйте этот адрес в HTML-файлах для баланса.")
        # except Exception as e:
        #     print(f"⚠️ Не удалось отправить уведомление админу: {e}")

        # Бесконечное ожидание, чтобы сервер не завершался
        await asyncio.Event().wait()
        
    except Exception as e:
        print(f"❌ Ошибка запуска веб-сервера: {e}")
        import traceback
        traceback.print_exc()

async def main():
    init_db()
    upgrade_db()
    ensure_stock_prices_table()
    generate_supplier_items()
    init_trading()
    
    print("🤖 Бот запущен в режиме polling")
    
    # Фоновые задачи
    asyncio.create_task(update_trading_loop())
    asyncio.create_task(auction_loop())
    asyncio.create_task(check_business_expiry())
    asyncio.create_task(process_deposits())
    asyncio.create_task(process_mining())
    asyncio.create_task(check_overdue_loans())
    asyncio.create_task(race_timeout_check())
    asyncio.create_task(update_stock_prices_loop())
    asyncio.create_task(dividends_loop())
    asyncio.create_task(clean_inactive_chats())
    asyncio.create_task(daily_day_increment())
    asyncio.create_task(start_web_server_async())  # <-- здесь

    await bot.delete_webhook(drop_pending_updates=True)
    print("✅ Вебхук удалён, запускаем polling...")
    
    await dp.start_polling(bot, allowed_updates=["message", "callback_query", "web_app_data"])

if __name__ == "__main__":
    asyncio.run(main())