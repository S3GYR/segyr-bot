import multiprocessing
import os

bind = os.getenv('GUNICORN_BIND', '0.0.0.0:8090')
workers = int(os.getenv('GUNICORN_WORKERS', multiprocessing.cpu_count()))
worker_class = 'uvicorn.workers.UvicornWorker'
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', 1000))
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', 100))
accesslog = os.getenv('GUNICORN_ACCESSLOG', '-')
errorlog = os.getenv('GUNICORN_ERRORLOG', '-')
loglevel = os.getenv('GUNICORN_LOGLEVEL', 'info')

timeout = int(os.getenv('GUNICORN_TIMEOUT', 60))
keepalive = int(os.getenv('GUNICORN_KEEPALIVE', 5))
