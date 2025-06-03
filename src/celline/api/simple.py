"""
Simple Celline Interactive Web API
Minimal implementation without heavy dependencies
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

# Simple toml alternative for basic parsing
def simple_toml_load(file_path):
    """Simple TOML parser for basic key=value pairs"""
    result = {}
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip().strip('"\'')
                    value = value.strip().strip('"\'')
                    result[key] = value
    except:
        pass
    return result

def simple_toml_dump(data, file_path):
    """Simple TOML writer for basic key=value pairs"""
    with open(file_path, 'w') as f:
        for key, value in data.items():
            f.write(f'{key} = "{value}"\n')

app = FastAPI(title="Celline Interactive API", version="1.0.0")

# Enable CORS for frontend - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class SampleInfo(BaseModel):
    id: str
    title: Optional[str] = None
    status: str = "pending"
    addedAt: datetime
    species: Optional[str] = None
    summary: Optional[str] = None

class ProjectInfo(BaseModel):
    name: str
    path: str
    samples: List[SampleInfo]
    
class AddSampleRequest(BaseModel):
    sample_ids: List[str]
    
class JobStatus(BaseModel):
    job_id: str
    status: str  # pending, running, completed, failed
    progress: float = 0.0
    message: str = ""
    created_at: datetime

# In-memory job tracking
active_jobs: Dict[str, JobStatus] = {}

@app.get("/")
async def root():
    return {"message": "Celline Interactive API", "status": "running"}

def get_current_project_path():
    """Get current project path from working directory"""
    current_dir = Path.cwd()
    
    # Look for setting.toml in current directory or parent directories
    for path in [current_dir] + list(current_dir.parents):
        setting_file = path / "setting.toml"
        if setting_file.exists():
            return str(path)
    
    # If no setting.toml found, return current directory
    return str(current_dir)

def create_default_project_structure(project_path: str):
    """Create default project structure if it doesn't exist"""
    try:
        project_dir = Path(project_path)
        
        # Create directories
        (project_dir / "data").mkdir(exist_ok=True)
        (project_dir / "results").mkdir(exist_ok=True)
        (project_dir / "resources").mkdir(exist_ok=True)
        (project_dir / "integration").mkdir(exist_ok=True)
        
        # Create default setting.toml
        setting_content = {
            "name": project_dir.name or "Celline Project",
            "version": "1.0.0",
            "description": "Interactive Celline Project"
        }
        
        setting_file = project_dir / "setting.toml"
        simple_toml_dump(setting_content, setting_file)
        
        # Create empty samples.toml
        samples_file = project_dir / "samples.toml"
        if not samples_file.exists():
            samples_file.write_text("# Celline samples configuration\n# Samples will be added automatically when you use 'Add Sample'\n")
        
        print(f"Created default project structure in {project_path}")
        
    except Exception as e:
        print(f"Warning: Could not create default project structure: {e}")

