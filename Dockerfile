# =====================================================================
#  صورة موحّدة: تعمل على Railway وعلى Docker (Compose) alike
#  - INSTALL_DOCKER_CLI=1  → يضيف Docker CLI (للـ Sandbox داخل حاوية)
#  - INSTALL_DOCKER_CLI=0  → صورة أنظف وأسرع (Railway / الإنتاج)
# =====================================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- متطلبات النظام ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---- Docker CLI (اختياري — يُستخدم فقط للـ Sandbox داخل الحاوية) ----
ARG INSTALL_DOCKER_CLI=0
RUN if [ "$INSTALL_DOCKER_CLI" = "1" ]; then \
        set -eux; \
        arch="$(dpkg --print-architecture)"; \
        case "$arch" in \
            amd64) darch=x86_64 ;; \
            arm64) darch=aarch64 ;; \
            *) darch="$arch" ;; \
        esac; \
        curl -fsSL "https://download.docker.com/linux/static/stable/${darch}/docker-27.3.1.tgz" -o /tmp/docker.tgz; \
        tar -xzf /tmp/docker.tgz -C /tmp; \
        mv /tmp/docker/docker /usr/local/bin/docker; \
        chmod +x /usr/local/bin/docker; \
        rm -rf /tmp/docker*; \
    fi

# ---- اعتماديات Python (طبقة مستقلة للتخزين المؤقت) ----
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---- الكود ----
COPY . .

# ---- مستخدم غير جذر ----
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# فحص الصحة (يُستخدم محليا؛ Railway يفحص عبر healthcheckPath)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1

# نقطة الدخول — البوت هو الافتراضي (للـ API: APP_ROLE=api)
CMD ["sh", "-c", "exec python -m app.bot"]
