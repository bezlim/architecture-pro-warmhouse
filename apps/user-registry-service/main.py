"""
User Registry & Billing Service
Manages user accounts, profiles, and billing for smart home devices
"""
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status, Depends
from pydantic import BaseModel, Field, EmailStr

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="User Registry & Billing Service",
    description="User management and billing service for smart home platform",
    version="1.0.0",
    openapi_url="/openapi.json"
)

# Environment variables
CORE_SERVICE_URL = os.getenv("CORE_SERVICE_URL", "http://core-service:8084")

# HTTP Client for inter-service communication
import httpx
http_client = httpx.AsyncClient(timeout=10.0)

# In-memory storage (will be replaced with PostgreSQL)
users_db: Dict[str, dict] = {}
billing_accounts_db: Dict[str, dict] = {}
transactions_db: List[dict] = []
subscriptions_db: Dict[str, dict] = {}

# ===========================================
# Models
# ===========================================

class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    phone: Optional[str] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None

class User(BaseModel):
    id: str
    email: str
    name: str
    phone: Optional[str] = None
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class BillingAccountCreate(BaseModel):
    user_id: str
    currency: str = "USD"

class BillingAccount(BaseModel):
    id: str
    user_id: str
    balance: float = 0.0
    currency: str
    status: str = "active"
    created_at: datetime = Field(default_factory=datetime.now)

class TransactionCreate(BaseModel):
    account_id: str
    amount: float
    type: str  # "charge", "credit", "payment", "refund"
    description: str
    metadata: Optional[Dict[str, Any]] = None

class Transaction(BaseModel):
    id: str
    account_id: str
    amount: float
    type: str
    description: str
    status: str = "completed"
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)

class SubscriptionPlan(BaseModel):
    id: str
    name: str
    price: float
    currency: str
    billing_period: str  # "monthly", "yearly"
    features: List[str]
    device_limit: int

class SubscriptionCreate(BaseModel):
    user_id: str
    plan_id: str

class Subscription(BaseModel):
    id: str
    user_id: str
    plan_id: str
    status: str  # "active", "cancelled", "expired"
    start_date: datetime
    end_date: Optional[datetime] = None
    auto_renew: bool = True

class HealthResponse(BaseModel):
    status: str
    service: str

# ===========================================
# Subscription Plans (default)
# ===========================================

DEFAULT_PLANS = {
    "free": SubscriptionPlan(
        id="free",
        name="Free",
        price=0.0,
        currency="USD",
        billing_period="monthly",
        features=["Basic device control", "Up to 5 devices"],
        device_limit=5
    ),
    "basic": SubscriptionPlan(
        id="basic",
        name="Basic",
        price=4.99,
        currency="USD",
        billing_period="monthly",
        features=["All Free features", "Up to 20 devices", "Mobile app access"],
        device_limit=20
    ),
    "pro": SubscriptionPlan(
        id="pro",
        name="Pro",
        price=9.99,
        currency="USD",
        billing_period="monthly",
        features=["All Basic features", "Unlimited devices", "Advanced automation", "Priority support"],
        device_limit=-1  # unlimited
    ),
}

# ===========================================
# Helper functions
# ===========================================

def get_user_or_404(user_id: str) -> User:
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**users_db[user_id])

def get_account_or_404(account_id: str) -> BillingAccount:
    if account_id not in billing_accounts_db:
        raise HTTPException(status_code=404, detail="Billing account not found")
    return BillingAccount(**billing_accounts_db[account_id])

# ===========================================
# Health check
# ===========================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if the service is running"""
    return HealthResponse(status="ok", service="user-registry-service")

# ===========================================
# User endpoints
# ===========================================

