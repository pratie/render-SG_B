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
from models import User, PlanSelectionInput, PlanSelectionResponse
from auth.router import get_current_user

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payment", tags=["payment"])

# Pricing configuration
PRICING_PLANS = {
    "monthly": {
        "price": "$9/month",
        "duration_months": 1,
        "env_key": "DODO_MONTHLY_PRODUCT_ID"  # You'll need to add this to .env
    },
    "6month": {
        "price": "$39/6 months",
        "duration_months": 6,
        "env_key": "DODO_6MONTH_PRODUCT_ID"  # You'll need to add this to .env
    },
    "annual": {
        "price": "$69/year",
        "duration_months": 12,
        "env_key": "DODO_ANNUAL_PRODUCT_ID"  # You'll need to add this to .env
    }
}

def check_user_has_active_subscription(user: User) -> bool:
    """Check if user has an active paid subscription."""
    if not user.has_paid or user.subscription_plan == "none":
        return False
    
    # Check if subscription has expired
    if user.plan_expires_at and user.plan_expires_at < datetime.utcnow():
        return False
    
    return True

@router.get("/subscription-required")
async def check_subscription_access(
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check if user has access to paid features."""
    user = db.query(User).filter(User.email == current_user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    has_access = check_user_has_active_subscription(user)
    
    return {
        "has_access": has_access,
        "subscription_plan": user.subscription_plan,
        "plan_expires_at": user.plan_expires_at,
        "message": "Active subscription required" if not has_access else "Access granted"
    }

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
            "subscription_plan": user.subscription_plan,
            "plan_expires_at": user.plan_expires_at,
        }
    except Exception as e:
        logger.error(f"Error checking payment status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans")
async def get_pricing_plans():
    """Get available pricing plans - paid only, no free tier."""
    return {
        "plans": [
            {
                "id": "monthly",
                "name": "Monthly",
                "price": "$9",
                "billing": "per month",
                "duration": "1 month",
                "savings": None,
                "description": "Perfect for trying out"
            },
            {
                "id": "6month",
                "name": "6 Months", 
                "price": "$39",
                "billing": "every 6 months",
                "duration": "6 months",
                "savings": "Save 28%",
                "description": "Great for growing businesses"
            },
            {
                "id": "annual",
                "name": "Annual",
                "price": "$69", 
                "billing": "per year",
                "duration": "12 months",
                "savings": "Save 36%",
                "popular": True,
                "description": "Best value for serious growth"
            }
        ],
        "note": "All plans include full access to Reddit monitoring and AI-powered commenting"
    }

@router.post("/create-checkout-session", response_model=PlanSelectionResponse)
async def create_checkout_session(
    plan_selection: PlanSelectionInput,
    current_user_email: str = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a Dodo Payments checkout session for selected plan."""
    try:
        # Validate plan selection
        if plan_selection.plan not in PRICING_PLANS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid plan. Available plans: {list(PRICING_PLANS.keys())}"
            )
        
        plan_config = PRICING_PLANS[plan_selection.plan]
        
        # Reload environment variables for each request
        load_dotenv(override=True)
        
        # Get Dodo Payments configuration
        dodo_api_key = os.getenv('DODO_PAYMENTS_API_KEY')
        dodo_product_id = os.getenv(plan_config["env_key"])
        
        logger.info(f"Using plan: {plan_selection.plan}")
        logger.info(f"Plan config: {plan_config}")
        logger.info(f"Env key: {plan_config['env_key']}")
        logger.info(f"Using product ID: {dodo_product_id}")
        
        # Debug: Print all env vars to check if they're loaded correctly
        logger.info(f"Monthly ID: {os.getenv('DODO_MONTHLY_PRODUCT_ID')}")
        logger.info(f"6Month ID: {os.getenv('DODO_6MONTH_PRODUCT_ID')}")
        logger.info(f"Annual ID: {os.getenv('DODO_ANNUAL_PRODUCT_ID')}")

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
        
        # Store payment ID and selected plan in database for reference
        if hasattr(payment, 'id'):
            user = db.query(User).filter(User.email == current_user_email).first()
            if user:
                user.dodo_payment_id = payment.id
                # Store selected plan temporarily (will be finalized on successful payment)
                user.subscription_plan = f"pending_{plan_selection.plan}"
                db.commit()
                logger.info(f"Stored Dodo payment ID: {payment.id} and plan: {plan_selection.plan} for user: {current_user_email}")
        
        logger.info(f"Created Dodo payment link: {payment.payment_link}")
        return {
            "checkout_url": payment.payment_link,
            "plan": plan_selection.plan,
            "price": plan_config["price"]
        }
        
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
            
            # Handle subscription plan from pending state
            if user.subscription_plan and user.subscription_plan.startswith("pending_"):
                selected_plan = user.subscription_plan.replace("pending_", "")
                user.subscription_plan = selected_plan
                
                # Calculate expiration date based on plan
                if selected_plan in PRICING_PLANS:
                    from datetime import timedelta
                    duration_months = PRICING_PLANS[selected_plan]["duration_months"]
                    user.plan_expires_at = user.payment_date + timedelta(days=duration_months * 30)
                    logger.info(f"Set plan expiration for {selected_plan}: {user.plan_expires_at}")
            
            # Store payment ID if provided
            if payment_id:
                user.dodo_payment_id = payment_id
                logger.info(f"Stored Dodo payment ID: {payment_id}")
            else:
                # Remove stripe_payment_id reference if no new payment ID
                user.stripe_payment_id = None
                
            db.commit()
            logger.info(f"Payment status UPDATED for user: {current_user_email} with plan: {user.subscription_plan}")
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
                    logger.info(f"Current subscription_plan: {user.subscription_plan}")
                    user.has_paid = True
                    user.payment_date = datetime.utcnow()
                    user.dodo_payment_id = payment_id
                    
                    # Handle subscription plan from pending state or product cart
                    if user.subscription_plan and user.subscription_plan.startswith("pending_"):
                        logger.info(f"Processing pending plan: {user.subscription_plan}")
                        selected_plan = user.subscription_plan.replace("pending_", "")
                        user.subscription_plan = selected_plan
                        
                        # Calculate expiration date based on plan
                        if selected_plan in PRICING_PLANS:
                            from datetime import timedelta
                            duration_months = PRICING_PLANS[selected_plan]["duration_months"]
                            user.plan_expires_at = user.payment_date + timedelta(days=duration_months * 30)
                            logger.info(f"Set plan expiration for {selected_plan}: {user.plan_expires_at}")
                    else:
                        # Fallback: determine plan from product cart in webhook
                        product_cart = payment_data.get("product_cart", [])
                        if product_cart:
                            product_id = product_cart[0].get("product_id")
                            logger.info(f"Determining plan from product_id: {product_id}")
                            
                            # Map product ID to plan
                            for plan_name, plan_config in PRICING_PLANS.items():
                                if os.getenv(plan_config["env_key"]) == product_id:
                                    user.subscription_plan = plan_name
                                    from datetime import timedelta
                                    duration_months = plan_config["duration_months"]
                                    user.plan_expires_at = user.payment_date + timedelta(days=duration_months * 30)
                                    logger.info(f"Mapped product {product_id} to plan: {plan_name}")
                                    break
                    
                    db.commit()
                    logger.info(f"Payment status UPDATED for user: {customer_email} via webhook with plan: {user.subscription_plan}")
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