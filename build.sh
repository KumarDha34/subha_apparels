#!/bin/bash

echo "🚀 Starting Vercel build process..."

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Collect static files
echo "📁 Collecting static files..."
python3 manage.py collectstatic --noinput

# Run migrations
echo "🗄️ Running migrations..."
python3 manage.py migrate --noinput

echo "✅ Build complete!"