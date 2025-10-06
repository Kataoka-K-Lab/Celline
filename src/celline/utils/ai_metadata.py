"""
AI-powered metadata extraction utility.
Supports both OpenAI GPT and Anthropic Claude for extracting structured metadata from web pages.
"""

from __future__ import annotations
import os
import json
from typing import Dict, Optional, Literal
from pathlib import Path
from rich.console import Console

console = Console()

AIProvider = Literal["openai", "claude", "auto"]


class AIMetadataExtractor:
    """Extract structured metadata from text using AI (OpenAI or Claude)."""

    def __init__(self, provider: AIProvider = "auto"):
        """
        Initialize AI metadata extractor.

        Args:
            provider: AI provider to use ("openai", "claude", or "auto")
                     "auto" will try OpenAI first, then Claude
        """
        self.provider = provider
        self.api_key: Optional[str] = None
        self.active_provider: Optional[str] = None

    def _load_env(self) -> None:
        """Load environment variables from .env file."""
        from celline.config import Config

        env_path = Path(Config.PROJ_ROOT) / '.env'
        if not env_path.exists():
            raise FileNotFoundError(
                f"Required .env file not found at {env_path}. "
                "Please create a .env file with OPENAI_API_KEY or ANTHROPIC_API_KEY."
            )

        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            raise ImportError(
                "python-dotenv package is required for AI functionality. "
                "Install with: pip install python-dotenv"
            )

    def _validate_and_select_provider(self) -> tuple[str, str]:
        """
        Validate API keys and select provider.

        Returns:
            Tuple of (provider_name, api_key)

        Raises:
            ValueError: If no valid API key is found
        """
        self._load_env()

        openai_key = os.getenv('OPENAI_API_KEY')
        claude_key = os.getenv('ANTHROPIC_API_KEY')

        if self.provider == "openai":
            if not openai_key:
                raise ValueError(
                    "OPENAI_API_KEY not found in .env file. "
                    "Please add OPENAI_API_KEY=your_key_here to your .env file."
                )
            return ("openai", openai_key)

        elif self.provider == "claude":
            if not claude_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY not found in .env file. "
                    "Please add ANTHROPIC_API_KEY=your_key_here to your .env file."
                )
            return ("claude", claude_key)

        else:  # auto
            if openai_key:
                return ("openai", openai_key)
            elif claude_key:
                return ("claude", claude_key)
            else:
                raise ValueError(
                    "No AI API key found in .env file. "
                    "Please add either OPENAI_API_KEY or ANTHROPIC_API_KEY to your .env file."
                )

    def extract_metadata(self, content: str, accession_id: str, content_type: str = "auto") -> Dict[str, str]:
        """
        Extract metadata from content using AI.

        Args:
            content: Text content to analyze (from web page, XML, etc.)
            accession_id: Accession ID being processed
            content_type: Type of content ("project", "sample", or "auto")

        Returns:
            Dictionary with extracted metadata fields
        """
        try:
            provider_name, api_key = self._validate_and_select_provider()
            self.active_provider = provider_name
            self.api_key = api_key

            console.print(f"[cyan]Using {provider_name.upper()} for AI metadata extraction...[/cyan]")

            if provider_name == "openai":
                return self._extract_with_openai(content, accession_id, content_type)
            else:
                return self._extract_with_claude(content, accession_id, content_type)

        except Exception as e:
            console.print(f"[yellow]⚠ AI extraction failed: {e}[/yellow]")
            return {}

    def _extract_with_openai(self, content: str, accession_id: str, content_type: str) -> Dict[str, str]:
        """Extract metadata using OpenAI GPT."""
        try:
            import openai

            client = openai.OpenAI(api_key=self.api_key)

            prompt = self._build_prompt(content, accession_id, content_type)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a bioinformatics expert specializing in genomics data analysis. Extract information accurately and return only valid JSON."
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=800
            )

            result_text = response.choices[0].message.content.strip()
            return self._parse_json_response(result_text, accession_id)

        except Exception as e:
            console.print(f"[red]OpenAI API error: {e}[/red]")
            return {}

    def _extract_with_claude(self, content: str, accession_id: str, content_type: str) -> Dict[str, str]:
        """Extract metadata using Anthropic Claude."""
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)

            prompt = self._build_prompt(content, accession_id, content_type)

            message = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=800,
                temperature=0.1,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                system="You are a bioinformatics expert specializing in genomics data analysis. Extract information accurately and return only valid JSON."
            )

            result_text = message.content[0].text.strip()
            return self._parse_json_response(result_text, accession_id)

        except Exception as e:
            console.print(f"[red]Claude API error: {e}[/red]")
            return {}

    def _build_prompt(self, content: str, accession_id: str, content_type: str) -> str:
        """Build extraction prompt based on content type."""
        # Truncate content if too long (keep first 8000 chars)
        if len(content) > 8000:
            content = content[:8000] + "\n... (content truncated)"

        base_fields = """
{{
  "platform": "sequencing platform (e.g., '10x Chromium', 'Smart-seq2', 'Illumina NextSeq', etc.)",
  "tissue": "tissue or organ studied (e.g., 'brain', 'liver', 'blood', etc.)",
  "cell_type": "specific cell type if mentioned (e.g., 'neurons', 'hepatocytes', 'T cells', etc.)",
  "organism": "organism studied (e.g., 'human', 'mouse', 'rat', etc.)",
  "condition": "experimental condition (e.g., 'healthy', 'disease', 'treatment', etc.)",
  "age": "age information (e.g., '8 weeks', 'adult', 'E18.5', etc.)",
  "sex": "biological sex (e.g., 'male', 'female', 'mixed', etc.)",
  "treatment": "any treatment applied (e.g., 'control', 'drug', 'stimulation', etc.)",
  "disease": "disease or pathology if studied (e.g., 'Alzheimer's', 'cancer', 'diabetes', etc.)",
  "genotype": "genetic background or strain (e.g., 'C57BL/6', 'wild-type', 'knockout', etc.)",
  "experiment_type": "type of experiment (e.g., 'single-cell RNA-seq', 'bulk RNA-seq', 'ATAC-seq', etc.)",
  "research_focus": "main research question or focus (1-2 sentences)"
}}
"""

        prompt = f"""Analyze the following genomics data page and extract key metadata.

Please return ONLY a valid JSON object with these fields:
{base_fields}

For each field:
- Extract the most specific and accurate information
- If information is not clearly stated, use "unknown"
- Keep descriptions concise

Accession ID: {accession_id}

Content:
{content}

Return ONLY the JSON object, no additional text."""

        return prompt

    def _parse_json_response(self, response_text: str, accession_id: str) -> Dict[str, str]:
        """Parse JSON from AI response."""
        try:
            # Try to extract JSON from response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1

            if start_idx != -1 and end_idx != 0:
                json_str = response_text[start_idx:end_idx]
                result = json.loads(json_str)
                console.print(f"[green]✓ AI metadata extracted for {accession_id}[/green]")
                return result
            else:
                result = json.loads(response_text)
                console.print(f"[green]✓ AI metadata extracted for {accession_id}[/green]")
                return result

        except json.JSONDecodeError as e:
            console.print(f"[yellow]⚠ Could not parse AI response as JSON for {accession_id}: {e}[/yellow]")
            return {}


def extract_metadata_from_url(url: str, accession_id: str, provider: AIProvider = "auto") -> Dict[str, str]:
    """
    Convenience function to extract metadata from a URL.

    Args:
        url: URL to fetch and analyze
        accession_id: Accession ID being processed
        provider: AI provider to use

    Returns:
        Dictionary with extracted metadata
    """
    try:
        import requests

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Extract text from HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()

        # Get text
        text = soup.get_text(separator='\n', strip=True)

        # Extract metadata
        extractor = AIMetadataExtractor(provider=provider)
        return extractor.extract_metadata(text, accession_id)

    except Exception as e:
        console.print(f"[red]Error fetching URL {url}: {e}[/red]")
        return {}
