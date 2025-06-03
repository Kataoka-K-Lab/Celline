"""
Celline Interactive Web API
FastAPI backend for Celline interactive frontend
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import os
import toml
import json
from pathlib import Path
import asyncio
import uuid
from datetime import datetime

# Import Celline modules
from celline.functions.add import Add
from celline.functions.download import Download  
from celline.functions.count import Count
from celline.functions.preprocess import Preprocess
from celline.functions.info import Info
from celline.interfaces import Project

app = FastAPI(title="Celline Interactive API", version="1.0.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080", "http://localhost:3000"],
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

# In-memory job tracking (for simplicity)
active_jobs: Dict[str, JobStatus] = {}

@app.get("/")
async def root():
    return {"message": "Celline Interactive API"}

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
            "project": {
                "name": project_dir.name or "Celline Project",
                "version": "1.0.0",
                "description": "Interactive Celline Project"
            },
            "analysis": {
                "wait_time": 2
            },
            "R": {
                "r_path": "/usr/bin/R"
            }
        }
        
        setting_file = project_dir / "setting.toml"
        with open(setting_file, 'w') as f:
            toml.dump(setting_content, f)
        
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
        setting_file = os.path.join(project_path, "setting.toml")
        settings = {}
        if os.path.exists(setting_file):
            try:
                with open(setting_file, 'r') as f:
                    settings = toml.load(f)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error reading setting.toml: {e}")
        
        # Read samples
        samples_file = os.path.join(project_path, "samples.toml")
        samples_data = {}
        if os.path.exists(samples_file):
            try:
                with open(samples_file, 'r') as f:
                    samples_data = toml.load(f)
            except Exception as e:
                # Log error but continue - samples.toml might be empty
                print(f"Warning: Error reading samples.toml: {e}")
                samples_data = {}
        
        # Get sample statuses by checking directory structure
        samples = []
        for sample_id, sample_name in samples_data.items():
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
                title=sample_name if isinstance(sample_name, str) else sample_id,
                status=status,
                addedAt=datetime.now()  # TODO: get actual creation time
            ))
        
        # Get project name with fallback
        project_name = settings.get("project", {}).get("name", os.path.basename(project_path) or "Untitled Project")
        
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
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id=job_id,
            status="pending",
            message="Adding samples...",
            created_at=datetime.now()
        )
        active_jobs[job_id] = job
        
        # Start background task
        background_tasks.add_task(run_add_samples, job_id, request.sample_ids)
        
        return {"job_id": job_id, "message": "Sample addition started"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def run_add_samples(job_id: str, sample_ids: List[str]):
    """Background task to add samples using real Celline functions"""
    try:
        active_jobs[job_id].status = "running"
        active_jobs[job_id].message = "Adding samples to project..."
        
        # Use real Celline add function
        project_path = get_current_project_path()
        project = Project(project_path, "Celline Interactive Project")
        
        # Create SampleInfo objects for the add function
        sample_infos = [Add.SampleInfo(id=sample_id, title="") for sample_id in sample_ids]
        
        # Create and execute the Add function
        add_function = Add(sample_infos)
        
        # Update job status with more detailed information
        active_jobs[job_id].message = f"Processing {len(sample_ids)} samples..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real add function in a thread pool to avoid blocking
        import concurrent.futures
        import asyncio
        
        def run_add_sync():
            return add_function.call(project)
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_add_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully added {len(sample_ids)} samples to database"
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to add samples: {str(e)}"
        import traceback
        print(f"Error in run_add_samples: {traceback.format_exc()}")

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
        project_path = get_current_project_path()
        project = Project(project_path, "Celline Interactive Project")
        
        # Create and execute the Download function
        download_function = Download()
        
        # Update job status
        active_jobs[job_id].message = f"Downloading data for {sample_id}..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real download function in a thread pool
        import concurrent.futures
        
        def run_download_sync():
            return download_function.call(project)
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_download_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully downloaded {sample_id}"
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to download: {str(e)}"
        import traceback
        print(f"Error in run_download: {traceback.format_exc()}")

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
        project_path = get_current_project_path()
        project = Project(project_path, "Celline Interactive Project")
        
        # Create and execute the Count function
        count_function = Count()
        
        # Update job status
        active_jobs[job_id].message = f"Running Cell Ranger count on {sample_id}..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real count function in a thread pool
        import concurrent.futures
        
        def run_count_sync():
            return count_function.call(project)
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_count_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully counted {sample_id}"
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to count: {str(e)}"
        import traceback
        print(f"Error in run_count: {traceback.format_exc()}")

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
        project_path = get_current_project_path()
        project = Project(project_path, "Celline Interactive Project")
        
        # Create and execute the Preprocess function
        preprocess_function = Preprocess()
        
        # Update job status
        active_jobs[job_id].message = f"Running QC and preprocessing on {sample_id}..."
        active_jobs[job_id].progress = 10.0
        
        # Execute the real preprocess function in a thread pool
        import concurrent.futures
        
        def run_preprocess_sync():
            return preprocess_function.call(project)
        
        # Run the synchronous Celline function in a thread pool
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            await loop.run_in_executor(pool, run_preprocess_sync)
        
        active_jobs[job_id].status = "completed"
        active_jobs[job_id].progress = 100.0
        active_jobs[job_id].message = f"Successfully preprocessed {sample_id}"
        
    except Exception as e:
        active_jobs[job_id].status = "failed"
        active_jobs[job_id].message = f"Failed to preprocess: {str(e)}"
        import traceback
        print(f"Error in run_preprocess: {traceback.format_exc()}")

@app.get("/api/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of a background job"""
    if job_id not in active_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return active_jobs[job_id]

@app.get("/api/jobs", response_model=List[JobStatus])
async def get_all_jobs():
    """Get all job statuses"""
    return list(active_jobs.values())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)