# 🎓 أكاديمية الأمن السيبراني والبرمجة

بوت تلجرام + تطبيق (Mini App) لتعلّم **كل لغات البرمجة** والأمن السيبراني:
دروس مفصّلة، أكواد حقيقية مُتحقَّقة، مختبرات عملية، واختبارات لكل مرحلة.

> مشروع **مستقل تمامًا** — لا علاقة له بأي تطبيق آخر.

---

## ✨ الميزات (بدون أي اشتراكات — مجاني بالكامل)

**التعلّم والمحتوى**
1. مسارات ومراحل ودروس متدرّجة.
2. كل درس: شرح + **≥25 مثال كود** + مخرجات متوقعة، مع **موسوعة أكواد**: تشريح سطري
   لكل كود، و**≥8 استخدامات موثّقة** (التوقيع + مثال + الخرج)، والمعاملات والقيمة المُرجعة
   والأخطاء الشائعة والملاحظات الأمنية.
3. صوت وفيديو وعرض كود منسّق لكل درس.
4. مختبرات عملية (Sandbox حقيقي بـDocker).
5. تحديات CTF وتلميحات (بخصم نقاط).
6. تغطية عالمية: سجلّ كل لغات البرمجة + المكتبات والأطر.
7. بحث دلالي داخل المحتوى.

**التقييم والتقدّم**
8. اختبار بعد كل درس — لا تُفتح المرحلة التالية إلا بالنجاح.
9. دروس برمجية تُشترط فيها سلامة تشغيل الكود.
10. حفظ التقدّم الدائم في قاعدة البيانات.
11. ملاحظات شخصية ومرجعيات (Bookmarks).
12. تصدير المحتوى (PDF/Offline).

**التحفيز**
13. نقاط XP ومستويات.
14. شارات وإنجازات.
15. سلسلة أيام (Streaks).
16. لوحة صدارة (Leaderboard).
17. درس يومي + تذكيرات.
18. شهادات إتمام للكورسات + **شهادات المسارات التعلّمية**.
19. أدوات اختبار ويب (Burp-lite): Repeater + Fuzzer-lite + Decoder.
20. بيئات هدف عملية (Juice Shop / DVWA) بمهام موجّهة ونقاط.

**المجتمع والإدارة**
21. مساعد ذكي (AI) يشرح أي كود.
22. نقاش لكل درس + أسئلة وأجوبة.
23. أدوار: طالب/معلّم/مشرف + لوحة إدارة.
22. بثّ إعلانات للمشتركين.
23. تحليلات لوحة الإدارة (الإتمام، والصعوبة، والدروس).
24. سجلّ تدقيق كامل (Audit Log).
25. نسخ احتياطي دوري واسترجاع.

**تجربة المستخدم**
26. واجهة عربية/إنجليزية ومظهر فاتح/داكن.
27. تطبيق Mini App غني داخل تلجرام.
28. QR لفتح التطبيق وربط الحساب.
29. إشعارات ذكية.
30. دعم فني داخل البوت.

> **بدون اشتراكات ولا دفع** — كل الميزات مفتوحة للجميع.

---

## 🚂 النشر على Railway (10 دقائق — موصى به)

أسرع طريقة لتشغيل البوت **24/7 في السحابة**: HTTPS ونطاق عام تلقائيا، بلا SSH وبلا خادم.

```bash
# 1) سجّل في railway.app (بـ GitHub، مجاني 30 يوم بدون كرت ائتمان)
# 2) New Project → Deploy from GitHub repo → ghghglala425-afk/aldhaiBot
# 3) أضف PostgreSQL (زر واحد) → يحقن DATABASE_URL تلقائيا
# 4) أضف المتغيرات: BOT_TOKEN · GEMINI_API_KEY · ADMIN_IDS · AI_FREE_MODE=1
# 5) Redeploy → البوت يعمل خلال دقيقة
```

**التفاصيل الكاملة:** [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md)

| الخطة | التكلفة | الرصيد |
|---|---|---|
| Trial (30 يوم) | **$0** | $5 لمرة واحدة، بدون كرت ائتمان |
| Free | $0 | $1/شهر (الخدمة تتوقف بعد ~6 أيام) |
| **Hobby** | **$5/شهر** | $5 مشمول — الخيار المستقر |

