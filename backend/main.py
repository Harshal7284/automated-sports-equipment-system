from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
from datetime import datetime, timezone
import uuid

# 1. Initialize FastAPI & Supabase Client
app = FastAPI(title="Automated Sports Equipment Issuance and Fine Autopay API")

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = "https://pyuupxyjvppkklymnfxx.supabase.co"
SUPABASE_KEY = "sb_publishable_weanlz_NF1LAy2G6goaOvg_W5Ic3eGn"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ==========================================
# 2. REQUEST DATA MODELS (Must be at the top)
# ==========================================
class IssueRequest(BaseModel):
    user_id: str
    equipment_id: int
    due_date: str

class ReturnRequest(BaseModel):
    transaction_id: int

class AddEquipment(BaseModel):
    name: str
    category: str
    total_stock: int
    daily_fine_rate: float

class UpdateEquipment(BaseModel):
    equipment_id: int
    name: str
    category: str
    total_stock: int
    daily_fine_rate: float

class AddUserRequest(BaseModel):
    uid: str
    name: str
    email: str
    initial_balance: float = Field(..., ge=150.0, description="Initial balance must be at least 150")

class UpdateUserRequest(BaseModel):
    user_id: str
    uid: str
    name: str
    email: str

class UpdateWalletRequest(BaseModel):
    user_id: str
    balance: float = Field(..., ge=0.0)

class ExchangeEquipment(BaseModel):
    transaction_id: int
    new_equipment_id: int


# ==========================================
# 3. API ENDPOINTS
# ==========================================

@app.get("/")
def home():
    return {"message": "Sports Equipment Autopay API is live!"}


# --- EQUIPMENT ENDPOINTS ---

@app.get("/equipment")
def get_equipment_catalog():
    res = supabase.table("equipment").select("*").execute()
    return {"data": res.data}

@app.post("/equipment/add")
def add_new_equipment(req: AddEquipment):
    data = {
        "name": req.name,
        "category": req.category,
        "total_stock": req.total_stock,
        "available_stock": req.total_stock,
        "daily_fine_rate": req.daily_fine_rate
    }
    res = supabase.table("equipment").insert(data).execute()
    return {"message": "Item added successfully", "data": res.data}

@app.put("/equipment/update")
def update_existing_equipment(req: UpdateEquipment):
    existing_item = supabase.table("equipment").select("*").eq("equipment_id", req.equipment_id).execute()
    if not existing_item.data:
        raise HTTPException(status_code=404, detail="Equipment ID not found.")
        
    old_total = existing_item.data[0]["total_stock"]
    old_available = existing_item.data[0]["available_stock"]
    stock_difference = req.total_stock - old_total
    new_available = old_available + stock_difference
    
    if new_available < 0:
        raise HTTPException(status_code=400, detail="Cannot reduce stock. Items are checked out!")

    data = {
        "name": req.name,
        "category": req.category,
        "total_stock": req.total_stock,
        "available_stock": new_available,
        "daily_fine_rate": req.daily_fine_rate
    }
    res = supabase.table("equipment").update(data).eq("equipment_id", req.equipment_id).execute()
    return {"message": "Item updated successfully", "data": res.data}

@app.delete("/equipment/delete/{equipment_id}")
def delete_equipment(equipment_id: int):
    res = supabase.table("equipment").delete().eq("equipment_id", equipment_id).execute()
    return {"message": f"Item {equipment_id} deleted successfully"}

@app.post("/equipment/issue")
def issue_equipment(req: IssueRequest):
    due_date = datetime.fromisoformat(req.due_date.replace('Z', '+00:00'))
    if due_date <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Due date must be in the future.")

    user = supabase.table("users").select("*").eq("user_id", req.user_id).execute()
    if not user.data or user.data[0]["account_status"] == "locked":
        raise HTTPException(status_code=400, detail="Account is locked or invalid.")

    item = supabase.table("equipment").select("*").eq("equipment_id", req.equipment_id).execute()
    if not item.data or item.data[0]["available_stock"] <= 0:
        raise HTTPException(status_code=400, detail="Item out of stock.")

    new_stock = item.data[0]["available_stock"] - 1
    supabase.table("equipment").update({"available_stock": new_stock}).eq("equipment_id", req.equipment_id).execute()

    now_iso = datetime.now(timezone.utc).isoformat()
    transaction = supabase.table("transactions").insert({
        "user_id": req.user_id,
        "equipment_id": req.equipment_id,
        "issue_date": now_iso,
        "due_date": req.due_date,
        "status": "issued"
    }).execute()

    return {"message": "Equipment issued successfully", "transaction": transaction.data}