@app.post("/users", response_model=User, status_code=201)
async def create_user(user: UserCreate):
    """Create a new user account"""
    user_id = f"user_{uuid4().hex[:12]}"
    now = datetime.now()
    
    new_user = User(
        id=user_id,
        email=user.email,
        name=user.name,
        phone=user.phone,
        created_at=now,
        updated_at=now
    )
    
    users_db[user_id] = new_user.dict()
    
    # Create default billing account
    account_id = f"billing_{user_id}"
    billing_account = BillingAccount(
        id=account_id,
        user_id=user_id,
        currency="USD"
    )
    billing_accounts_db[account_id] = billing_account.dict()
    
    # Create free subscription
    subscription_id = f"sub_{user_id}"
    subscription = Subscription(
        id=subscription_id,
        user_id=user_id,
        plan_id="free",
        status="active",
        start_date=now
    )
    subscriptions_db[subscription_id] = subscription.dict()
    
    logger.info(f"Created user: {user_id} with email: {user.email}")
    return new_user

@app.get("/users", response_model=List[User])
async def get_users():
    """Get all users"""
    return [User(**u) for u in users_db.values()]

@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    """Get user by ID"""
    return get_user_or_404(user_id)

@app.put("/users/{user_id}", response_model=User)
async def update_user(user_id: str, user_update: UserUpdate):
    """Update user information"""
    user = get_user_or_404(user_id)
    
    if user_update.name:
        user.name = user_update.name
    if user_update.phone:
        user.phone = user_update.phone
    if user_update.email:
        user.email = user_update.email
    
    user.updated_at = datetime.now()
    users_db[user_id] = user.dict()
    
    return user

@app.delete("/users/{user_id}")
async def delete_user(user_id: str):
    """Delete user account"""
    if user_id not in users_db:
        raise HTTPException(status_code=404, detail="User not found")
    
    del users_db[user_id]
    return {"message": "User deleted successfully"}

# ===========================================
# Billing Account endpoints
# ===========================================

@app.get("/users/{user_id}/billing", response_model=BillingAccount)
async def get_billing_account(user_id: str):
    """Get billing account for user"""
    get_user_or_404(user_id)  # Validate user exists
    
    for account in billing_accounts_db.values():
        if account["user_id"] == user_id:
            return BillingAccount(**account)
    
    raise HTTPException(status_code=404, detail="Billing account not found")

@app.post("/users/{user_id}/billing/topup", response_model=Transaction)
async def topup_account(user_id: str, amount: float, description: str = "Account topup"):
    """Add funds to user billing account"""
    get_user_or_404(user_id)
    
    # Find billing account
    account = None
    for acc in billing_accounts_db.values():
        if acc["user_id"] == user_id:
            account = BillingAccount(**acc)
            break
    
    if not account:
        raise HTTPException(status_code=404, detail="Billing account not found")
    
    # Create transaction
    transaction_id = f"txn_{uuid4().hex[:12]}"
    transaction = Transaction(
        id=transaction_id,
        account_id=account.id,
        amount=amount,
        type="credit",
        description=description,
        status="completed"
    )
    transactions_db.append(transaction.dict())
    
    # Update balance
    account.balance += amount
    billing_accounts_db[account.id] = account.dict()
    
    return transaction

@app.get("/users/{user_id}/billing/transactions", response_model=List[Transaction])
async def get_transactions(user_id: str, limit: int = 50):
    """Get transaction history for user"""
    get_user_or_404(user_id)
    
    # Find billing account
    account_id = None
    for acc in billing_accounts_db.values():
        if acc["user_id"] == user_id:
            account_id = acc["id"]
            break
    
    if not account_id:
        raise HTTPException(status_code=404, detail="Billing account not found")
    
    # Get transactions
    user_transactions = [
        Transaction(**t) for t in transactions_db 
        if t["account_id"] == account_id
    ][-limit:]
    
    return user_transactions

# ===========================================
# Subscription endpoints
# ===========================================

@app.get("/subscriptions/plans", response_model=List[SubscriptionPlan])
async def get_subscription_plans():
    """Get available subscription plans"""
    return list(DEFAULT_PLANS.values())

@app.get("/users/{user_id}/subscription", response_model=Subscription)
async def get_user_subscription(user_id: str):
    """Get current subscription for user"""
    get_user_or_404(user_id)
    
    for sub in subscriptions_db.values():
        if sub["user_id"] == user_id:
            return Subscription(**sub)
    
    raise HTTPException(status_code=404, detail="Subscription not found")

