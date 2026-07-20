# Exit on error
set -o errexit

# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput


python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(email='garment@admin.com').exists():
    User.objects.create_superuser(email='garment@admin.com', password='garment@Admin')
    print('Superuser created successfully!')
"