@app.get("/api/project", response_model=ProjectInfo)
async def get_project_info():
    """Get current project information and samples"""
    try:
        # Get current project path
        project_path = get_current_project_path()
        if not project_path:
            raise HTTPException(status_code=404, detail="No active project found")
        
        # If no setting.toml exists, create a basic one
        setting_file = os.path.join(project_path, "setting.toml")
        if not os.path.exists(setting_file):
            create_default_project_structure(project_path)
        
        # Read project settings
        settings = {}
        if os.path.exists(setting_file):
            try:
                settings = simple_toml_load(setting_file)
            except Exception as e:
                print(f"Warning: Error reading setting.toml: {e}")
        
        # Read samples
        samples_file = os.path.join(project_path, "samples.toml")
        samples_data = {}
        if os.path.exists(samples_file):
            try:
                samples_data = simple_toml_load(samples_file)
            except Exception as e:
                print(f"Warning: Error reading samples.toml: {e}")
        
        # Get sample statuses by checking directory structure
        samples = []
        for sample_id, sample_name in samples_data.items():
            if sample_id.startswith('#'):  # Skip comments
                continue
                
            sample_path = os.path.join(project_path, "resources", sample_id)
            data_path = os.path.join(project_path, "data", sample_id)
            
            # Determine sample status based on what exists
            status = "pending"
            if os.path.exists(os.path.join(data_path, "seurat.seurat")):
                status = "completed"
            elif os.path.exists(os.path.join(sample_path, "counted")):
                status = "processing"
            elif os.path.exists(os.path.join(sample_path, "raw")):
                status = "downloaded"
                
            samples.append(SampleInfo(
                id=sample_id,
                title=sample_name if sample_name != sample_id else None,
                status=status,
                addedAt=datetime.now()  # TODO: get actual creation time
            ))
        
        # Get project name with fallback
        project_name = settings.get("name", os.path.basename(project_path) or "Untitled Project")
        
        return ProjectInfo(
            name=project_name,
            path=project_path,
            samples=samples
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/samples/add")
async def add_samples(request: AddSampleRequest, background_tasks: BackgroundTasks):
    """Add new samples to the project"""
    try:
        print(f"[API] Add samples request received: {request.sample_ids}")
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id=job_id,
            status="pending",
            message="Adding samples...",
            created_at=datetime.now()
        )
        active_jobs[job_id] = job
        
        # Start background task
        print(f"[API] Starting background task for job {job_id}")
        background_tasks.add_task(run_add_samples, job_id, request.sample_ids)
        
        return {"job_id": job_id, "message": "Sample addition started"}
        
    except Exception as e:
        print(f"[API] Error in add_samples endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def run_add_samples(job_id: str, sample_ids: List[str]):
    """Background task to add samples using real Celline functions"""
    try:
        active_jobs[job_id].status = "running"
        active_jobs[job_id].message = "Adding samples to project..."
        
        # Use real Celline add function
        from celline.functions.add import Add
        from celline.interfaces import Project
        import concurrent.futures
        
        project_path = get_current_project_path()
        print(f"[API] Using project path: {project_path}")
        
        # Create a new project instance
        project = Project(project_path, "default")
        
        # Create SampleInfo objects for the add function
        sample_infos = [Add.SampleInfo(id=sample_id, title="") for sample_id in sample_ids]
        
        # Update job status with more detailed information
        active_jobs[job_id].message = f"Processing {len(sample_ids)} samples..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real add function in a thread pool to avoid blocking
        def run_add_sync():
            print(f"[API] Executing Add function for samples: {sample_ids}")
            add_function = Add(sample_infos)
            result = add_function.call(project)
            print(f"[API] Add function completed")
            return result
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_add_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully added {len(sample_ids)} samples to database"
        print(f"[API] Job {job_id} completed successfully")
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to add samples: {str(e)}"
        import traceback
        print(f"[API] Error in run_add_samples: {traceback.format_exc()}")

@app.post("/api/samples/{sample_id}/download")
async def download_sample(sample_id: str, background_tasks: BackgroundTasks):
    """Download sample data"""
    try:
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id=job_id,
            status="pending", 
            message="Starting download...",
            created_at=datetime.now()
        )
        active_jobs[job_id] = job
        
        background_tasks.add_task(run_download, job_id, sample_id)
        
        return {"job_id": job_id, "message": "Download started"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def run_download(job_id: str, sample_id: str):
    """Background task to download sample using real Celline functions"""
    try:
        active_jobs[job_id].status = "running"
        active_jobs[job_id].message = f"Downloading {sample_id}..."
        
        # Use real Celline download function
        from celline.functions.download import Download
        from celline.interfaces import Project
        import concurrent.futures
        
        project_path = get_current_project_path()
        print(f"[API] Using project path for download: {project_path}")
        
        project = Project(project_path, "default")
        
        # Update job status
        active_jobs[job_id].message = f"Downloading data for {sample_id}..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real download function in a thread pool
        def run_download_sync():
            print(f"[API] Executing Download function for sample: {sample_id}")
            download_function = Download()
            result = download_function.call(project)
            print(f"[API] Download function completed")
            return result
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_download_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully downloaded {sample_id}"
        print(f"[API] Download job {job_id} completed successfully")
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to download: {str(e)}"
        import traceback
        print(f"[API] Error in run_download: {traceback.format_exc()}")

@app.post("/api/samples/{sample_id}/count")
async def count_sample(sample_id: str, background_tasks: BackgroundTasks):
    """Run Cell Ranger count on sample"""
    try:
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id=job_id,
            status="pending",
            message="Starting count...",
            created_at=datetime.now()
        )
        active_jobs[job_id] = job
        
        background_tasks.add_task(run_count, job_id, sample_id)
        
        return {"job_id": job_id, "message": "Count started"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def run_count(job_id: str, sample_id: str):
    """Background task to run count using real Celline functions"""
    try:
        active_jobs[job_id].status = "running"
        active_jobs[job_id].message = f"Running count on {sample_id}..."
        
        # Use real Celline count function
        from celline.functions.count import Count
        from celline.interfaces import Project
        import concurrent.futures
        
        project_path = get_current_project_path()
        print(f"[API] Using project path for count: {project_path}")
        
        project = Project(project_path, "default")
        
        # Update job status
        active_jobs[job_id].message = f"Running Cell Ranger count on {sample_id}..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real count function in a thread pool
        def run_count_sync():
            print(f"[API] Executing Count function for sample: {sample_id}")
            count_function = Count()
            result = count_function.call(project)
            print(f"[API] Count function completed")
            return result
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_count_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully counted {sample_id}"
        print(f"[API] Count job {job_id} completed successfully")
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to count: {str(e)}"
        import traceback
        print(f"[API] Error in run_count: {traceback.format_exc()}")

@app.post("/api/samples/{sample_id}/preprocess")
async def preprocess_sample(sample_id: str, background_tasks: BackgroundTasks):
    """Run preprocessing/QC on sample"""
    try:
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id=job_id,
            status="pending",
            message="Starting preprocessing...",
            created_at=datetime.now()
        )
        active_jobs[job_id] = job
        
        background_tasks.add_task(run_preprocess, job_id, sample_id)
        
        return {"job_id": job_id, "message": "Preprocessing started"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def run_preprocess(job_id: str, sample_id: str):
    """Background task to run preprocessing using real Celline functions"""
    try:
        active_jobs[job_id].status = "running"
        active_jobs[job_id].message = f"Preprocessing {sample_id}..."
        
        # Use real Celline preprocess function
        from celline.functions.preprocess import Preprocess
        from celline.interfaces import Project
        import concurrent.futures
        
        project_path = get_current_project_path()
        print(f"[API] Using project path for preprocess: {project_path}")
        
        project = Project(project_path, "default")
        
        # Update job status
        active_jobs[job_id].message = f"Running QC and preprocessing on {sample_id}..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real preprocess function in a thread pool
        def run_preprocess_sync():
            print(f"[API] Executing Preprocess function for sample: {sample_id}")
            preprocess_function = Preprocess()
            result = preprocess_function.call(project)
            print(f"[API] Preprocess function completed")
            return result
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_preprocess_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully preprocessed {sample_id}"
        print(f"[API] Preprocess job {job_id} completed successfully")
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to preprocess: {str(e)}"
        import traceback
        print(f"[API] Error in run_preprocess: {traceback.format_exc()}")

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of a background job"""
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = active_jobs[job_id]
    print(f"[API] Job {job_id} status requested: {job.status} - {job.message}")
    return job

@app.get("/api/jobs", response_model=List[JobStatus])
async def get_all_jobs():
    """Get all job statuses"""
    return list(active_jobs.values())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)