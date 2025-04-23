from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session
from models.models import User
from Authentication.functions import hash_password, verify_password, create_access_token, decode_token,send_email
from Authentication.inputs import UserCreate, ForgotPasswordRequest, ResetPasswordRequest
from database.database import get_db
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from datetime import timedelta
import logging
import random
from fastapi.responses import JSONResponse


router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@router.post("/signup")
def signup(user: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter((User.username == user.username) | (User.email == user.email)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")
    new_user = User(
        username=user.username,
        email=user.email,
        password_hash=hash_password(user.password),
        designation=user.designation
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User created successfully"}

@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user.username, "employee_id": user.employee_id})

    response = JSONResponse(content={"message": "Login successful"})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60, 
        expires=60 * 60,
        secure=False  
    )
    return response

@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Email not found")

    otp = str(random.randint(100000, 999999))
    payload = {"sub": user.email, "otp": otp}
    token = create_access_token(payload, expires_delta=timedelta(minutes=10))

    email_body = f"Hi {user.username},\n\nYour OTP for password reset is: {otp}\n\nThis OTP is valid for 10 minutes."
    send_email(user.email, "Your OTP for Password Reset", email_body)

    return {"message": "OTP has been sent to your email", "token": token}

@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    payload = decode_token(data.token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    email = payload.get("sub")
    token_otp = payload.get("otp")

    if email != data.email or token_otp != data.otp:
        raise HTTPException(status_code=400, detail="Invalid email or OTP")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "Password reset successful"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(
        key="access_token",
        path="/",         
        httponly=True,    
        samesite="lax"    
    )
    return {"message": "Logged out"}



# temp
from fastapi import Security

@router.get("/me")
def get_me(token: str = Depends(oauth2_scheme)):
    return {"message": "You're authenticated", "token": token}
