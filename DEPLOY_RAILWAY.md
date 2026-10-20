# 🚂 النشر على Railway (10 دقائق)

دليل نشر بوت **أكاديمية الأمن السيبراني والبرمجة** على [Railway](https://railway.app)
مع HTTPS ونطاق عام تلقائي — **بدون SSH، بدون خادم، بدون إعداد DNS**.

---

## المتطلبات

| المتطلب | الحالة |
|---|---|
| حساب GitHub فيه المستودع | ✅ `ghghglala425-afk/aldhaiBot` |
| حساب Railway | ⬜ سجّل بـ GitHub (مجاني، بدون كرت ائتمان في Trial) |
| توكن البوت | ✅ من @BotFather |
| مفتاح Gemini | ✅ من [Google AI Studio](https://aistudio.google.com/apikey) |

---

## الخطوة 1 — إنشاء المشروع (دقيقة)

1. افتح <https://railway.app> → **Login** (سجّل بحساب GitHub).
2. **New Project** → **Deploy from GitHub repo**.
3. اختر `ghghglala425-afk/aldhaiBot` → **Deploy**.

> ⚠️ **مهم:** أول نشر يبدأ تلقائيا بلا متغيرات → سيفشل (لا `BOT_TOKEN`).
> هذا طبيعي، سنصلحه الآن.

---

## الخطوة 2 — إضافة قاعدة البيانات (30 ثانية)

### ❓ «ماذا أضيف إلى قاعدة PostgreSQL لربطها بالبوت؟»

**لا تضيف شيئا إلى قاعدة البيانات يدوياً.**

| السؤال | الجواب |
|---|---|
| هل أنشئ جداول يدوياً؟ | ❌ **لا** — 34 جدولاً تُنشأ تلقائيا عند أول إقلاع (`create_all`) |
| هل أضيف Extensions؟ | ❌ **لا** — لا حاجة (البحث بـ `ILIKE`، لا `pg_trgm`) |
| هل أكتب SQL يدوياً؟ | ❌ **لا** — المخطط من `core/models.py` |
| هل أزرع البيانات يدوياً؟ | ❌ **لا** — **الزرع تلقائي عند الإقلاع** (48 لغة + كورس + شارات + مسارات) |

**ما تضيفه فعلاً هو متغير واحد في Variables كل خدمة:**

1. في المشروع: **+ New** → **Database** → **PostgreSQL**.
2. **Variables خدمة Postgres** → انسخ رابط `DATABASE_URL`.
3. **Variables خدمة البوت** → أضف:
   ```
   DATABASE_URL = ${{Postgres.DATABASE_URL}}
   ```
4. **Variables خدمة الـ API** → نفس السطر.

> ⚠️ **المتغير المحقون يظهر في خدمة Postgres فقط** — كل خدمة تحتاجه بنفسها.
>
> 💡 استخدم المضيف **الداخلي** `postgres.railway.internal`:
> لا يحتاج IPv6 ولا يُحتسب ضمن egress.

### 💾 الـ Volume (لحفظ البيانات مع SQLite)

إذا لم تفعّل PostgreSQL، استخدم **Volume** على المسار `/app/data`:
- خدمة البوت → **+ New** → **Volume** → Mount Path: `/app/data`
- ثم في Variables: `DATABASE_URL=sqlite+aiosqlite:///./data/app.db`

> بدون Volume، أي إعادة نشر على Railway **تفقد البيانات** (نظام الملفات مؤقت).

---

## 🛟 إذا ظهر خطأ: `socket.gaierror: Name or service not known`

هذا يعني أن `DATABASE_URL` يشير إلى **مضيف غير موجود**:

| السبب | الحل |
|---|---|
| المتغير غير مضبوط في الخدمة | أضف `DATABASE_URL` إلى Variables الخدمة |
| مرجع غير محلول (`${{Postgres...}}` حرفي) | تأكد أن اسم الخدمة **دقيق** (`Postgres` كما في Railway) |
| مضيف `db` (اسم Compose) | غيّره إلى مضيف Postgres الحقيقي |

> ✅ **الكود لم يعد ينهار بسبب هذا الخطأ** — يتحوّل تلقائيا إلى SQLite ويشتغل.
> راقب Logs لترى: `مضيف قاعدة البيانات ... التحويل إلى SQLite`.
> لكن Postgres أفضل للبيانات المشتركة بين البوت والـ API.

### ⚠️ خطوة إلزامية: `DATABASE_URL` في **كل** خدمة

بدون هذا المتغير يستعمل البوت **SQLite داخل الحاوية** — و**كل البيانات تضيع عند كل
إعادة نشر** (تسجيل المستخدم، الدروس المكتملة، النقاط…).

```
Variables خدمة البوت  →  DATABASE_URL = ${{Postgres.DATABASE_URL}}
Variables خدمة الـ API →  DATABASE_URL = ${{Postgres.DATABASE_URL}}
```

> 🔍 **كيف تتأكد؟** افتح `https://<نطاق-خدمتك>.up.railway.app/diag`:
> - `"database": {"kind": "postgresql", "persistent": true}` ✅
> - `"database": {"kind": "sqlite", "misconfigured": true}` ❌
>
> 🔔 وإذا كان الخطأ موجودا، يرسل البوت **إشعارا تلقائيا** للمشرف على تيليجرام.

### 🔍 التشخيص السريع (بدون قراءة السجلات)

بعد النشر افتح في المتصفح:

```
https://<نطاق-خدمتك>.up.railway.app/diag
```

يعيد JSON فيه كل ما يهم:

```json
{
  "token_valid": true,
  "bot_username": "TrsttryBot",
  "database": {"kind": "postgresql", "connected": true, "error": null},
  "ai": {"configured": true, "providers": ["gemini"], "model": "gemini-3.5-flash-lite"},
  "errors": [], "warnings": []
}
```

| الحقل | معناه |
|---|---|
| `token_valid` | `false` يعني أن التوكن مرفوض من تيليجرام (أعد issuance من @BotFather) |
| `database.connected` | `false` يعني أن Postgres غير موصول |
| `errors` / `warnings` | مشاكل الإعدادات بالتفصيل |

### 🔍 للتأكد من القاعدة المستعملة فعليا
```
GET https://<your-service>.up.railway.app/health
→ {"status":"ok","database":"postgresql","database_host":"postgres.railway.internal",...}
```

### 🛟 إذا ظهر: `FATAL: sorry, too many clients already`

عدد اتصالات PostgreSQL تجاوز الحد. التطبيق يستخدم **5 + 5 = 10 اتصالات كحد أقصى لكل خدمة**
(قابلة للضبط عبر `DB_POOL_SIZE` و `DB_MAX_OVERFLOW` في Variables). تأكد من:
- عدم وجود نسخ قديمة من البوت متصلة بالقاعدة.
- `Num Replicas = 1` لكل خدمة.

---

## الخطوة 3 — متغيرات خدمة البوت (دقيقة)

> ⚠️ **BOT_MODE على Railway = polling (ليس webhook).**
> الـ proxy في Railway ينهي TLS ويعيد التوجيه إلى HTTP، بينما خادم webhook في
> python-telegram-bot يستمع بـ TLS — فلا يصله شيء. الكود يحوّل الوضع تلقائيا
> على Railway، لكن اجعل المتغير polling صراحة.

**خدمة الـ bot** (التي أنشأتها في الخطوة 1) → تبويب **Variables**:

| المفتاح | القيمة | ملاحظة |
|---|---|---|
| `BOT_TOKEN` | `‏<من @BotFather>` | ⚠️ سري |
| `GEMINI_API_KEY` | `‏<من AI Studio>` | ⚠️ سري |
| `ADMIN_IDS` | `5444436820` | معرّفك الرقمي |
| `AI_FREE_MODE` | `1` | الوضع المجاني |
| `AI_PROVIDER_ORDER` | `gemini,groq,openrouter` | ترتيب المزوّدين |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | ⚠️ `2.5-flash-lite` لم يعد متاحا |
| `AI_DAILY_TOKEN_BUDGET` | `250000` | سقف التوكنات اليومي |
| `AI_API_KEY` | *(اتركه فارغا)* | يُتجاهل في الوضع المجاني |
| `AI_BASE_URL` | `https://api.openai.com/v1` | يُتجاهل في الوضع المجاني |
| `SECRET_KEY` | `‏<سلسلة عشوائية 64>` | سري |
| `VERIFY_EXEC` | `0` | بلا Docker |
| `SANDBOX_LOCAL` | `0` | بلا تنفيذ محلي |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | ⚠️ **في كل خدمة** (بوت + API) |
| `DB_POOL_SIZE` | `5` | اتصالات دائمة لكل خدمة |
| `DB_MAX_OVERFLOW` | `5` | اتصال إضافي عند الذروة |
| `LOG_LEVEL` | `INFO` | |
| `ENV` | `prod` | ⚠️ يفرض `SECRET_KEY` قويا |

> 🔐 **كل الأسرار تُخزَّن مشفّرة** في Railway. لا تضعها في الكود ولا في GitHub.

> 🌱 **البيانات الأساسية تُزرع تلقائيا** عند أول إقلاع (48 لغة + كورس تجريبي + 8 شارات + 3 مسارات).
> لا حاجة لأي أمر يدوي. الزرع آمن للتكرار ولا يكرّر البيانات.

**التوليد العشوائي لـ `SECRET_KEY`:**
```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

---

## الخطوة 4 — إعدادات خدمة البوت (30 ثانية)

**خدمة الـ bot** → تبويب **Settings**:

| الحقل | القيمة |
|---|---|
| **Start Command** | `sh -c 'exec python -m app.bot'` |
| **Healthcheck Path** | `/health` ✅ (البوت يشغّل خادم صحي صغير على `PORT`) |
| **Restart Policy** | `On Failure` · Max Retries `10` |
| **Num Replicas** | `1` ⚠️ **لا تزيدها** — نسختان = تعارض Telegram |

> 🔎 `railway.json` في جذر المستودع يوفّر هذه الإعدادات تلقائيا.
>
> ℹ️ **لماذا خادم صحي؟** البوت يعمل بوضع Polling فلا يستمع على أي منفذ.
> بدون خادم `/health` صغير (مدمج في `app/bot.py`) ستفتح Railway اتصالاً
> مرفوضاً وتعتبر الخدمة غير سليمة فتعيد تشغيلها في حلقة لا نهائية.

---

## الخطوة 5 — خدمة الـ API (دقيقة) *(اختياري)*

1. في المشروع: **+ New** → **Service** → اختر نفس المستودع.
2. تبويب **Settings**:
   - **Config Path** (أو *Railway Config*): `railway.api.json`
   - أو **Start Command** يدويا:
     `sh -c 'exec uvicorn api.main:app --host 0.0.0.0 --port $PORT'`
3. **Variables**: انسخ نفس المتغيرات أعلاه (نفس الـ `DATABASE_URL`).
4. عند النشر، سيعطيك Railway نطاقا مثل `cyber-academy-api.up.railway.app`.
5. ضعه في متغير البوت: `MINIAPP_URL=https://<that-domain>`
   (وهذا يظهر زر «🎯 فتح التطبيق» في البوت).

> ⚠️ **Start Command يحتاج `sh -c`** لأن Railway لا يوسّع `$PORT` في exec-form.

---

## الخطوة 6 — النشر والتحقق (دقيقة)

1. **Deployments** → **Redeploy** لخدمة البوت.
2. راقب **Logs** — يجب أن ترى:
   ```
   ✅ بدء تشغيل قاعدة البيانات: PostgreSQL
   ✅ وضع AI: مجاني (gemini) — ميزانية 250000 توكن/يوم
   ✅ عامل التوليد يعمل (تزامن=2)
   ✅ التطبيق بدأ
   ```
3. افتح البوت في تيليجرام → `/start` → `/register` → `/courses`.

---

## 🔄 التحديثات المستقبلية

ادفع إلى `main` — Railway ينشر تلقائيا:

```bash
git push
```

أو من مجلد المشروع:
```bash
railway up
```

---

## 💰 التكلفة (أسعار 2026)

| الخطة | السعر | الرصيد | ملاحظات |
|---|---|---|---|
| **Trial** | **$0** | $5 لمرة واحدة · 30 يوم | ✅ **بدون كرت ائتمان** — ابدأ هنا |
| **Free** | $0 | $1/شهر | ⚠️ الخدمة تتوقف بعد ~6 أيام |
| **Hobby** | **$5/شهر** | $5 مشمول | ✅ **مستقر** — بوت 0.5GB RAM ≈ $5 |
| **Pro** | $20/شهر | $20 مشمول | عند التوسع الكبير |

أسعار الموارد: RAM `$10/GB/شهر` · CPU `$20/vCPU/شهر` · Storage `$0.15/GB/شهر` · Egress `$0.05/GB`

**تقدير التكلفة الشهرية:**

| المكوّن | التكلفة |
|---|---|
| خدمة البوت (0.5 GB RAM) | ~$5 |
| خدمة API (0.25 GB RAM) | ~$2.5 |
| PostgreSQL (0.5 GB) | ~$5 |
| **المجموع** | **~$12/شهر** (مُغطّى جزئيا بالـ $5Included) |

> 💡 **توفير:** احذف خدمة الـ API (البوت لا يحتاجها) → ~$5/شهر.
> أو استخدم SQLite على Volume بدل PostgreSQL → نفس التكلفة تقريباً.

---

## ⚠️ ملاحظات مهمة

| الملاحظة | التفاصيل |
|---|---|
| **نسخة واحدة فقط** | `Num Replicas = 1` — نسختان في Polling = `Conflict: terminated by other getUpdates` |
| **لا Docker داخلي** | `VERIFY_EXEC=0` — لا تنفيذ أكواد داخل Railway |
| **عامل التوليد** | يعمل **داخل** عملية البوت — لا حاجة لخدمة Celery منفصلة |
| **الشحن** | `AI_DAILY_TOKEN_BUDGET` يحمي من استنفاد حصة Gemini |
| **Tab Switching** | مجاني (2 domains) · Hobby: 4 · Pro: 20 |

---

## 🔧 استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `InvalidToken: The token ... was rejected` | التوكن غير صالح أو ملغى — خذ توكنا جديدا من @BotFather (أو احذف البوت القديم). `/diag` يوضح `token_valid: false` |
| `Railway rate limit of 500 logs/sec` | إغراق سجلات — غالبا توكن خاطئ يدور في حلقة. الكود يتحقق من التوكن مرة واحدة ويتوقف + يخنق الرسائل المتكررة |
| `socket.gaierror: Name or service not known` | `DATABASE_URL` يشير لمضيف غير موجود — انظر قسم «🛟» أدناه |
| `The asyncio extension requires an async driver` | ✅ مُصلَح — `core/config.py` يضيف `+asyncpg` تلقائيا |
| `Conflict: terminated by other getUpdates` | نسخة أخرى تعمل بنفس التوكن — أوقفها (نسخة محلية أو خدمة Railway ثانية) |
| `Application failed to start` | راجع `/diag` في المتصفح — يحدد المتغير الناقص بالضبط |
| `429 Too Many Requests` | نفدت حصة Gemini — انتظر الغد أو أضف مفتاح Groq |
| `AI غير مضبوط` | `AI_FREE_MODE=1` + `GEMINI_API_KEY` في Variables |
| البوت لا يستجيب بعد Deploy | Railway يعيد التشغيل — انتظر 30 ثانية، وتأكد من Logs |
| البيانات تختفي بعد كل نشر | أضف **Volume** على `/app/data` أو استخدم PostgreSQL |

---

## 📋 أوامر مفيدة

```bash
# نشر بدون رفع (يتطلب Railway CLI)
npm i -g @railway/cli
railway login
railway link
railway up

# سجلات مباشرة
railway logs

# حالة
railway status
```

---

## 🔐 تدوير الأسرار (مهم)

الأسرار ظهرت في محادثة سابقة. بعد نجاح النشر:

1. **@BotFather** → `/revoke` → ضع التوكن الجديد في Railway Variables.
2. **[Google AI Studio](https://aistudio.google.com/apikey)** → احذف المفتاح → أنشئ غيره.
3. **عدّل `SECRET_KEY`** في Railway → يعيد Railway النشر تلقائيا (تتحوّل الجلسات القديمة).
