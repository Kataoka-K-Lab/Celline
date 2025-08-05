"""
MAGE-TAB (Microarray Gene Expression Tabular) Parser

This module provides utilities for parsing ArrayExpress MAGE-TAB files:
- IDF (Investigation Design Format): Study-level metadata
- SDRF (Sample and Data Relationship Format): Sample-to-file mappings
- ADF (Array Design Format): Array/platform descriptions

Reference: https://www.ebi.ac.uk/arrayexpress/help/magetab_spec.html
"""

from typing import Dict, List, Tuple, Optional, Any
import requests
import pandas as pd
from dataclasses import dataclass
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class StudyMetadata:
    """Structured study metadata from IDF"""
    accession: str
    title: str
    description: str
    experiment_type: str
    organism: str
    pubmed_id: Optional[str] = None
    doi: Optional[str] = None
    release_date: Optional[str] = None
    submission_date: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    protocols: List[str] = None


@dataclass
class SampleMetadata:
    """Structured sample metadata from SDRF"""
    source_name: str
    sample_name: Optional[str] = None
    organism: Optional[str] = None
    tissue: Optional[str] = None
    cell_type: Optional[str] = None
    disease: Optional[str] = None
    treatment: Optional[str] = None
    age: Optional[str] = None
    sex: Optional[str] = None
    biosample_id: Optional[str] = None
    assay_names: List[str] = None
    ena_runs: List[str] = None


@dataclass
class AssayMetadata:
    """Structured assay metadata from SDRF"""
    assay_name: str
    source_name: str
    technology_type: Optional[str] = None
    array_design_ref: Optional[str] = None
    platform: Optional[str] = None
    data_files: List[str] = None
    ena_experiment: Optional[str] = None
    ena_run: Optional[str] = None


