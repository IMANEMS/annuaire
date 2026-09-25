"""Vérifie que le nettoyage écarte les lignes sans département."""

import pandas as pd

from annuaire.nettoyage import retirer_sans_departement


def test_retire_les_lignes_sans_departement() -> None:
    df = pd.DataFrame({"libelle_departement": ["Rhône", None, "Isère"]})
    resultat = retirer_sans_departement(df)
    assert len(resultat) == 2


if __name__ == "__main__":
    test_retire_les_lignes_sans_departement()
    print("OK")