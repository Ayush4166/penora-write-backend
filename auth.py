import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os
from fastapi import APIRouter, HTTPException  # <-- FIXED: Added HTTPException import!
from pydantic import BaseModel
from jose import jwt
import datetime
from google.oauth2 import id_token
from google.auth.transport import requests
import bcrypt
from pymongo import MongoClient

load_dotenv()

GMAIL_EMAIL = os.getenv("GMAIL_EMAIL")
GMAIL_PASSWORD = os.getenv("GMAIL_PASSWORD")

MONGO_URL = os.getenv("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client["penora_write"]

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
MAX_PASSWORD_LENGTH = 128
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
# Pydantic Models
class LoginRequest(BaseModel):
    username: str
    password: str

class SignupRequest(BaseModel):       # <-- Added signup support
    username: str
    password: str

class GoogleLoginRequest(BaseModel):
    credential: str

# Email sending function
def send_welcome_email(user_email, user_name):
    try:
        message = MIMEMultipart('alternative')
        message['Subject'] = 'Welcome to Penora Write!'
        message['From'] = GMAIL_EMAIL
        message['To'] = user_email

        text = f"""\
Hi {user_name},

Thank you for logging into Penora Write!

We're excited to have you on board. Start creating amazing stories with our AI-powered story generator today.

Best regards,
Penora Write Team
        """

        html = f"""\
<html>
  <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
    <div style="background-color: white; padding: 30px; border-radius: 10px; max-width: 600px; margin: 0 auto;">
      <h1 style="color: #333;">Welcome to Penora Write! 🎉</h1>
      <p style="font-size: 16px; color: #555;">Hi <strong>{user_name}</strong>,</p>
      <p style="font-size: 16px; color: #555;">
        Thank you for logging into <strong>Penora Write</strong>!
      </p>
      <p style="font-size: 16px; color: #555;">
        We're excited to have you on board. Start creating amazing stories with our AI-powered story generator today.
      </p>
      <div style="background-color: #f0f0f0; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <p style="color: #666; font-style: italic;">
          🚀 Tip: Try different story types - Funny, Sad, Adventure, Horror, Romance, and Sci-Fi!
        </p>
      </div>
      <p style="font-size: 14px; color: #888;">
        Best regards,<br/>
        <strong>Penora Write Team</strong>
      </p>
    </div>
  </body>
</html>
        """

        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        message.attach(part1)
        message.attach(part2)

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_EMAIL, GMAIL_PASSWORD)
            server.sendmail(GMAIL_EMAIL, user_email, message.as_string())
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

# Router
router = APIRouter()

# Signup endpoint (REGISTER new users)
@router.post('/signup')
def signup(request: SignupRequest):
    user = db.users.find_one({"username": request.username})
    if user:
        raise HTTPException(status_code=400, detail="User already exists")
    if not request.username or not request.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    hashed = bcrypt.hashpw(request.password.encode(), bcrypt.gensalt())
    db.users.insert_one({"username": request.username, "hashed_password": hashed})
    return {"message": "Account created!"}

# Login endpoint
@router.post('/login')
def login(request: LoginRequest):
    user = db.users.find_one({"username": request.username})
    
    if not user or not bcrypt.checkpw(request.password.encode(), user['hashed_password']):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = jwt.encode({
        'username': user['username'],
        'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    }, SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "email": user['username']
    }

# Google Login endpoint
@router.post('/google-login')
async def google_login(request: GoogleLoginRequest):
    try:
        idinfo = id_token.verify_oauth2_token(request.credential, requests.Request(), GOOGLE_CLIENT_ID)
        
        user_id = idinfo['sub']
        email = idinfo['email']
        name = idinfo.get('name', 'User')
        
        existing_user = db.users.find_one({"google_id": user_id})
        
        if not existing_user:
            new_user = {
                "username": email,
                "google_id": user_id,
                "name": name,
                "email": email,
                "created_at": datetime.datetime.utcnow()
            }
            db.users.insert_one(new_user)
            
            # Send welcome email to new user
            send_welcome_email(email, name)
        
        token = jwt.encode({
            'username': email,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        }, SECRET_KEY, algorithm=ALGORITHM)
        
        return {
            "access_token": token,
            "token_type": "bearer",
            "email": email
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
