from dataclasses import dataclass
from typing import Final, Optional
import requests
import json
from celline.DB.dev.model import BaseModel, BaseSchema


@dataclass
class CNCB_PRJCA_Schema(BaseSchema):
    summary: str


class CNCB_PRJCA(BaseModel[CNCB_PRJCA_Schema]):
    """CNCB BioProject (PRJCA) model with GWH REST API integration"""
    
    BASE_API_URL: Final[str] = "https://ngdc.cncb.ac.cn/gwh/gsa/ajax"
    BASE_WEB_URL: Final[str] = "https://ngdc.cncb.ac.cn/bioproject/browse"

    def set_class_name(self) -> str:
        return self.__class__.__name__

    def def_schema(self) -> type[CNCB_PRJCA_Schema]:
        return CNCB_PRJCA_Schema

    @classmethod
    def _fetch_project_metadata(cls, project_id: str) -> dict:
        """Fetch project metadata from CNCB GWH API with comprehensive error handling"""
        # Validate project ID format
        if not project_id.startswith("PRJCA"):
            raise ValueError(f"Invalid CNCB project ID format: {project_id}. Must start with 'PRJCA'")
        
        # Try multiple approaches with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # First try the BioProject API endpoint
                url = f"{cls.BASE_API_URL}/getBioProjectByAccession"
                params = {"accession": project_id}
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if data and "data" in data and data["data"]:
                            # Validate returned data structure
                            project_data = data["data"]
                            if isinstance(project_data, dict) and project_data.get("accession") == project_id:
                                return project_data
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid JSON response for {project_id} (attempt {attempt + 1}): {e}")
                
                elif response.status_code == 404:
                    raise ValueError(f"CNCB project {project_id} not found (HTTP 404)")
                elif response.status_code >= 500:
                    print(f"Warning: CNCB server error for {project_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching {project_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
        
        # Fallback to web scraping if API fails
        try:
            return cls._scrape_project_metadata(project_id)
        except Exception as e:
            print(f"Warning: Both API and web scraping failed for {project_id}: {e}")
        
        # Return minimal data structure as last resort
        return {
            "accession": project_id,
            "title": f"CNCB Project {project_id}",
            "description": "Metadata unavailable - API and web scraping failed",
            "biosample_ids": []
        }
    
    @classmethod
    def _scrape_project_metadata(cls, project_id: str) -> dict:
        """Fallback web scraping for project metadata"""
        try:
            from bs4 import BeautifulSoup
            url = f"{cls.BASE_WEB_URL}/{project_id}"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract title and summary from the page
                title_elem = soup.find('td', text='Title')
                title = title_elem.find_next_sibling('td').get_text(strip=True) if title_elem else f"CNCB Project {project_id}"
                
                summary_elem = soup.find('td', text='Description')
                summary = summary_elem.find_next_sibling('td').get_text(strip=True) if summary_elem else "Description unavailable"
                
                return {
                    "accession": project_id,
                    "title": title,
                    "description": summary,
                    "biosample_ids": []
                }
        except ImportError:
            print("Warning: BeautifulSoup not available for web scraping")
        except Exception as e:
            print(f"Warning: Web scraping failed for {project_id}: {e}")
        
        return {
            "accession": project_id,
            "title": f"CNCB Project {project_id}",
            "description": "Metadata unavailable",
            "biosample_ids": []
        }
    
    @classmethod 
    def _fetch_project_samples(cls, project_id: str) -> list[str]:
        """Fetch BioSample IDs associated with the project with error handling"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                url = f"{cls.BASE_API_URL}/getBioSamplesByBioProject"
                params = {"bioproject": project_id}
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if data and "data" in data and isinstance(data["data"], list):
                            # Validate and filter sample IDs
                            sample_ids = []
                            for sample in data["data"]:
                                if isinstance(sample, dict) and sample.get("accession"):
                                    acc_id = sample["accession"]
                                    # Validate CNCB sample ID format
                                    if acc_id.startswith(("SAMC", "CRX")):
                                        sample_ids.append(acc_id)
                            return sample_ids
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid JSON response for samples of {project_id} (attempt {attempt + 1}): {e}")
                
                elif response.status_code == 404:
                    print(f"Warning: No samples found for project {project_id} (HTTP 404)")
                    return []
                elif response.status_code >= 500:
                    print(f"Warning: Server error fetching samples for {project_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching samples for {project_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
            except Exception as e:
                print(f"Warning: Unexpected error fetching samples for {project_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    continue
        
        print(f"Warning: Failed to fetch samples for project {project_id} after {max_retries} attempts")
        return []

    def search(self, acceptable_id: str, force_search=False) -> CNCB_PRJCA_Schema:
        """Search for CNCB BioProject by accession ID"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        
        # Fetch project metadata and samples
        metadata = self._fetch_project_metadata(acceptable_id)
        sample_ids = self._fetch_project_samples(acceptable_id)
        
        return self.add_schema(
            CNCB_PRJCA_Schema(
                key=acceptable_id,
                parent=None,  # Projects are top-level
                children=",".join(sample_ids) if sample_ids else None,
                title=metadata.get("title", f"CNCB Project {acceptable_id}"),
                summary=metadata.get("description", "Summary unavailable")
            )
        )
