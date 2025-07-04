# utils.py
import os
# utils.py
import os
import logging
import resend
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
    logger.info(f"Resend API key loaded: {RESEND_API_KEY[:10]}...{RESEND_API_KEY[-4:]}")
else:
    logger.error("RESEND_API_KEY environment variable not found")

# Get Frontend URL from environment
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
logger.info(f"Frontend URL configured as: {FRONTEND_URL}")

def get_db_session():
    """Dependency to get DB session for background tasks."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def send_magic_link_email(email: str, token: str):
    """Sends a magic link email to the user."""
    if not RESEND_API_KEY:
        logger.error("RESEND_API_KEY is not set. Cannot send email.")
        return

    magic_link = f"{FRONTEND_URL}/verify-email?token={token}"

    try:
        params = {
            "from": "SneakyGuy <support@mail.sneakyguy.com>",
            "to": [email],
            "subject": "Sign in to SneakyGuy",
            "html": f'<h3>Hello!</h3><p>Click the link below to finish signing in to SneakyGuy.</p><a href="{magic_link}">Sign in</a>'
        }
        email_response = resend.Emails.send(params)
        logger.info(f"Magic link email sent to {email}: {email_response['id']}")
    except Exception as e:
        logger.error(f"Failed to send magic link email to {email}: {e}")