> `railway.json` و `railway.api.json` جاهزان، و `core/config.py` يضيف `+asyncpg`
> تلقائيا إلى `DATABASE_URL` الذي يحقنه Railway.

**النشر على خادمك الخاص (Oracle/GCP/VPS):** [DEPLOY_ORACLE.md](DEPLOY_ORACLE.md)

---

## ⚡ التشغيل السريع: البوت فقط (بلا Docker، بموديل محلي)

المسار الأسرع للتجربة على ويندوز. يحتاج **Python 3.12**، و**LM Studio** (اختياري لكنه مطلوب لتوليد المحتوى والمساعد الذكي).

```powershell
# 1) انسخ الإعدادات واملأ BOT_TOKEN (و AI_* إن أردت التوليد)
copy .env.example .env

# 2) شغّل كل شيء: بيئة افتراضية + اعتماديات + بيانات أساسية + البوت
.\run_bot.ps1
```

سكربت `run_bot.ps1` يقوم تلقائيا بـ:
- إنشاء بيئة `.venv312` وتثبيت الاعتماديات (مع تعافٍ من حجب إضافة SQLAlchemy C على ويندوز).
- استخدام قاعدة **SQLite** (`./data/app.db`) و`VERIFY_EXEC=0` — أي **بلا Docker**.
- تهيئة البيانات الأساسية (48 لغة + الكورسات + المسارات) ثم تشغيل البوت بوضع **Polling**
  مع **عامل توليد المحتوى في الخلفية**.

خيارات: `.\run_bot.ps1 -NoSeed` (تخطّي التهيئة) · `-Recreate` (إعادة بناء البيئة) · `-DatabaseUrl "sqlite+aiosqlite:///./data/app.db"`.

### إعداد LM Studio (الموديل المحلي)

1. حمّل موديلا مناسبا (يفضّل 7B–14B بجودة JSON جيدة).
2. في LM Studio: **Developer ▸ Start Server** — سيعمل على `http://localhost:1234/v1`.
3. فعّل **Max parallel requests ≥ 4** (لأن العامل يولّد عدة دروس بالتوازي).
4. اضبط `.env`:

```env
AI_BASE_URL=http://localhost:1234/v1
AI_API_KEY=lm-studio
AI_MODEL=<معرّف الموديل كما يظهر في LM Studio>
AI_MAX_TOKENS=16384
AI_JSON_MODE=auto
GEN_WORKER_CONCURRENCY=2
```

> البوت يعمل حتى بلا `AI_API_KEY` (تصفّح اللغات/الكورسات)، لكن **توليد الدروس** و**المساعد الذكي**
> و**بناء المخططات** تبقى معطّلة حتى يضبط الموديل.

### الوضع المجاني (بلا بطاقة ولا LM Studio)

إن لم ترغب بتشغيل موديل محلي، استخدم طبقة المزوّدين المجانيين المدمجة
(Gemini / Groq / OpenRouter) — تُجرَّب بالترتيب وتنتقل تلقائيا عند نفاد الحصة أو الفشل:

```env
AI_FREE_MODE=1
AI_API_KEY=
GEMINI_API_KEY=<من https://aistudio.google.com/apikey>
# اختياري: مفتاح ثانٍ من مشروع Google آخر لمضاعفة الحصة اليومية
GEMINI_API_KEY_2=
GROQ_API_KEY=<اختياري من https://console.groq.com/keys>
OPENROUTER_API_KEY=<اختياري من https://openrouter.ai/keys>
AI_DAILY_TOKEN_BUDGET=2000000
GEMINI_MODEL=gemini-3.5-flash-lite
GEMINI_FALLBACK_MODEL=gemini-3.8-flash
GEMINI_MODEL_CHAIN=gemini-3.5-flash-lite,gemini-3.8-flash,gemini-3.6-flash,gemini-3.1-flash-lite
GEMINI_AUTODETECT=1
```

> أسماء موديلات Gemini تتقاعد بسرعة. عند رفض الاسم (HTTP 404 «no longer available»)
> يجرّب البوت سلسلة `GEMINI_MODEL_CHAIN` ثم يكتشف الموديلات المتاحة فعليا من `/models`
> (`GEMINI_AUTODETECT=1`) ويثبّت أول موديل ناجح. لا تعِد الموديل المتقاعد إلى `.env`.
> زد `AI_DAILY_TOKEN_BUDGET` إذا أردت توليد كل الدروس (200 درس) في يوم واحد.

