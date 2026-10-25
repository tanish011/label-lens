import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-this-before-deployment" if DEBUG else "")
if not DEBUG and (not SECRET_KEY or SECRET_KEY == "dev-only-change-this-before-deployment"):
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a unique secret before production deployment.")
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
VERCEL_HOSTS = [os.getenv(name, "").strip().split(":")[0] for name in ("VERCEL_URL", "VERCEL_PROJECT_PRODUCTION_URL")]
ALLOWED_HOSTS.extend(host for host in VERCEL_HOSTS if host and host not in ALLOWED_HOSTS)
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "rest_framework", "catalog.apps.CatalogConfig", "recommendations.apps.RecommendationsConfig"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=not DEBUG)}
elif os.getenv("DB_ENGINE", "sqlite").lower() == "mysql":
    DATABASES = {"default": {"ENGINE": "django.db.backends.mysql", "NAME": os.getenv("DB_NAME", "labellens"), "USER": os.getenv("DB_USER", "labellens"), "PASSWORD": os.getenv("DB_PASSWORD", ""), "HOST": os.getenv("DB_HOST", "127.0.0.1"), "PORT": os.getenv("DB_PORT", "3306"), "OPTIONS": {"charset": "utf8mb4"}, "CONN_MAX_AGE": 60}}
else:
    if not DEBUG:
        raise ImproperlyConfigured("Production requires DATABASE_URL; SQLite is only for local development.")
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / os.getenv("DB_NAME", "db.sqlite3")}}
AUTH_PASSWORD_VALIDATORS = [{"NAME": f"django.contrib.auth.password_validation.{v}"} for v in ["UserAttributeSimilarityValidator", "MinimumLengthValidator", "CommonPasswordValidator", "NumericPasswordValidator"]]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/accounts/login/"
REST_FRAMEWORK = {"DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"], "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"], "DEFAULT_THROTTLE_RATES": {"anon": "120/hour"}}
OFF_BASE_URL = os.getenv("OFF_BASE_URL", "https://world.openfoodfacts.org").rstrip("/")
OFF_USER_AGENT = os.getenv("OFF_USER_AGENT", "LabelLens/1.0 (contact not configured)")
OFF_TIMEOUT_SECONDS = float(os.getenv("OFF_TIMEOUT_SECONDS", "8"))
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "labellens-cache"}}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "True").lower() == "true"
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", "False").lower() == "true"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
    CSRF_TRUSTED_ORIGINS.extend(f"https://{host}" for host in VERCEL_HOSTS if host and f"https://{host}" not in CSRF_TRUSTED_ORIGINS)
