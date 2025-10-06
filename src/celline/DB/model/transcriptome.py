import os
# transcriptome.py
from dataclasses import dataclass
from typing import Optional
from celline.DB.dev.model import BaseModel, BaseSchema, Primary

# ---------- スキーマ ----------
@dataclass
class Transcriptome_Schema(BaseSchema):
    species:      str    = ""
    parent:   Optional[str]   = None
    children: Optional[str]   = None
    title:    Optional[str]   = ""
    built_path: str           = ""  # Cell Ranger transcriptome path
    star_index: Optional[str] = None  # STAR genome index path

# ---------- モデル ----------
class Transcriptome(BaseModel[Transcriptome_Schema]):

    def set_class_name(self) -> str:
        return __class__.__name__

    def def_schema(self):
        return Transcriptome_Schema

    # ← フィルタを species に変更
    def search(self, species: str, force_search=False) -> Optional[str]:
        """Search for Cell Ranger transcriptome path by species."""
        print(self.get(Transcriptome_Schema, lambda d: True))
        hit = self.get(Transcriptome_Schema, lambda d: d.species == species)
        return hit[0].built_path if hit else None

    def search_star_index(self, species: str, force_search=False) -> Optional[str]:
        """Search for STAR genome index path by species."""
        hit = self.get(Transcriptome_Schema, lambda d: d.species == species)
        return hit[0].star_index if hit and hit[0].star_index else None

    def add_path(self, species: str, built_path: str, star_index: Optional[str] = None, *, force_update: bool = True):
        """Add transcriptome paths for a species.

        Args:
            species: Species name (e.g., "Homo sapiens", "Mus musculus")
            built_path: Path to Cell Ranger transcriptome reference
            star_index: Path to STAR genome index (optional)
            force_update: If True, update existing entry
        """
        import os
        if not os.path.isdir(built_path):
            raise FileNotFoundError(f"Cell Ranger transcriptome not found: {built_path}")

        if star_index and not os.path.isdir(star_index):
            raise FileNotFoundError(f"STAR index not found: {star_index}")

        if self.search(species) and not force_update:
            print(f"[INFO] Transcriptome for {species} already exists. Skip.")
            return

        self.add_schema(
            Transcriptome_Schema(
                key=species,
                species=species,
                parent=None,
                children=None,
                title=species,
                built_path=built_path,
                star_index=star_index,
            )
        )

    def add_star_index(self, species: str, star_index: str):
        """Add or update STAR index for existing transcriptome.

        Args:
            species: Species name
            star_index: Path to STAR genome index
        """
        import os
        if not os.path.isdir(star_index):
            raise FileNotFoundError(f"STAR index not found: {star_index}")

        hit = self.get(Transcriptome_Schema, lambda d: d.species == species)
        if not hit:
            raise ValueError(f"No transcriptome found for species: {species}. Add Cell Ranger transcriptome first.")

        # Update existing schema with STAR index
        schema = hit[0]
        schema.star_index = star_index
        self.add_schema(schema, force_update=True)
