import os
import sys
import decouple
import json
import pathlib

from django.contrib.messages import constants as messages

from ledger_api_client.settings_base import *
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT_URLCONF = 'parkstay.urls'
SITE_ID = 1

# number of seconds before expiring a temporary booking
BOOKING_TIMEOUT = 1800 

INSTALLED_APPS += [
    'webtemplate_dbca',
#    'bootstrap3',
    'parkstay',
    'taggit',
    'rest_framework',
    'rest_framework_gis',
    'django_summernote',
    'ledger_api_client',
#    'django_site_queue',
    'appmonitor_client',
    'crispy_bootstrap5',
    'crispy_forms',

]

MIDDLEWARE_CLASSES += [
    'parkstay.middleware.BookingTimerMiddleware',
    'parkstay.middleware.CacheControl',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    #'wagov_utils.components.debug.middleware.DebugControl',
]

SESSION_COOKIE_HTTPONLY=True
# maximum number of days allowed for a booking
PS_MAX_BOOKING_LENGTH = 28 

# minimum number of remaining campsites to trigger an availaiblity warning
PS_CAMPSITE_COUNT_WARNING = 10

# number of days before clearing un unpaid booking
PS_UNPAID_BOOKING_LAPSE_DAYS = 5

WSGI_APPLICATION = 'parkstay.wsgi.application'
#MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': (
#        'parkstay.perms.OfficerPermission',
    ),
}

# disable Django REST Framework UI on prod
if not DEBUG:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']=('rest_framework.renderers.JSONRenderer',)
else:
    REST_FRAMEWORK['DEFAULT_RENDERER_CLASSES']=('rest_framework.renderers.JSONRenderer','rest_framework_csv.renderers.CSVRenderer')

# show the DRF API root view (list of API endpoints) at /api/
SHOW_API_ROOT = decouple.config('SHOW_API_ROOT', default=False, cast=bool)

TEMPLATES[0]['DIRS'].append(os.path.join(BASE_DIR, 'parkstay', 'templates'))
TEMPLATES[0]['DIRS'].append(os.path.join(BASE_DIR, 'django_site_queue', 'templates'))
TEMPLATES[0]['OPTIONS']['context_processors'].append('parkstay.context_processors.parkstay_url')

#SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': os.path.join(BASE_DIR, 'parkstay', 'cache'),
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}

STATICFILES_DIRS.append(os.path.join(os.path.join(BASE_DIR, 'parkstay', 'static')))

#STATICFILES_DIRS.append(os.path.join(os.path.join(BASE_DIR, 'ledger_api_client', 'static')))
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")


BPAY_ALLOWED = decouple.config('BPAY_ALLOWED',default=False)

OSCAR_BASKET_COOKIE_OPEN = 'parkstay_basket'


CRON_CLASSES = [
    'parkstay.cron.UnpaidBookingsReportCronJob',
    'appmonitor_client.cron.CronJobAppMonitorClient',    
]

# Additional logging for parkstay
LOGGING['loggers']['booking_checkout'] = {
    'handlers': ['file'],
    'level': 'INFO'
}

LOGGING['loggers']['django.db.backends'] = {
    'handlers': ['file'],
    'level': 'DEBUG',
    'propagate': True, 
}

## To see database sql queries
#LOGGING = {
#    'version': 1,
#    'disable_existing_loggers': False,
#    'handlers': {
#        'file': {
#            'level': 'DEBUG',
#            'class': 'logging.FileHandler',
#            'filename': str(BASE_DIR)+'/logs/sql.log',
#        },
#    },
#    'loggers': {
#        'django.db.backends': {
#            'handlers': ['file'],
#            'level': 'DEBUG',
#            'propagate': True,
#        },
#    },
#}

os.environ['LEDGER_REFUND_TRANSACTION_CALLBACK_MODULE'] = 'parkstay:parkstay.api.refund_transaction_callback'
os.environ['LEDGER_INVOICE_TRANSACTION_CALLBACK_MODULE'] = 'parkstay:parkstay.api.invoice_callback'
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10240

