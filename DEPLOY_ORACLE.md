# النشر على Oracle Cloud Free Tier (ARM) + DuckDNS + SSL

## نظرة عامة
هذا الدليل يشرح كيفية نشر بوت "أكاديمية الأمن السيبراني والبرمجة" على **Oracle Cloud Free Tier** مع:
- **ARM Architecture** (4 OCPUs, 24 GB RAM مجاناً)
- **DuckDNS** للـ subdomain المجاني
- **Let's Encrypt** لـ SSL التلقائي
- **Docker Compose** للخدمات

---

## المتطلبات المسبقة

1. **حساب Oracle Cloud** مع Always Free مُفعّل
2. **DuckDNS account** (مجاني)
3. **مفتاح Telegram Bot** من @BotFather
4. **مفتاح Gemini API** من Google AI Studio
5. **SSH key** (Ed25519 مُوصى به)

---

## الخطوة 1: إنشاء VM على Oracle Cloud

1. ادخل إلى [Oracle Cloud Console](https://cloud.oracle.com)
2. أنشئ **Compute Instance**:
   - **Shape**: `VM.Standard.A1.Flex`
   - **OCPUs**: 4 (الحد الأقصى المجاني)
   - **Memory**: 24 GB (الحد الأقصى المجاني)
   - **Image**: **Ubuntu 22.04 أو 24.04 (ARM)**
   - **SSH Key**: ارفع مفتاحك العام (`id_ed25519.pub`)
3. **Network Security**:
   - افتح منافذ: **22 (SSH)**، **80 (HTTP)**، **443 (HTTPS)**، **8443 (Webhook)**
   - في **Security Lists** أو **Network Security Groups**

---

## الخطوة 2: إعداد DuckDNS

1. سجل في [duckdns.org](https://duckdns.org)
2. اختر subdomain (مثال: `mybot.duckdns.org`)
3. انسخ **Token** من صفحة الحساب

---

## الخطوة 3: على السيرفر (مرة واحدة)

```bash
# 1. انسخ سكريبت الإعداد
scp scripts/setup_oracle.sh ubuntu@YOUR_VM_IP:~/

# 2. على السيرفر، عدل المتغيرات في السكريبت:
ssh ubuntu@YOUR_VM_IP
nano ~/setup_oracle.sh
# عدل: DUCKDNS_DOMAIN، DUCKDNS_TOKEN، EMAIL

# 3. شغل السكريبت
chmod +x ~/setup_oracle.sh
~/setup_oracle.sh
```

هذا سيقوم بـ:
- تحديث النظام وتثبيت Docker + Docker Compose
- إعداد firewall (ufw)
- إعداد DuckDNS auto-update (cron كل 5 دقائق)
- إنشاء مجلدات المشروع و `.env.prod`

---

## الخطوة 4: نسخ ملفات المشروع

```bash
# من جهازك المحلي، انسخ كل الملفات:
scp -r docker-compose.prod.yml Dockerfile.prod nginx.conf .env.prod.template scripts/ ubuntu@YOUR_VM_IP:~/bot-project/

# على السيرفر:
ssh ubuntu@YOUR_VM_IP
cd ~/bot-project
cp .env.prod.template .env.prod
nano .env.prod  # عدل القيم الحقيقية
```

**قيم مطلوبة في `.env.prod`:**
```env
BOT_TOKEN=<من @BotFather>
GEMINI_API_KEY=<من https://aistudio.google.com/apikey>
ADMIN_IDS=<معرّفك الرقمي من @userinfobot>
WEBHOOK_SECRET=...  # سيُولد تلقائياً
DB_PASSWORD=...      # سيُولد تلقائياً
WEBHOOK_URL=https://yourbot.duckdns.org
```

> ⚠️ **لا تضع الأسرار الحقيقية في ملفات المستودع** — انسخ القيم من `.env` المحلية
> (المستبعد من Git عبر `.gitignore`) إلى `.env.prod` على السيرفر.

---

## الخطوة 5: البناء والتشغيل

```bash
cd ~/bot-project

# انسخ ملفات النشر (إذا لم تكن موجودة)
# تأكد من وجود: docker-compose.prod.yml, nginx.conf, Dockerfile.prod

# بناء وتشغيل
docker compose -f docker-compose.prod.yml up -d --build

# راقب السجلات
docker compose -f docker-compose.prod.yml logs -f
```

---

## الخطوة 6: الحصول على شهادة SSL

انتظر بضع دقائق حتى ينتشر DNS، ثم:

```bash
cd ~/bot-project

# احصل على الشهادة
docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot -w /var/www/certbot \
  -d yourbot.duckdns.org \
  --email your@email.com --agree-tos --non-interactive

# أعد تشغيل nginx
docker compose -f docker-compose.prod.yml restart nginx
```

---

## الخطوة 10: ضبط Webhook في Telegram

```bash
# على السيرفر أو من جهازك
export BOT_TOKEN="<ضع التوكن من @BotFather هنا>"
export WEBHOOK_SECRET="YOUR_WEBHOOK_SECRET_FROM_ENV"

curl -X POST "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://yourbot.duckdns.org/webhook\", \"secret_token\": \"$WEBHOOK_SECRET\"}"

# تحقق
curl "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo"
```

---

## التحديثات المستقبلية

```bash
cd ~/bot-project
./scripts/deploy.sh
```

أو يدوياً:
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
```

---

## مراقبة السجلات

```bash
# جميع الخدمات
docker compose -f docker-compose.prod.yml logs -f

# خدمة محددة
docker compose -f docker-compose.prod.yml logs -f bot
docker compose -f docker-compose.prod.yml logs -f api
docker compose -f docker-compose.prod.yml logs -f worker
```

---

## استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `database is locked` | تأكد من `VERIFY_EXEC=0`، تحقق من `pgbouncer` |
| `409 Conflict: terminated by other getUpdates` | تأكد من `BOT_MODE=webhook`، لا تشغل polling |
| `SSL certificate problem` | تأكد من DuckDNS يعمل، `certbot renew` |
| `ARM architecture error` | تأكد من `platform: linux/arm64` في compose |
| `Out of memory` | قلل `GEN_WORKER_CONCURRENCY=1`، أضف swap |

---

## صيانة دورية

```bash
# تحديث النظام (أسبوعياً)
sudo apt update && sudo apt upgrade -y

# تنظيف Docker (شهرياً)
docker system prune -f

# تجديد الشهادة (تلقائي عبر certbot timer)
systemctl status certbot.timer
```

---

## الملفات المهمة

| الملف | الوصف |
|---|---|
| `docker-compose.prod.yml` | تعريف جميع الخدمات |
| `Dockerfile.prod` | Multi-stage build لـ ARM |
| `nginx.conf` | Reverse proxy + SSL + Rate limiting |
| `.env.prod` | أسرارك (لا ترفع لـ Git) |
| `scripts/setup_oracle.sh` | إعداد السيرفر لأول مرة |
| `scripts/deploy.sh` | نشر/تحديث سريع |

---

## أمان إضافي

1. **غيّر توكن البوت دورياً**: `@BotFather` → `/revoke`
2. **حدّث مفاتيح Gemini**: احذف القديم، أنشئ جديد في AI Studio
3. **راقب السجلات**: `docker compose logs -f | grep -i error`
4. **نسخ احتياطي DB**: `docker exec bot-project-db-1 pg_dump -U cyber cyberbot > backup.sql`

---

## دعم

في حال واجهت مشاكل:
1. راجع السجلات: `docker compose logs -f`
2. تحقق من صحة الحاوية: `docker compose ps`
3. تأكد من منافذ Oracle Cloud Security List
5. تأكد من DuckDNS يعمل: `curl https://www.duckdns.org/update?domains=yourbot&token=TOKEN&ip=`