class MAGETABParser:
    """Parser for MAGE-TAB format files"""
    
    def __init__(self, base_url: str = "https://ftp.ebi.ac.uk/biostudies/arrayexpress"):
        self.base_url = base_url
        self.logger = logging.getLogger(__name__)
    
    def parse_study(self, study_id: str) -> Dict[str, Any]:
        """Parse complete MAGE-TAB for a study
        
        Args:
            study_id: ArrayExpress study accession (e.g., E-MTAB-12345)
            
        Returns:
            dict: Complete parsed metadata including IDF, SDRF, and structured data
        """
        try:
            ftp_path = self._construct_ftp_path(study_id)
            base_url = f"{self.base_url}/{ftp_path}"
            
            result = {
                "study_id": study_id,
                "study_metadata": None,
                "samples": {},
                "assays": {},
                "raw_data": {
                    "idf": {},
                    "sdrf_rows": [],
                    "adf": {}
                },
                "files": {
                    "data_files": [],
                    "processed_files": [],
                    "raw_files": []
                },
                "errors": []
            }
            
            # Parse IDF (Investigation Design Format)
            try:
                idf_url = f"{base_url}/{study_id}.idf.txt"
                idf_data = self._parse_idf(idf_url)
                result["raw_data"]["idf"] = idf_data
                result["study_metadata"] = self._extract_study_metadata(study_id, idf_data)
            except Exception as e:
                result["errors"].append(f"IDF parsing failed: {str(e)}")
                self.logger.error(f"IDF parsing failed for {study_id}: {e}")
            
            # Parse SDRF (Sample and Data Relationship Format)
            try:
                sdrf_url = f"{base_url}/{study_id}.sdrf.txt"
                sdrf_data, samples, assays, files = self._parse_sdrf(sdrf_url)
                result["raw_data"]["sdrf_rows"] = sdrf_data
                result["samples"] = samples
                result["assays"] = assays
                result["files"].update(files)
            except Exception as e:
                result["errors"].append(f"SDRF parsing failed: {str(e)}")
                self.logger.error(f"SDRF parsing failed for {study_id}: {e}")
            
            # Parse ADF (Array Design Format) if available
            try:
                # ADF files may have different names, try to detect from SDRF
                adf_refs = self._extract_adf_references(result["raw_data"]["sdrf_rows"])
                for adf_ref in adf_refs:
                    adf_url = f"{base_url}/{adf_ref}.adf.txt"
                    adf_data = self._parse_adf(adf_url)
                    if adf_data:
                        result["raw_data"]["adf"][adf_ref] = adf_data
            except Exception as e:
                result["errors"].append(f"ADF parsing failed: {str(e)}")
                self.logger.warning(f"ADF parsing failed for {study_id}: {e}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Complete MAGE-TAB parsing failed for {study_id}: {e}")
            return {"error": str(e), "study_id": study_id}
    
    def _construct_ftp_path(self, study_id: str) -> str:
        """Construct FTP path for study files"""
        if study_id.startswith("E-MTAB-"):
            number = study_id.split("-")[-1]
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-MTAB/{group}/{study_id}"
        elif study_id.startswith("E-GEOD-"):
            number = study_id.split("-")[-1]
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-GEOD/{group}/{study_id}"
        else:
            prefix = study_id.split("-")[1] if "-" in study_id else "UNKNOWN"
            number = study_id.split("-")[-1] if "-" in study_id else "000"
            group = number[-3:] if len(number) >= 3 else number
            return f"fire/E-{prefix}/{group}/{study_id}"
    
    def _parse_idf(self, idf_url: str) -> Dict[str, str]:
        """Parse IDF file"""
        try:
            response = requests.get(idf_url, timeout=60)
            if response.status_code != 200:
                raise Exception(f"IDF file not found: HTTP {response.status_code}")
            
            idf_data = {}
            lines = response.text.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if '\t' in line:
                    parts = line.split('\t', 1)
                    if len(parts) >= 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        if key and value:
                            idf_data[key] = value
            
            return idf_data
            
        except Exception as e:
            raise Exception(f"IDF parsing failed: {str(e)}")
    
    def _parse_sdrf(self, sdrf_url: str) -> Tuple[List[Dict], Dict[str, SampleMetadata], Dict[str, AssayMetadata], Dict[str, List]]:
        """Parse SDRF file"""
        try:
            response = requests.get(sdrf_url, timeout=60)
            if response.status_code != 200:
                raise Exception(f"SDRF file not found: HTTP {response.status_code}")
            
            lines = response.text.strip().split('\n')
            if len(lines) < 2:
                raise Exception("SDRF file is empty or malformed")
            
            headers = [h.strip() for h in lines[0].split('\t')]
            rows = []
            samples = {}
            assays = {}
            files = {"data_files": [], "processed_files": [], "raw_files": []}
            
            # Process each data row
            for line_num, line in enumerate(lines[1:], 2):
                try:
                    fields = [f.strip() for f in line.split('\t')]
                    if len(fields) != len(headers):
                        self.logger.warning(f"SDRF line {line_num}: field count mismatch")
                        # Pad with empty strings or truncate
                        while len(fields) < len(headers):
                            fields.append("")
                        fields = fields[:len(headers)]
                    
                    row_data = dict(zip(headers, fields))
                    rows.append(row_data)
                    
                    # Extract sample information
                    sample_data = self._extract_sample_from_row(row_data)
                    if sample_data.source_name and sample_data.source_name not in samples:
                        samples[sample_data.source_name] = sample_data
                    
                    # Extract assay information
                    assay_data = self._extract_assay_from_row(row_data)
                    if assay_data.assay_name and assay_data.assay_name not in assays:
                        assays[assay_data.assay_name] = assay_data
                    
                    # Extract file information
                    file_info = self._extract_files_from_row(row_data)
                    for file_type, file_list in file_info.items():
                        files[file_type].extend(file_list)
                
                except Exception as e:
                    self.logger.warning(f"SDRF line {line_num} parsing failed: {e}")
                    continue
            
            # Deduplicate file lists
            for file_type in files:
                files[file_type] = list(set(files[file_type]))
            
            return rows, samples, assays, files
            
        except Exception as e:
            raise Exception(f"SDRF parsing failed: {str(e)}")
    
    def _parse_adf(self, adf_url: str) -> Dict[str, Any]:
        """Parse ADF file (simplified)"""
        try:
            response = requests.get(adf_url, timeout=60)
            if response.status_code != 200:
                return {}
            
            adf_data = {"headers": {}, "features": []}
            lines = response.text.strip().split('\n')
            
            # Parse header section
            in_header = True
            feature_start = -1
            
            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue
                
                if line.startswith('[') and line.endswith(']'):
                    section = line[1:-1]
                    if section.lower() in ['main', 'features', 'feature']:
                        if section.lower() in ['features', 'feature']:
                            in_header = False
                            feature_start = i + 1
                    continue
                
                if in_header and '\t' in line:
                    parts = line.split('\t', 1)
                    if len(parts) >= 2:
                        key = parts[0].strip()
                        value = parts[1].strip()
                        adf_data["headers"][key] = value
                elif not in_header and feature_start > 0 and i >= feature_start:
                    # Parse feature table (simplified)
                    fields = line.split('\t')
                    if len(fields) > 1:
                        adf_data["features"].append(fields)
            
            return adf_data
            
        except Exception as e:
            self.logger.warning(f"ADF parsing failed: {str(e)}")
            return {}
    
    def _extract_study_metadata(self, study_id: str, idf_data: Dict[str, str]) -> StudyMetadata:
        """Extract structured metadata from IDF data"""
        return StudyMetadata(
            accession=study_id,
            title=idf_data.get("Investigation Title", ""),
            description=idf_data.get("Study Description", idf_data.get("Experiment Description", "")),
            experiment_type=idf_data.get("Experiment Type", idf_data.get("Study Type", "")),
            organism=idf_data.get("Organism", ""),
            pubmed_id=idf_data.get("PubMed ID", idf_data.get("Publication PubMed ID")),
            doi=idf_data.get("DOI", idf_data.get("Publication DOI")),
            release_date=idf_data.get("Public Release Date"),
            submission_date=idf_data.get("Date of Experiment"),
            contact_name=idf_data.get("Person Last Name", ""),
            contact_email=idf_data.get("Person Email", ""),
            protocols=self._extract_protocols(idf_data)
        )
    
    def _extract_protocols(self, idf_data: Dict[str, str]) -> List[str]:
        """Extract protocol information from IDF"""
        protocols = []
        for key, value in idf_data.items():
            if "protocol" in key.lower() and value:
                protocols.append(f"{key}: {value}")
        return protocols
    
    def _extract_sample_from_row(self, row_data: Dict[str, str]) -> SampleMetadata:
        """Extract sample metadata from SDRF row"""
        # Common column name mappings
        source_name = row_data.get("Source Name", "")
        
        return SampleMetadata(
            source_name=source_name,
            sample_name=row_data.get("Sample Name", source_name),
            organism=self._get_characteristic_value(row_data, ["organism", "species"]),
            tissue=self._get_characteristic_value(row_data, ["organism part", "tissue", "cell type"]),
            cell_type=self._get_characteristic_value(row_data, ["cell type", "cell_type"]),
            disease=self._get_characteristic_value(row_data, ["disease", "disease state", "phenotype"]),
            treatment=self._get_characteristic_value(row_data, ["treatment", "compound", "drug"]),
            age=self._get_characteristic_value(row_data, ["age"]),
            sex=self._get_characteristic_value(row_data, ["sex", "gender"]),
            biosample_id=self._get_comment_value(row_data, ["biosample_id", "biosample", "biosamples_id"]),
            assay_names=[row_data.get("Assay Name", "")] if row_data.get("Assay Name") else [],
            ena_runs=self._extract_ena_runs_from_row(row_data)
        )
    
    def _extract_assay_from_row(self, row_data: Dict[str, str]) -> AssayMetadata:
        """Extract assay metadata from SDRF row"""
        return AssayMetadata(
            assay_name=row_data.get("Assay Name", ""),
            source_name=row_data.get("Source Name", ""),
            technology_type=row_data.get("Technology Type", ""),
            array_design_ref=row_data.get("Array Design REF", ""),
            platform=row_data.get("Platform", row_data.get("Instrument Model", "")),
            data_files=self._extract_data_files_from_row(row_data),
            ena_experiment=self._get_comment_value(row_data, ["ena_experiment", "experiment_accession"]),
            ena_run=self._get_comment_value(row_data, ["ena_run", "run_accession"])
        )
    
    def _extract_files_from_row(self, row_data: Dict[str, str]) -> Dict[str, List[str]]:
        """Extract file information from SDRF row"""
        files = {"data_files": [], "processed_files": [], "raw_files": []}
        
        for key, value in row_data.items():
            key_lower = key.lower()
            if value and ("file" in key_lower or "data" in key_lower):
                if "raw" in key_lower or "fastq" in key_lower or "sra" in key_lower:
                    files["raw_files"].append(value)
                elif "processed" in key_lower or "normalized" in key_lower:
                    files["processed_files"].append(value)
                else:
                    files["data_files"].append(value)
        
        return files
    
    def _extract_data_files_from_row(self, row_data: Dict[str, str]) -> List[str]:
        """Extract data file names from SDRF row"""
        files = []
        for key, value in row_data.items():
            key_lower = key.lower()
            if value and ("file" in key_lower or "data" in key_lower):
                files.append(value)
        return files
    
    def _extract_ena_runs_from_row(self, row_data: Dict[str, str]) -> List[str]:
        """Extract ENA run accessions from SDRF row"""
        runs = []
        for key, value in row_data.items():
            if value and any(x in key.lower() for x in ["ena_run", "run_accession", "comment[ena_run]"]):
                if value.startswith(("ERR", "SRR", "DRR")):
                    runs.append(value)
        return runs
    
    def _get_characteristic_value(self, row_data: Dict[str, str], possible_names: List[str]) -> Optional[str]:
        """Get characteristic value from row data"""
        for name in possible_names:
            # Try direct match
            if name in row_data and row_data[name]:
                return row_data[name]
            
            # Try with "Characteristics [...]" format
            char_key = f"Characteristics [{name}]"
            if char_key in row_data and row_data[char_key]:
                return row_data[char_key]
            
            # Try case-insensitive search
            for key, value in row_data.items():
                if name.lower() in key.lower() and "characteristic" in key.lower() and value:
                    return value
        
        return None
    
    def _get_comment_value(self, row_data: Dict[str, str], possible_names: List[str]) -> Optional[str]:
        """Get comment value from row data"""
        for name in possible_names:
            # Try direct match
            if name in row_data and row_data[name]:
                return row_data[name]
            
            # Try with "Comment [...]" format
            comment_key = f"Comment [{name}]"
            if comment_key in row_data and row_data[comment_key]:
                return row_data[comment_key]
            
            # Try case-insensitive search
            for key, value in row_data.items():
                if name.lower() in key.lower() and "comment" in key.lower() and value:
                    return value
        
        return None
    
    def _extract_adf_references(self, sdrf_rows: List[Dict[str, str]]) -> List[str]:
        """Extract ADF references from SDRF data"""
        adf_refs = set()
        for row in sdrf_rows:
            adf_ref = row.get("Array Design REF", "")
            if adf_ref:
                adf_refs.add(adf_ref)
        return list(adf_refs)
    
    def to_dataframe(self, parsed_data: Dict[str, Any]) -> pd.DataFrame:
        """Convert parsed MAGE-TAB data to pandas DataFrame"""
        if "samples" not in parsed_data:
            return pd.DataFrame()
        
        rows = []
        for sample_name, sample_data in parsed_data["samples"].items():
            row = {
                "source_name": sample_data.source_name,
                "sample_name": sample_data.sample_name,
                "organism": sample_data.organism,
                "tissue": sample_data.tissue,
                "cell_type": sample_data.cell_type,
                "disease": sample_data.disease,
                "treatment": sample_data.treatment,
                "age": sample_data.age,
                "sex": sample_data.sex,
                "biosample_id": sample_data.biosample_id,
                "assay_names": ",".join(sample_data.assay_names) if sample_data.assay_names else "",
                "ena_runs": ",".join(sample_data.ena_runs) if sample_data.ena_runs else ""
            }
            rows.append(row)
        
        return pd.DataFrame(rows)
    
    def save_parsed_data(self, parsed_data: Dict[str, Any], output_dir: str):
        """Save parsed MAGE-TAB data to files"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        study_id = parsed_data.get("study_id", "unknown")
        
        # Save structured metadata as JSON
        import json
        metadata_file = output_path / f"{study_id}_metadata.json"
        
        # Convert dataclasses to dict for JSON serialization
        json_data = {
            "study_id": study_id,
            "study_metadata": parsed_data["study_metadata"].__dict__ if parsed_data["study_metadata"] else {},
            "samples": {k: v.__dict__ for k, v in parsed_data["samples"].items()},
            "assays": {k: v.__dict__ for k, v in parsed_data["assays"].items()},
            "files": parsed_data["files"],
            "errors": parsed_data.get("errors", [])
        }
        
        with open(metadata_file, 'w') as f:
            json.dump(json_data, f, indent=2, default=str)
        
        # Save samples as CSV
        df = self.to_dataframe(parsed_data)
        if not df.empty:
            csv_file = output_path / f"{study_id}_samples.csv"
            df.to_csv(csv_file, index=False)
        
        self.logger.info(f"Parsed MAGE-TAB data saved to {output_path}")


# Convenience functions
def parse_arrayexpress_study(study_id: str, output_dir: str = None) -> Dict[str, Any]:
    """Parse ArrayExpress study MAGE-TAB files
    
    Args:
        study_id: ArrayExpress study accession (e.g., E-MTAB-12345)
        output_dir: Optional directory to save parsed data
        
    Returns:
        dict: Complete parsed metadata
    """
    parser = MAGETABParser()
    parsed_data = parser.parse_study(study_id)
    
    if output_dir:
        parser.save_parsed_data(parsed_data, output_dir)
    
    return parsed_data


def extract_samples_from_sdrf(sdrf_url: str) -> List[Dict[str, str]]:
    """Extract sample information from SDRF URL
    
    Args:
        sdrf_url: Direct URL to SDRF file
        
    Returns:
        list: List of sample dictionaries
    """
    parser = MAGETABParser()
    try:
        _, samples, _, _ = parser._parse_sdrf(sdrf_url)
        return [sample.__dict__ for sample in samples.values()]
    except Exception as e:
        logger.error(f"SDRF extraction failed: {e}")
        return []