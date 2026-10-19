from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import tasks, evaluations, projects

app = FastAPI(title="InternSim AI Backend", version="1.0.0")

# Configure CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:[0-9]+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(evaluations.router, prefix="/api/evaluations", tags=["evaluations"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])

@app.get("/")
def read_root():
    return {"message": "Welcome to InternSim AI API"}
