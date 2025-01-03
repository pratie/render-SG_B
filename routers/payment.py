from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict
import stripe
import logging
import os
from dotenv import load_dotenv

from database import get_db
from models import User
from auth.router import get_current_user

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["payment"])

@router.get("/status")
async def get_payment_status(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict:
    """Get the payment status for the current user."""
    try:
        user = db.query(User).filter(User.email == current_user_email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {
            "has_paid": user.has_paid,
            "payment_date": user.payment_date,
        }
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/create-checkout-session")
async def create_checkout_session(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a Stripe checkout session."""
    try:
        # Reload environment variables for each request
        load_dotenv(override=True)
        
        # Get fresh Stripe configuration
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        raw_product_id = os.getenv('STRIPE_PRODUCT_ID', '')
        STRIPE_PRODUCT_ID = raw_product_id.strip().split('#')[0].strip().replace('"', '').replace("'", '')
        
        logger.info(f"Raw Product ID: {raw_product_id}")
        logger.info(f"Cleaned Product ID: {STRIPE_PRODUCT_ID}")

        if not stripe.api_key or not STRIPE_PRODUCT_ID:
            raise HTTPException(
                status_code=500,
                detail="Stripe configuration is not properly set up"
            )

        logger.info(f"Creating checkout session for user: {current_user_email}")
        logger.info(f"Using product ID: {STRIPE_PRODUCT_ID}")

        # Create checkout session with an existing price
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product': STRIPE_PRODUCT_ID,
                    'unit_amount': 4900,  # $49.00
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=os.getenv('STRIPE_SUCCESS_URL', 'http://localhost:3000/projects?payment=success'),
            cancel_url=os.getenv('STRIPE_CANCEL_URL', 'http://localhost:3000/payment-cancelled'),
            client_reference_id=current_user_email,
            metadata={
                'user_email': current_user_email
            }
        )
        
        logger.info(f"Created checkout session: {checkout_session.id}")
        return {"checkout_url": checkout_session.url}
        
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/success")
async def payment_success(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user payment status after successful payment."""
    try:
        logger.info(f"Processing successful payment for user: {current_user_email}")
        user = db.query(User).filter(User.email == current_user_email).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Only update if not already paid
        if not user.has_paid:
            user.has_paid = True
            user.payment_date = datetime.utcnow()
            db.commit()
            logger.info(f"Payment status updated for user: {current_user_email}")
        
        return {"status": "success", "message": "Payment status updated successfully"}
    except Exception as e:
        logger.error(f"Error updating payment status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))