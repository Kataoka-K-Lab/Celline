from dataclasses import dataclass
from typing import Final, Optional
import requests
import json
from celline.DB.dev.model import BaseModel, SampleSchema


@dataclass
class CNCB_CRA_Schema(SampleSchema):
    """CNCB BioSample (SAMC) schema"""
    pass


class CNCB_CRA(BaseModel[CNCB_CRA_Schema]):
    """CNCB BioSample (SAMC) model with GWH REST API integration"""
    
    BASE_API_URL: Final[str] = "https://ngdc.cncb.ac.cn/gwh/gsa/ajax"
    BASE_WEB_URL: Final[str] = "https://ngdc.cncb.ac.cn/biosample/browse"

    def set_class_name(self) -> str:
        return self.__class__.__name__

    def def_schema(self) -> type[CNCB_CRA_Schema]:
        return CNCB_CRA_Schema
    
    @classmethod
    def _fetch_biosample_metadata(cls, sample_id: str) -> dict:
        """Fetch BioSample metadata from CNCB GWH API with comprehensive error handling"""
        # Validate sample ID format
        if not sample_id.startswith(("SAMC", "CRX")):
            raise ValueError(f"Invalid CNCB sample ID format: {sample_id}. Must start with 'SAMC' or 'CRX'")
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Try BioSample API endpoint
                url = f"{cls.BASE_API_URL}/getBioSampleByAccession"
                params = {"accession": sample_id}
                response = requests.get(url, params=params, timeout=30)
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if data and "data" in data and data["data"]:
                            sample_data = data["data"]
                            if isinstance(sample_data, dict) and sample_data.get("accession") == sample_id:
                                return sample_data
                    except (json.JSONDecodeError, KeyError) as e:
                        print(f"Warning: Invalid JSON response for {sample_id} (attempt {attempt + 1}): {e}")
                
                elif response.status_code == 404:
                    raise ValueError(f"CNCB sample {sample_id} not found (HTTP 404)")
                elif response.status_code >= 500:
                    print(f"Warning: Server error for {sample_id} (attempt {attempt + 1}): HTTP {response.status_code}")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(2 ** attempt)
                        continue
                
            except requests.RequestException as e:
                print(f"Warning: Network error fetching {sample_id} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(2 ** attempt)
                    continue
        
        # Fallback to web scraping
        try:
            return cls._scrape_biosample_metadata(sample_id)
        except Exception as e:
            print(f"Warning: Both API and web scraping failed for {sample_id}: {e}")
        
        return {
            "accession": sample_id,
            "title": f"CNCB BioSample {sample_id}",
            "description": "Metadata unavailable - API and web scraping failed",
            "organism": "Unknown",
            "bioproject_id": ""
        }
    
    @classmethod
    def _scrape_biosample_metadata(cls, sample_id: str) -> dict:
        """Fallback web scraping for biosample metadata"""
        try:
            from bs4 import BeautifulSoup
            url = f"{cls.BASE_WEB_URL}/{sample_id}"
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Extract metadata from the page
                title_elem = soup.find('td', text='Title')
                title = title_elem.find_next_sibling('td').get_text(strip=True) if title_elem else f"CNCB BioSample {sample_id}"
                
                desc_elem = soup.find('td', text='Description')
                description = desc_elem.find_next_sibling('td').get_text(strip=True) if desc_elem else "Description unavailable"
                
                organism_elem = soup.find('td', text='Organism')
                organism = organism_elem.find_next_sibling('td').get_text(strip=True) if organism_elem else "Unknown"
                
                project_elem = soup.find('td', text='BioProject')
                bioproject_id = project_elem.find_next_sibling('td').get_text(strip=True) if project_elem else ""
                
                return {
                    "accession": sample_id,
                    "title": title,
                    "description": description,
                    "organism": organism,
                    "bioproject_id": bioproject_id
                }
        except ImportError:
            print("Warning: BeautifulSoup not available for web scraping")
        except Exception as e:
            print(f"Warning: Web scraping failed for {sample_id}: {e}")
        
        return {
            "accession": sample_id,
            "title": f"CNCB BioSample {sample_id}",
            "description": "Metadata unavailable",
            "organism": "Unknown",
            "bioproject_id": ""
        }
    
    @classmethod
    def _fetch_sample_experiments(cls, sample_id: str) -> list[str]:
        """Fetch Experiment IDs (CRX) associated with the BioSample"""
        try:
            url = f"{cls.BASE_API_URL}/getExperimentsByBioSample"
            params = {"biosample": sample_id}
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data and "data" in data and isinstance(data["data"], list):
                    return [exp.get("accession", "") for exp in data["data"] if exp.get("accession")]
        except Exception as e:
            print(f"Warning: Failed to fetch experiments for sample {sample_id}: {e}")
        
        return []
    
    @classmethod
    def _fetch_sample_runs(cls, sample_id: str) -> list[str]:
        """Fetch Run IDs (CRR/HRR/HRA) associated with the BioSample with error handling"""
        try:
            # First get experiments, then get runs from experiments
            experiments = cls._fetch_sample_experiments(sample_id)
            if not experiments:
                print(f"Warning: No experiments found for sample {sample_id}")
                return []
            
            all_runs = []
            max_retries = 2  # Lower retries for nested calls
            
            for exp_id in experiments:
                if not exp_id.strip():
                    continue
                    
                for attempt in range(max_retries):
                    try:
                        url = f"{cls.BASE_API_URL}/getRunsByExperiment"
                        params = {"experiment": exp_id}
                        response = requests.get(url, params=params, timeout=30)
                        
                        if response.status_code == 200:
                            try:
                                data = response.json()
                                if data and "data" in data and isinstance(data["data"], list):
                                    # Validate and filter run IDs
                                    for run in data["data"]:
                                        if isinstance(run, dict) and run.get("accession"):
                                            run_id = run["accession"]
                                            # Validate CNCB run ID format
                                            if run_id.startswith(("CRR", "HRR", "HRA")):
                                                all_runs.append(run_id)
                                break  # Success, exit retry loop
                            except (json.JSONDecodeError, KeyError) as e:
                                print(f"Warning: Invalid JSON for runs of experiment {exp_id} (attempt {attempt + 1}): {e}")
                        
                        elif response.status_code == 404:
                            print(f"Warning: No runs found for experiment {exp_id}")
                            break  # Don't retry 404s
                        elif response.status_code >= 500 and attempt < max_retries - 1:
                            import time
                            time.sleep(1)  # Shorter delay for nested calls
                            continue
                        
                    except requests.RequestException as e:
                        print(f"Warning: Network error fetching runs for experiment {exp_id} (attempt {attempt + 1}): {e}")
                        if attempt < max_retries - 1:
                            import time
                            time.sleep(1)
                            continue
            
            return list(set(all_runs))  # Remove duplicates
            
        except Exception as e:
            print(f"Warning: Failed to fetch runs for sample {sample_id}: {e}")
            return []

    def search(self, acceptable_id: str, force_search=False) -> CNCB_CRA_Schema:
        """Search for CNCB BioSample by accession ID"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        
        # Fetch biosample metadata and associated runs
        metadata = self._fetch_biosample_metadata(acceptable_id)
        run_ids = self._fetch_sample_runs(acceptable_id)
        
        return self.add_schema(
            CNCB_CRA_Schema(
                key=acceptable_id,
                parent=metadata.get("bioproject_id") or None,
                children=",".join(run_ids) if run_ids else None,
                title=metadata.get("title", f"CNCB BioSample {acceptable_id}"),
                summary=metadata.get("description", "Summary unavailable"),
                species=metadata.get("organism", "Unknown"),
                raw_link=""  # CNCB doesn't typically provide direct raw data links at sample level
            )
        )