SYSTEM_NAME = decouple.config('SYSTEM_NAME', default='Parkstay WA')
EMAIL_FROM = decouple.config('EMAIL_FROM', default=ADMINS[0])
DEFAULT_FROM_EMAIL = EMAIL_FROM
WAITING_QUEUE_ENABLED = decouple.config('WAITING_QUEUE_ENABLED',default=False, cast=bool)
QUEUE_GROUP_NAME = decouple.config('QUEUE_GROUP_NAME', default=None)
QUEUE_WAITING_URL = decouple.config('QUEUE_WAITING_URL', default=None)
QUEUE_SCRIPT_EXEMPT_KEY = decouple.config('QUEUE_SCRIPT_EXEMPT_KEY', default='')
ACCEPTED_REFERER_URL =  decouple.config('ACCEPTED_REFERER_URL', default=['http://localhost'])

PS_PAYMENT_SYSTEM_ID = decouple.config('PS_PAYMENT_SYSTEM_ID', default='S483')
if not VALID_SYSTEMS:
    VALID_SYSTEMS = [PS_PAYMENT_SYSTEM_ID]
EXPLORE_PARKS_URL = decouple.config('EXPLORE_PARKS_URL', default='https://parks.dpaw.wa.gov.au/park-stay')
PRIVACY_POLICY_URL = decouple.config('PRIVACY_POLICY_URL', default='https://www.dbca.wa.gov.au/privacy')
PARKS_EXTERNAL_BOOKING_URL = decouple.config('PARKS_EXTERNAL_BOOKING_URL',default='https://parkstaybookings.dbca.wa.gov.au')
PARKSTAY_EXTERNAL_URL = decouple.config('PARKSTAY_EXTERNAL_URL',default='https://parkstay.dbca.wa.gov.au')
DEV_STATIC = decouple.config('DEV_STATIC',default=False)
DEV_STATIC_URL = decouple.config('DEV_STATIC_URL', default='')
DEV_STATIC_SEARCH_AVAIL = decouple.config('DEV_STATIC_SEARCH_AVAIL',default=False)
DEV_STATIC_SEARCH_AVAIL_URL = decouple.config('DEV_STATIC_SEARCH_AVAIL_URL', default='')
DEPT_DOMAINS = decouple.config('DEPT_DOMAINS', default=['dpaw.wa.gov.au', 'dbca.wa.gov.au'])
#LEDGER_REFUND_EMAIL = env('LEDGER_REFUND_EMAIL', False )
os.environ['LEDGER_REFUND_EMAIL'] = 'True'
VERSION_NO = '3.12'
# Only change if you make changes to Booking Properties
BOOKING_PROPERTY_CACHE_VERSION='v1.04'
QUEUE_DOMAIN = decouple.config('QUEUE_DOMAIN',default='')
QUEUE_URL = decouple.config('QUEUE_URL',default='')
QUEUE_ENDPOINT_URL = decouple.config('QUEUE_ENDPOINT_URL', default='')
QUEUE_BACKEND_URL = decouple.config('QUEUE_BACKEND_URL',default='')
QUEUE_ACTIVE_HOSTS = decouple.config('QUEUE_ACTIVE_HOSTS',default='')
ENABLE_QUEUE_MIDDLEWARE = decouple.config('ENABLE_QUEUE_MIDDLEWARE',default=False, cast=bool)
if ENABLE_QUEUE_MIDDLEWARE is True or ENABLE_QUEUE_MIDDLEWARE == 'True':
    MIDDLEWARE_CLASSES += [
        'parkstay.queue_middleware.QueueControl',
    ]

# Use git commit hash for purging cache in browser for deployment changes
GIT_COMMIT_HASH = ''
GIT_COMMIT_DATE = ''
if len(GIT_COMMIT_HASH) == 0:
    GIT_COMMIT_HASH = os.popen('cat /app/git_hash').read()
    if len(GIT_COMMIT_HASH) == 0:
        print ("ERROR: No git hash provided")
        if  os.path.isdir(BASE_DIR+'/.git/') is True:
            GIT_COMMIT_DATE = os.popen('cd '+BASE_DIR+' ; git log -1 --format=%cd').read()
            GIT_COMMIT_HASH = os.popen('cd  '+BASE_DIR+' ; git log -1 --format=%H').read()        
LEDGER_TEMPLATE = 'bootstrap5'

ALERT_URL=decouple.config('ALERT_URL',default='')
LEGACY_BOOKING_URL=decouple.config('LEGACY_BOOKING_URL',default='')
CAMPSITE_BOOKING_API_KEY = decouple.config('CAMPSITE_BOOKING_API_KEY', default='')

