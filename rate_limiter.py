# rate_limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "100 per hour"]
)

async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Handler for rate limit exceeded exceptions"""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": "Too many analysis requests. Please try again later.",
            "retry_after_seconds": exc.retry_after
        }
    )

def get_analysis_rate_limit():
    """Rate limit specifically for analysis endpoints"""
    return limiter.limit(
        limit_value="30/minute",
        key_func=get_remote_address,
        error_message="Analysis API rate limit exceeded. Please wait before making another request."
    )