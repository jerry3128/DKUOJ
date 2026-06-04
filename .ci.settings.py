COMPRESS_OUTPUT_DIR = 'cache'
STATICFILES_FINDERS += ('compressor.finders.CompressorFinder',)
STATIC_ROOT = os.path.join(BASE_DIR, 'static')

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'
    }
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'dmoj',
        'USER': 'root',
        'PASSWORD': 'root',
        # Default to localhost (GitHub Actions MySQL); CI can point this at a
        # service alias (e.g. 'mysql' on GitLab CI) via the DB_HOST env var.
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    },
}

# Emit JUnit XML so GitLab can render per-test results (artifacts:reports:junit).
# This file is copied to dmoj/local_settings.py only in CI, so the runner override
# is automatically scoped to CI and never affects local/dev test runs.
TEST_RUNNER = 'xmlrunner.extra.djangotestrunner.XMLTestRunner'
TEST_OUTPUT_DIR = 'test-reports'
TEST_OUTPUT_VERBOSE = 2
