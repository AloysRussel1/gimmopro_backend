import os
from pathlib import Path
from datetime import timedelta
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# En prod (Railway), SECRET_KEY DOIT être définie en variable d'environnement.
# Le fallback ci-dessous n'est là que pour ne pas casser le dev local existant.
SECRET_KEY = os.environ.get(
    'SECRET_KEY', "django-insecure-s0umx7ci3a2u0&a7xjjr=la$@@)(!rr(3_1musxl&va)#z$dd$"
)

# Par défaut False (sûr par défaut en prod) — le .env local définit DEBUG=True
# pour ne pas changer le comportement du poste de dev.
DEBUG = os.environ.get('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '*').split(',')

INSTALLED_APPS = [
    "app",
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    "django.middleware.security.SecurityMiddleware",
    'whitenoise.middleware.WhiteNoiseMiddleware',
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# CORS_ALLOWED_ORIGINS peut être surchargé via variable d'environnement
# (liste séparée par des virgules) — sinon on retombe sur les origines de dev
# + Vercel déjà connues. CORS_ALLOW_ALL_ORIGINS=True dans les env vars Railway
# permet un déploiement "zéro friction" tant que l'URL définitive du frontend
# n'est pas encore fixée (django-cors-headers reste compatible avec les
# credentials dans ce mode : il reflète l'Origin de la requête, jamais "*").
CORS_ALLOW_ALL_ORIGINS = os.environ.get('CORS_ALLOW_ALL_ORIGINS', 'False') == 'True'
_cors_env = os.environ.get('CORS_ALLOWED_ORIGINS', '')
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(',') if o.strip()] or [
    "http://localhost:5173",
    "http://localhost:8100",
    "http://localhost:3000",
    "https://gimmopro.vercel.app",
    "https://gimmopro-cuq15jjtj-aloysrussel1s-projects.vercel.app",
]
CORS_ALLOW_CREDENTIALS = True

# Nécessaire pour /admin/ (auth par session + CSRF) derrière le domaine
# Railway — sans ça, le POST du formulaire de login admin échoue en prod
# (schéma https obligatoire dans chaque origine listée).
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()]

# Durcissement HTTPS — désactivé par défaut (ne casse rien tant que le
# domaine Railway n'est pas encore stabilisé) ; à activer une fois en prod.
# Railway termine le TLS en amont et transmet en HTTP en interne : sans
# SECURE_PROXY_SSL_HEADER, SECURE_SSL_REDIRECT=True provoquerait une boucle
# de redirection infinie (Django ne verrait jamais une requête "https" directe).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
_https_prod = os.environ.get('SECURE_SSL_REDIRECT', 'False') == 'True'
SECURE_SSL_REDIRECT   = _https_prod
SESSION_COOKIE_SECURE = _https_prod
CSRF_COOKIE_SECURE    = _https_prod
SECURE_HSTS_SECONDS   = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))

ROOT_URLCONF = "gimmopro_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "gimmopro_backend.wsgi.application"

# DATABASE_URL est fourni automatiquement par Railway quand un service
# PostgreSQL est attaché au projet (dj_database_url.config() le lit tout
# seul depuis l'environnement). En local, s'il est absent, on retombe sur
# SQLite pour ne pas bloquer le développement quotidien — NB: on garde ce
# fallback plutôt que `default=os.environ.get('DATABASE_URL')` (qui vaudrait
# None en local et casserait `manage.py runserver` sans Postgres local).
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# ── Authentification ──────────────────────────────
# Permet login avec username OU email
AUTHENTICATION_BACKENDS = [
    'app.backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':    timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME':   timedelta(days=7),
    'ROTATE_REFRESH_TOKENS':    True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# ── Email (reset mot de passe, vérification d'email) ──────────────
# En dev/local : "console" affiche l'email dans les logs du serveur au lieu
# de l'envoyer réellement. AVANT LA PROD, il faut définir EMAIL_BACKEND=
# django.core.mail.backends.smtp.EmailBackend (ou un backend tiers) et les
# identifiants SMTP réels dans les variables d'environnement — sans ça,
# reset de mot de passe et vérification d'email ne délivrent rien pour de vrai.
EMAIL_BACKEND       = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT          = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_HOST_USER     = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS       = os.environ.get('EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL  = os.environ.get('DEFAULT_FROM_EMAIL', 'no-reply@gimmopro.local')

# URL du frontend React — utilisée pour construire les liens envoyés par email
# (reset mot de passe, vérification), puisque c'est React qui affiche ces pages,
# pas Django.
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173')

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-ca"
TIME_ZONE     = "America/Toronto"
USE_I18N      = True
USE_TZ        = True

STATIC_URL          = "static/"
STATIC_ROOT         = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD  = "django.db.models.BigAutoField"

# WhiteNoise sert les fichiers statiques directement depuis Gunicorn en prod
# (pas besoin de Nginx/CDN séparé sur Railway). STORAGES est la façon moderne
# (Django ≥4.2) de configurer ça — STATICFILES_STORAGE est dépréciée.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Fichiers uploadés par les utilisateurs (documents/pièces jointes). Servis en
# dev via urls.py (voir static() dans DEBUG uniquement) ; en prod, un stockage
# objet (S3, etc.) ou le reverse-proxy doit prendre le relais — ces pièces
# étant sensibles (CNI, contrats…), elles ne sont JAMAIS servies via une URL
# publique ; l'API passe systématiquement par DocumentDownloadView.
# NB: sur Railway, le filesystem n'est PAS persistant entre déploiements —
# les fichiers uploadés seront perdus au prochain déploiement tant qu'un
# stockage objet externe (S3, Cloudflare R2…) n'est pas branché ici.
MEDIA_URL  = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"