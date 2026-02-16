import elephantq
from fastapi import FastAPI

elephantq.configure(database_url="postgresql://localhost/myapp")

app = FastAPI()

@elephantq.job()
async def process_upload(file_path: str):
    return f"Processed {file_path}"

@app.post("/upload")
async def upload(file_path: str):
    job_id = await elephantq.enqueue(process_upload, file_path=file_path)
    return {"job_id": job_id}
