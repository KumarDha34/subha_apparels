#!/bin/bash
echo "🚀 Starting Vercel build..."
pip install -r requirements.txt
python3 manage.py collectstatic --noinput
python3 manage.py migrate --noinput
echo "✅ Build complete!"