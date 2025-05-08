from fastapi import APIRouter, Depends, HTTPException, Request, Header, Body
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict
from dodopayments import DodoPayments
from standardwebhooks import Webhook
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
    """Create a Dodo Payments checkout session."""
    try:
        # Reload environment variables for each request
        load_dotenv(override=True)
        
        # Get Dodo Payments configuration
        dodo_api_key = os.getenv('DODO_PAYMENTS_API_KEY')
        dodo_product_id = os.getenv('DODO_product_id')
        
        logger.info(f"Using product ID: {dodo_product_id}")

        if not dodo_api_key or not dodo_product_id:
            raise HTTPException(
                status_code=500,
                detail="Dodo Payments configuration is not properly set up"
            )

        logger.info(f"Creating checkout session for user: {current_user_email}")
        
        # Initialize Dodo Payments client according to documentation
        client = DodoPayments(
            bearer_token=dodo_api_key,
            environment="test_mode" if os.getenv("ENV", "development").lower() == "development" else "live_mode"
        )
        
        # Log the API key format for debugging (masking most of it)
        if dodo_api_key:
            masked_key = dodo_api_key[:5] + "..." + dodo_api_key[-5:] if len(dodo_api_key) > 10 else "***"
            logger.info(f"Using API key format: {masked_key}")
        
        # Create payment link
        payment = client.payments.create(
            payment_link=True,
            billing={
                "city": "New York",
                "country": "US",
                "state": "NY",
                "street": "123 Example Street",
                "zipcode": 10001,
            },
            customer={
                "email": current_user_email,
                "name": current_user_email.split('@')[0],  # Use part of email as name
            },
            product_cart=[
                {
                    "product_id": dodo_product_id,
                    "quantity": 1
                }
            ],
            return_url=os.getenv("DODO_SUCCESS_URL", "http://localhost:3000/projects?payment=success")
        )
        
        # Store payment ID in database for reference
        if hasattr(payment, 'id'):
            user = db.query(User).filter(User.email == current_user_email).first()
            if user:
                user.dodo_payment_id = payment.id
                db.commit()
                logger.info(f"Stored Dodo payment ID: {payment.id} for user: {current_user_email}")
        
        logger.info(f"Created Dodo payment link: {payment.payment_link}")
        return {"checkout_url": payment.payment_link}
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/success")
async def payment_success(
    payment_data: dict = Body(None),
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user payment status after successful payment."""
    try:
        logger.info(f"===== PAYMENT SUCCESS ENDPOINT CALLED =====")
        logger.info(f"Processing successful payment for user: {current_user_email}")
        
        # Extract payment ID from request body if provided
        payment_id = None
        if payment_data and "paymentId" in payment_data:
            payment_id = payment_data["paymentId"]
            logger.info(f"Payment ID received from frontend: {payment_id}")
        
        user = db.query(User).filter(User.email == current_user_email).first()
        if not user:
            logger.error(f"User not found: {current_user_email}")
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"Current payment status - has_paid: {user.has_paid}, payment_date: {user.payment_date}")
        
        # Only update if not already paid
        if not user.has_paid:
            user.has_paid = True
            user.payment_date = datetime.utcnow()
            
            # Store payment ID if provided
            if payment_id:
                user.dodo_payment_id = payment_id
                logger.info(f"Stored Dodo payment ID: {payment_id}")
            else:
                # Remove stripe_payment_id reference if no new payment ID
                user.stripe_payment_id = None
                
            db.commit()
            logger.info(f"Payment status UPDATED for user: {current_user_email}")
        else:
            logger.info(f"User already paid, no update needed: {current_user_email}")
        
        return {"status": "success", "message": "Payment status updated successfully"}
    except Exception as e:
        logger.error(f"Error updating payment status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/webhook/")
async def dodo_webhook(
    request: Request,
    webhook_id: str = Header(None),
    webhook_signature: str = Header(None),
    webhook_timestamp: str = Header(None),
    db: Session = Depends(get_db)
):
    """Handle Dodo Payments webhook events."""
    try:
        logger.info(f"===== WEBHOOK ENDPOINT CALLED =====")
        logger.info(f"Webhook headers - ID: {webhook_id}, Timestamp: {webhook_timestamp}")
        
        # Load webhook secret
        webhook_secret = os.getenv("DODO_PAYMENTS_WEBHOOK_SECRET")
        if not webhook_secret:
            logger.error("Webhook secret not configured")
            raise HTTPException(status_code=500, detail="Webhook configuration error")
        
        # Initialize webhook handler
        webhook_handler = Webhook(webhook_secret)
        
        # Get raw request body
        raw_body = await request.body()
        logger.info(f"Received webhook body of length: {len(raw_body)}")
        
        # Verify webhook signature
        try:
            webhook_handler.verify(
                raw_body,
                {
                    "webhook-id": webhook_id,
                    "webhook-signature": webhook_signature,
                    "webhook-timestamp": webhook_timestamp
                }
            )
            logger.info("Webhook signature verification SUCCESSFUL")
        except Exception as e:
            logger.error(f"Invalid webhook signature: {str(e)}")
            raise HTTPException(status_code=400, detail="Invalid webhook signature")
        
        # Parse payload
        payload = await request.json()
        event_type = payload.get("type")
        logger.info(f"Received Dodo webhook event type: {event_type}")
        logger.info(f"Webhook payload data: {payload.get('data', {})}")
        
        # Handle payment.succeeded event
        if event_type == "payment.succeeded":
            logger.info("Processing payment.succeeded event")
            # Extract payment ID and customer email from payload
            payment_data = payload.get("data", {})
            payment_id = payment_data.get("payment_id")  # Get payment_id directly from data
            customer_email = None
            customer_data = payment_data.get("customer", {})
            if customer_data:
                customer_email = customer_data.get("email")
            
            logger.info(f"Payment ID: {payment_id}, Customer Email: {customer_email}")
            
            if customer_email:
                # Update user payment status
                user = db.query(User).filter(User.email == customer_email).first()
                if user:
                    logger.info(f"Found user by email: {customer_email}")
                    logger.info(f"Current status - has_paid: {user.has_paid}, payment_date: {user.payment_date}")
                    user.has_paid = True
                    user.payment_date = datetime.utcnow()
                    user.dodo_payment_id = payment_id
                    db.commit()
                    logger.info(f"Payment status UPDATED for user: {customer_email} via webhook")
                else:
                    logger.error(f"User not found by email: {customer_email}")
            elif payment_id:
                # If email not found, try to find user by payment ID
                user = db.query(User).filter(User.dodo_payment_id == payment_id).first()
                if user:
                    logger.info(f"Found user by payment ID: {payment_id}")
                    logger.info(f"Current status - has_paid: {user.has_paid}, payment_date: {user.payment_date}")
                    user.has_paid = True
                    user.payment_date = datetime.utcnow()
                    db.commit()
                    logger.info(f"Payment status UPDATED for user with payment ID: {payment_id} via webhook")
                else:
                    logger.error(f"User not found by payment ID: {payment_id}")
            else:
                logger.error("No customer email or payment ID found in webhook payload")
        else:
            logger.info(f"Ignoring non-payment event: {event_type}")
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))