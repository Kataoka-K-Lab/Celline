import os
from typing import NamedTuple, Type, Optional
from celline.DB.dev.model import BaseModel, Primary, BaseSchema
from pprint import pprint

from dataclasses import dataclass

@dataclass
class Transcriptome_Schema(BaseSchema):
    built_path: str

class Transcriptome(BaseModel[Transcriptome_Schema]):

    def set_class_name(self) -> str:
        return __class__.__name__

    def def_schema(self) -> Type[Transcriptome_Schema]:
        return Transcriptome_Schema

    def search(self, acceptable_id: str, force_search=False) -> Optional[str]:
        target = self.get(Transcriptome_Schema, lambda d: d.key == acceptable_id)
        if len(target) > 0:
            return target[0].built_path
        return None


    def add_path(self, species: str, built_path: str, force_update=True):
        obj = Transcriptome()
        if not os.path.isdir(built_path):
            print(f"Built_path does not exist. {built_path}")
        if (self.search(species) is not None) and (not force_update):
            print(f"Transcriptome of {species} is already exists.")
            return
        obj.add_schema(Transcriptome_Schema(key=species, parent=None, children=None, title=species, built_path=built_path))
