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
    built_path: str           = ""

# ---------- モデル ----------
class Transcriptome(BaseModel[Transcriptome_Schema]):

    def set_class_name(self) -> str:
        return __class__.__name__

    def def_schema(self):
        return Transcriptome_Schema

    # ← フィルタを species に変更
    def search(self, species: str, force_search=False) -> Optional[str]:
        print(self.get(Transcriptome_Schema, lambda d: True))
        hit = self.get(Transcriptome_Schema, lambda d: d.species == species)
        return hit[0].built_path if hit else None

    def add_path(self, species: str, built_path: str, *, force_update: bool = True):
        import os
        if not os.path.isdir(built_path):
            raise FileNotFoundError(built_path)

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
            )
        )
