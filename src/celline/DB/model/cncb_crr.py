from dataclasses import dataclass
from typing import Final, Optional
import requests
import json
from celline.DB.dev.model import BaseModel, RunSchema


@dataclass
class CNCB_CRR_Schema(RunSchema):
    """CNCB Run (CRR/HRR/HRA) schema"""
    summary: str
    species: str


class CNCB_CRR(BaseModel[CNCB_CRR_Schema]):
    """CNCB Run (CRR/HRR/HRA) model with GWH REST API integration"""
    
    BASE_API_URL: Final[str] = "https://ngdc.cncb.ac.cn/gwh/gsa/ajax"
    BASE_WEB_URL: Final[str] = "https://ngdc.cncb.ac.cn/gsa"
    DOWNLOAD_BASE_URL: Final[str] = "https://download.cncb.ac.cn/gsa"

    def set_class_name(self) -> str:
        return self.__class__.__name__

    def def_schema(self) -> type[CNCB_CRR_Schema]:
        return CNCB_CRR_Schema
    
    @classmethod
    def _determine_run_type(cls, run_id: str) -> str:
        """Determine run type based on accession prefix"""
        if run_id.startswith("CRR"):
            return "public"  # Public data
        elif run_id.startswith(("HRR", "HRA")):
            return "restricted"  # Restricted/controlled access
        else:
            return "unknown"
    
    @classmethod
    def _fetch_run_metadata(cls, run_id: str) -> dict:
        """Fetch Run metadata from CNCB GWH API with comprehensive error handling"""
        # Validate run ID format
        if not run_id.startswith(("CRR", "HRR", "HRA")):
            raise ValueError(f"Invalid CNCB run ID format: {run_id}. Must start with 'CRR', 'HRR', or 'HRA'")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Try Run API endpoint
                url = f"{cls.BASE_API_URL}/getRunByAccession"
                params = {"accession": run_id}
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if data and "data" in data and data["data"]:
                            run_data = data["data"]
                            if isinstance(run_data, dict) and run_data.get("accession") == run_id:
                                return run_data
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid JSON response for {run_id} (attempt {attempt + 1}): {e}")
                
                elif response.status_code == 404:
                    # Try experiment-based search for 404s
                    break
                elif response.status_code >= 500:
                    print(f"Warning: Server error for {run_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching {run_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
        
        # Fallback to experiment-based search
        try:
            return cls._fetch_run_via_experiment(run_id)
        except Exception as e:
            print(f"Warning: Both direct and experiment-based search failed for {run_id}: {e}")
        
        return {
            "accession": run_id,
            "title": f"CNCB Run {run_id}",
            "description": "Metadata unavailable - all fetch methods failed",
            "organism": "Unknown",
            "experiment_id": "",
            "biosample_id": "",
            "files": []
        }
    
    @classmethod
    def _fetch_run_via_experiment(cls, run_id: str) -> dict:
        """Fetch run metadata via experiment search"""
        try:
            url = f"{cls.BASE_API_URL}/searchRun"
            params = {"query": run_id}
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data and "data" in data and isinstance(data["data"], list):
                    for run in data["data"]:
                        if run.get("accession") == run_id:
                            return run
        except Exception as e:
            print(f"Warning: Experiment-based search failed for {run_id}: {e}")
        
        return {
            "accession": run_id,
            "title": f"CNCB Run {run_id}",
            "description": "Metadata unavailable",
            "organism": "Unknown",
            "experiment_id": "",
            "biosample_id": "",
            "files": []
        }
    
    @classmethod
    def _fetch_run_files(cls, run_id: str) -> list[dict]:
        """Fetch file information for the run with error handling"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"{cls.BASE_API_URL}/getFilesByRun"
                params = {"run": run_id}
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if data and "data" in data and isinstance(data["data"], list):
                            # Validate file information
                            valid_files = []
                            for file_info in data["data"]:
                                if isinstance(file_info, dict) and file_info.get("filename"):
                                    # Ensure required fields exist
                                    file_data = {
                                        "filename": file_info.get("filename", ""),
                                        "filetype": file_info.get("filetype", "unknown"),
                                        "filesize": file_info.get("filesize", 0),
                                        "checksum": file_info.get("checksum", "")
                                    }
                                    valid_files.append(file_data)
                            return valid_files
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid JSON response for files of {run_id} (attempt {attempt + 1}): {e}")
                
                elif response.status_code == 404:
                    print(f"Warning: No files found for run {run_id}")
                    return []
                elif response.status_code >= 500:
                    print(f"Warning: Server error fetching files for {run_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching files for {run_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
            except Exception as e:
                print(f"Warning: Unexpected error fetching files for {run_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    continue
        
        print(f"Warning: Failed to fetch files for run {run_id} after {max_retries} attempts")
        return []
    
    @classmethod
    def _determine_strategy(cls, files: list[dict]) -> str:
        """Determine sequencing strategy from file information"""
        for file_info in files:
            filename = file_info.get("filename", "").lower()
            file_type = file_info.get("filetype", "").lower()
            
            if "bam" in filename or "bam" in file_type:
                return "bam"
            elif any(ext in filename for ext in ["fastq", "fq", ".gz"]):
                return "fastq"
            elif "sra" in filename or "sra" in file_type:
                return "sra"
        
        return "fastq"  # Default assumption
    
    @classmethod
    def _build_download_urls(cls, run_id: str, files: list[dict]) -> list[str]:
        """Build download URLs for run files with validation"""
        if not files:
            print(f"Warning: No files provided for URL building for {run_id}")
            return []
        
        urls = []
        run_type = cls._determine_run_type(run_id)
        
        try:
            for file_info in files:
                if not isinstance(file_info, dict):
                    continue
                    
                filename = file_info.get("filename", "")
                if not filename:
                    print(f"Warning: Empty filename in file info for {run_id}")
                    continue
                
                # Validate filename format
                if not cls._is_valid_filename(filename):
                    print(f"Warning: Invalid filename format: {filename}")
                    continue
                
                try:
                    if run_type == "public":
                        # Public CRR data - extract numeric part
                        numeric_part = run_id[3:]  # Remove 'CRR' prefix
                        if not numeric_part.isdigit():
                            print(f"Warning: Invalid CRR ID format for URL building: {run_id}")
                            continue
                        url = f"{cls.DOWNLOAD_BASE_URL}/CRR{numeric_part}/{filename}"
                    else:
                        # Restricted HRR/HRA data (requires authentication)
                        url = f"{cls.DOWNLOAD_BASE_URL}/{run_id}/{filename}"
                    
                    urls.append(url)
                    
                except Exception as e:
                    print(f"Warning: Failed to build URL for file {filename} in run {run_id}: {e}")
                    continue
        
        except Exception as e:
            print(f"Warning: Error building download URLs for {run_id}: {e}")
        
        return urls
    
    @classmethod
    def _is_valid_filename(cls, filename: str) -> bool:
        """Validate filename format"""
        if not filename or len(filename) > 255:
            return False
        
        # Check for common file extensions
        valid_extensions = {
            '.fastq', '.fq', '.fastq.gz', '.fq.gz',
            '.bam', '.sam', '.cram',
            '.sra', '.tar', '.tar.gz'
        }
        
        return any(filename.lower().endswith(ext) for ext in valid_extensions)

    def search(self, acceptable_id: str, force_search=False) -> CNCB_CRR_Schema:
        """Search for CNCB Run by accession ID"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        
        # Fetch run metadata and files
        metadata = self._fetch_run_metadata(acceptable_id)
        files = self._fetch_run_files(acceptable_id)
        
        # Determine strategy and build download URLs
        strategy = self._determine_strategy(files)
        download_urls = self._build_download_urls(acceptable_id, files)
        
        return self.add_schema(
            CNCB_CRR_Schema(
                key=acceptable_id,
                parent=metadata.get("biosample_id") or metadata.get("experiment_id"),
                children=None,  # Runs are leaf nodes
                title=metadata.get("title", f"CNCB Run {acceptable_id}"),
                strategy=strategy,
                raw_link=",".join(download_urls) if download_urls else "",
                summary=metadata.get("description", "Summary unavailable"),
                species=metadata.get("organism", "Unknown")
            )
        )
