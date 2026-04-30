web: gunicorn config.wsgi:application --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:$PORT --timeout 120 --keep-alive 5
release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
