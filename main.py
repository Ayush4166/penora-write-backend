from fastapi import FastAPI, Depends, HTTPException, Request, Body
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt, JWTError
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
import httpx
import os
from bson import ObjectId

from auth import router as auth_router, SECRET_KEY, ALGORITHM

load_dotenv()  # NEW: load .env

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes
app.include_router(auth_router)

# MongoDB (now from env)
MONGO_URL = os.getenv("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client["penora_write"]
stories_col = db["stories"]

# OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401, detail="Could not validate credentials"
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("username") or payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


# SAVE STORY
@app.post("/stories/save")
async def save_story(request: Request, token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    data = await request.json()
    print("SAVE_STORY_CALL", user, data)  # debug log

    story = data.get("story")
    story_type = data.get("story_type")
    title = data.get("title", "")

    stories_col.insert_one(
        {
            "username": user,
            "title": title,
            "story": story,
            "story_type": story_type,
            "saved_at": datetime.utcnow(),
        }
    )

    return {"msg": "Story saved!"}


# GET MY STORIES
@app.get("/stories/my")
async def get_my_stories(token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    result = list(stories_col.find({"username": user}))
    for item in result:
        item["_id"] = str(item["_id"])
        if isinstance(item.get("saved_at"), datetime):
            item["saved_at"] = item["saved_at"].isoformat()
    return {"stories": result}


# UPDATE STORY
@app.put("/stories/update/{story_id}")
async def update_story(
    story_id: str, data: dict = Body(...), token: str = Depends(oauth2_scheme)
):
    user = get_current_user(token)
    new_title = data.get("title", "")
    new_story = data.get("story", "")
    new_story_type = data.get("story_type", "")

    result = stories_col.update_one(
        {"_id": ObjectId(story_id), "username": user},
        {
            "$set": {
                "title": new_title,
                "story": new_story,
                "story_type": new_story_type,
                "updated_at": datetime.utcnow(),
            }
        },
    )

    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Story not found or not updated")

    return {"msg": "Story updated!"}


# DELETE STORY
@app.delete("/stories/delete/{story_id}")
async def delete_story(story_id: str, token: str = Depends(oauth2_scheme)):
    user = get_current_user(token)
    result = stories_col.delete_one({"_id": ObjectId(story_id), "username": user})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Story not found or not deleted")

    return {"msg": "Story deleted!"}


# GEMINI GENERATION – key from env only
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


@app.post("/generate")
async def generate_story(payload: dict = Body(...)):
    idea = payload.get("idea", "")
    story_type = payload.get("storyType", "short")
    tone = payload.get("tone", "neutral")
    length = payload.get("length", "medium")

    if length == "short":
        length_hint = "about 300 words"
    elif length == "long":
        length_hint = "at least 1500 words"
    else:
        length_hint = "about 800 words"

    prompt = f"Write a {tone} {story_type} of {length_hint} based on this idea: {idea}"

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}],
            }
        ]
    }
    params = {"key": GEMINI_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=60) as client_http:
            response = await client_http.post(
                url, headers=headers, params=params, json=payload
            )
            if response.status_code != 200:
                return {"story": f"Gemini API error: {response.text}"}
            data_resp = response.json()
            story = data_resp["candidates"][0]["content"]["parts"][0]["text"]
    except httpx.ReadTimeout:
        story = "Gemini request timed out. Please check internet/firewall or try a shorter prompt."
    except Exception as e:
        story = f"Gemini request failed: {str(e)}"

    return {"story": story}
