from fastapi import FastAPI
from .database import create_db_and_tables
from .routers import user, verification_code, friend_request

app = FastAPI()

app.include_router(user.router)
app.include_router(verification_code.router)
app.include_router(friend_request.router)


@app.get("/")
def hello_world():
    return "Hello world"

@app.on_event("startup")
def on_startup():
    create_db_and_tables()