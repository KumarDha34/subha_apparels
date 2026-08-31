#!/bin/bash
echo "🚀 Starting Vercel build..."

# Install dependencies
pip install -r requirements.txt

# Run migrations only (skip collectstatic)
python3 manage.py migrate --noinput

echo "✅ Build complete!"