- كل مزوّد له حدود (RPM/RPD/TPD) مضبوطة في `.env`؛ عند بلوغها يُستبعد مؤقتا ويُنتقل للتالي.
- الاستهلاك اليومي يُسجَّل في جدول `ai_usage` ويُصفَّر تلقائيا كل يوم.
- `AI_DAILY_TOKEN_BUDGET` سقف إجمالي لكل المزوّدين (`0` = بلا سقف) — يحمي الحصة من النفاد السريع.
- زر **توليد الآن** و**بناء المخطط** متاحان **للمشرف فقط** (`ADMIN_IDS`) لمنع استهلاك الحصة.
- للتحقق: `/status` يعرض الوضع (`free`/`direct`/`off`) والمزوّدين المتاحين.

### التشغيل 24/7 على ويندوز

```powershell
# مراقب يعيد تشغيل البوت تلقائيا عند أي توقّف/انهيار
.\run_forever.ps1

# أو: تثبيت مهمة مجدولة تعمل عند الدخول وبلا نافذة، مع إعادة تشغيل تلقائية
.\install_autostart.ps1 -StartNow

# إلغاء التثبيت
.\install_autostart.ps1 -Uninstall
```

- السجلات: `data\logs\bot.log` (دوّار 5×5MB) و`data\logs\watchdog.log`.
- نسخة احتياطية آمنة (تستخدم واجهة SQLite Backup مع WAL):
  ```powershell
  .\backup_db.ps1                 # يحتفظ بآخر 7 نسخ في data\backups
  .\backup_db.ps1 -Keep 14
  ```
- أضف أمر النسخ إلى مهمة مجدولة يومية إن أردت (Task Scheduler ← Create Task ← Daily).

### الأمان المدمج

- البوت يعمل في **المحادثات الخاصة فقط** (يرفض المجموعات/القنوات).
- التوليد اليدوي وبناء المخططات والتسخين: **للمشرف فقط**.
- حدّ معدّل لكل مستخدم على الميزات المكلفة (المساعد/التشغيل/البحث/الأدوات).
- `POST /api/auth/telegram` لا ينشئ حسابات تلقائيا — يجب التسجيل من البوت أولا.
- `/api/admin/*` يتطلب توكن مشرف. `SECRET_KEY` إلزامي في الإنتاج.
- SQLite بوضع **WAL + busy_timeout** لتحمّل الكتابة المتزامنة (بوت + عامل + API).

### الحجم والتحميل التدريجي (Outline-first + Lazy)

- كل لغة = **10 مراحل × 20 درسا = 200 درس** (و48 لغة ≈ **9600 درس**).
- بدل توليد كل شيء دفعة واحدة (مستهلك للوقت والتوكن)، يُبنى أولا **مخطط اللغة** (عناوين الدروس)
  فتصبح كل الدروس **قابلة للتصفّح** فورا، ثم يُولَّد الدرس **كاملا عند فتحه** (Lazy)،
  مع **تسخين أول 20 درسا** تلقائيا عند إتمام المخطط.
- **فتح أي لغة يبني مخططها (200 درس) محليا وفوريا بلا أي نداء AI** — حتى لو كان المساعد متوقفا،
  تظهر الدروس كلها للتصفّح مباشرة. الـAI يُستخدم فقط لتوليد محتوى الدرس عند فتحه.
- للمشرف: `/build status` · `/build all` (مخطط كل اللغات) · `/build <lang>` · `/build warm <lang>` · `/build retry`.
- اضبط `GEN_STAGES` / `GEN_LESSONS_PER_STAGE` / `GEN_WARM_LESSONS` / `GEN_WORKER_CONCURRENCY` في `.env`.
- فحص ذاتي شامل (بلا شبكة/AI، على قاعدة مؤقتة): `python scripts/audit.py` — يفحص 48 لغة × 200 درس،
  الاختبارات والإجابات، تشغيل كل أكواد الدرس التجريبي، ورحلة مستخدم كاملة (فتح/اختبار/شهادة/تمرين).

