from logging.config import fileConfig
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# Add the parent directory to the Python path
parent_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.append(parent_dir)

# Load environment variables
load_dotenv()

# Import your models here
from models import Base

# this is the Alembic Config object
config = context.config

# Get environment (development or production)
ENV = os.getenv("ENV", "development")
IS_RENDER = os.getenv("RENDER", "false").lower() == "true"

# Get DATABASE_URL from environment, with absolute path for production
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    if ENV == "production" or IS_RENDER:
        DATABASE_URL = "sqlite:////var/data/reddit_analysis.db"
    else:
        DATABASE_URL = "sqlite:///./reddit_analysis.db"
else:
    # Ensure we're using absolute path in production
    if (ENV == "production" or IS_RENDER) and "sqlite://" in DATABASE_URL:
        if not DATABASE_URL.startswith("sqlite:////"):
            # Convert relative path to absolute
            db_path = DATABASE_URL.split("sqlite:///")[1]
            if not db_path.startswith("/"):
                DATABASE_URL = f"sqlite:////var/data/reddit_analysis.db"

print(f"Using DATABASE_URL: {DATABASE_URL}")
print(f"Current directory: {os.getcwd()}")
print(f"Parent directory: {parent_dir}")

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
    # Get database path from URL
    db_path = DATABASE_URL.split(":///")[-1]
    db_dir = os.path.dirname(db_path)
    
    print(f"Database path: {db_path}")
    print(f"Database directory: {db_dir}")
    
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
