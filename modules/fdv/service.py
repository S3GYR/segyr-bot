from __future__ import annotations

from typing import Dict

from modules.fdv.engine import compute_fdv
from modules.fdv.schema import FDVData


class FDVService:
    """Service léger pour calculer les indicateurs FDV d'un chantier."""

    def build_for_chantier(self, chantier: Dict[str, object] | FDVData) -> FDVData:
        chantier_dict = chantier if isinstance(chantier, dict) else chantier.__dict__
        return compute_fdv(chantier_dict, chantier_dict.get("fdv"))
