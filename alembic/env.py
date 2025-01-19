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

# Configure SQLite for different environments
if ENV == "production":
    DATABASE_URL = "sqlite:////data/reddit_analysis.db"
else:
    DATABASE_URL = "sqlite:///./reddit_analysis.db"

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

# Exclude SQLite system tables
def include_object(object, name, type_, reflected, compare_to):
    return not (type_ == "table" and name in ["sqlite_sequence", "sqlite_master"])

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Special handling for SQLite
    if DATABASE_URL.startswith("sqlite"):
        # Ensure the database directory exists
        db_path = DATABASE_URL.replace("sqlite:///", "")
        if db_path.startswith("/"):  # Absolute path
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        engine_config = {
            "sqlalchemy.url": DATABASE_URL,
            "sqlalchemy.poolclass": str(pool.StaticPool.__name__),
        }
        
        connectable = engine_from_config(
            engine_config,
            prefix="sqlalchemy.",
            poolclass=pool.StaticPool,
        )
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
