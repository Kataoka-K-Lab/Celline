"""
Export metadata report functionality for Celline.
"""

import argparse
import os
from datetime import datetime
from typing import Optional, Dict, List
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.status import Status

from celline.functions._base import CellineFunction
from celline.sample.sample_handler import SampleResolver
from celline.DB.dev.handler import HandleResolver
from celline.config import Config

console = Console()


class ExportMetaReport(CellineFunction):
    """Generate HTML metadata report from samples.toml."""

    def __init__(self, output_file: str = "metadata_report.html", use_ai: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.output_file = output_file
        self.use_ai = use_ai

    def register(self) -> str:
        return "export_metareport"

    def call(self, project):
        """Generate metadata report."""
        console.print("[cyan]🔍 Collecting sample metadata...[/cyan]")

        # Validate AI environment if --ai flag is used
        api_key = None
        if self.use_ai:
            console.print("[cyan]🤖 AI analysis enabled - validating environment...[/cyan]")
            api_key = self._validate_ai_environment(project)

        # Read samples using SampleResolver
        try:
            SampleResolver.refresh()  # Ensure fresh data
            samples_info = SampleResolver.samples
        except Exception as e:
            console.print(f"[red]Error reading samples: {e}[/red]")
            return project

        if not samples_info:
            console.print("[yellow]No samples found in samples.toml[/yellow]")
            return project

        console.print(f"Found {len(samples_info)} samples to process")

        # Collect metadata for each sample
        sample_metadata = []

        for sample_id, sample_info in samples_info.items():
            console.print(f"[dim]Processing {sample_id}...[/dim]")
            try:
                # Get metadata from the sample schema (already cached)
                metadata = sample_info.schema

                # Determine the data source based on sample ID pattern
                data_source = self._identify_data_source(sample_id)

                console.print(f"[green]✓ Retrieved metadata for {sample_id} from {data_source}[/green]")

                sample_metadata.append({
                    'id': sample_id,
                    'description': self._get_sample_description(sample_id),
                    'metadata': metadata,
                    'data_source': data_source,
                    'error': None
                })
            except Exception as e:
                console.print(f"[red]✗ Failed to retrieve {sample_id}: {str(e)}[/red]")
                sample_metadata.append({
                    'id': sample_id,
                    'description': self._get_sample_description(sample_id),
                    'metadata': None,
                    'data_source': 'Unknown',
                    'error': str(e)
                })

        # Enrich sample metadata with additional details
        console.print("[cyan]🔬 Enriching metadata with experimental details...[/cyan]")
        enriched_metadata = self._enrich_sample_metadata(sample_metadata)

        # Initialize final_metadata with enriched_metadata (this is our working variable)
        final_metadata = enriched_metadata

        # AI analysis if enabled
        ai_analysis_results = []
        normalizations = {}

        if self.use_ai and api_key:
            console.print("[cyan]🤖 Starting AI analysis of project and sample data...[/cyan]")

            # Count total items to analyze
            total_projects = len(set(getattr(sample['metadata'], 'parent', None)
                                   for sample in enriched_metadata
                                   if sample['error'] is None and sample['metadata']
                                   and getattr(sample['metadata'], 'parent', '').startswith('GSE')))
            total_samples = sum(1 for sample in enriched_metadata
                              if sample['error'] is None and sample['id'].startswith('GSM'))

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:

                # Create progress tasks
                project_task = progress.add_task("[cyan]Analyzing projects", total=total_projects)
                sample_task = progress.add_task("[green]Analyzing samples", total=total_samples)

                # Analyze projects and samples
                processed_projects = set()

                for sample in enriched_metadata:
                    if sample['error'] is None and sample['metadata']:
                        # Analyze project-level data (only once per project)
                        project_id = getattr(sample['metadata'], 'parent', None)
                        if project_id and project_id.startswith('GSE') and project_id not in processed_projects:
                            processed_projects.add(project_id)

                            try:
                                progress.update(project_task, description=f"[cyan]Analyzing project {project_id}")
                                # Get project XML
                                import requests
                                url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={project_id}&targ=gse&form=xml&view=full"
                                response = requests.get(url, timeout=15)

                                if response.status_code == 200:
                                    project_text = self._extract_xml_text(response.content)
                                    if project_text:
                                        project_analysis = self._analyze_with_openai(api_key, project_text, 'project')
                                        if project_analysis:
                                            project_analysis['type'] = 'project'
                                            project_analysis['id'] = project_id
                                            ai_analysis_results.append(project_analysis)

                                progress.advance(project_task)

                            except Exception as e:
                                console.print(f"[yellow]Could not analyze project {project_id}: {e}[/yellow]")
                                progress.advance(project_task)

                        # Analyze sample-level data
                        sample_id = sample['id']
                        if sample_id.startswith('GSM'):
                            try:
                                progress.update(sample_task, description=f"[green]Analyzing sample {sample_id}")
                                # Get sample XML
                                url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample_id}&targ=gsm&form=xml&view=full"
                                response = requests.get(url, timeout=10)

                                if response.status_code == 200:
                                    sample_text = self._extract_xml_text(response.content)
                                    if sample_text:
                                        sample_analysis = self._analyze_with_openai(api_key, sample_text, 'sample', sample_id)
                                        if sample_analysis:
                                            sample_analysis['type'] = 'sample'
                                            sample_analysis['id'] = sample_id
                                            sample_analysis['project_id'] = project_id
                                            ai_analysis_results.append(sample_analysis)

                                progress.advance(sample_task)

                            except Exception as e:
                                console.print(f"[yellow]Could not analyze sample {sample_id}: {e}[/yellow]")
                                progress.advance(sample_task)

                # Normalize terminology
                if ai_analysis_results:
                    with Status("[cyan]🔄 Normalizing terminology...", console=console) as status:
                        normalizations = self._normalize_terminology(api_key, ai_analysis_results)

                        # Apply normalizations
                        for result in ai_analysis_results:
                            for field in ['platform', 'tissue', 'condition', 'organism']:
                                if field in result and result[field] in normalizations:
                                    result[field] = normalizations[result[field]]

                    console.print(f"[green]✓ AI analysis completed: {len(ai_analysis_results)} items analyzed[/green]")

                # Integrate AI results into metadata
                final_metadata = self._integrate_ai_results(enriched_metadata, ai_analysis_results)
        else:
            # If AI is not enabled, use the original enriched_metadata without AI integration
            final_metadata = enriched_metadata

        # Generate chart data for all distributions
        species_labels, species_values = self._generate_species_chart_data(final_metadata)
        projects_labels, projects_values = self._generate_projects_chart_data(final_metadata)
        datasets_labels, datasets_values = self._generate_datasets_chart_data(final_metadata)

        # Generate AI-enhanced charts if available
        if self.use_ai and ai_analysis_results:
            platform_labels, platform_values = self._generate_platform_chart_data(ai_analysis_results)
            tissue_labels, tissue_values = self._generate_tissue_chart_data(ai_analysis_results)
            condition_labels, condition_values = self._generate_condition_chart_data(ai_analysis_results)

            charts_html = self._generate_enhanced_charts_html(
                species_labels, species_values,
                projects_labels, projects_values,
                datasets_labels, datasets_values,
                platform_labels, platform_values,
                tissue_labels, tissue_values,
                condition_labels, condition_values
            )
        else:
            charts_html = self._generate_charts_html(species_labels, species_values,
                                                     projects_labels, projects_values,
                                                     datasets_labels, datasets_values)

        # Extract citation information from GSE projects
        citations = self._extract_gse_citations(final_metadata)
        references_html = self._generate_references_html(citations)

        # Generate research summaries if AI analysis was performed
        research_summaries_html = ""
        if self.use_ai and ai_analysis_results:
            research_summaries = self._extract_research_summaries(ai_analysis_results)
            research_summaries_html = self._generate_research_summary_html(research_summaries)

        # Generate HTML report
        console.print(f"[cyan]📝 Generating HTML report: {self.output_file}[/cyan]")
        self._generate_html_report(final_metadata, project, charts_html, references_html, research_summaries_html)

        return project

    def _identify_data_source(self, sample_id: str) -> str:
        """Identify the data source based on sample ID pattern."""
        if sample_id.startswith('GSM') or sample_id.startswith('GSE'):
            return 'GEO (Gene Expression Omnibus)'
        elif sample_id.startswith('SRR') or sample_id.startswith('SRX'):
            return 'SRA (Sequence Read Archive)'
        elif sample_id.startswith('CRA') or sample_id.startswith('CRR'):
            return 'CNCB (China National Center for Bioinformation)'
        else:
            return 'Public Database'

    def _get_sample_description(self, sample_id: str) -> str:
        """Get sample description from samples.toml."""
        import toml
        from celline.config import Config

        samples_path = f"{Config.PROJ_ROOT}/samples.toml"
        try:
            with open(samples_path, 'r', encoding='utf-8') as f:
                samples = toml.load(f)
            return samples.get(sample_id, sample_id)
        except Exception:
            return sample_id

    def _enrich_sample_metadata(self, sample_metadata: List[Dict]) -> List[Dict]:
        """Enrich sample metadata with additional SRA and experimental details."""
        enriched_metadata = []

        for sample in sample_metadata:
            if sample['error'] is None:
                try:
                    # Get additional experimental details from GEO
                    enhanced_data = self._get_experimental_details(sample['id'])
                    if enhanced_data:
                        # Add experimental details to metadata
                        for key, value in enhanced_data.items():
                            # Always set the enriched data, as it's more detailed than basic metadata
                            setattr(sample['metadata'], key, value)

                    # Get SRA strategy information
                    sra_info = self._get_sra_strategy_info(sample['metadata'])
                    if sra_info:
                        for key, value in sra_info.items():
                            setattr(sample['metadata'], key, value)

                except Exception as e:
                    console.print(f"[yellow]Could not enrich metadata for {sample['id']}: {e}[/yellow]")

            enriched_metadata.append(sample)

        return enriched_metadata

    def _get_experimental_details(self, sample_id: str) -> Optional[Dict]:
        """Get additional experimental details from GEO API."""
        try:
            import requests
            import xml.etree.ElementTree as ET

            if not sample_id.startswith('GSM'):
                return None

            # Use the correct GEO API endpoint
            url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample_id}&targ=gsm&form=xml&view=full"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                # Parse XML with namespace handling
                root = ET.fromstring(response.content)
                details = {}

                # Define namespace for GEO XML
                ns = {'geo': 'http://www.ncbi.nlm.nih.gov/geo/info/MINiML'}

                # Extract title
                title_elem = root.find('.//geo:Sample/geo:Title', ns)
                if title_elem is not None and title_elem.text:
                    details['title'] = title_elem.text.strip()

                # Extract description/summary
                desc_elem = root.find('.//geo:Sample/geo:Description', ns)
                if desc_elem is not None and desc_elem.text:
                    details['description'] = desc_elem.text.strip()

                # Extract protocol information
                for protocol_elem in root.findall('.//geo:Sample/geo:Protocol', ns):
                    if protocol_elem.text:
                        protocol_text = protocol_elem.text.strip()
                        if len(protocol_text) > 50:  # Only use substantial protocol descriptions
                            details['experimental_protocol'] = protocol_text
                            break

                # Extract characteristics (organism, tissue, etc.)
                characteristics = {}
                for char_elem in root.findall('.//geo:Sample/geo:Characteristics', ns):
                    tag_attr = char_elem.get('tag')
                    if tag_attr and char_elem.text:
                        characteristics[tag_attr] = char_elem.text.strip()

                if characteristics:
                    details['characteristics'] = characteristics

                # Extract supplementary file links (raw data links)
                supp_files = []
                for supp_elem in root.findall('.//geo:Sample/geo:Supplementary-Data', ns):
                    if supp_elem.text:
                        supp_files.append(supp_elem.text.strip())

                if supp_files:
                    details['supplementary_files'] = supp_files

                return details if details else None

        except Exception as e:
            console.print(f"[dim yellow]Could not retrieve experimental details for {sample_id}: {e}[/dim yellow]")
            return None

    def _get_sra_strategy_info(self, metadata) -> Optional[Dict]:
        """Get SRA strategy and library information."""
        try:
            if not hasattr(metadata, 'key') or not metadata.key:
                return None

            import requests
            import xml.etree.ElementTree as ET

            # First try to get SRX from the sample metadata
            srx_id = None
            if hasattr(metadata, 'srx_id') and metadata.srx_id:
                srx_id = metadata.srx_id
            elif hasattr(metadata, 'children') and metadata.children:
                # Sometimes SRX is in children
                children = str(metadata.children)
                if 'SRX' in children:
                    import re
                    srx_match = re.search(r'SRX\d+', children)
                    if srx_match:
                        srx_id = srx_match.group()

            if not srx_id:
                return None

            # Query SRA API for strategy information
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=sra&id={srx_id}&rettype=xml"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                root = ET.fromstring(response.content)
                strategy_info = {}

                # Extract library strategy, source, and layout
                for elem in root.iter():
                    if elem.tag == 'LIBRARY_STRATEGY':
                        strategy_info['strategy'] = elem.text
                    elif elem.tag == 'LIBRARY_SOURCE':
                        strategy_info['library_source'] = elem.text
                    elif elem.tag == 'LIBRARY_LAYOUT':
                        # Get the layout type (SINGLE or PAIRED)
                        for child in elem:
                            strategy_info['library_layout'] = child.tag
                            break
                    elif elem.tag == 'PLATFORM':
                        # Get platform information
                        for platform_child in elem:
                            if platform_child.tag in ['ILLUMINA', 'OXFORD_NANOPORE', 'PACBIO_SMRT']:
                                strategy_info['platform'] = platform_child.tag
                                for instrument in platform_child:
                                    if instrument.tag == 'INSTRUMENT_MODEL':
                                        strategy_info['instrument'] = instrument.text
                                        break
                                break

                return strategy_info if strategy_info else None

        except Exception as e:
            console.print(f"[dim yellow]Could not retrieve SRA strategy info: {e}[/dim yellow]")
            return None

    def _generate_strategy_info_html(self, metadata) -> str:
        """Generate HTML for sequencing strategy information."""
        strategy_html = ""

        # Check for strategy information
        strategy_attrs = ['strategy', 'library_source', 'library_layout', 'platform', 'instrument']
        strategy_data = {}

        for attr in strategy_attrs:
            if hasattr(metadata, attr):
                value = getattr(metadata, attr)
                if value:
                    strategy_data[attr] = value

        if strategy_data:
            items_html = ""
            for attr, value in strategy_data.items():
                attr_label = attr.replace('_', ' ').title()
                items_html += f'''
                <div class="metadata-item">
                    <span class="metadata-label">{attr_label}:</span>
                    <span class="metadata-value">{value}</span>
                </div>'''

            # Determine file format based on strategy
            file_format = "Unknown"
            if 'strategy' in strategy_data:
                if strategy_data['strategy'] in ['RNA-Seq', 'ChIP-Seq', 'ATAC-seq']:
                    file_format = "FASTQ"
                elif strategy_data['strategy'] in ['WGS', 'WXS']:
                    file_format = "FASTQ (possibly BAM)"

            items_html += f'''
            <div class="metadata-item">
                <span class="metadata-label">Expected Format:</span>
                <span class="metadata-value">{file_format}</span>
            </div>'''

            strategy_html = f'''
            <div class="strategy-info">
                <h4>🧬 Sequencing Strategy Information</h4>
                {items_html}
            </div>'''

        return strategy_html

    def _generate_species_chart_data(self, sample_metadata: List[Dict]) -> tuple:
        """Generate species distribution data for pie chart."""
        species_count = {}

        for sample in sample_metadata:
            if sample['error'] is None and sample['metadata']:
                species = getattr(sample['metadata'], 'species', 'Unknown')
                if species and species != 'Not specified':
                    species_count[species] = species_count.get(species, 0) + 1
                else:
                    species_count['Unknown'] = species_count.get('Unknown', 0) + 1

        if not species_count:
            return [], []

        species_labels = list(species_count.keys())
        species_values = list(species_count.values())

        return species_labels, species_values

    def _generate_projects_chart_data(self, sample_metadata: List[Dict]) -> tuple:
        """Generate projects distribution data for pie chart."""
        projects_count = {}

        for sample in sample_metadata:
            if sample['error'] is None and sample['metadata']:
                project = getattr(sample['metadata'], 'parent', 'Unknown Project')
                if project and project != 'Not specified':
                    projects_count[project] = projects_count.get(project, 0) + 1
                else:
                    projects_count['Unknown Project'] = projects_count.get('Unknown Project', 0) + 1

        if not projects_count:
            return [], []

        projects_labels = list(projects_count.keys())
        projects_values = list(projects_count.values())

        return projects_labels, projects_values

    def _generate_datasets_chart_data(self, sample_metadata: List[Dict]) -> tuple:
        """Generate datasets distribution data for pie chart."""
        datasets_count = {}

        for sample in sample_metadata:
            if sample['error'] is None:
                data_source = sample['data_source']
                # Simplify data source names for better display
                if 'GEO' in data_source:
                    dataset = 'GEO'
                elif 'SRA' in data_source:
                    dataset = 'SRA'
                elif 'CNCB' in data_source:
                    dataset = 'CNCB'
                else:
                    dataset = 'Other'

                datasets_count[dataset] = datasets_count.get(dataset, 0) + 1

        if not datasets_count:
            return [], []

        datasets_labels = list(datasets_count.keys())
        datasets_values = list(datasets_count.values())

        return datasets_labels, datasets_values

    def _generate_charts_html(self, species_labels: List[str], species_values: List[int],
                             projects_labels: List[str], projects_values: List[int],
                             datasets_labels: List[str], datasets_values: List[int]) -> str:
        """Generate HTML for all distribution pie charts displayed horizontally."""
        charts_html = "<div class='charts-container'>"

        # Generate colors for the pie charts
        colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
            '#4BC0C0', '#FF6384', '#36A2EB', '#FFCE56'
        ]

        # Species chart
        if species_labels and species_values:
            species_labels_json = str(species_labels).replace("'", '"')
            species_values_json = str(species_values)
            species_colors_json = str(colors[:len(species_labels)]).replace("'", '"')

            charts_html += f'''
            <div class="chart-item">
                <h3>🧬 Species Distribution</h3>
                <div class="chart-canvas">
                    <canvas id="speciesChart" width="300" height="300"></canvas>
                </div>
            </div>'''

        # Projects chart
        if projects_labels and projects_values:
            projects_labels_json = str(projects_labels).replace("'", '"')
            projects_values_json = str(projects_values)
            projects_colors_json = str(colors[:len(projects_labels)]).replace("'", '"')

            charts_html += f'''
            <div class="chart-item">
                <h3>🗂️ Projects Distribution</h3>
                <div class="chart-canvas">
                    <canvas id="projectsChart" width="300" height="300"></canvas>
                </div>
            </div>'''

        # Datasets chart
        if datasets_labels and datasets_values:
            datasets_labels_json = str(datasets_labels).replace("'", '"')
            datasets_values_json = str(datasets_values)
            datasets_colors_json = str(colors[:len(datasets_labels)]).replace("'", '"')

            charts_html += f'''
            <div class="chart-item">
                <h3>💾 Datasets Distribution</h3>
                <div class="chart-canvas">
                    <canvas id="datasetsChart" width="300" height="300"></canvas>
                </div>
            </div>'''

        charts_html += "</div>"

        # Add JavaScript for all charts
        script_html = "<script>\ndocument.addEventListener('DOMContentLoaded', function() {"

        if species_labels and species_values:
            script_html += f'''
            const speciesCtx = document.getElementById('speciesChart').getContext('2d');
            const speciesChart = new Chart(speciesCtx, {{
                type: 'pie',
                data: {{
                    labels: {species_labels_json},
                    datasets: [{{
                        data: {species_values_json},
                        backgroundColor: {species_colors_json},
                        borderColor: '#ffffff',
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 10,
                                usePointStyle: true,
                                font: {{ size: 10 }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = Math.round((value / total) * 100);
                                    return label + ': ' + value + ' samples (' + percentage + '%)';
                                }}
                            }}
                        }}
                    }}
                }}
            }});'''

        if projects_labels and projects_values:
            script_html += f'''
            const projectsCtx = document.getElementById('projectsChart').getContext('2d');
            const projectsChart = new Chart(projectsCtx, {{
                type: 'pie',
                data: {{
                    labels: {projects_labels_json},
                    datasets: [{{
                        data: {projects_values_json},
                        backgroundColor: {projects_colors_json},
                        borderColor: '#ffffff',
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 10,
                                usePointStyle: true,
                                font: {{ size: 10 }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = Math.round((value / total) * 100);
                                    return label + ': ' + value + ' samples (' + percentage + '%)';
                                }}
                            }}
                        }}
                    }}
                }}
            }});'''

        if datasets_labels and datasets_values:
            script_html += f'''
            const datasetsCtx = document.getElementById('datasetsChart').getContext('2d');
            const datasetsChart = new Chart(datasetsCtx, {{
                type: 'pie',
                data: {{
                    labels: {datasets_labels_json},
                    datasets: [{{
                        data: {datasets_values_json},
                        backgroundColor: {datasets_colors_json},
                        borderColor: '#ffffff',
                        borderWidth: 2
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: {{
                        legend: {{
                            position: 'bottom',
                            labels: {{
                                padding: 10,
                                usePointStyle: true,
                                font: {{ size: 10 }}
                            }}
                        }},
                        tooltip: {{
                            callbacks: {{
                                label: function(context) {{
                                    const label = context.label || '';
                                    const value = context.parsed;
                                    const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                    const percentage = Math.round((value / total) * 100);
                                    return label + ': ' + value + ' samples (' + percentage + '%)';
                                }}
                            }}
                        }}
                    }}
                }}
            }});'''

        script_html += "\n});\n</script>"

        return charts_html + script_html

    def _extract_gse_citations(self, sample_metadata: List[Dict]) -> List[Dict]:
        """Extract citation information from GSE projects."""
        citations = []
        processed_projects = set()

        for sample in sample_metadata:
            if sample['error'] is None and sample['metadata']:
                project_id = getattr(sample['metadata'], 'parent', None)
                if project_id and project_id.startswith('GSE') and project_id not in processed_projects:
                    processed_projects.add(project_id)

                    try:
                        import requests
                        import xml.etree.ElementTree as ET

                        # Query GEO API for GSE project
                        url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={project_id}&targ=gse&form=xml&view=full"
                        response = requests.get(url, timeout=15)

                        if response.status_code == 200:
                            root = ET.fromstring(response.content)
                            ns = {'geo': 'http://www.ncbi.nlm.nih.gov/geo/info/MINiML'}

                            # Extract citation information
                            series_elem = root.find('.//geo:Series', ns)
                            if series_elem is not None:
                                citation_info = {
                                    'project_id': project_id,
                                    'title': None,
                                    'pubmed_ids': [],
                                    'summary': None,
                                    'contributors': [],
                                    'submission_date': None,
                                    'release_date': None
                                }

                                # Extract title
                                title_elem = series_elem.find('geo:Title', ns)
                                if title_elem is not None and title_elem.text:
                                    citation_info['title'] = title_elem.text.strip()

                                # Extract PubMed IDs
                                for pubmed_elem in series_elem.findall('geo:Pubmed-ID', ns):
                                    if pubmed_elem.text:
                                        citation_info['pubmed_ids'].append(pubmed_elem.text.strip())

                                # Extract summary
                                summary_elem = series_elem.find('geo:Summary', ns)
                                if summary_elem is not None and summary_elem.text:
                                    citation_info['summary'] = summary_elem.text.strip()

                                # Extract contributors
                                for contrib_ref in series_elem.findall('geo:Contributor-Ref', ns):
                                    contrib_id = contrib_ref.get('ref')
                                    if contrib_id:
                                        contrib_elem = root.find(f'.//geo:Contributor[@iid="{contrib_id}"]', ns)
                                        if contrib_elem is not None:
                                            person_elem = contrib_elem.find('geo:Person', ns)
                                            if person_elem is not None:
                                                first = person_elem.find('geo:First', ns)
                                                middle = person_elem.find('geo:Middle', ns)
                                                last = person_elem.find('geo:Last', ns)

                                                name_parts = []
                                                if first is not None and first.text:
                                                    name_parts.append(first.text.strip())
                                                if middle is not None and middle.text:
                                                    name_parts.append(middle.text.strip())
                                                if last is not None and last.text:
                                                    name_parts.append(last.text.strip())

                                                if name_parts:
                                                    citation_info['contributors'].append(' '.join(name_parts))

                                # Extract dates
                                status_elem = series_elem.find('geo:Status', ns)
                                if status_elem is not None:
                                    submission_elem = status_elem.find('geo:Submission-Date', ns)
                                    if submission_elem is not None and submission_elem.text:
                                        citation_info['submission_date'] = submission_elem.text.strip()

                                    release_elem = status_elem.find('geo:Release-Date', ns)
                                    if release_elem is not None and release_elem.text:
                                        citation_info['release_date'] = release_elem.text.strip()

                                # Only add if we have meaningful information
                                if citation_info['title'] or citation_info['pubmed_ids'] or citation_info['contributors']:
                                    citations.append(citation_info)

                    except Exception as e:
                        console.print(f"[dim yellow]Could not extract citation for {project_id}: {e}[/dim yellow]")

        return citations

    def _validate_ai_environment(self, project) -> str:
        """Validate .env file and OPENAI_API_KEY."""
        import os
        from pathlib import Path

        # Check for .env file in PROJ_ROOT
        env_path = Path(Config.PROJ_ROOT) / '.env'
        if not env_path.exists():
            raise FileNotFoundError(f"Required .env file not found at {env_path}. Please create a .env file with OPENAI_API_KEY.")

        # Load environment variables from .env
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            raise ImportError("python-dotenv package is required for --ai functionality. Install with: pip install python-dotenv")

        # Check for OPENAI_API_KEY
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in .env file. Please add OPENAI_API_KEY=your_key_here to your .env file.")

        console.print(f"[green]✓ Environment validation successful[/green]")
        return api_key

    def _extract_xml_text(self, xml_content: str) -> str:
        """Extract all text content from XML, not limited to specific tags."""
        try:
            import xml.etree.ElementTree as ET

            # Parse XML
            root = ET.fromstring(xml_content)

            # Extract all text content recursively
            def extract_text_recursive(element):
                texts = []

                # Add element text
                if element.text and element.text.strip():
                    texts.append(element.text.strip())

                # Add tail text
                if element.tail and element.tail.strip():
                    texts.append(element.tail.strip())

                # Recursively process children
                for child in element:
                    texts.extend(extract_text_recursive(child))

                return texts

            all_texts = extract_text_recursive(root)

            # Join all texts with spaces, remove duplicates while preserving order
            seen = set()
            unique_texts = []
            for text in all_texts:
                if text not in seen and len(text) > 2:  # Filter out very short text snippets
                    seen.add(text)
                    unique_texts.append(text)

            return ' '.join(unique_texts)

        except Exception as e:
            console.print(f"[yellow]Warning: Could not extract text from XML: {e}[/yellow]")
            return ""

    def _analyze_with_openai(self, api_key: str, content: str, content_type: str, sample_id: str = None) -> Dict:
        """Analyze content using OpenAI GPT-4o."""
        try:
            import openai

            client = openai.OpenAI(api_key=api_key)

            # Design prompts based on content type
            if content_type == 'project':
                prompt = f"""Analyze the following genomics project information and extract key experimental details and research context.

Please identify and return ONLY a JSON object with these fields:
{{
  "platform": "sequencing platform (e.g., '10x Chromium', 'Smart-seq2', 'CITE-seq', 'Illumina NextSeq', etc.)",
  "tissue": "tissue or body part being studied (e.g., 'brain', 'liver', 'blood', etc.)",
  "condition": "experimental condition (e.g., 'healthy', 'disease', 'treatment', 'wildtype', etc.)",
  "organism": "organism studied (e.g., 'human', 'mouse', 'rat', etc.)",
  "experiment_type": "type of experiment (e.g., 'single-cell RNA-seq', 'bulk RNA-seq', 'ATAC-seq', etc.)",
  "research_objective": "main research goal or hypothesis (concise, 1-2 sentences)",
  "key_findings": "major findings or discoveries (concise summary, 1-2 sentences)",
  "biological_significance": "biological or clinical relevance (concise, 1-2 sentences)",
  "methodology_summary": "brief description of experimental approach (1-2 sentences)",
  "contact_email": "contact email address if available",
  "principal_investigator": "principal investigator or corresponding author name",
  "organization": "research institution or organization",
  "funding_source": "funding agencies or grants if mentioned"
}}

Focus on extracting the most specific and accurate information. If information is not clearly stated, use "unknown".

Project content:
{content}"""
            else:  # sample
                prompt = f"""Analyze the following genomics sample information and extract key experimental details.

Please identify and return ONLY a JSON object with these fields:
{{
  "platform": "sequencing platform (e.g., '10x Chromium', 'Smart-seq2', 'CITE-seq', 'Illumina NextSeq', etc.)",
  "tissue": "tissue or body part being studied (e.g., 'brain', 'liver', 'blood', etc.)",
  "condition": "experimental condition (e.g., 'healthy', 'disease', 'treatment', 'wildtype', etc.)",
  "organism": "organism studied (e.g., 'human', 'mouse', 'rat', etc.)",
  "cell_type": "specific cell type if mentioned (e.g., 'neurons', 'hepatocytes', 'T cells', etc.)",
  "treatment": "any treatment or intervention applied (e.g., 'control', 'drug treatment', 'stimulation', etc.)",
  "developmental_stage": "developmental stage (e.g., 'embryonic', 'adult', 'postnatal day 7', 'E18.5', etc.)",
  "strain": "strain or genetic background (e.g., 'C57BL/6', 'BALB/c', 'wild-type', etc.)",
  "sex": "biological sex if specified (e.g., 'male', 'female', 'mixed', etc.)",
  "age": "age information (e.g., '8 weeks', '3 months', 'adult', etc.)"
}}

Focus on extracting the most specific and accurate information. If information is not clearly stated, use "unknown".

Sample ID: {sample_id or 'Unknown'}
Sample content:
{content}"""

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a bioinformatics expert specializing in genomics data analysis. Extract information accurately and return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistent results
                max_tokens=500
            )

            # Parse JSON response
            import json
            result_text = response.choices[0].message.content.strip()

            # Try to extract JSON from response
            try:
                # Look for JSON object in the response
                start_idx = result_text.find('{')
                end_idx = result_text.rfind('}') + 1
                if start_idx != -1 and end_idx != 0:
                    json_str = result_text[start_idx:end_idx]
                    result = json.loads(json_str)
                else:
                    result = json.loads(result_text)

                console.print(f"[green]✓ AI analysis completed for {content_type} {sample_id or ''}[/green]")
                return result

            except json.JSONDecodeError as je:
                console.print(f"[yellow]Warning: Could not parse AI response as JSON for {content_type} {sample_id or ''}: {je}[/yellow]")
                return {}

        except Exception as e:
            console.print(f"[red]Error in AI analysis for {content_type} {sample_id or ''}: {e}[/red]")
            return {}

    def _normalize_terminology(self, api_key: str, analysis_results: List[Dict]) -> Dict[str, str]:
        """Use AI to normalize terminology across all results."""
        try:
            import openai
            import json

            client = openai.OpenAI(api_key=api_key)

            # Extract all unique values for each field
            platforms = set()
            tissues = set()
            conditions = set()
            organisms = set()

            for result in analysis_results:
                for field, field_set in [
                    ('platform', platforms),
                    ('tissue', tissues),
                    ('condition', conditions),
                    ('organism', organisms)
                ]:
                    value = result.get(field, '').strip()
                    if value and value.lower() != 'unknown':
                        field_set.add(value)

            # Create normalization mappings for each field
            normalizations = {}

            # Extract research summaries for normalization
            research_objectives = set()
            key_findings = set()

            for result in analysis_results:
                for field, field_set in [
                    ('research_objective', research_objectives),
                    ('key_findings', key_findings)
                ]:
                    value = result.get(field, '').strip()
                    if value and value.lower() != 'unknown' and len(value) > 10:  # Only meaningful summaries
                        field_set.add(value)

            for field_name, values in [
                ('platforms', platforms),
                ('tissues', tissues),
                ('conditions', conditions),
                ('organisms', organisms)
            ]:
                if len(values) > 1:
                    values_list = list(values)
                    prompt = f"""Normalize the following {field_name} terms to use consistent terminology.

Terms to normalize: {values_list}

Return ONLY a JSON object mapping each original term to its normalized version.
For example: {{"cerebral cortex": "cortex", "brain cortex": "cortex", "10X Chromium": "10x Chromium"}}

Rules:
- Use the most common/standard terminology
- Be consistent with capitalization
- Combine similar terms under one standard name
- Keep important specificity when needed

Normalization mapping:"""

                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": "You are a bioinformatics expert. Normalize terminology to standard forms and return only valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        temperature=0.1,
                        max_tokens=500
                    )

                    try:
                        result_text = response.choices[0].message.content.strip()
                        start_idx = result_text.find('{')
                        end_idx = result_text.rfind('}') + 1
                        if start_idx != -1 and end_idx != 0:
                            json_str = result_text[start_idx:end_idx]
                            field_normalizations = json.loads(json_str)
                            normalizations.update(field_normalizations)

                    except json.JSONDecodeError:
                        console.print(f"[yellow]Warning: Could not parse normalization response for {field_name}[/yellow]")

            console.print(f"[green]✓ Terminology normalization completed[/green]")
            return normalizations

        except Exception as e:
            console.print(f"[yellow]Warning: Could not normalize terminology: {e}[/yellow]")
            return {}

    def _integrate_ai_results(self, sample_metadata: List[Dict], ai_results: List[Dict]) -> List[Dict]:
        """Integrate AI analysis results into sample metadata."""
        # Create lookup dictionaries
        project_ai_data = {result['id']: result for result in ai_results if result.get('type') == 'project'}
        sample_ai_data = {result['id']: result for result in ai_results if result.get('type') == 'sample'}

        enhanced_metadata = []

        for sample in sample_metadata:
            if sample['error'] is None and sample['metadata']:
                # Get project-level AI data
                project_id = getattr(sample['metadata'], 'parent', None)
                project_ai = project_ai_data.get(project_id, {})

                # Get sample-level AI data
                sample_ai = sample_ai_data.get(sample['id'], {})

                # Add AI analysis to sample
                sample['ai_analysis'] = {
                    'project': project_ai,
                    'sample': sample_ai
                }

                # Add derived fields for easier access
                sample['ai_platform'] = sample_ai.get('platform') or project_ai.get('platform', 'Unknown')
                sample['ai_tissue'] = sample_ai.get('tissue') or project_ai.get('tissue', 'Unknown')
                sample['ai_condition'] = sample_ai.get('condition') or project_ai.get('condition', 'Unknown')
                sample['ai_organism'] = sample_ai.get('organism') or project_ai.get('organism', 'Unknown')

            enhanced_metadata.append(sample)

        return enhanced_metadata

    def _generate_platform_chart_data(self, ai_results: List[Dict]) -> tuple:
        """Generate platform distribution data from AI analysis."""
        platform_count = {}

        for result in ai_results:
            platform = result.get('platform', 'Unknown')
            if platform and platform.lower() != 'unknown':
                platform_count[platform] = platform_count.get(platform, 0) + 1

        if not platform_count:
            return [], []

        platform_labels = list(platform_count.keys())
        platform_values = list(platform_count.values())

        return platform_labels, platform_values

    def _generate_tissue_chart_data(self, ai_results: List[Dict]) -> tuple:
        """Generate tissue distribution data from AI analysis."""
        tissue_count = {}

        for result in ai_results:
            tissue = result.get('tissue', 'Unknown')
            if tissue and tissue.lower() != 'unknown':
                tissue_count[tissue] = tissue_count.get(tissue, 0) + 1

        if not tissue_count:
            return [], []

        tissue_labels = list(tissue_count.keys())
        tissue_values = list(tissue_count.values())

        return tissue_labels, tissue_values

    def _generate_condition_chart_data(self, ai_results: List[Dict]) -> tuple:
        """Generate condition distribution data from AI analysis."""
        condition_count = {}

        for result in ai_results:
            condition = result.get('condition', 'Unknown')
            if condition and condition.lower() != 'unknown':
                condition_count[condition] = condition_count.get(condition, 0) + 1

        if not condition_count:
            return [], []

        condition_labels = list(condition_count.keys())
        condition_values = list(condition_count.values())

        return condition_labels, condition_values

    def _generate_enhanced_charts_html(self, species_labels, species_values,
                                      projects_labels, projects_values,
                                      datasets_labels, datasets_values,
                                      platform_labels, platform_values,
                                      tissue_labels, tissue_values,
                                      condition_labels, condition_values) -> str:
        """Generate HTML for enhanced charts including AI-extracted data."""
        charts_html = "<div class='charts-container'>"

        colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
            '#4BC0C0', '#FF6384', '#36A2EB', '#FFCE56'
        ]

        # Define all charts to generate
        chart_configs = [
            ('species', 'Species', species_labels, species_values, '🧬'),
            ('projects', 'Projects', projects_labels, projects_values, '🗂️'),
            ('datasets', 'Datasets', datasets_labels, datasets_values, '💾'),
            ('platform', 'Platforms (AI)', platform_labels, platform_values, '🔬'),
            ('tissue', 'Tissues (AI)', tissue_labels, tissue_values, '🧠'),
            ('condition', 'Conditions (AI)', condition_labels, condition_values, '⚙️')
        ]

        # Generate chart HTML for each configuration
        for chart_id, chart_title, labels, values, icon in chart_configs:
            if labels and values:
                labels_json = str(labels).replace("'", '"')
                values_json = str(values)
                colors_json = str(colors[:len(labels)]).replace("'", '"')

                charts_html += f'''
                <div class="chart-item">
                    <h3>{icon} {chart_title} Distribution</h3>
                    <div class="chart-canvas">
                        <canvas id="{chart_id}Chart" width="300" height="300"></canvas>
                    </div>
                </div>'''

        charts_html += "</div>"

        # Generate JavaScript for all charts
        script_html = "<script>\ndocument.addEventListener('DOMContentLoaded', function() {"

        for chart_id, chart_title, labels, values, icon in chart_configs:
            if labels and values:
                labels_json = str(labels).replace("'", '"')
                values_json = str(values)
                colors_json = str(colors[:len(labels)]).replace("'", '"')

                script_html += f'''
                const {chart_id}Ctx = document.getElementById('{chart_id}Chart').getContext('2d');
                const {chart_id}Chart = new Chart({chart_id}Ctx, {{
                    type: 'pie',
                    data: {{
                        labels: {labels_json},
                        datasets: [{{
                            data: {values_json},
                            backgroundColor: {colors_json},
                            borderColor: '#ffffff',
                            borderWidth: 2
                        }}]
                    }},
                    options: {{
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: {{
                            legend: {{
                                position: 'bottom',
                                labels: {{
                                    padding: 10,
                                    usePointStyle: true,
                                    font: {{ size: 10 }}
                                }}
                            }},
                            tooltip: {{
                                callbacks: {{
                                    label: function(context) {{
                                        const label = context.label || '';
                                        const value = context.parsed;
                                        const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                        const percentage = Math.round((value / total) * 100);
                                        return label + ': ' + value + ' samples (' + percentage + '%)';
                                    }}
                                }}
                            }}
                        }}
                    }}
                }});'''

        script_html += "\n});\n</script>"

        return charts_html + script_html

    def _extract_research_summaries(self, ai_results: List[Dict]) -> List[Dict]:
        """Extract research summaries from AI analysis results."""
        research_summaries = []

        for result in ai_results:
            if result.get('type') == 'project' and result.get('id'):
                project_summary = {
                    'project_id': result['id'],
                    'research_objective': result.get('research_objective', 'Not available'),
                    'key_findings': result.get('key_findings', 'Not available'),
                    'biological_significance': result.get('biological_significance', 'Not available'),
                    'methodology_summary': result.get('methodology_summary', 'Not available'),
                    'contact_email': result.get('contact_email', 'Not available'),
                    'principal_investigator': result.get('principal_investigator', 'Not available'),
                    'organization': result.get('organization', 'Not available'),
                    'funding_source': result.get('funding_source', 'Not available')
                }

                # Only add if we have meaningful information
                if any(v != 'Not available' and v != 'unknown' and len(str(v)) > 5
                      for v in project_summary.values() if isinstance(v, str)):
                    research_summaries.append(project_summary)

        return research_summaries

    def _generate_research_summary_html(self, research_summaries: List[Dict]) -> str:
        """Generate HTML for research summary section."""
        if not research_summaries:
            return ""

        summaries_html = ""
        for summary in research_summaries:
            # Generate contact information
            contact_html = ""
            if summary['contact_email'] != 'Not available' and summary['contact_email'] != 'unknown':
                contact_html += f'<div class="contact-item"><strong>Email:</strong> <a href="mailto:{summary["contact_email"]}" class="contact-link">{summary["contact_email"]}</a></div>'

            if summary['principal_investigator'] != 'Not available' and summary['principal_investigator'] != 'unknown':
                contact_html += f'<div class="contact-item"><strong>Principal Investigator:</strong> {summary["principal_investigator"]}</div>'

            if summary['organization'] != 'Not available' and summary['organization'] != 'unknown':
                contact_html += f'<div class="contact-item"><strong>Organization:</strong> {summary["organization"]}</div>'

            if summary['funding_source'] != 'Not available' and summary['funding_source'] != 'unknown':
                contact_html += f'<div class="contact-item"><strong>Funding:</strong> {summary["funding_source"]}</div>'

            # Generate research information
            research_html = ""
            if summary['research_objective'] != 'Not available' and summary['research_objective'] != 'unknown':
                research_html += f'<div class="research-item"><strong>Research Objective:</strong> {summary["research_objective"]}</div>'

            if summary['methodology_summary'] != 'Not available' and summary['methodology_summary'] != 'unknown':
                research_html += f'<div class="research-item"><strong>Methodology:</strong> {summary["methodology_summary"]}</div>'

            if summary['key_findings'] != 'Not available' and summary['key_findings'] != 'unknown':
                research_html += f'<div class="research-item"><strong>Key Findings:</strong> {summary["key_findings"]}</div>'

            if summary['biological_significance'] != 'Not available' and summary['biological_significance'] != 'unknown':
                research_html += f'<div class="research-item"><strong>Biological Significance:</strong> {summary["biological_significance"]}</div>'

            if contact_html or research_html:
                summaries_html += f'''
                <div class="research-summary-item">
                    <h4><a href="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={summary['project_id']}" target="_blank" class="db-link">{summary['project_id']}</a> Research Summary (AI)</h4>
                    {research_html}
                    {f'<div class="contact-section"><h5>📧 Contact Information (AI)</h5>{contact_html}</div>' if contact_html else ''}
                </div>'''

        if summaries_html:
            return f'''
            <div class="research-summaries-section">
                <h2>🔬 Research Summaries (AI)</h2>
                <div class="research-summaries-container">
                    {summaries_html}
                </div>
            </div>'''

        return ""

    def _generate_ai_analysis_html(self, sample: Dict) -> str:
        """Generate HTML for AI analysis results."""
        if 'ai_analysis' not in sample or not sample['ai_analysis']:
            return ""

        ai_data = sample['ai_analysis']
        project_ai = ai_data.get('project', {})
        sample_ai = ai_data.get('sample', {})

        # Combine project and sample AI data for display
        combined_data = {}

        # Sample-level data takes precedence
        for field in ['platform', 'tissue', 'condition', 'organism', 'cell_type', 'treatment', 'experiment_type']:
            sample_value = sample_ai.get(field)
            project_value = project_ai.get(field)

            if sample_value and sample_value.lower() != 'unknown':
                combined_data[field] = {'value': sample_value, 'source': 'sample'}
            elif project_value and project_value.lower() != 'unknown':
                combined_data[field] = {'value': project_value, 'source': 'project'}

        if not combined_data:
            return ""

        # Generate HTML for AI analysis
        ai_items_html = ""
        field_labels = {
            'platform': 'Sequencing Platform',
            'tissue': 'Tissue/Organ',
            'condition': 'Experimental Condition',
            'organism': 'Organism',
            'cell_type': 'Cell Type',
            'treatment': 'Treatment',
            'experiment_type': 'Experiment Type'
        }

        for field, data in combined_data.items():
            label = field_labels.get(field, field.title())
            value = data['value']
            source = data['source']
            badge_text = 'Sample-level (AI)' if source == 'sample' else 'Project-level (AI)'

            ai_items_html += f"""
            <div class="metadata-item">
                <span class="metadata-label">{label}:</span>
                <span class="metadata-value">{value} <span class="ai-badge">{badge_text}</span></span>
            </div>"""

        return f"""
        <div class="ai-analysis-section">
            <h5>🤖 AI-Extracted Information (AI)</h5>
            {ai_items_html}
        </div>"""

    def _generate_references_html(self, citations: List[Dict]) -> str:
        """Generate HTML for the references section."""
        if not citations:
            return ""

        references_html = ""
        for citation in citations:
            pubmed_links = ""
            if citation['pubmed_ids']:
                pubmed_parts = []
                for pmid in citation['pubmed_ids']:
                    pubmed_parts.append(f'<a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" target="_blank" class="db-link">PMID:{pmid}</a>')
                pubmed_links = ' | '.join(pubmed_parts)

            contributors_text = ""
            if citation['contributors']:
                if len(citation['contributors']) > 3:
                    contributors_text = ', '.join(citation['contributors'][:3]) + ' et al.'
                else:
                    contributors_text = ', '.join(citation['contributors'])

            dates_text = ""
            if citation['submission_date'] or citation['release_date']:
                date_parts = []
                if citation['submission_date']:
                    date_parts.append(f"Submitted: {citation['submission_date']}")
                if citation['release_date']:
                    date_parts.append(f"Released: {citation['release_date']}")
                dates_text = ' | '.join(date_parts)

            references_html += f'''
            <div class="reference-item">
                <div class="reference-header">
                    <h4><a href="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={citation['project_id']}" target="_blank" class="db-link">{citation['project_id']}</a>: {citation['title'] or 'No title available'}</h4>
                </div>
                <div class="reference-details">
                    {f'<div class="reference-authors"><strong>Authors:</strong> {contributors_text}</div>' if contributors_text else ''}
                    {f'<div class="reference-links"><strong>Publications:</strong> {pubmed_links}</div>' if pubmed_links else ''}
                    {f'<div class="reference-dates"><strong>Dates:</strong> {dates_text}</div>' if dates_text else ''}
                    {f'<div class="reference-summary"><strong>Summary:</strong> {citation["summary"][:500] + "..." if len(citation["summary"]) > 500 else citation["summary"]}</div>' if citation['summary'] else ''}
                </div>
            </div>'''

        return f'''
        <div class="references-section">
            <h2>📄 Reference List</h2>
            <div class="references-container">
                {references_html}
            </div>
        </div>'''

    def _generate_html_report(self, sample_metadata: List[Dict], project, charts_html: str, references_html: str, research_summaries_html: str = ""):
        """Generate HTML report."""
        html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Celline Metadata Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 20px rgba(0,0,0,0.1);
        }}
        .header {{
            border-bottom: 3px solid #2c3e50;
            padding-bottom: 20px;
            margin-bottom: 30px;
            display: flex;
            align-items: center;
            gap: 20px;
        }}
        .header-icon {{
            height: 2.5em;
            width: auto;
            object-fit: contain;
        }}
        .header-text {{
            flex: 1;
        }}
        h1 {{
            color: #2c3e50;
            margin: 0;
            font-size: 2.5em;
        }}
        .subtitle {{
            color: #7f8c8d;
            font-size: 1.1em;
            margin-top: 5px;
        }}
        .summary {{
            background-color: #ecf0f1;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }}
        .summary-item {{
            text-align: center;
        }}
        .summary-number {{
            font-size: 2em;
            font-weight: bold;
            color: #3498db;
        }}
        .summary-label {{
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .sample {{
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-bottom: 25px;
            overflow: hidden;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .sample-header {{
            background-color: #3498db;
            color: white;
            padding: 15px 20px;
            font-weight: bold;
            font-size: 1.2em;
        }}
        .sample-header.error {{
            background-color: #e74c3c;
        }}
        .sample-content {{
            padding: 20px;
        }}
        .metadata-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }}
        .metadata-section {{
            background-color: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
        }}
        .metadata-section h3 {{
            margin-top: 0;
            color: #2c3e50;
            font-size: 1.1em;
        }}
        .metadata-item {{
            margin-bottom: 10px;
        }}
        .metadata-label {{
            font-weight: bold;
            color: #34495e;
            display: inline-block;
            min-width: 100px;
        }}
        .metadata-value {{
            color: #555;
            word-break: break-word;
        }}
        .error-message {{
            background-color: #fdf2f2;
            color: #e74c3c;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #e74c3c;
        }}
        .description {{
            background-color: #f0f9ff;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #3498db;
            margin-bottom: 20px;
        }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            text-align: center;
            color: #7f8c8d;
            font-size: 0.9em;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            background-color: #e8f4fd;
            color: #2980b9;
            border-radius: 12px;
            font-size: 0.85em;
            margin-right: 5px;
        }}
        .data-source-badge {{
            background-color: #e8f4fd;
            color: #2980b9;
            font-weight: bold;
            font-size: 0.8em;
        }}
        .db-link {{
            color: #2980b9;
            text-decoration: none;
            font-weight: bold;
        }}
        .db-link:hover {{
            text-decoration: underline;
        }}
        .charts-container {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            display: flex;
            flex-wrap: wrap;
            justify-content: space-around;
            gap: 20px;
        }}
        .chart-item {{
            flex: 1;
            min-width: 220px;
            max-width: 280px;
            text-align: center;
        }}
        .ai-analysis-section {{
            background-color: #e8f5e8;
            border: 1px solid #c3e6c3;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
            border-left: 4px solid #28a745;
        }}
        .ai-analysis-section h5 {{
            margin: 0 0 10px 0;
            color: #155724;
            font-size: 1.1em;
        }}
        .ai-badge {{
            background-color: #d4edda;
            color: #155724;
            font-size: 0.8em;
            padding: 2px 6px;
            border-radius: 10px;
            margin-left: 5px;
        }}
        .chart-item h3 {{
            margin: 0 0 15px 0;
            color: #2c3e50;
            font-size: 1.1em;
        }}
        .chart-canvas {{
            max-width: 300px;
            margin: 0 auto;
        }}
        .references-section {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .references-section h2 {{
            margin: 0 0 20px 0;
            color: #2c3e50;
            border-bottom: 2px solid #3498db;
            padding-bottom: 10px;
        }}
        .references-container {{
            display: flex;
            flex-direction: column;
            gap: 15px;
        }}
        .reference-item {{
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 15px;
            background-color: #f8f9fa;
            border-left: 4px solid #3498db;
        }}
        .reference-header h4 {{
            margin: 0 0 10px 0;
            color: #2c3e50;
            font-size: 1.1em;
        }}
        .reference-details {{
            color: #555;
            line-height: 1.5;
        }}
        .reference-details > div {{
            margin-bottom: 8px;
        }}
        .reference-authors {{
            font-style: italic;
        }}
        .reference-summary {{
            background-color: #ffffff;
            padding: 10px;
            border-radius: 5px;
            border-left: 3px solid #17a2b8;
        }}
        .research-summaries-section {{
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .research-summaries-section h2 {{
            margin: 0 0 20px 0;
            color: #2c3e50;
            border-bottom: 2px solid #e74c3c;
            padding-bottom: 10px;
        }}
        .research-summaries-container {{
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .research-summary-item {{
            border: 1px solid #e9ecef;
            border-radius: 8px;
            padding: 20px;
            background-color: #f8f9fa;
            border-left: 4px solid #e74c3c;
        }}
        .research-summary-item h4 {{
            margin: 0 0 15px 0;
            color: #2c3e50;
            font-size: 1.2em;
        }}
        .research-item {{
            margin-bottom: 12px;
            line-height: 1.6;
            color: #555;
        }}
        .contact-section {{
            background-color: #fff3cd;
            padding: 15px;
            border-radius: 5px;
            margin-top: 15px;
            border-left: 3px solid #ffc107;
        }}
        .contact-section h5 {{
            margin: 0 0 10px 0;
            color: #856404;
        }}
        .contact-item {{
            margin-bottom: 8px;
            color: #856404;
        }}
        .contact-link {{
            color: #2980b9;
            text-decoration: none;
            font-weight: bold;
        }}
        .contact-link:hover {{
            text-decoration: underline;
        }}
        .strategy-info {{
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 5px;
        }}
        .strategy-info h4 {{
            margin: 0 0 10px 0;
            color: #856404;
        }}
        /* Project and Sample Nested Structure Styles */
        .project-section {{
            border: 2px solid #3498db;
            border-radius: 10px;
            margin-bottom: 30px;
            overflow: hidden;
            background-color: #ffffff;
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        }}
        .project-header {{
            background: linear-gradient(135deg, #3498db, #2980b9);
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .project-header h2 {{
            margin: 0;
            font-size: 1.5em;
        }}
        .sample-count {{
            background-color: rgba(255,255,255,0.2);
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 0.9em;
        }}
        .project-links-section {{
            background-color: #e8f4fd;
            padding: 15px 20px;
            border-bottom: 1px solid #d1ecf1;
        }}
        .project-links-section h4 {{
            margin: 0 0 10px 0;
            color: #0c5460;
        }}
        .samples-container {{
            padding: 20px;
        }}
        .samples-container h3 {{
            margin: 0 0 20px 0;
            color: #2c3e50;
            border-bottom: 2px solid #ecf0f1;
            padding-bottom: 10px;
        }}
        .sample-subsection {{
            border: 1px solid #e9ecef;
            border-radius: 8px;
            margin-bottom: 20px;
            background-color: #fafafa;
            overflow: hidden;
        }}
        .sample-header {{
            background: linear-gradient(135deg, #17a2b8, #138496);
            color: white;
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .sample-header h4 {{
            margin: 0;
            font-size: 1.2em;
        }}
        .sample-basic-info {{
            padding: 15px 20px;
            background-color: #ffffff;
            border-bottom: 1px solid #e9ecef;
        }}
        .sample-links-section {{
            background-color: #fff3cd;
            padding: 15px 20px;
            border-bottom: 1px solid #ffeaa7;
        }}
        .sample-links-section h5 {{
            margin: 0 0 10px 0;
            color: #856404;
        }}
        .sample-summary {{
            padding: 15px 20px;
            background-color: #ffffff;
        }}
        .sample-summary h5 {{
            margin: 0 0 10px 0;
            color: #2c3e50;
        }}
        .sample-link {{
            margin-left: 15px;
            padding: 3px 0;
        }}
        .error-samples-section {{
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
        }}
        .error-samples-section h2 {{
            color: #721c24;
            margin-top: 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            {celline_icon_html}
            <div class="header-text">
                <h1>Celline Metadata Report</h1>
                <div class="subtitle">Generated on {timestamp} • Data retrieved from public genomics databases</div>
            </div>
        </div>

        <div class="summary">
            <div class="summary-item">
                <div class="summary-number">{total_samples}</div>
                <div class="summary-label">Total Samples</div>
            </div>
            <div class="summary-item">
                <div class="summary-number">{successful_samples}</div>
                <div class="summary-label">Successfully Processed</div>
            </div>
            <div class="summary-item">
                <div class="summary-number">{failed_samples}</div>
                <div class="summary-label">Failed</div>
            </div>
        </div>

        {references_html}

        {research_summaries_html}

        {charts_html}

        {samples_html}

        <div class="footer">
            Generated by Celline Export MetaReport • Data retrieved from public genomics databases • Project: {project_path}
        </div>
    </div>
</body>
</html>
"""

        # Count samples
        total_samples = len(sample_metadata)
        successful_samples = sum(1 for s in sample_metadata if s['error'] is None)
        failed_samples = total_samples - successful_samples

        # Get embedded icon
        celline_icon_data = self._get_embedded_icon()
        celline_icon_html = f'<img src="{celline_icon_data}" alt="Celline Logo" class="header-icon">' if celline_icon_data else ''

        # Group samples by project and generate nested HTML
        projects = self._group_samples_by_project(sample_metadata)
        samples_html = ""

        # Generate error samples first (not grouped by project)
        error_samples_html = ""
        for sample in sample_metadata:
            if sample['error']:
                error_samples_html += self._generate_error_sample_html(sample)

        if error_samples_html:
            samples_html += f"""
            <div class="error-samples-section">
                <h2>⚠️ Failed Samples</h2>
                {error_samples_html}
            </div>
            """

        # Generate project sections for successful samples
        for project_id, project_samples in projects.items():
            samples_html += self._generate_project_section_html(project_id, project_samples)

        # Fill template
        html_content = html_template.format(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            total_samples=total_samples,
            successful_samples=successful_samples,
            failed_samples=failed_samples,
            celline_icon_html=celline_icon_html,
            references_html=references_html,
            research_summaries_html=research_summaries_html,
            charts_html=charts_html,
            samples_html=samples_html,
            project_path=getattr(project, 'PROJ_PATH', 'Unknown')
        )

        # Write HTML file
        output_path = os.path.join(getattr(project, 'PROJ_PATH', '.'), self.output_file)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def _generate_successful_sample_html(self, sample: Dict) -> str:
        """Generate HTML for a successfully processed sample."""
        metadata = sample['metadata']
        data_source = sample['data_source']

        # Generate appropriate links based on data source
        sample_link = self._generate_sample_link(metadata.key, data_source)
        parent_link = self._generate_sample_link(metadata.parent, data_source) if metadata.parent else metadata.parent

        # Get additional metadata if available
        additional_info = self._extract_additional_metadata(metadata)

        html = f"""
        <div class="sample">
            <div class="sample-header">
                {sample['id']} <span class="badge data-source-badge">{data_source}</span>
            </div>
            <div class="sample-content">
                <div class="description">
                    <strong>Description:</strong> {sample['description']}
                </div>

                <div class="metadata-grid">
                    <div class="metadata-section">
                        <h3>📊 Basic Information</h3>
                        <div class="metadata-item">
                            <span class="metadata-label">Sample ID:</span>
                            <span class="metadata-value">{sample_link}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Title:</span>
                            <span class="metadata-value">{metadata.title if metadata.title else 'Not specified'}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Species:</span>
                            <span class="metadata-value">{metadata.species if metadata.species else 'Not specified'}</span>
                        </div>
                        <div class="metadata-item">
                            <span class="metadata-label">Parent Project:</span>
                            <span class="metadata-value">{parent_link if parent_link else 'Not available'}</span>
                        </div>
                    </div>

                    <div class="metadata-section">
                        <h3>🔬 Technical Details</h3>
                        {self._generate_technical_details_html(metadata)}
                        <div class="metadata-item">
                            <span class="metadata-label">Child Runs:</span>
                            <span class="metadata-value">{self._get_child_runs_display(sample['id'])}</span>
                        </div>
                    </div>

                    <div class="metadata-section">
                        <h3>📝 Experimental Summary</h3>
                        <div class="metadata-item">
                            <div class="metadata-value">{self._get_experimental_summary(metadata)}</div>
                        </div>
                    </div>

                    {self._generate_strategy_info_html(metadata)}
                    {self._generate_raw_links_html(metadata, data_source)}
                    {additional_info}
                    {self._generate_ai_analysis_html(sample)}
                </div>
            </div>
        </div>
        """
        return html

    def _generate_error_sample_html(self, sample: Dict) -> str:
        """Generate HTML for a failed sample."""
        html = f"""
        <div class="sample">
            <div class="sample-header error">
                {sample['id']} <span class="badge" style="background-color: #fdf2f2; color: #e74c3c;">Error</span>
            </div>
            <div class="sample-content">
                <div class="description">
                    <strong>Description:</strong> {sample['description']}
                </div>

                <div class="error-message">
                    <strong>Error:</strong> {sample['error']}
                </div>
            </div>
        </div>
        """
        return html

    def _generate_sample_link(self, sample_id: str, data_source: str) -> str:
        """Generate appropriate link for sample based on data source."""
        if not sample_id:
            return "Not available"

        if 'GEO' in data_source:
            return f'<a href="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample_id}" target="_blank" class="db-link">{sample_id}</a>'
        elif 'SRA' in data_source:
            return f'<a href="https://www.ncbi.nlm.nih.gov/sra/{sample_id}" target="_blank" class="db-link">{sample_id}</a>'
        elif 'CNCB' in data_source:
            return f'<a href="https://bigd.big.ac.cn/gsa/{sample_id}" target="_blank" class="db-link">{sample_id}</a>'
        else:
            return sample_id

    def _generate_technical_details_html(self, metadata) -> str:
        """Generate technical details HTML based on available metadata."""
        details_html = ""

        # Check for SRX ID (common in SRA data)
        if hasattr(metadata, 'srx_id') and metadata.srx_id:
            details_html += f'''
            <div class="metadata-item">
                <span class="metadata-label">SRX ID:</span>
                <span class="metadata-value">{metadata.srx_id}</span>
            </div>'''

        # Check for additional technical attributes
        technical_attrs = ['strategy', 'platform', 'instrument', 'library_source']
        for attr in technical_attrs:
            if hasattr(metadata, attr):
                value = getattr(metadata, attr)
                if value:
                    attr_label = attr.replace('_', ' ').title()
                    details_html += f'''
                    <div class="metadata-item">
                        <span class="metadata-label">{attr_label}:</span>
                        <span class="metadata-value">{value}</span>
                    </div>'''

        return details_html

    def _extract_additional_metadata(self, metadata) -> str:
        """Extract additional metadata that might be available."""
        additional_html = ""

        # Check for additional attributes that might be present
        additional_attrs = {
            'description': 'Description',
            'submission_date': 'Submission Date',
            'publication_date': 'Publication Date',
            'last_update_date': 'Last Update',
            'contact_name': 'Contact',
            'organization_name': 'Organization'
        }

        available_additional = []
        for attr, label in additional_attrs.items():
            if hasattr(metadata, attr):
                value = getattr(metadata, attr)
                if value:
                    available_additional.append((label, value))

        if available_additional:
            items_html = ""
            for label, value in available_additional:
                items_html += f'''
                <div class="metadata-item">
                    <span class="metadata-label">{label}:</span>
                    <span class="metadata-value">{value}</span>
                </div>'''

            additional_html = f'''
            <div class="metadata-section">
                <h3>ℹ️ Additional Information</h3>
                {items_html}
            </div>'''

        return additional_html

    def _generate_raw_links_html(self, metadata, data_source: str = None) -> str:
        """Generate HTML for raw data links with meaningful titles."""
        # First try to get supplementary files from enriched experimental details
        links = []

        if hasattr(metadata, 'supplementary_files') and metadata.supplementary_files:
            if isinstance(metadata.supplementary_files, list):
                links = metadata.supplementary_files
            else:
                links = [metadata.supplementary_files]
        elif hasattr(metadata, 'raw_link') and metadata.raw_link:
            # Fallback to raw_link if supplementary_files not available
            links = [link.strip() for link in str(metadata.raw_link).split(',') if link.strip()]

        if not links:
            return ""

        links_html = ""
        for link in links:  # Show ALL links, not just first 3
            if link.startswith('ftp://') or link.startswith('http'):
                # Use filename as title directly (no processing)
                filename = link.split('/')[-1] if '/' in link else link
                links_html += f'<div class="metadata-item"><a href="{link}" target="_blank" class="db-link">{filename}</a></div>'
            else:
                links_html += f'<div class="metadata-item"><span class="metadata-value">{link}</span></div>'

        return f"""
        <div class="metadata-section">
            <h3>💾 Raw Data Links</h3>
            {links_html}
        </div>
        """

    def _get_project_supplemental_data(self, project_id: str) -> Optional[List[str]]:
        """Get real supplemental data from GSE project."""
        try:
            import requests
            import xml.etree.ElementTree as ET

            if not project_id.startswith('GSE'):
                return None

            # Query GEO API for GSE project supplemental data
            url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={project_id}&targ=gse&form=xml&view=full"
            response = requests.get(url, timeout=15)

            if response.status_code == 200:
                root = ET.fromstring(response.content)

                # Define namespace for GEO XML
                ns = {'geo': 'http://www.ncbi.nlm.nih.gov/geo/info/MINiML'}

                # Extract supplementary data from GSE
                supp_files = []

                # Look for supplementary data in Series element
                series_elem = root.find('.//geo:Series', ns)
                if series_elem is not None:
                    for supp_elem in series_elem.findall('.//geo:Supplementary-Data', ns):
                        if supp_elem.text:
                            file_url = supp_elem.text.strip()
                            supp_files.append(file_url)

                # Also check for platform-level supplementary data
                for platform_elem in root.findall('.//geo:Platform', ns):
                    for supp_elem in platform_elem.findall('.//geo:Supplementary-Data', ns):
                        if supp_elem.text:
                            file_url = supp_elem.text.strip()
                            if file_url not in supp_files:
                                supp_files.append(file_url)

                return supp_files if supp_files else None

        except Exception as e:
            console.print(f"[dim yellow]Could not retrieve project supplemental data for {project_id}: {e}[/dim yellow]")
            return None

    def _get_experimental_summary(self, metadata) -> str:
        """Get the best available experimental summary from enriched metadata."""
        # Priority order for summary sources
        summary_sources = [
            ('experimental_protocol', 'Experimental Protocol'),
            ('description', 'Description'),
            ('api_summary', 'API Summary'),
            ('abstract', 'Abstract'),
            ('summary', 'Summary')
        ]

        for attr_name, source_type in summary_sources:
            if hasattr(metadata, attr_name):
                value = getattr(metadata, attr_name)
                if value and str(value).strip():
                    summary_text = str(value).strip()
                    # If the summary is very long, truncate it
                    if len(summary_text) > 800:
                        summary_text = summary_text[:800] + "..."
                    return summary_text

        # If no good summary found, return a more informative message
        return "No detailed experimental summary available from the data source."

    def _group_samples_by_project(self, sample_metadata: List[Dict]) -> Dict[str, List[Dict]]:
        """Group samples by project ID for nested display."""
        projects = {}

        for sample in sample_metadata:
            if sample['error'] is None and sample['metadata']:
                project_id = getattr(sample['metadata'], 'parent', 'Unknown Project')
                if project_id not in projects:
                    projects[project_id] = []
                projects[project_id].append(sample)

        return projects

    def _generate_project_section_html(self, project_id: str, samples: List[Dict]) -> str:
        """Generate HTML for a project section with nested samples."""
        sample_sections = ""

        # Generate sample sections first
        for sample in samples:
            sample_sections += self._generate_sample_subsection_html(sample)

        # Get real project-level supplemental data from GSE
        project_supp_data = self._get_project_supplemental_data(project_id)

        # Generate project-level raw data links from actual GSE supplemental data
        project_links_html = ""
        if project_supp_data:
            for link in sorted(project_supp_data):
                if link.startswith('ftp://') or link.startswith('http'):
                    filename = link.split('/')[-1] if '/' in link else link
                    project_links_html += f'<div class="metadata-item"><a href="{link}" target="_blank" class="db-link">{filename}</a></div>'
                else:
                    project_links_html += f'<div class="metadata-item"><span class="metadata-value">{link}</span></div>'

        project_links_section = f"""
        <div class="project-links-section">
            <h4>💾 Raw Data Links for Project</h4>
            {project_links_html if project_links_html else '<div class="metadata-item"><span class="metadata-value">No project-level links available</span></div>'}
        </div>
        """ if project_links_html else ""

        return f"""
        <div class="project-section">
            <div class="project-header">
                <h2>🗂️ Project: {project_id}</h2>
                <div class="project-info">
                    <span class="sample-count">{len(samples)} sample{'s' if len(samples) != 1 else ''}</span>
                </div>
            </div>

            {project_links_section}

            <div class="samples-container">
                <h3>📋 Samples in this Project</h3>
                {sample_sections}
            </div>
        </div>
        """

    def _generate_sample_subsection_html(self, sample: Dict) -> str:
        """Generate HTML for a sample subsection within a project."""
        metadata = sample['metadata']
        data_source = sample['data_source']

        # Generate sample-specific raw data links
        sample_links_html = ""
        links = []

        if hasattr(metadata, 'supplementary_files') and metadata.supplementary_files:
            links = metadata.supplementary_files if isinstance(metadata.supplementary_files, list) else [metadata.supplementary_files]
        elif hasattr(metadata, 'raw_link') and metadata.raw_link:
            links = [link.strip() for link in str(metadata.raw_link).split(',') if link.strip()]

        for link in links:
            if link.startswith('ftp://') or link.startswith('http'):
                filename = link.split('/')[-1] if '/' in link else link
                sample_links_html += f'<div class="metadata-item sample-link"><a href="{link}" target="_blank" class="db-link">{filename}</a></div>'

        sample_links_section = f"""
        <div class="sample-links-section">
            <h5>💾 Raw Data Links for Sample</h5>
            {sample_links_html if sample_links_html else '<div class="metadata-item"><span class="metadata-value">No sample-specific links available</span></div>'}
        </div>
        """ if sample_links_html else ""

        # Generate appropriate links based on data source
        sample_link = self._generate_sample_link(metadata.key, data_source)

        return f"""
        <div class="sample-subsection">
            <div class="sample-header">
                <h4>🧪 {sample['id']}: {sample['description']}</h4>
                <span class="badge data-source-badge">{data_source}</span>
            </div>

            <div class="sample-basic-info">
                <div class="metadata-item">
                    <span class="metadata-label">Sample ID:</span>
                    <span class="metadata-value">{sample_link}</span>
                </div>
                <div class="metadata-item">
                    <span class="metadata-label">Title:</span>
                    <span class="metadata-value">{metadata.title if metadata.title else 'Not specified'}</span>
                </div>
                <div class="metadata-item">
                    <span class="metadata-label">Species:</span>
                    <span class="metadata-value">{metadata.species if metadata.species else 'Not specified'}</span>
                </div>
            </div>

            {sample_links_section}

            <div class="technical-details">
                <h5>🔬 Technical Details</h5>
                <div class="metadata-item">
                    <span class="metadata-label">Child Runs:</span>
                    <span class="metadata-value">{self._get_child_runs_display(sample['id'])}</span>
                </div>
                {self._generate_strategy_info_html(metadata)}
            </div>

            <div class="sample-summary">
                <h5>📝 Experimental Summary</h5>
                <div class="metadata-value">{self._get_experimental_summary(metadata)}</div>
            </div>

            {self._generate_ai_analysis_html(sample)}
        </div>
        """

    def _get_child_runs_display(self, sample_id: str) -> str:
        """Get child runs (SRR IDs) for display."""
        try:
            import requests
            import xml.etree.ElementTree as ET
            import re

            if not sample_id.startswith('GSM'):
                return 'Not available'

            # First get SRX ID from GEO
            url = f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={sample_id}&targ=gsm&form=xml&view=full"
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                return 'Not available'

            root = ET.fromstring(response.content)
            ns = {'geo': 'http://www.ncbi.nlm.nih.gov/geo/info/MINiML'}

            srx_id = None

            # Look for SRA relations to get SRX
            for relation_elem in root.findall('.//geo:Sample/geo:Relation', ns):
                relation_type = relation_elem.get('type')
                target = relation_elem.get('target')
                if relation_type == 'SRA' and target:
                    # Extract SRX ID from URL
                    srx_match = re.search(r'SRX\d+', target)
                    if srx_match:
                        srx_id = srx_match.group()
                        break

            if not srx_id:
                return 'Not available'

            # Now get SRR IDs from SRX using SRA API
            sra_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=sra&id={srx_id}&rettype=xml"
            sra_response = requests.get(sra_url, timeout=10)

            if sra_response.status_code == 200:
                sra_root = ET.fromstring(sra_response.content)
                srr_ids = []

                # Extract SRR IDs from SRA XML
                for run_elem in sra_root.iter('RUN'):
                    run_accession = run_elem.get('accession')
                    if run_accession and run_accession.startswith('SRR'):
                        srr_ids.append(run_accession)

                if srr_ids:
                    return ', '.join(srr_ids)
                else:
                    return f'{srx_id} (no SRR found)'
            else:
                return f'{srx_id} (SRA query failed)'

        except Exception as e:
            console.print(f"[dim yellow]Could not retrieve child runs for {sample_id}: {e}[/dim yellow]")
            return 'Not available'

    def _get_embedded_icon(self) -> str:
        """Get base64 encoded Celline icon for HTML embedding."""
        try:
            import base64

            # Get the icon path relative to this file
            icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'celline_icon.png')

            if os.path.exists(icon_path):
                with open(icon_path, 'rb') as f:
                    icon_data = f.read()

                # Encode to base64
                base64_data = base64.b64encode(icon_data).decode('utf-8')
                return f"data:image/png;base64,{base64_data}"
            else:
                console.print(f"[dim yellow]Celline icon not found at {icon_path}[/dim yellow]")
                return ""

        except Exception as e:
            console.print(f"[dim yellow]Could not load Celline icon: {e}[/dim yellow]")
            return ""

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments specific to export_metareport."""
        parser.add_argument(
            '--output',
            type=str,
            default='metadata_report.html',
            help='Output HTML file name (default: metadata_report.html)'
        )
        parser.add_argument(
            '--ai',
            action='store_true',
            help='Use OpenAI GPT-4o to analyze and extract platform, tissue, and condition information from XML data'
        )

    def cli(self, project, args: Optional[argparse.Namespace] = None):
        """CLI entry point."""
        if args:
            if hasattr(args, 'output'):
                self.output_file = args.output
            if hasattr(args, 'ai'):
                self.use_ai = args.ai
        return self.call(project)

    def get_description(self) -> str:
        return "Generate HTML metadata report from samples.toml sample IDs."

    def get_usage_examples(self) -> list[str]:
        return [
            "celline export metareport",
            "celline export metareport --output my_report.html"
        ]