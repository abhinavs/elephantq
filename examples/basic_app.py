from fastapi import FastAPI

import soniq

await soniq.configure(database_url="postgresql://localhost/myapp")

app = FastAPI()


@soniq.job()
async def process_upload(file_path: str):
    return f"Processed {file_path}"


@app.post("/upload")
async def upload(file_path: str):
    job_id = await soniq.enqueue(process_upload, file_path=file_path)
    return {"job_id": job_id}