@app.post("/users/{user_id}/subscription", response_model=Subscription)
async def change_subscription(user_id: str, subscription: SubscriptionCreate):
    """Change user subscription plan"""
    get_user_or_404(user_id)
    
    if subscription.plan_id not in DEFAULT_PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan ID")
    
    plan = DEFAULT_PLANS[subscription.plan_id]
    
    # Check if user has sufficient balance for paid plans
    if plan.price > 0:
        for acc in billing_accounts_db.values():
            if acc["user_id"] == user_id:
                if acc["balance"] < plan.price:
                    raise HTTPException(
                        status_code=402,
                        detail=f"Insufficient balance. Required: ${plan.price}"
                    )
                break
    
    # Cancel current subscription
    for sub_id, sub in subscriptions_db.items():
        if sub["user_id"] == user_id and sub["status"] == "active":
            sub["status"] = "cancelled"
            sub["end_date"] = datetime.now().isoformat()
    
    # Create new subscription
    new_sub_id = f"sub_{user_id}_{uuid4().hex[:8]}"
    now = datetime.now()
    
    if plan.billing_period == "monthly":
        end_date = now + timedelta(days=30)
    elif plan.billing_period == "yearly":
        end_date = now + timedelta(days=365)
    else:
        end_date = None
    
    new_subscription = Subscription(
        id=new_sub_id,
        user_id=user_id,
        plan_id=subscription.plan_id,
        status="active",
        start_date=now,
        end_date=end_date
    )
    
    subscriptions_db[new_sub_id] = new_subscription.dict()
    
    # Charge for subscription if paid plan
    if plan.price > 0:
        for acc in billing_accounts_db.values():
            if acc["user_id"] == user_id:
                acc["balance"] -= plan.price
                billing_accounts_db[acc["id"]] = acc
                
                # Create transaction
                transaction_id = f"txn_{uuid4().hex[:12]}"
                transaction = Transaction(
                    id=transaction_id,
                    account_id=acc["id"],
                    amount=plan.price,
                    type="charge",
                    description=f"Subscription: {plan.name}",
                    status="completed"
                )
                transactions_db.append(transaction.dict())
                break
    
    logger.info(f"User {user_id} changed subscription to {subscription.plan_id}")
    return new_subscription

# ===========================================
# OpenAPI and Swagger
# ===========================================

@app.get("/swagger/", include_in_schema=False)
async def get_swagger():
    """Serve Swagger UI"""
    from fastapi.responses import FileResponse
    return FileResponse("docs/index.html")


# ===========================================
# Core Service Integration (Device Management)
# ===========================================

@app.get("/users/{user_id}/devices", response_model=List[Dict[str, Any]])
async def get_user_devices(user_id: str):
    """Get all devices for a user from Core Service"""
    get_user_or_404(user_id)  # Validate user exists
    
    try:
        response = await http_client.get(f"{CORE_SERVICE_URL}/devices")
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to get devices from Core Service: {e}")
        raise HTTPException(status_code=503, detail="Core Service unavailable")


@app.post("/users/{user_id}/devices", status_code=201)
async def register_user_device(user_id: str, device_info: Dict[str, Any]):
    """Register a new device for user via Core Service"""
    get_user_or_404(user_id)  # Validate user exists
    
    # Check user subscription device limit
    subscription = None
    for sub in subscriptions_db.values():
        if sub["user_id"] == user_id and sub["status"] == "active":
            subscription = sub
            break
    
    if subscription:
        plan = DEFAULT_PLANS.get(subscription["plan_id"])
        if plan and plan.device_limit > 0:
            # Count current devices (would need to fetch from Core Service)
            # For now, just check if plan allows more devices
            pass
    
    try:
        # Add user_id to device metadata
        device_info["metadata"] = device_info.get("metadata", {})
        device_info["metadata"]["owner_id"] = user_id
        
        response = await http_client.post(
            f"{CORE_SERVICE_URL}/devices",
            json=device_info,
            timeout=10.0
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to register device in Core Service: {e}")
        raise HTTPException(status_code=503, detail="Core Service unavailable")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8086)