SESSION_ENGINE = 'django.contrib.sessions.backends.file'
SESSION_FILE_PATH = decouple.config('SESSION_FILE_PATH', default='/app/session_store/')

DATA_STORE = decouple.config('DATA_STORE', default=os.path.join(BASE_DIR, 'data_store'))
if os.path.isdir(DATA_STORE):
    pass
else:
    os.mkdir(DATA_STORE)

#LEDGER_UI_ACCOUNTS_MANAGEMENT = [
#            {'first_name': {'options' : {'view': True, 'edit': True}}},
#            {'last_name': {'options' : {'view': True, 'edit': True}}},
#            {'residential_address': {'options' : {'view': True, 'edit': True}}},
#            {'phone_number' : {'options' : {'view': True, 'edit': True}}},
#            {'mobile_number' : {'options' : {'view': True, 'edit': True}}},
#]
# for am in LEDGER_UI_ACCOUNTS_MANAGEMENT:
#     LEDGER_UI_ACCOUNTS_MANAGEMENT_KEYS.append(list(am.keys())[0])
    

LEDGER_UI_CARDS_MANAGEMENT = True
BOOKING_PREFIX="PB"
MIDDLEWARE = MIDDLEWARE_CLASSES
MIDDLEWARE_CLASSES = None

DEFAULT_SEARCH_AVAILABILITY_LOCATION=decouple.config('DEFAULT_SEARCH_AVAILABILITY_LOCATION',default='')

MAP_STREETS_URL = decouple.config('MAP_STREETS_URL', default='https://kb.dbca.wa.gov.au/geoserver/gwc/service/wmts')
MAP_STREETS_LAYER = decouple.config('MAP_STREETS_LAYER', default='kaartdijin-boodja-public:mapbox-streets-public')
MAP_TENURE_URL = decouple.config('MAP_TENURE_URL', default='https://kb.dbca.wa.gov.au/geoserver/gwc/service/wmts')
MAP_TENURE_LAYER = decouple.config('MAP_TENURE_LAYER', default='kaartdijin-boodja-public:CPT_DBCA_LEGISLATED_TENURE')

SESSION_COOKIE_AGE = 3600
DEBUG_CONTROL = False

APPLICATION_VERSION = decouple.config("APPLICATION_VERSION", default="1.0.0") + "-" + GIT_COMMIT_HASH[:7]
RUNNING_DEVSERVER = len(sys.argv) > 1 and sys.argv[1] == "runserver"

# Sentry settings
SENTRY_DSN = decouple.config("SENTRY_DSN", default=None)
SENTRY_SAMPLE_RATE = decouple.config("SENTRY_SAMPLE_RATE", default=1.0)  # Error sampling rate
SENTRY_TRANSACTION_SAMPLE_RATE = decouple.config(
    "SENTRY_TRANSACTION_SAMPLE_RATE", default=0.0
)  # Transaction sampling
if not RUNNING_DEVSERVER and SENTRY_DSN and EMAIL_INSTANCE:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        sample_rate=SENTRY_SAMPLE_RATE,
        traces_sample_rate=SENTRY_TRANSACTION_SAMPLE_RATE,
        environment=EMAIL_INSTANCE.lower(),
        release=APPLICATION_VERSION,
    )

MESSAGE_TAGS = {
    messages.DEBUG: 'alert-info',
    messages.INFO: 'alert-info',
    messages.SUCCESS: 'alert-success',
    messages.WARNING: 'alert-warning',
    messages.ERROR: 'alert-danger',
}
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

CSRF_TRUSTED_ORIGINS_STRING = decouple.config("CSRF_TRUSTED_ORIGINS", default='[]')
print (CSRF_TRUSTED_ORIGINS_STRING)
CSRF_TRUSTED_ORIGINS = json.loads(str(CSRF_TRUSTED_ORIGINS_STRING))
# CSRF_COOKIE_DOMAIN = decouple.config("CSRF_COOKIE_DOMAIN", default='.dbca.wa.gov.au')
CSRF_COOKIE_SECURE = decouple.config('CSRF_COOKIE_SECURE',default=True, cast=bool) 
SESSION_COOKIE_SECURE = decouple.config('SESSION_COOKIE_SECURE', default=True, cast=bool)
# This is needed so that the chmod is not called in django/core/files/storage.py
# (_save method of FileSystemStorage class)
# As it causes a permission exception when using azure network drives
FILE_UPLOAD_PERMISSIONS = None