---

## 🚀 التشغيل الكامل محليا بـDocker (خطوة بخطوة)

### 1) المتطلبات
- **Docker Desktop** (مثبّت ويعمل).
- توكن بوت من [@BotFather](https://t.me/BotFather).
- مفتاح ذكاء اصطناعي متوافق مع OpenAI.

> ⚠️ **متطلب عتاد مهم:** Docker Desktop لتشغيل حاويات Linux يحتاج تفعيل الافتراضية:
> ميزتي *WSL* و*Virtual Machine Platform*، مع تشغيل **VT-x/AMD-V من الـBIOS/UEFI**.
> إن كان ويندوز يعمل **داخل جهاز افتراضي** فيجب تفعيل **الافتراضية المتداخلة (nested virtualization)** على المضيف.
> التشخيص السريع:
> ```powershell
> wsl --status                 # يجب ألا يظهر "virtualization is not enabled"
> docker info --format "{{.ServerVersion}}"
> ```
> بدون ذلك لا يقلع محرّك Docker. **ويمكن تشغيل المنصّة بدون Docker** (انظر «التشغيل بدون Docker» أدناه):
> يبقى التعلّم والاختبارات والمسارات وأدوات الويب تعمل، وتتعطّل فقط ميزات تنفيذ الأكواد وبيئات الهدف.

### 2) الإعداد
```powershell
copy .env.example .env
```
ثم افتح `.env` واملأ:
```
BOT_TOKEN=ضع_التوكن_هنا
AI_API_KEY=ضع_المفتاح_هنا
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
SECRET_KEY=سلسلة_عشوائية_طويلة
```

### 3) التشغيل
```powershell
docker compose up --build
```
سيشغّل تلقائيا: قاعدة البيانات + Redis + الـAPI + البوت.
افتح تلجرام وكتب `/start` لبوتك.

### 4) تعبئة بيانات أولية (اختياري)
في نافذة أخرى:
```powershell
docker compose exec api python -m pipeline.seed
```

> **Sandbox:** الحاويتان `api` و`bot` تصلان إلى Docker عبر `/var/run/docker.sock`
> لتشغيل أكواد الدروس في حاويات معزولة (بلا شبكة + حدود موارد).
> على Linux قد تحتاج إضافة المستخدم لمجموعة `docker` أو ضبط أذونات المقبس.

> **Mini App:** لتظهر داخل تلجرام يحتاج الـAPI إلى رابط عام (HTTPS)، ثم
> `MINIAPP_URL=https://<host>/app`. محليًا يمكنك معاينة الصفحة على `http://localhost:8000/app`.

> **وضع البوت:** الافتراضي `BOT_MODE=polling` (يعمل بلا دومين). للنشر عبر
> `BOT_MODE=webhook` اضبط `WEBHOOK_URL` (HTTPS) ويُبنى المسار تلقائيًا
> `WEBHOOK_URL/WEBHOOK_PATH`، ويمكن تأمينه بـ`WEBHOOK_SECRET`.

### 5) التشغيل بدون Docker (بيئة بلا افتراضية)
يمكن تشغيل الـAPI والبوت مباشرة عبر Python دون Docker (مفيد إن تعذّر WSL2/nested virtualization).
**أمر واحد:**
```powershell
.\run_local.ps1
```
أو يدويا:
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```
ثم في `.env`:
```
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
VERIFY_EXEC=0          # بلا تنفيذ عند توليد الدروس (تحقق نحوي فقط) — أسرع وأسلم
TARGET_EXTERNAL_URLS=  # اتركه فارغا للنمط الموجّه، أو juice-shop=https://<host> لهدف خارجي
```
وأخيرا:
```powershell
.\.venv\Scripts\python -m pipeline.seed     # بيانات أولية (يُنشئ مجلد data/ تلقائيا)
.\.venv\Scripts\python -m api.main          # الـAPI + Mini App على http://localhost:8000/app
.\.venv\Scripts\python -m app.bot           # البوت (polling)
```
> إن حجب Windows App Control إضافة SQLAlchemy المترجمة، ثبّت نسخة بايثون فقط ثم:
> `$env:DISABLE_SQLALCHEMY_CEXT="1"` قبل التشغيل (أو `pip install --no-binary sqlalchemy sqlalchemy`).

**ما يعمل بدون Docker:** التعلّم، الدروس، موسوعة الأكواد، الاختبارات، النقاط، الشارات،
المسارات والشهادات، أدوات الويب (`PROXY_ALLOWED_HOSTS`)، و**مهام بيئات الهدف** (بلا حاوية).

**التنفيذ (Sandbox):** **لا يُنفَّذ أي كود على مضيف جهازك/الخادم إطلاقا** — لا يوجد مسار
تنفيذ محلي في الكود نفسه. مسارَان فقط:

1. **خدمة تنفيذ خارجية معزولة** — تعمل بلا Docker ولا تمسّ جهازك (الكود يُرسل لطرف ثالث؛
   لا تستخدمه لأكواد حساسة). مدعوم مزوّدان:
   - **Judge0 CE** (مجاني بلا مفتاح، الأسهل):
     `EXEC_PROVIDER=judge0` و`EXEC_API_URL=https://ce.judge0.com` و`VERIFY_EXEC=1`.
   - **Piston**: `EXEC_PROVIDER=piston` و`EXEC_API_URL=https://<piston-host>/api/v2`
     (الخادم العام لـemkc يتطلب رمز تصريح منذ 2026-02؛ اطلبه لمشروع تعليمي غير تجاري).
2. **Docker** على الخادم (بلا شبكة + حدود موارد).

بدون الاثنين يُصنَّف التنفيذ "متخطى" (تحقق نحوي) ولا يُشغَّل أي كود. للتحقق من الوضع: `/status`.

**بيئات الهدف بدون Docker:** إمّا **نمط موجّه** (تُحلّ المهام وتُحتسب نقاطها بلا حاوية)، أو
**هدف خارجي** عبر `TARGET_EXTERNAL_URLS` (يُعرض زر «فتح الهدف» بدل تشغيل حاوية).

> ملاحظة: أُعمدة/جداول جديدة (`Lab.external_url`, `learning_paths`, `path_certificates`, `proxy_log`)
> تُنشأ تلقائيا على قاعدة **جديدة** عبر `create_all`. لقاعدة موجودة أعد الإنشاء أو نفّذ `ALTER TABLE labs ADD COLUMN external_url VARCHAR(400);`.

---

## 🤖 أوامر البوت
```
/start /help        القائمة الرئيسية
/register /login    إنشاء حساب أو الدخول
/me                 ملفي الشخصي (نقاط، مستوى، سلسلة)
/courses            تصفّح الكورسات
/daily              درس اليوم
/rank               لوحة الصدارة
/notes /bookmarks   ملاحظاتي ومرجعياتي
/certificates       شهاداتي
/paths              المسارات التعلّمية (رحلة متعددة الكورسات + شهادة مسار)
/tools              أدوات اختبار الويب (Repeater / Fuzzer-lite / Decoder)
/status             حالة النظام (قاعدة البيانات، Docker، وضع التنفيذ)
/stats /broadcast   (للمشرف) إحصائيات وبثّ
```

## 🖼️ تطبيق Mini App
يعمل على المسار **`/app`** من نفس الـAPI (صفحة مستقلة تدخل تلجرام عبر `initData`).
لعرض زر «فتح التطبيق» في البوت، اضبط `.env`:
```
MINIAPP_URL=https://<نطاق-الـAPI-العام>/app
```
داخل Mini App: تصفّح الكورسات والدروس، اقرأ الشرح وموسوعة الأكواد (تشريح سطري + استخدامات
موثّقة)، أدِّ الاختبارات، حلّ المختبرات وبيئات الهدف، وتابع المسارات — مع مصادقة تلقائية
عبر `POST /api/auth/telegram`.

## 🛤️ المسارات التعلّمية والشهادات
المسارات تجمع عدة كورسات في رحلة واحدة، وعند إتمامها 100% تُصدر **شهادة مسار** برمز فريد:
`GET /api/paths` · `GET /api/paths/{slug}`.

## 🕵️ أدوات اختبار الويب (Burp-lite)
متوفّرة في Mini App ومحصورة بنطاقات مسموحة (`PROXY_ALLOWED_HOSTS`، الافتراضي localhost) لمنع إساءة الاستخدام:
```
POST /api/proxy/request   {method,url,headers,body}        # Repeater
POST /api/proxy/fuzz      {url,payloads[],marker:"FUZZ"}   # Intruder-lite
POST /api/proxy/decode    {op,value}                       # Base64/URL/Hex/HTML/Hash
```
كل طلب يُسجَّل في جدول `proxy_log` للمراجعة.

## 🎯 بيئات الهدف (TryHackMe-like)
مختبرات تشغيل حاويات حقيقية (OWASP Juice Shop، DVWA) مع مهام موجّهة تُحتسب نقاطها:
```
GET  /api/labs/{id}/target
POST /api/labs/{id}/target/start | /stop
POST /api/labs/{id}/target/tasks/{order}   {answer}
```
تتطلّب صلاحية الوصول إلى Docker عبر `docker.sock` (مضبوط في compose).

## 📚 مسارات التعلّم (للتطبيق)
```
GET  /api/courses
GET  /api/courses/{slug}/lessons
GET  /api/lessons/{id}            (يشمل أمثلة الأكواد)
GET  /api/lessons/{id}/quiz       (الأسئلة والخيارات بدون كشف الصحيح)
POST /api/lessons/{id}/attempt    {responses:{qid:[oid]}} → النتيجة وفتح الدرس التالي
GET  /api/lessons/{id}/labs
POST /api/labs/{id}/submit        {flag}
GET  /api/leaderboard | /api/me/rank | /api/daily
GET  /api/notes | /api/bookmarks | /api/certificates
GET  /api/codes/{id}              (تفاصيل كود من موسوعة الأكواد)
GET  /api/paths | /api/paths/{slug}   (المسارات + شهادتها)
```

## 🧱 المعمارية
```
تلجرام (Bot) ┐
             ├─→ FastAPI ─→ PostgreSQL
Mini App ────┘     ├── Redis
                   ├── Scheduler (دروس/تذكيرات)
                   ├── AI Content Engine (توليد + تحقّق)
                   └── Docker Sandbox (تنفيذ الأكواد)
```

## 🤖 توليد المحتوى (مسبق كامل + بوابة تحقق صارمة)

كل درس يمرّ بدورة: **توليد → تحقق نحوي → تنفيذ فعلي في Sandbox → اختبارات → حلقة إصلاح → حفظ**.
ولا يُنشر أي درس إلا بعد اجتياز كل الفحوص.

```powershell
# توليد 3 دروس للتجربة
docker compose exec api python -m pipeline.build_all --limit 3

# توليد كورس كامل مع النشر
docker compose exec api python -m pipeline.build_all --course python-security --publish

# توليد كل ما لم يُولَّد بعد
docker compose exec api python -m pipeline.build_all --only-missing
```

قابل للضبط في `.env`:
- `GEN_MIN_CODES` (الحد الأدنى للأكواد لكل درس، افتراضي 15)
- `VERIFY_EXEC` (تنفيذ الأكواد فعليا)
- `GEN_MAX_REPAIRS` (عدد محاولات الإصلاح التلقائي)
- `AUTO_PUBLISH` (نشر تلقائي بعد النجاح)

أو عبر الـAPI (كمسؤول):
```
POST /api/admin/generate   {"courses":["python-security"],"limit":10,"publish":true}
GET  /api/admin/generate/{job_id}
GET  /api/languages
```

## 📁 الهيكل
```
core/       النواة: إعدادات، قاعدة بيانات، نماذج، أمان، مستودع
api/        واجهة REST (مصادقة، كتالوج، إدارة)
app/        بوت تلجرام (معالجات، أزرار)
pipeline/   محرّك توليد المحتوى + بذور البيانات
sandbox/    صور Docker لتشغيل أكواد الطلاب بأمان
tests/      اختبارات
```

## 🔐 الأمان
- كلمات المرور بـPBKDF2-SHA256 (240 ألف دورة).
- توكنات JWT موقّعة.
- Sandbox بلا شبكة + حدود موارد.
- أدوات اختبار الويب محصورة بنطاقات مسموحة (`PROXY_ALLOWED_HOSTS`).
- سجلّ تدقيق لكل العمليات الحساسة.

## 🧪 الاختبارات
```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
```
