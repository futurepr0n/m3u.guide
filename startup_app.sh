#!/bin/bash

set -e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

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

# Do not bring up a deployment that advertises missing or corrupt Jellyfin
# packages. This also catches forgotten checksum updates after rebuilding a ZIP.
python3 validate_plugin_repository.py \
    || handle_error "Jellyfin plugin repository validation failed"

# Provider credentials are encrypted with a stable Fernet key. Prefer a value
# injected by the deployment secret manager. For a simple bare-metal install,
# persist a generated key outside source control and reuse it on every start.
if [ -z "${M3UGUIDE_CREDENTIAL_KEY:-}" ]; then
    M3UGUIDE_CREDENTIAL_KEY_FILE="${M3UGUIDE_CREDENTIAL_KEY_FILE:-$SCRIPT_DIR/.secrets/m3uguide_credential.key}"
    if [ -f "$M3UGUIDE_CREDENTIAL_KEY_FILE" ]; then
        M3UGUIDE_CREDENTIAL_KEY="$(tr -d '\r\n' < "$M3UGUIDE_CREDENTIAL_KEY_FILE")"
    else
        echo "Generating persistent provider credential encryption key..."
        umask 077
        mkdir -p "$(dirname -- "$M3UGUIDE_CREDENTIAL_KEY_FILE")"
        M3UGUIDE_CREDENTIAL_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode("ascii"))')"
        printf '%s\n' "$M3UGUIDE_CREDENTIAL_KEY" > "$M3UGUIDE_CREDENTIAL_KEY_FILE"
        chmod 600 "$M3UGUIDE_CREDENTIAL_KEY_FILE"
    fi
    export M3UGUIDE_CREDENTIAL_KEY
fi

# Refuse to start before touching legacy plaintext credentials if the supplied
# key is missing, malformed, or cannot initialize Fernet.
python3 -c 'import os; from cryptography.fernet import Fernet; Fernet(os.environ["M3UGUIDE_CREDENTIAL_KEY"].encode("ascii"))' \
    || handle_error "M3UGUIDE_CREDENTIAL_KEY is not a valid Fernet key"

# Generate initial secret key if not exists
if [ -z "$FLASK_SECRET_KEY" ]; then
    export FLASK_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    echo "Generated new secret key"
    # Save to .env file
    echo "FLASK_SECRET_KEY=$FLASK_SECRET_KEY" > .env
fi

# Initialize database if it doesn't exist. Relative Flask-SQLAlchemy SQLite
# paths live below the instance directory.
if [ ! -f "instance/app.db" ]; then
    echo "Initializing database..."
    python3 -c "from app import app; from models import db; app.app_context().push(); db.create_all()"
fi

# Run the application
echo "Starting application..."
python3 app.py || handle_error "Failed to start application"
