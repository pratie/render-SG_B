from logging.config import fileConfig
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Add the parent directory to the Python path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

# Load environment variables
load_dotenv()

# Import your models here
from models import Base

# this is the Alembic Config object
config = context.config

# Get environment (development or production)
ENV = os.getenv("ENV", "development")
IS_RENDER = os.getenv("RENDER", "false").lower() == "true"

# Get DATABASE_URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Configure SQLite for different environments
    if ENV == "production" or IS_RENDER:
        DATABASE_URL = "sqlite:////var/data/reddit_analysis.db"
    else:
        DATABASE_URL = "sqlite:///./reddit_analysis.db"

print(f"Using DATABASE_URL: {DATABASE_URL}")

# Override sqlalchemy.url with environment-specific configuration
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# Configure SQLite-specific options
config.set_section_option(config.config_ini_section, "sqlalchemy.pool_pre_ping", "true")
config.set_section_option(config.config_ini_section, "sqlalchemy.pool_recycle", "3600")

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Create database directory if it doesn't exist
    db_path = DATABASE_URL.split(":///")[-1]
    db_dir = os.path.dirname(db_path)
    
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"Created database directory: {db_dir}")
        except Exception as e:
            print(f"Warning: Could not create database directory: {e}")
    
    # Create empty database file if it doesn't exist
    if not os.path.exists(db_path):
        try:
            Path(db_path).touch()
            if ENV == "production" or IS_RENDER:
                os.chmod(db_path, 0o666)
            print(f"Created database file: {db_path}")
        except Exception as e:
            print(f"Warning: Could not create database file: {e}")

    # Configure the database connection
    configuration = config.get_section(config.config_ini_section)
    if not configuration:
        configuration = {}
    configuration["sqlalchemy.url"] = DATABASE_URL

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
