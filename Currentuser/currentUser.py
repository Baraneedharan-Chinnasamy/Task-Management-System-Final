from fastapi import HTTPException,Depends, Request
from database.database import get_db
from Authentication.functions import decode_token
from sqlalchemy.orm import Session
from models.models import User  # Adjust the import path based on your project structure

def get_current_user(request: Request,
    db: Session = Depends(get_db)):
    token = request.cookies.get("access_token")  # Make sure this matches the actual cookie name!
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated (token missing)")

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    employee_id = payload.get("employee_id")
    if employee_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user