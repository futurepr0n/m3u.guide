#!/bin/bash

# Function to handle errors and testing git
handle_error() {
    echo "Error: $1"
    exit 1
}

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv || handle_error "Failed to create virtual environment"
fi

# Activate virtual environment
source venv/bin/activate || handle_error "Failed to activate virtual environment"

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip || handle_error "Failed to upgrade pip"

# Install requirements
echo "Installing requirements..."
pip install -r requirements.txt || handle_error "Failed to install requirements"

# Generate initial secret key if not exists
if [ -z "$FLASK_SECRET_KEY" ]; then
    export FLASK_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    echo "Generated new secret key"
    # Save to .env file
    echo "FLASK_SECRET_KEY=$FLASK_SECRET_KEY" > .env
fi

# Initialize database if it doesn't exist
if [ ! -f "app.db" ]; then
    echo "Initializing database..."
    python3 -c "from app import app; from models import db; app.app_context().push(); db.create_all()"
fi

# Run the application
echo "Starting application..."
python3 app.py || handle_error "Failed to start application"
