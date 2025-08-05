from typing import Union, Optional
from celline.DB.dev.handler import BaseHandler
from celline.DB.model import CNCB_PRJCA, CNCB_CRA, CNCB_CRR
from celline.log.logger import get_logger


class CNCBHandler(BaseHandler[CNCB_PRJCA, CNCB_CRA, CNCB_CRR]):
    """Handler for CNCB (China National Center for Bioinformation) accessions
    
    Supports:
    - PRJCA: BioProject accessions
    - SAMC: BioSample accessions  
    - CRX: Experiment accessions
    - CRR: Public run accessions
    - HRR/HRA: Restricted run accessions
    """
    
    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger(__name__)
    
    def resolver(self, acceptable_id: str) -> Optional[Union[CNCB_PRJCA, CNCB_CRA, CNCB_CRR]]:
        """Resolve CNCB accession ID to appropriate model class"""
        # Initialize model instances
        self._project = CNCB_PRJCA()
        self._sample = CNCB_CRA()  # SAMC accessions
        self._run = CNCB_CRR()     # CRR/HRR/HRA accessions
        
        # Project level - BioProject
        if acceptable_id.startswith("PRJCA"):
            self.logger.info(f"Resolved {acceptable_id} as CNCB BioProject")
            return CNCB_PRJCA
        
        # Sample level - BioSample
        elif acceptable_id.startswith("SAMC"):
            self.logger.info(f"Resolved {acceptable_id} as CNCB BioSample")
            return CNCB_CRA
        
        # Experiment level - map to sample for now since we don't have a separate CRX model
        elif acceptable_id.startswith("CRX"):
            self.logger.info(f"Resolved {acceptable_id} as CNCB Experiment (treating as sample)")
            return CNCB_CRA
        
        # Run level - Public runs
        elif acceptable_id.startswith("CRR"):
            self.logger.info(f"Resolved {acceptable_id} as CNCB public run")
            return CNCB_CRR
        
        # Run level - Restricted runs (Human/controlled access)
        elif acceptable_id.startswith(("HRR", "HRA")):
            self.logger.info(f"Resolved {acceptable_id} as CNCB restricted run")
            return CNCB_CRR
        
        # Unknown accession pattern
        else:
            self.logger.warning(f"Unknown CNCB accession pattern: {acceptable_id}")
            return None
    
    def download(self, acceptable_id: str, output_dir: str, **kwargs) -> bool:
        """Download CNCB data files
        
        Args:
            acceptable_id: CNCB accession ID
            output_dir: Directory to save downloaded files
            **kwargs: Additional download options
            
        Returns:
            bool: Success status
        """
        try:
            model_class = self.resolver(acceptable_id)
            if model_class is None:
                self.logger.error(f"Cannot resolve accession ID: {acceptable_id}")
                return False
            
            # Handle different types
            if model_class == CNCB_CRR:
                return self._download_run_data(acceptable_id, output_dir, **kwargs)
            elif model_class == CNCB_CRA:
                return self._download_sample_data(acceptable_id, output_dir, **kwargs)
            elif model_class == CNCB_PRJCA:
                return self._download_project_data(acceptable_id, output_dir, **kwargs)
            else:
                self.logger.error(f"Download not supported for {model_class}")
                return False
                
        except Exception as e:
            self.logger.error(f"Download failed for {acceptable_id}: {str(e)}")
            return False
    
    def _download_run_data(self, run_id: str, output_dir: str, **kwargs) -> bool:
        """Download run-level data (CRR/HRR/HRA) following Celline directory structure"""
        import os
        import urllib.request
        from pathlib import Path as PathLib
        from celline.utils.path import Path as CellinePath
        
        try:
            # Get run metadata and files
            run_data = self._run.search(run_id)
            if not run_data.raw_link:
                self.logger.warning(f"No download links available for {run_id}")
                return False
            
            # Determine parent sample ID for directory structure
            parent_sample_id = run_data.parent or run_id
            
            # Create Celline-style directory structure
            # For CNCB, we use the parent sample ID as project_id and sample_id
            celline_path = CellinePath(parent_sample_id, run_id)
            celline_path.prepare()
            
            # Create CNCB-specific structure: resources/{parent_sample}/{run_id}/raw/fastqs/
            fastq_dir = PathLib(celline_path.resources_sample_raw_fastqs)
            fastq_dir.mkdir(parents=True, exist_ok=True)
            
            # Also create a run-specific subdirectory
            run_subdir = fastq_dir / run_id
            run_subdir.mkdir(exist_ok=True)
            
            # Download each file
            urls = run_data.raw_link.split(",")
            success_count = 0
            
            for url in urls:
                if not url.strip():
                    continue
                    
                filename = url.split("/")[-1]
                output_path = run_subdir / filename
                
                try:
                    self.logger.info(f"Downloading {filename} from {url} to {output_path}")
                    urllib.request.urlretrieve(url, output_path)
                    success_count += 1
                    self.logger.info(f"Successfully downloaded {filename}")
                except Exception as e:
                    self.logger.error(f"Failed to download {filename}: {str(e)}")
            
            # Create a download manifest
            manifest_path = run_subdir / "download_manifest.txt"
            with open(manifest_path, 'w') as f:
                f.write(f"# CNCB Download Manifest for {run_id}\n")
                f.write(f"# Downloaded on: {self._get_timestamp()}\n")
                f.write(f"# Parent Sample: {parent_sample_id}\n")
                f.write(f"# Run Strategy: {run_data.strategy}\n")
                f.write(f"# Species: {run_data.species}\n")
                f.write("\n# Downloaded Files:\n")
                for url in urls:
                    if url.strip():
                        filename = url.split("/")[-1]
                        f.write(f"{filename}\t{url}\n")
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Run download failed for {run_id}: {str(e)}")
            return False
    
    def _download_sample_data(self, sample_id: str, output_dir: str, **kwargs) -> bool:
        """Download sample-level data (SAMC) - downloads all associated runs following Celline structure"""
        from celline.utils.path import Path as CellinePath
        from pathlib import Path as PathLib
        
        try:
            # Get sample metadata
            sample_data = self._sample.search(sample_id)
            if not sample_data.children:
                self.logger.warning(f"No runs found for sample {sample_id}")
                return False
            
            # Create sample-level directory structure
            # For CNCB samples, use parent project as project_id if available
            project_id = sample_data.parent or sample_id
            celline_path = CellinePath(project_id, sample_id)
            celline_path.prepare()
            
            # Create sample metadata file
            sample_info_path = PathLib(celline_path.data_sample) / "cncb_sample_info.txt"
            sample_info_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(sample_info_path, 'w') as f:
                f.write(f"# CNCB Sample Information for {sample_id}\n")
                f.write(f"# Downloaded on: {self._get_timestamp()}\n")
                f.write(f"Sample ID: {sample_id}\n")
                f.write(f"Title: {sample_data.title}\n")
                f.write(f"Summary: {sample_data.summary}\n")
                f.write(f"Species: {sample_data.species}\n")
                f.write(f"Parent Project: {sample_data.parent}\n")
                f.write(f"Associated Runs: {sample_data.children}\n")
            
            # Download all runs for this sample
            run_ids = sample_data.children.split(",")
            success_count = 0
            
            for run_id in run_ids:
                if run_id.strip():
                    if self._download_run_data(run_id.strip(), output_dir, **kwargs):
                        success_count += 1
            
            self.logger.info(f"Sample {sample_id}: Downloaded {success_count}/{len(run_ids)} runs successfully")
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Sample download failed for {sample_id}: {str(e)}")
            return False
    
    def _download_project_data(self, project_id: str, output_dir: str, **kwargs) -> bool:
        """Download project-level data (PRJCA) - downloads all associated samples/runs following Celline structure"""
        from celline.config import Config
        from pathlib import Path as PathLib
        
        try:
            # Get project metadata
            project_data = self._project.search(project_id)
            if not project_data.children:
                self.logger.warning(f"No samples found for project {project_id}")
                return False
            
            # Create project-level metadata file
            project_info_dir = PathLib(Config.PROJ_ROOT) / "data" / project_id
            project_info_dir.mkdir(parents=True, exist_ok=True)
            
            project_info_path = project_info_dir / "cncb_project_info.txt"
            with open(project_info_path, 'w') as f:
                f.write(f"# CNCB Project Information for {project_id}\n")
                f.write(f"# Downloaded on: {self._get_timestamp()}\n")
                f.write(f"Project ID: {project_id}\n")
                f.write(f"Title: {project_data.title}\n")
                f.write(f"Summary: {project_data.summary}\n")
                f.write(f"Associated Samples: {project_data.children}\n")
            
            # Download all samples for this project
            sample_ids = project_data.children.split(",")
            success_count = 0
            total_runs = 0
            
            for sample_id in sample_ids:
                if sample_id.strip():
                    if self._download_sample_data(sample_id.strip(), output_dir, **kwargs):
                        success_count += 1
                        # Count runs for this sample
                        try:
                            sample_data = self._sample.search(sample_id.strip())
                            if sample_data.children:
                                total_runs += len(sample_data.children.split(","))
                        except Exception:
                            pass
            
            self.logger.info(f"Project {project_id}: Downloaded {success_count}/{len(sample_ids)} samples successfully")
            self.logger.info(f"Total runs processed: {total_runs}")
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Project download failed for {project_id}: {str(e)}")
            return False
    
    def _get_timestamp(self) -> str:
        """Get current timestamp in standard format"""
        import datetime
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def create_directory_structure(self, project_id: str, sample_id: str) -> bool:
        """Create standard Celline directory structure for CNCB data
        
        This ensures CNCB data follows the same directory patterns as SRA data:
        - resources/{project_id}/{sample_id}/{raw,counted,src,logs}/
        - data/{project_id}/{sample_id}/{src,logs}/
        """
        try:
            from celline.utils.path import Path as CellinePath
            
            # Create standard Celline directory structure
            celline_path = CellinePath(project_id, sample_id)
            celline_path.prepare()
            
            self.logger.info(f"Created directory structure for CNCB data: {project_id}/{sample_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to create directory structure for {project_id}/{sample_id}: {str(e)}")
            return False