@app.post("/equipment/return")
def return_equipment(req: ReturnRequest):
    tx = supabase.table("transactions").select("*").eq("transaction_id", req.transaction_id).execute()
    if not tx.data or tx.data[0]["status"] != "issued":
        raise HTTPException(status_code=400, detail="Invalid or closed transaction.")

    transaction = tx.data[0]
    user_id = transaction["user_id"]
    equipment_id = transaction["equipment_id"]
    due_date = datetime.fromisoformat(transaction["due_date"])
    now = datetime.now(timezone.utc)

    fine_amount = 0.0
    if now > due_date:
        days_late = (now - due_date).days + 1
        item = supabase.table("equipment").select("daily_fine_rate").eq("equipment_id", equipment_id).execute()
        rate = item.data[0]["daily_fine_rate"] if item.data else 10.0
        fine_amount = float(days_late * rate)

    item_data = supabase.table("equipment").select("available_stock").eq("equipment_id", equipment_id).execute()
    new_stock = item_data.data[0]["available_stock"] + 1
    supabase.table("equipment").update({"available_stock": new_stock}).eq("equipment_id", equipment_id).execute()

    current_balance = 0.0
    if fine_amount > 0:
        wallet = supabase.table("wallets").select("*").eq("user_id", user_id).execute()
        current_balance = wallet.data[0]["balance"] if wallet.data else 0.0

        if current_balance >= fine_amount:
            new_balance = current_balance - fine_amount
            supabase.table("wallets").update({"balance": new_balance}).eq("user_id", user_id).execute()
            supabase.table("autopay_logs").insert({
                "transaction_id": req.transaction_id, "user_id": user_id,
                "amount_deducted": fine_amount, "payment_status": "success"
            }).execute()
        else:
            supabase.table("users").update({"account_status": "locked"}).eq("user_id", user_id).execute()
            supabase.table("autopay_logs").insert({
                "transaction_id": req.transaction_id, "user_id": user_id,
                "amount_deducted": fine_amount, "payment_status": "failed_insufficient_funds"
            }).execute()

    supabase.table("transactions").update({
        "return_date": now.isoformat(), "fine_amount": fine_amount, "status": "returned"
    }).eq("transaction_id", req.transaction_id).execute()

    return {"message": "Equipment returned successfully", "fine_charged": fine_amount}


# --- USER ENDPOINTS ---

@app.get("/users")
def get_all_users():
    res = supabase.table("users").select("*").execute()
    return {"users": res.data}

@app.post("/users/add")
def add_user(req: AddUserRequest):
    generated_user_id = str(uuid.uuid4())
    user_data = {
        "user_id": generated_user_id,
        "uid": req.uid,
        "name": req.name,
        "email": req.email,
        "role": "student",
        "account_status": "active"
    }
    res = supabase.table("users").insert(user_data).execute()
    
    supabase.table("wallets").insert({
        "user_id": generated_user_id,
        "balance": req.initial_balance
    }).execute()

    return {"message": "User registered successfully!", "data": res.data}

@app.put("/users/update")
def update_user(req: UpdateUserRequest):
    data = {"uid": req.uid, "name": req.name, "email": req.email}
    res = supabase.table("users").update(data).eq("user_id", req.user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="User ID not found.")
    return {"message": "User updated successfully", "data": res.data}

@app.delete("/users/delete/{user_id}")
def delete_user(user_id: str):
    res = supabase.table("users").delete().eq("user_id", user_id).execute()
    return {"message": "User deleted successfully"}


# --- WALLETS, TRANSACTIONS & LOGS ENDPOINTS ---

@app.get("/wallets")
def get_all_wallets():
    res = supabase.table("wallets").select("*").execute()
    return {"wallets": res.data}

@app.put("/wallets/update")
def update_wallet_balance(req: UpdateWalletRequest):
    res = supabase.table("wallets").update({"balance": req.balance}).eq("user_id", req.user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Wallet not found for this user.")
    return {"message": "Wallet balance updated successfully!", "data": res.data}

@app.get("/transactions")
def get_all_transactions():
    res = supabase.table("transactions").select("*").execute()
    return {"transactions": res.data}

@app.put("/transactions/exchange")
def exchange_equipment(req: ExchangeEquipment):
    tx = supabase.table("transactions").select("*").eq("transaction_id", req.transaction_id).execute()
    if not tx.data or tx.data[0]["status"] != "issued":
        raise HTTPException(status_code=400, detail="Invalid or closed transaction.")
        
    old_eq_id = tx.data[0]["equipment_id"]
    if old_eq_id == req.new_equipment_id:
        return {"message": "No change needed."}

    new_item = supabase.table("equipment").select("*").eq("equipment_id", req.new_equipment_id).execute()
    if not new_item.data or new_item.data[0]["available_stock"] <= 0:
        raise HTTPException(status_code=400, detail="New item is out of stock.")

    old_item = supabase.table("equipment").select("available_stock").eq("equipment_id", old_eq_id).execute()
    new_old_stock = old_item.data[0]["available_stock"] + 1
    supabase.table("equipment").update({"available_stock": new_old_stock}).eq("equipment_id", old_eq_id).execute()

    new_new_stock = new_item.data[0]["available_stock"] - 1
    supabase.table("equipment").update({"available_stock": new_new_stock}).eq("equipment_id", req.new_equipment_id).execute()

    supabase.table("transactions").update({"equipment_id": req.new_equipment_id}).eq("transaction_id", req.transaction_id).execute()

    return {"message": "Transaction corrected and stock balanced successfully!"}

@app.get("/autopay_logs")
def get_autopay_logs():
    res = supabase.table("autopay_logs").select("*").execute()
    return {"autopay_logs": res.data}