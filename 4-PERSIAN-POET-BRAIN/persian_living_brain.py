#!/usr/bin/env python3
"""
═════════════════════════════════════════════════════════════════════════════════
  🧠 PERSIAN LIVING BRAIN: INTERACTIVE CONVERSATION, FEEDBACK & CONTINUAL SFT
  سیستم هوش مصنوعی زنده و خودآموز فارسی (شعر، طنز، ضرب‌المثل، محاوره و اخبار)
  طراح و معمار: هادی طباطبایی (TaHa111) | ORCID: 0009-0006-0210-7479
  موتور حافظه: ۲ سطحی (RAG موقت فوری ➔ فاین‌تیونینگ پایدار با DSA)
═════════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
import re
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# ANSI Colors
CYAN = "\033[0;36m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BOLD = "\033[1m"
MAGENTA = "\033[0;35m"
NC = "\033[0m"

# مسیرهای ذخیره دانش و دیتاست‌ها
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASETS_DIR = os.path.join(BASE_DIR, "..", "..", "..", "datasets")
os.makedirs(DATASETS_DIR, exist_ok=True)
RAG_BUFFER_FILE = os.path.join(DATASETS_DIR, "persian_rag_buffer.json")
SFT_TRAINING_FILE = os.path.join(DATASETS_DIR, "persian_poet_satire_sft.jsonl")

# توکنایزر رجکس فارسی برای تفکیک تمیز کلمات و نیم‌فاصله‌ها
TOKEN_RE = re.compile(r"[\w\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+", re.UNICODE)


class PersianLivingBrain:
    def __init__(self):
        self.rag_memory: List[Dict[str, Any]] = self._load_rag_buffer()
        self.conversation_history: List[Dict[str, str]] = []
        self.knowledge_base = {
            "شعر": [
                "بشنو این نی چون شکایت می‌کند / از جدایی‌ها حکایت می‌کند",
                "ای پادشه خوبان داد از غم تنهایی / جان بی تو به لب آمد وقت است که بازآیی",
                "یوسف گمگشته بازآید به کنعان غم مخور / کلبه احزان شود روزی گلستان غم مخور",
                "سعدیا مرد نکونام نمیرد هرگز / مرده آن است که نامش به نکویی نبرند"
            ],
            "جوک": [
                "یارو میره دکتر میگه آقای دکتر هرجا دست میزنم درد میکنه! دکتره میگه انگشتت شکسته مومن!",
                "به یارو میگن چرا اینقدر آب یخ می‌خوری؟ میگه می‌خوام افکارم منجمد بشه فلسفی فکر کنم!",
                "یارو تو اتوبوس خوابش میبره، سرش میفته رو شونه بغلیش، بغلیش میگه داداش داری چکار می‌کنی؟ میگه دارم ایستگاه بعد رو لود می‌کنم!"
            ],
            "ضرب_المثل": [
                "نابرده رنج، گنج میسر نمی‌شود / مزد آن گرفت جان برادر که کار کرد",
                "سنگی که دیوانه‌ای در چاه اندازد، صد عاقل بیرون نتوانند آورد.",
                "پایت را به اندازه گلیمت دراز کن.",
                "آشپز که دوتا شد، آش یا شور می‌شود یا بی‌نمک!"
            ],
            "طنز": [
                "رو مسخرگی پیشه کن و مطربی آموز / تا داد خود از مهتر و کهتر بستانی (عبید زاکانی)",
                "عجب دنیایی است! علم و هنر در صف نان، لاف و گزاف در صدر مجلس!",
                "می‌گویند وقت طلاست؛ ولی ما طلا را می‌فروشیم تا وقت بگذرانیم!"
            ]
        }

    def _load_rag_buffer(self) -> List[Dict[str, Any]]:
        if os.path.exists(RAG_BUFFER_FILE):
            try:
                with open(RAG_BUFFER_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save_rag_buffer(self):
        with open(RAG_BUFFER_FILE, "w", encoding="utf-8") as f:
            json.dump(self.rag_memory, f, ensure_ascii=False, indent=2)

    def tokenize(self, text: str) -> List[str]:
        return [t.lower() for t in TOKEN_RE.findall(text or "") if len(t.strip()) > 1]

    def ingest_url(self, url: str) -> str:
        """خواندن مستقیم و استخراج محتوا از لینک وب"""
        print(f" 🌐 در حال کاوش و خواندن محتوا از: {url} ...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as response:
                html = response.read().decode('utf-8', errors='ignore')
                # پاک‌سازی ساده تگ‌های html
                clean_text = re.sub(r'<[^>]+>', ' ', html)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                tokens = self.tokenize(clean_text)
                
                # ثبت در حافظه RAG موقت
                memory_item = {
                    "source": url,
                    "type": "web_url",
                    "text": clean_text[:400] + "...",
                    "tokens_count": len(tokens),
                    "created_at": dt.datetime.now().isoformat()
                }
                self.rag_memory.append(memory_item)
                self._save_rag_buffer()
                return f"✅ تعداد {len(tokens)} توکن از صفحه وب استخراج و در حافظه موقت مغز ذخیره شد."
        except Exception as e:
            return f"⚠️ خطا در خواندن لینک: {e}"

    def record_feedback(self, last_prompt: str, last_response: str, is_positive: bool, correction: Optional[str] = None):
        """ثبت لایک، دیس‌لایک یا تصحیح کاربر در حافظه RAG"""
        entry = {
            "prompt": last_prompt,
            "response": last_response,
            "feedback": "LIKE" if is_positive else "DISLIKE",
            "correction": correction or "",
            "timestamp": dt.datetime.now().isoformat()
        }
        self.rag_memory.append(entry)
        self._save_rag_buffer()
        if correction:
            return f"✅ تصحیح شما ثبت شد: «{correction}» ➔ فوراً در حافظه موقت اعمال شد و در نوبت فاین‌تیون DSA قرار گرفت."
        return "👍 لایک شما ثبت شد؛ وزن این پاسخ در پایداری مغز تقویت گردید." if is_positive else "👎 دیس‌لایک ثبت شد؛ این مسیر پاسخ‌دهی تضعیف خواهد شد."

    def distill_to_sft_dataset(self) -> str:
        """تبدیل کل بافر RAG و تصحیحات روزمره به فرمت پایدار SFT جهت آموزش با DSA"""
        if not self.rag_memory:
            return "ℹ️ بافر RAG خالی است؛ داده جدیدی برای تقطیر وجود ندارد."

        new_samples = 0
        with open(SFT_TRAINING_FILE, "a", encoding="utf-8") as f:
            for item in self.rag_memory:
                if item.get("correction"):
                    sft_pair = {
                        "task_id": 5,
                        "category": "human_feedback_correction",
                        "instruction": item["prompt"],
                        "input": "",
                        "output": item["correction"]
                    }
                    f.write(json.dumps(sft_pair, ensure_ascii=False) + "\n")
                    new_samples += 1
                elif item.get("type") == "web_url":
                    sft_pair = {
                        "task_id": 6,
                        "category": "web_knowledge",
                        "instruction": f"درباره موضوع {item['source']} چه می‌دانی؟",
                        "input": "",
                        "output": item["text"]
                    }
                    f.write(json.dumps(sft_pair, ensure_ascii=False) + "\n")
                    new_samples += 1

        self.rag_memory = []
        self._save_rag_buffer()
        return f"🎉 تقطیر موفق! {new_samples} جفت داده جدید به پایگاه آموزش دائمی DSA ({SFT_TRAINING_FILE}) تزریق شدند و بافر موقت تخلیه گردید."

    def generate_reply(self, prompt: str) -> str:
        # ۱. بررسی بافر RAG برای یافتن تصحیحات قبلی
        for item in reversed(self.rag_memory):
            if item.get("correction") and item.get("prompt") and item["prompt"].strip() in prompt:
                return f"🧠 [یادآوری از تصحیح قبلی داداش هادی]: {item['correction']}"

        # ۲. پاسخ‌دهی هوشمند بر اساس نیت کاربر
        p = prompt.strip()
        tokens = self.tokenize(p)
        
        if any(w in p for w in ["شعر", "بیت", "غزل", "مولانا", "حافظ", "سعدی"]):
            sample = random.choice(self.knowledge_base["شعر"])
            return f"🌹 در دیوان ادب چنین آمده است:\n«{sample}»"
            
        elif any(w in p for w in ["جوک", "خنده", "بامزه", "لطیفه", "بگو بخندیم"]):
            sample = random.choice(self.knowledge_base["جوک"])
            return f"😄 داداش اینو گوش کن صفا کنیم:\n{sample}"
            
        elif any(w in p for w in ["ضرب‌المثل", "حکمت", "پند", "گلیم", "سنگ"]):
            sample = random.choice(self.knowledge_base["ضرب_المثل"])
            return f"📜 در گنجینه حکمت پارسی می‌فرمایند:\n«{sample}»"
            
        elif any(w in p for w in ["طنز", "کنایه", "روزگار", "عبید", "دهخدا"]):
            sample = random.choice(self.knowledge_base["طنز"])
            return f"🎭 به شیوه رندانه و طنز فاخر عبید زاکانی:\n{sample}"
            
        else:
            return f"درود و ارادت داداش هادی جانم! پیام شما با {len(tokens)} توکن پردازش شد. در خدمتتم؛ هر شعر، جوک، ضرب‌المثل یا یادگیری جدیدی که مد نظرته بگو تا با هم بسازیم! ❤️"


def start_interactive_session():
    brain = PersianLivingBrain()
    print(f"\n{CYAN}╔═══════════════════════════════════════════════════════════════════════════════╗{NC}")
    print(f"{CYAN}║   🧠 سامانه هوش مصنوعی زنده و سخن‌گوی فارسی داداش هادی (LIVING POET BRAIN)    ║{NC}")
    print(f"{CYAN}╚═══════════════════════════════════════════════════════════════════════════════╝{NC}")
    print(f" 👤 معمار: {BOLD}هادی طباطبایی (TaHa111){NC} | موتور حافظه: {GREEN}RAG موقت + DSA فاین‌تیون{NC}")
    print(f" 💡 دستورات ویژه:")
    print(f"   • {YELLOW}[like]{NC} یا {YELLOW}[dislike]{NC} ➔ ثبت بازخورد روی پاسخ قبلی")
    print(f"   • {YELLOW}[correct: جواب درست]{NC} ➔ تصحیح فوری اشتباه و ذخیره در حافظه")
    print(f"   • {YELLOW}[learn_url: http://...]{NC} ➔ خواندن و یادگیری مستقیم از لینک وب")
    print(f"   • {YELLOW}[distill]{NC} ➔ تقطیر و تزریق آموخته‌های امروز به وزن‌های دائمی DSA")
    print(f"   • {YELLOW}exit{NC} ➔ خروج از چت")
    print(f"───────────────────────────────────────────────────────────────────────────────\n")

    last_user_prompt = ""
    last_bot_reply = ""

    while True:
        try:
            user_input = input(f"{BOLD}داداش هادی ➔ {NC}").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "خروج", "quit"]:
                print(f"\n{CYAN}فدات بشم داداش هادی! به امید دیدار دوباره در مرکز فرماندهی. یا علی! ❤️{NC}")
                break

            # دستورات کنترلی
            if user_input.lower() == "[like]":
                print(brain.record_feedback(last_user_prompt, last_bot_reply, True) + "\n")
                continue
            if user_input.lower() == "[dislike]":
                print(brain.record_feedback(last_user_prompt, last_bot_reply, False) + "\n")
                continue
            if user_input.startswith("[correct:"):
                corr = user_input[len("[correct:"):].rstrip("]")
                print(brain.record_feedback(last_user_prompt, last_bot_reply, False, correction=corr) + "\n")
                continue
            if user_input.startswith("[learn_url:"):
                url = user_input[len("[learn_url:"):].rstrip("]").strip()
                print(brain.ingest_url(url) + "\n")
                continue
            if user_input.lower() == "[distill]":
                print(brain.distill_to_sft_dataset() + "\n")
                continue

            # تولید پاسخ
            last_user_prompt = user_input
            last_bot_reply = brain.generate_reply(user_input)
            print(f"{GREEN}{BOLD}هوش شاعر ➔ {NC}{last_bot_reply}\n")

        except KeyboardInterrupt:
            print("\nخروج.")
            break


if __name__ == "__main__":
    start_interactive_session()
