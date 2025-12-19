from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime,timedelta,timezone

# debugpy.wait_for_client()
app = FastAPI(
    title="CV/Resume Evaluation Orchestrator API",
    version="0.0.1",
    description=(
        "Microservices for CV/Resume evaluation orchestrator (In progress krub)"
    ),
    contact={
        "name": "Tun Kedsaro",
        "email": "tun.k@terradigitalventures.com"
    },
)
origins = [
    "*"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the API endpoints
@app.get('/')
def health():
    return {
        "message": "OK now can update"
    }

@app.get('/v1/orchestrator/evaluate-cvresume')
def evaluate_cv():
    return {
        "message": "OK now can update"
    }