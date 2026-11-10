"""Mesure chaque approche dans son PROPRE processus.

Deux raisons : le pic de RSS est une mesure par processus, et une approche qui a deja
charge le fichier fausserait le cache de la suivante.
"""

import json
import subprocess
import sys
from pathlib import Path

FACTEUR = 1_048_576 if sys.platform == "darwin" else 1024

CODE = """
import json
import resource
import sys
import time

sys.path.insert(0, ".")
from comparer import APPROCHES

fonction = list(APPROCHES.values())[{i}]
debut = time.perf_counter()
resultat = fonction()
duree = time.perf_counter() - debut
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({{"duree": duree, "rss": rss, "resultat": resultat}}))
"""


def verifier_donnees(csv: Path, parquet: Path) -> str | None:
    """Les approches pandas lisent le CSV, Polars lit le Parquet : il faut le même jeu.

    Si le CSV a été régénéré après la conversion, le Parquet décrit un autre fichier
    et la comparaison n'a plus de sens.
    """
    for chemin in (csv, parquet):
        if not chemin.exists():
            return f"{chemin} introuvable : lancez generer_donnees.py puis convertir.py"
    if parquet.stat().st_mtime < csv.stat().st_mtime:
        return (
            f"{parquet} est plus ancien que {csv} : il a été produit à partir d'une "
            "autre version du CSV. Relancez convertir.py avant de mesurer."
        )
    return None


def main() -> int:
    sys.path.insert(0, ".")
    from comparer import APPROCHES, CSV, PARQUET

    probleme = verifier_donnees(CSV, PARQUET)
    if probleme:
        print(f"Données incohérentes : {probleme}", file=sys.stderr)
        return 1

    print(f"{'Approche':30s} {'Durée':>9s} {'Pic RSS':>11s} {'× plus lent':>12s}")
    print("-" * 66)
    resultats = []
    for i, nom in enumerate(APPROCHES):
        p = subprocess.run(
            [sys.executable, "-c", CODE.format(i=i)],
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode:
            print(f"{nom:30s} ÉCHEC :\n{p.stderr.strip()}", file=sys.stderr)
            return p.returncode
        try:
            r = json.loads(p.stdout)
        except json.JSONDecodeError as erreur:
            print(f"{nom}: sortie de mesure invalide: {erreur}", file=sys.stderr)
            return 1
        resultats.append((nom, r))

    resultat_reference = resultats[0][1]["resultat"]
    concordent = all(r["resultat"] == resultat_reference for _, r in resultats[1:])
    duree_reference = min(r["duree"] for _, r in resultats)
    for nom, r in resultats:
        print(
            f"{nom:30s} {r['duree']:6.1f} s "
            f"{r['rss'] / FACTEUR:8.0f} Mo "
            f"{r['duree'] / duree_reference:11.1f}×"
        )
    total = sum(resultat_reference.values())
    if not concordent:
        print("\nDétail des totaux :")
        for nom, r in resultats:
            print(f"  {nom:30s} {sum(r['resultat'].values()):>10d}")
    print(
        f"\nMême résultat pour les {len(resultats)} approches : "
        f"{'oui' if concordent else 'NON'} ({total} établissements ouverts)"
    )
    return 0 if concordent else 1


if __name__ == "__main__":
    raise SystemExit(main())
