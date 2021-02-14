gunicorn oj.wsgi --user oj --group oj --bind 127.0.0.1:12080 --workers 1 --threads 2 --max-requests-jitter 10000 --max-requests 1000000 --keep-alive 32 &>/dev/null &

