"""Le modèle métier : un établissement validé à l'entrée."""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Les sources parlent la langue de l'API ; le modèle parle la langue du métier.
# Cette table est le seul endroit où l'on traduit l'une dans l'autre.
CORRESPONDANCE: dict[str, str] = {
    "identifiant_de_l_etablissement": "identifiant",
    "nom_etablissement": "nom",
    "type_etablissement": "type_etablissement",
    "statut_public_prive": "statut",
    "code_departement": "code_departement",
    "libelle_departement": "departement",
    "libelle_region": "region",
    "etat": "etat",
    "date_ouverture": "date_ouverture",
}


class Etablissement(BaseModel):
    """Un établissement scolaire, quelle que soit la source d'où il vient."""

    identifiant: str = Field(min_length=1)
    nom: str
    type_etablissement: str
    statut: Literal["Public", "Privé"]
    code_departement: str
    departement: str = Field(min_length=1)
    region: str
    etat: Literal["OUVERT", "FERME", "À FERMER"]
    date_ouverture: str | None = None

    @field_validator("departement", mode="before")
    @classmethod
    def normaliser_departement(cls, valeur: object) -> object:
        """Traite les départements vides ou composés d'espaces comme absents."""
        if isinstance(valeur, str):
            return valeur.strip()
        return valeur

    @field_validator("code_departement", mode="before")
    @classmethod
    def normaliser_code_departement(cls, valeur: object) -> object:
        """'26' ou 26 devient '026' : on tranche une fois, à l'entrée."""
        if isinstance(valeur, str | int):
            return str(valeur).zfill(3)
        return valeur  # None ou autre : Pydantic le refusera

    @property
    def est_ouvert(self) -> bool:
        """La logique métier demande 'est ouvert ?', pas 'etat == "OUVERT"'."""
        return self.etat == "OUVERT"

    @classmethod
    def depuis_brut(cls, brut: dict[str, Any]) -> "Etablissement":
        """Traduit un enregistrement brut (clés de l'API) puis le valide."""
        traduit = {
            cle_modele: brut.get(cle_brute)
            for cle_brute, cle_modele in CORRESPONDANCE.items()
        }
        return cls.model_validate(traduit)
